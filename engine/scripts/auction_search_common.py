"""Shared backtest helper for the auction-family research search scripts.

The auction signals (composite / saty / tpo) emit backtester-compatible frames
(entry_signal / bias / stop_level / target_*), so — unlike the inline trend
search (`mes_trend_search.py`) — they are executed through the real `Backtester`
for faithful stop / target / trailing logic.

Costs are taken from the per-scenario `spec` dict (commission + slippage) and
passed into the Backtester via its constructor overrides, so the
cost-sensitivity sweep varies them exactly as it does for the trend champion.
`spread_ticks` is forced to 0 to match the trend research harness's cost model
(commission + slippage only, no separate half-spread), keeping the gate-v2
comparison between the auction families and the trend champion apples-to-apples.

The returned dict matches the standard research-harness contract
(total_trades, pf, wr, net_pnl, ret_pct, trades[]) consumed by
rolling_wfo_validator / fixed_params_temporal_validator / cost_sensitivity_sweep
and ultimately validate_strategy.py (which reads results[].trades[].pnl).
"""

from __future__ import annotations

from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent

INITIAL_CAPITAL = 10_000.0
CONTRACTS = 1

# Backtester execution semantics — identical to signal_confluence_audit._BT_KWARGS
# so the auction arms execute exactly as they did in the single-split screen.
_BT_KWARGS = {
    "initial_capital": INITIAL_CAPITAL,
    "trailing_stop": True,
    "t1_exit_pct": 1.0,
    "t2_exit_pct": 0.0,
    "strict_trailing": True,
    "eod_close": False,
    "use_targets": False,
    "fixed_contracts": CONTRACTS,
    "max_drawdown": 0.99,
    "max_daily_loss": 0.99,
}


def spec_dict(symbol: str) -> dict:
    """Build the canonical {multiplier, tick_size, commission, slippage_ticks}
    spec from CONTRACT_SPECS — the same source the validators use, so research
    and production never drift."""
    from backtest.contract_specs import get_spec  # lazy heavy import

    s = get_spec(symbol)
    return {
        "multiplier": s.multiplier,
        "tick_size": s.tick_size,
        "commission": s.commission,
        "slippage_ticks": s.slippage_ticks,
    }


def summarize_trades(trades: list[dict]) -> dict:
    """Aggregate a per-trade ledger into the standard research-harness contract.

    Mirrors mes_trend_search._run conventions exactly: PF uses a 999.0 sentinel
    for a no-loss combo (so rolling_wfo's `pf < 900` finite filter and the
    main() sort treat it as trivial/overfit, not a real winner).
    """
    if not trades:
        return {"total_trades": 0, "pf": 0.0, "wr": 0.0, "net_pnl": 0.0,
                "ret_pct": 0.0, "trades": []}
    pnls = [float(t["pnl"]) for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    pf = gross_profit / gross_loss if gross_loss > 0 else float("inf")
    net_pnl = sum(pnls)
    return {
        "total_trades": len(trades),
        "pf": round(pf, 3) if pf != float("inf") else 999.0,
        "wr": round(len(wins) / len(pnls) * 100, 2),
        "net_pnl": round(net_pnl, 2),
        "ret_pct": round(net_pnl / INITIAL_CAPITAL * 100, 2),
        "trades": trades,
    }


def run_signal_bt(df_sig, symbol: str, atr_trail: float, spec: dict) -> dict:
    """Backtest a backtester-compatible signal frame; costs come from `spec`.

    Parameters
    ----------
    df_sig : DataFrame
        Output of an auction signal generator (entry_signal / stop_level / etc.).
    symbol : str
        Instrument symbol (passed to Backtester.run).
    atr_trail : float
        Trailing-stop ATR multiple.
    spec : dict
        {multiplier, tick_size, commission, slippage_ticks} — the per-scenario
        cost spec the cost sweep scales. commission/slippage flow into the
        Backtester; spread is forced to 0 (see module docstring).
    """
    from backtest import Backtester  # lazy heavy import — keeps module import cheap

    bt = Backtester(
        **_BT_KWARGS,
        trailing_atr_mult=atr_trail,
        commission_per_contract=spec["commission"],
        slippage_ticks=spec["slippage_ticks"],
        spread_ticks=0.0,  # match trend research harness cost model (no half-spread)
    )
    r = bt.run(df_sig, symbol, spec["multiplier"])
    trades = [t.to_dict() for t in r.trades]
    return summarize_trades(trades)


def run_grid_search(family: str, grid: dict, run_one, default_symbol: str = "MES") -> int:
    """CLI grid-search driver shared by the auction search scripts.

    Loads OHLCV, runs `run_one(df, params, spec, symbol)` over the cartesian
    product of `grid`, writes `{symbol}_{family}_search_results.json` (sorted by
    PF, 999 sentinels last) with per-trade ledgers, and prints a top-10 table.
    `run_one` returns the standard contract from summarize_trades/run_signal_bt.
    """
    import argparse
    import json
    import time
    from itertools import product

    from backtest.data_loader import BacktestDataLoader  # lazy heavy import

    ap = argparse.ArgumentParser(description=f"MES {family} grid search (auction gate-v2 input)")
    ap.add_argument("--symbol", default=default_symbol)
    ap.add_argument("--interval", default="1h")
    ap.add_argument("--start", default="2024-06-01")
    ap.add_argument("--end", default="2026-03-27")
    args = ap.parse_args()

    symbol = args.symbol.upper()
    spec = spec_dict(symbol)

    t0 = time.time()
    df = BacktestDataLoader().load(symbol, args.start, args.end, args.interval)
    if df is None or df.empty:
        print(f"[ERROR] No data loaded for {symbol}", flush=True)
        return 1
    print(f"Loaded {len(df)} bars for {symbol} {args.interval} {args.start}->{args.end}", flush=True)

    combos = [dict(zip(grid.keys(), vals, strict=False)) for vals in product(*grid.values())]
    print(f"{family} grid: {len(combos)} combos", flush=True)

    results = []
    for i, params in enumerate(combos, 1):
        r = run_one(df, params, spec, symbol)
        if r.get("skipped"):
            continue
        results.append({"params": params, **r})
        print(
            f"[{i:2d}/{len(combos)}] {params}  PF={r['pf']:6.2f}  WR={r['wr']:5.1f}%  "
            f"n={r['total_trades']:3d}  ret={r['ret_pct']:+6.2f}%",
            flush=True,
        )

    # Finite PF first, 999 (no-loss/trivial) sentinels last — matches mes_trend_search.
    results.sort(key=lambda x: (x["pf"] == 999.0, -x["pf"]))
    out_path = _SCRIPTS_DIR / f"{symbol.lower()}_{family}_search_results.json"
    with open(out_path, "w") as f:
        json.dump({
            "symbol": symbol,
            "family": family,
            "interval": args.interval,
            "start": args.start,
            "end": args.end,
            "spec": spec,
            "n_combos": len(combos),
            "elapsed_sec": round(time.time() - t0, 1),
            "results": results,
        }, f, indent=2)

    print(f"\nSaved {len(results)} results to {out_path}", flush=True)
    print(f"\nTOP 10 by PF ({symbol} {family}):", flush=True)
    print(f"{'rank':>4} {'PF':>7} {'WR%':>6} {'n':>4} {'ret%':>7}  params", flush=True)
    for i, r in enumerate(results[:10], 1):
        print(f"{i:>4} {r['pf']:>7.2f} {r['wr']:>6.1f} {r['total_trades']:>4d} "
              f"{r['ret_pct']:>+7.2f}  {r['params']}", flush=True)
    return 0
