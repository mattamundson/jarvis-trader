"""Cost sensitivity sweep — Tier A A5.

Takes a strategy config (symbol + family + params) and runs the research
`_run()` harness across multiple cost scenarios, producing a PF-decay curve.
Identifies the edge-breakeven cost level — the point beyond which realistic
execution frictions erase the observed edge.

Scenarios (commission_multiplier x slippage_multiplier over canonical spec):
  optimistic   — 0.5x commission, 0.5x slippage (house-tier pricing, tight fills)
  baseline     — 1.0x, 1.0x (canonical IB tier 1, 1h-bar typical slippage)
  realistic    — 2.0x, 2.0x (mid-session volatility, retail pricing)
  stressed     — 4.0x, 3.0x (event-driven volatility, wider spreads)
  catastrophic — 8.0x, 5.0x (open/close imbalances, news gaps)

Usage (from engine/):
    .venv/Scripts/python -u -m scripts.cost_sensitivity_sweep \\
        --symbol MES --family trend --rank 1
    .venv/Scripts/python -u -m scripts.cost_sensitivity_sweep \\
        --symbol MCL --family meanrev --rank 1
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ENGINE = _HERE.parent
if str(_ENGINE) not in sys.path:
    sys.path.insert(0, str(_ENGINE))

from backtest.contract_specs import get_spec  # noqa: E402
from backtest.data_loader import BacktestDataLoader  # noqa: E402

COST_SCENARIOS = [
    ("optimistic",   {"commission_mult": 0.5, "slippage_mult": 0.5}),
    ("baseline",     {"commission_mult": 1.0, "slippage_mult": 1.0}),
    ("realistic",    {"commission_mult": 2.0, "slippage_mult": 2.0}),
    ("stressed",     {"commission_mult": 4.0, "slippage_mult": 3.0}),
    ("catastrophic", {"commission_mult": 8.0, "slippage_mult": 5.0}),
]


def _scaled_spec(symbol: str, commission_mult: float, slippage_mult: float) -> dict:
    """Build a per-scenario spec dict compatible with research _run() signatures."""
    s = get_spec(symbol)
    return {
        "multiplier": s.multiplier,
        "tick_size": s.tick_size,
        "commission": s.commission * commission_mult,
        "slippage_ticks": max(1, int(round(s.slippage_ticks * slippage_mult))),
    }


def _load_params(results_file: Path, rank: int) -> dict:
    """Fetch combo params from a research-results JSON (flat shape)."""
    with open(results_file) as f:
        doc = json.load(f)
    results = doc.get("results", [])
    if not results:
        raise ValueError(f"No results in {results_file}")
    if rank < 1 or rank > len(results):
        raise ValueError(f"rank={rank} out of range (1..{len(results)})")
    return results[rank - 1].get("params", {})


def main():
    ap = argparse.ArgumentParser(description="Cost sensitivity sweep (Tier A A5)")
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--family", required=True,
                    choices=["trend", "meanrev", "breakout", "meanrev_regime",
                             "composite", "saty", "tpo"],
                    help="Strategy family (dispatches to the matching research _run)")
    ap.add_argument("--rank", type=int, default=1,
                    help="Which rank from the research results file to sweep")
    ap.add_argument("--results-file", default=None,
                    help="Override auto-detected results file")
    ap.add_argument("--start", default="2024-06-01")
    ap.add_argument("--end", default="2026-03-27")
    ap.add_argument("--interval", default="1h")
    args = ap.parse_args()

    symbol = args.symbol.upper()

    # Dispatch to the matching research harness
    if args.family == "trend":
        from scripts.mes_trend_search import _run as _run_trend
        default_rf = _ENGINE / "scripts" / f"{symbol.lower()}_trend_search_results.json"
        def runner(df, params, spec):
            return _run_trend(df, params["fast"], params["slow"],
                              params["atr_trail_mult"], spec)
    elif args.family == "meanrev":
        from scripts.mcl_meanrev_search import _run as _run_meanrev
        default_rf = _ENGINE / "scripts" / f"{symbol.lower()}_meanrev_search_results.json"
        def runner(df, params, spec):
            return _run_meanrev(df, params["bb_period"], params["bb_std"],
                                params["atr_stop_mult"], params["max_hold_bars"], spec)
    elif args.family == "breakout":
        from scripts.mnq_breakout_search import _run as _run_breakout
        default_rf = _ENGINE / "scripts" / f"{symbol.lower()}_breakout_search_results.json"
        def runner(df, params, spec):
            return _run_breakout(
                df,
                donchian_period=params["donchian_period"],
                vol_ma_period=params.get("vol_ma_period", 20),
                vol_mult=params.get("vol_mult", 1.0),
                stop_atr_mult=params.get("stop_atr_mult", 2.0),
                short_only=params.get("short_only", True),
                spec=spec,
            )
    elif args.family == "composite":
        from scripts.mes_composite_search import _run as _run_harness
        default_rf = _ENGINE / "scripts" / f"{symbol.lower()}_composite_search_results.json"
        def runner(df, params, spec):
            return _run_harness(df, params["entry_threshold"], params["band_mult"], spec, symbol)
    elif args.family == "saty":
        from scripts.mes_saty_search import _run as _run_harness
        default_rf = _ENGINE / "scripts" / f"{symbol.lower()}_saty_search_results.json"
        def runner(df, params, spec):
            return _run_harness(df, params["target_ratio"], spec, symbol)
    elif args.family == "tpo":
        from scripts.mes_tpo_search import _run as _run_harness
        default_rf = _ENGINE / "scripts" / f"{symbol.lower()}_tpo_search_results.json"
        def runner(df, params, spec):
            return _run_harness(df, params["enter"], params["stop_mult"], spec, symbol)
    else:  # meanrev_regime — Bollinger+RSI w/ regime filter (MCL bbwidth variant)
        from scripts.mcl_meanrev_regime_search import _run as _run_regime
        default_rf = _ENGINE / "scripts" / \
            f"{symbol.lower()}_meanrev_regime_search_results.json"
        def runner(df, params, spec):
            return _run_regime(
                df,
                bb_period=params["bb_period"],
                bb_std=params["bb_std"],
                rsi_long=params.get("rsi_long", 30.0),
                rsi_short=params.get("rsi_short", 70.0),
                stop_atr_mult=params["stop_atr_mult"],
                regime_filter_mode=params.get("regime_filter_mode", "bbwidth"),
                regime_filter_bbwidth_pct=params.get("regime_filter_bbwidth_pct", 40.0),
                regime_filter_adx_threshold=params.get("regime_filter_adx_threshold", 20.0),
                spec=spec,
            )

    results_file = Path(args.results_file) if args.results_file else default_rf
    params = _load_params(results_file, args.rank)
    print(f"Sweeping cost scenarios on {symbol} {args.family} rank={args.rank} params={params}", flush=True)

    t0 = time.time()
    loader = BacktestDataLoader()
    df = loader.load(symbol, args.start, args.end, args.interval)
    if df is None or df.empty:
        print(f"[ERROR] No data loaded for {symbol}", flush=True)
        return 1
    print(f"Loaded {len(df)} bars ({args.start} -> {args.end})\n", flush=True)

    scenario_results = []
    for label, mult in COST_SCENARIOS:
        spec = _scaled_spec(symbol, mult["commission_mult"], mult["slippage_mult"])
        r = runner(df, params, spec)
        if r.get("skipped"):
            continue
        scenario_results.append({
            "scenario": label,
            "commission_mult": mult["commission_mult"],
            "slippage_mult": mult["slippage_mult"],
            "commission": spec["commission"],
            "slippage_ticks": spec["slippage_ticks"],
            "pf": r["pf"],
            "wr": r["wr"],
            "total_trades": r["total_trades"],
            "net_pnl": r["net_pnl"],
            "ret_pct": r["ret_pct"],
        })

    print(f"{'scenario':>13}  {'comm_x':>6}  {'slip_x':>6}  {'comm':>6}  {'slip_t':>6}  "
          f"{'PF':>6}  {'WR%':>5}  {'n':>4}  {'ret%':>7}", flush=True)
    print("-" * 80, flush=True)
    for r in scenario_results:
        print(f"{r['scenario']:>13}  {r['commission_mult']:>6.1f}  {r['slippage_mult']:>6.1f}  "
              f"${r['commission']:>5.2f}  {r['slippage_ticks']:>6}  "
              f"{r['pf']:>6.2f}  {r['wr']:>5.1f}  {r['total_trades']:>4}  "
              f"{r['ret_pct']:>+7.2f}", flush=True)

    # Breakeven level — the worst scenario where PF >= 1.0
    breakeven = None
    for r in scenario_results:
        if r["pf"] >= 1.0:
            breakeven = r["scenario"]
    if breakeven:
        print(f"\nEdge survives up through: {breakeven}", flush=True)
    else:
        print("\nEdge does NOT survive even the optimistic cost scenario.", flush=True)

    out_path = _ENGINE / "scripts" / "validation_reports" / \
               f"{symbol}_{args.family}_rank{args.rank}_cost_sweep.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump({
            "symbol": symbol, "family": args.family, "rank": args.rank,
            "params": params, "interval": args.interval,
            "start": args.start, "end": args.end,
            "elapsed_sec": round(time.time() - t0, 1),
            "scenarios": scenario_results,
            "edge_survives_through": breakeven,
        }, f, indent=2)
    print(f"\nSaved cost sweep to {out_path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
