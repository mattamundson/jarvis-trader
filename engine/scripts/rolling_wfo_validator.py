"""Rolling walk-forward validator — Tier A A6.

Single-split WFO (train 2024-06..2025-06, test 2025-06..2026-03) is a noisy
sample. This script uses `WalkForwardValidator.generate_windows()` to produce
N overlapping windows and runs the research `_run()` harness on each test
window. The output is a distribution of test-window profit factors — the
real robustness test for a strategy.

Verdict bands:
    STRONG    — median test PF >= 1.5, % profitable windows >= 70%
    MODERATE  — median test PF >= 1.3, % profitable windows >= 60%
    WEAK      — median test PF >= 1.1, % profitable windows >= 50%
    FAIL      — below all of the above

Usage (from engine/):
    .venv/Scripts/python -u -m scripts.rolling_wfo_validator \\
        --symbol MES --family trend --rank 1
    .venv/Scripts/python -u -m scripts.rolling_wfo_validator \\
        --symbol MCL --family meanrev --rank 1 --train-months 6 --test-months 2
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

_HERE = Path(__file__).resolve().parent
_ENGINE = _HERE.parent
if str(_ENGINE) not in sys.path:
    sys.path.insert(0, str(_ENGINE))

from backtest.contract_specs import get_spec  # noqa: E402
from backtest.data_loader import BacktestDataLoader  # noqa: E402
from backtest.walk_forward import WalkForwardValidator  # noqa: E402


def _spec_dict(symbol: str) -> dict:
    s = get_spec(symbol)
    return {
        "multiplier": s.multiplier,
        "tick_size": s.tick_size,
        "commission": s.commission,
        "slippage_ticks": s.slippage_ticks,
    }


def _load_params(results_file: Path, rank: int) -> dict:
    with open(results_file) as f:
        doc = json.load(f)
    results = doc.get("results", [])
    if rank < 1 or rank > len(results):
        raise ValueError(f"rank={rank} out of range (1..{len(results)})")
    return results[rank - 1].get("params", {})


def _verdict(median_pf: float, pct_profitable: float) -> str:
    if median_pf >= 1.5 and pct_profitable >= 70.0:
        return "STRONG"
    if median_pf >= 1.3 and pct_profitable >= 60.0:
        return "MODERATE"
    if median_pf >= 1.1 and pct_profitable >= 50.0:
        return "WEAK"
    return "FAIL"


def main():
    ap = argparse.ArgumentParser(description="Rolling walk-forward validator (Tier A A6)")
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--family", required=True,
                    choices=["trend", "meanrev", "breakout", "meanrev_regime",
                             "composite", "saty", "tpo"])
    ap.add_argument("--rank", type=int, default=1)
    ap.add_argument("--results-file", default=None)
    ap.add_argument("--start", default="2024-06-01")
    ap.add_argument("--end", default="2026-03-27")
    ap.add_argument("--interval", default="1h")
    ap.add_argument("--train-months", type=int, default=6)
    ap.add_argument("--test-months", type=int, default=2)
    ap.add_argument("--step-months", type=int, default=1)
    args = ap.parse_args()

    symbol = args.symbol.upper()

    # Dispatch to the matching research harness
    if args.family == "trend":
        from scripts.mes_trend_search import _run as _run_harness
        default_rf = _ENGINE / "scripts" / f"{symbol.lower()}_trend_search_results.json"
        def runner(df, params, spec):
            return _run_harness(df, params["fast"], params["slow"],
                                params["atr_trail_mult"], spec)
    elif args.family == "meanrev":
        from scripts.mcl_meanrev_search import _run as _run_harness
        default_rf = _ENGINE / "scripts" / f"{symbol.lower()}_meanrev_search_results.json"
        def runner(df, params, spec):
            return _run_harness(df, params["bb_period"], params["bb_std"],
                                params["atr_stop_mult"], params["max_hold_bars"], spec)
    elif args.family == "breakout":
        from scripts.mnq_breakout_search import _run as _run_harness
        default_rf = _ENGINE / "scripts" / f"{symbol.lower()}_breakout_search_results.json"
        def runner(df, params, spec):
            return _run_harness(
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
        from scripts.mcl_meanrev_regime_search import _run as _run_harness
        default_rf = _ENGINE / "scripts" / \
            f"{symbol.lower()}_meanrev_regime_search_results.json"
        def runner(df, params, spec):
            return _run_harness(
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
    spec = _spec_dict(symbol)

    print(f"Rolling WFO: {symbol} {args.family} rank={args.rank} params={params}", flush=True)
    print(f"  train={args.train_months}mo test={args.test_months}mo step={args.step_months}mo", flush=True)

    t0 = time.time()
    loader = BacktestDataLoader()
    df = loader.load(symbol, args.start, args.end, args.interval)
    if df is None or df.empty:
        print(f"[ERROR] No data for {symbol}", flush=True)
        return 1

    wfv = WalkForwardValidator(
        train_months=args.train_months,
        test_months=args.test_months,
        step_months=args.step_months,
    )
    windows = wfv.generate_windows(df, symbol)
    if not windows:
        print("[ERROR] No windows generated -- check date range vs train/test months", flush=True)
        return 1
    print(f"  Generated {len(windows)} windows\n", flush=True)

    per_window = []
    for w in windows:
        tr_df = df.loc[w["train_start"]:w["train_end"]]
        te_df = df.loc[w["test_start"]:w["test_end"]]
        if len(te_df) < 30:
            continue
        tr_r = runner(tr_df, params, spec)
        te_r = runner(te_df, params, spec)
        if tr_r.get("skipped") or te_r.get("skipped"):
            continue
        per_window.append({
            "window": w["window_num"],
            "train_start": str(w["train_start"])[:10],
            "train_end": str(w["train_end"])[:10],
            "test_start": str(w["test_start"])[:10],
            "test_end": str(w["test_end"])[:10],
            "train_pf": tr_r["pf"],
            "train_n": tr_r["total_trades"],
            "test_pf": te_r["pf"],
            "test_n": te_r["total_trades"],
            "test_ret_pct": te_r["ret_pct"],
        })

    # Filter to windows with a meaningful sample in test
    valid = [w for w in per_window if w["test_n"] >= 3]
    if not valid:
        print("[ERROR] No windows produced >= 3 test trades", flush=True)
        return 1

    test_pfs = np.array([w["test_pf"] for w in valid])
    # Replace 999 sentinels (no losses) with nan to avoid skewing percentiles
    finite = test_pfs[(test_pfs > 0) & (test_pfs < 900)]

    if len(finite) == 0:
        stats = {"median": 0.0, "p25": 0.0, "p75": 0.0, "p5": 0.0, "p95": 0.0}
    else:
        stats = {
            "median": round(float(np.median(finite)), 3),
            "p25":    round(float(np.percentile(finite, 25)), 3),
            "p75":    round(float(np.percentile(finite, 75)), 3),
            "p5":     round(float(np.percentile(finite, 5)), 3),
            "p95":    round(float(np.percentile(finite, 95)), 3),
        }
    profitable = sum(1 for w in valid if w["test_pf"] >= 1.0)
    pct_profitable = profitable / len(valid) * 100
    pct_pf_15 = sum(1 for w in valid if w["test_pf"] >= 1.5) / len(valid) * 100

    verdict = _verdict(stats["median"], pct_profitable)

    # Print per-window table
    print(f"{'#':>3} {'train':>10}-{'':10} {'test':>10}-{'':10} {'tr_PF':>6} {'tr_n':>4} {'te_PF':>6} {'te_n':>4} {'ret%':>7}", flush=True)
    for w in valid:
        print(f"{w['window']:>3} {w['train_start']}-{w['train_end']} "
              f"{w['test_start']}-{w['test_end']} "
              f"{w['train_pf']:>6.2f} {w['train_n']:>4} {w['test_pf']:>6.2f} "
              f"{w['test_n']:>4} {w['test_ret_pct']:>+7.2f}", flush=True)

    print(f"\nTest-PF distribution across {len(valid)} windows:", flush=True)
    print(f"  median={stats['median']} p25={stats['p25']} p75={stats['p75']} p5={stats['p5']} p95={stats['p95']}", flush=True)
    print(f"  profitable (PF>=1.0): {profitable}/{len(valid)} ({pct_profitable:.1f}%)", flush=True)
    print(f"  strong      (PF>=1.5): {int(pct_pf_15 * len(valid) / 100)}/{len(valid)} ({pct_pf_15:.1f}%)", flush=True)
    print(f"\nRobustness verdict: {verdict}", flush=True)

    out_path = _ENGINE / "scripts" / "validation_reports" / \
               f"{symbol}_{args.family}_rank{args.rank}_rolling_wfo.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump({
            "symbol": symbol, "family": args.family, "rank": args.rank,
            "params": params,
            "train_months": args.train_months, "test_months": args.test_months,
            "step_months": args.step_months,
            "start": args.start, "end": args.end,
            "windows": per_window,
            "n_valid_windows": len(valid),
            "test_pf_distribution": stats,
            "pct_profitable": round(pct_profitable, 2),
            "pct_test_pf_ge_1_5": round(pct_pf_15, 2),
            "verdict": verdict,
            "elapsed_sec": round(time.time() - t0, 1),
        }, f, indent=2)
    print(f"\nSaved to {out_path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
