"""
MNQ Donchian-breakout grid search + ALT-battery harness (2026-04-22).

Motivation: MNQ SHORT-only don=20 cleared gate v2 CORE criterion DSR=1.0 but
failed the MBB PF CI floor (1.07 < 1.10) and the MC 95th DD cap on a $10K
account (22% >> 6%). The ALT path requires rolling_wfo + fixed_params +
cost_sensitivity_sweep aux validators, each of which dispatches by `--family`
to a per-family `_run(df, params, spec) -> dict` harness. This script provides
the `breakout` family's harness plus a standalone grid-search CLI.

Usage (from engine/):
    # Grid search + leaderboard:
    .venv/Scripts/python -u -m scripts.mnq_breakout_search --symbol MNQ
    # The rolling_wfo / fixed_params / cost_sweep validators import _run directly.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

_HERE = Path(__file__).resolve().parent
_ENGINE = _HERE.parent
if str(_ENGINE) not in sys.path:
    sys.path.insert(0, str(_ENGINE))

from backtest.breakout_signals import generate_donchian_breakout_signals  # noqa: E402
from backtest.contract_specs import CONTRACT_SPECS  # noqa: E402
from backtest.data_loader import BacktestDataLoader  # noqa: E402

SYMBOL_SPECS = {
    sym: {
        "multiplier": spec.multiplier,
        "tick_size": spec.tick_size,
        "commission": spec.commission,
        "slippage_ticks": spec.slippage_ticks,
    }
    for sym, spec in CONTRACT_SPECS.items()
    if sym in ("MNQ", "MES", "MCL", "MGC")
}

CONTRACTS = 1
INITIAL_CAPITAL = 10_000.0

GRID = {
    "donchian_period": [15, 20, 25, 30, 40],
    "vol_mult":        [0.0, 1.0, 1.5],
    "stop_atr_mult":   [1.5, 2.0, 2.5],
    "short_only":      [True, False],
}


def _run(
    df: pd.DataFrame,
    donchian_period: int,
    vol_ma_period: int,
    vol_mult: float,
    stop_atr_mult: float,
    short_only: bool,
    spec: dict,
) -> dict:
    """Simulate Donchian-breakout trades and return the standard metrics dict.

    Same result schema as scripts.mes_trend_search._run() so the ALT validators
    (rolling_wfo_validator, fixed_params_temporal_validator, cost_sensitivity_sweep)
    can consume this output without special-casing.

    Args:
        short_only: if True, long-side entries are dropped (per MNQ SHORT-only
            asymmetry found in the first-pass search).
    """
    sig = generate_donchian_breakout_signals(
        df,
        donchian_period=donchian_period,
        vol_ma_period=vol_ma_period,
        vol_mult=vol_mult,
        stop_atr_mult=stop_atr_mult,
    )

    multiplier = spec["multiplier"]
    tick_size = spec["tick_size"]
    commission = spec["commission"]
    slippage_ticks = spec.get("slippage_ticks", 2)

    slip_usd = slippage_ticks * tick_size * multiplier * CONTRACTS
    commission_round = commission * 2 * CONTRACTS

    in_pos = False
    direction = 0  # +1 long, -1 short
    entry_price = 0.0
    entry_time = None
    stop_price = 0.0
    trades = []

    close = sig["close"].values
    high = sig["high"].values
    low = sig["low"].values
    entry_signal = sig["entry_signal"].values
    exit_signal = sig["exit_signal"].values
    bias = sig["bias"].values
    stop_level = sig["stop_level"].values
    idx = sig.index

    for i in range(len(sig)):
        bar_time = idx[i]

        if in_pos:
            bar_high = float(high[i])
            bar_low = float(low[i])
            # Stop hit check: long stop hit if low ≤ stop, short stop hit if high ≥ stop.
            stop_hit = (
                (direction == +1 and bar_low <= stop_price)
                or (direction == -1 and bar_high >= stop_price)
            )

            # Exit signal from the generator (channel re-entry)
            exit_fired = exit_signal[i] == "EXIT_NOW"

            if stop_hit or exit_fired:
                exit_price = stop_price if stop_hit else float(close[i])
                pnl = (
                    (exit_price - entry_price) * direction * multiplier * CONTRACTS
                    - 2 * slip_usd - commission_round
                )
                trades.append({
                    "entry_time": str(entry_time),
                    "exit_time": str(bar_time),
                    "entry": entry_price,
                    "exit": exit_price,
                    "direction": "long" if direction == +1 else "short",
                    "pnl": pnl,
                    "reason": "stop" if stop_hit else "channel_exit",
                })
                in_pos = False
                direction = 0
                continue

        if not in_pos and entry_signal[i] == "ENTRY_NOW":
            b = bias[i]
            # Apply short_only filter
            if short_only and b == "STRONG_BULL":
                continue
            if b == "STRONG_BULL":
                direction = +1
            elif b == "STRONG_BEAR":
                direction = -1
            else:
                continue
            entry_price = float(close[i])
            entry_time = bar_time
            stop_price = float(stop_level[i])
            in_pos = True

    # Force-close any open position at the last bar
    if in_pos:
        exit_price = float(close[-1])
        pnl = (
            (exit_price - entry_price) * direction * multiplier * CONTRACTS
            - 2 * slip_usd - commission_round
        )
        trades.append({
            "entry_time": str(entry_time),
            "exit_time": str(idx[-1]),
            "entry": entry_price,
            "exit": exit_price,
            "direction": "long" if direction == +1 else "short",
            "pnl": pnl,
            "reason": "end_of_data",
        })

    if not trades:
        return {"total_trades": 0, "pf": 0.0, "wr": 0.0, "net_pnl": 0.0, "ret_pct": 0.0,
                "trades": [], "avg_win": 0.0, "avg_loss": 0.0}

    pnls = [t["pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    pf = gross_profit / gross_loss if gross_loss > 0 else float("inf")
    wr = len(wins) / len(pnls)
    net_pnl = sum(pnls)
    ret_pct = net_pnl / INITIAL_CAPITAL * 100

    return {
        "total_trades": len(trades),
        "pf": round(pf, 3) if pf != float("inf") else 999.0,
        "wr": round(wr * 100, 2),
        "net_pnl": round(net_pnl, 2),
        "ret_pct": round(ret_pct, 2),
        "trades": trades,
        "avg_win": round(float(np.mean(wins)), 2) if wins else 0.0,
        "avg_loss": round(float(np.mean(losses)), 2) if losses else 0.0,
    }


def main():
    ap = argparse.ArgumentParser(description="MNQ Donchian-breakout grid search (ALT-battery harness)")
    ap.add_argument("--symbol", default="MNQ", choices=sorted(SYMBOL_SPECS.keys()))
    ap.add_argument("--interval", default="1h")
    ap.add_argument("--start", default="2024-04-01")
    ap.add_argument("--end", default="2026-03-27")
    ap.add_argument("--vol-ma-period", type=int, default=20)
    args = ap.parse_args()

    symbol = args.symbol.upper()
    spec = SYMBOL_SPECS[symbol]

    t0 = time.time()
    loader = BacktestDataLoader()
    df = loader.load(symbol, args.start, args.end, args.interval)
    if df is None or df.empty:
        print(f"[ERROR] No data loaded for {symbol}", flush=True)
        return 1
    print(f"Loaded {len(df)} bars for {symbol} {args.interval} {args.start}->{args.end}", flush=True)
    print(f"Contract spec: mult={spec['multiplier']} tick={spec['tick_size']} "
          f"commission={spec['commission']} slippage_ticks={spec['slippage_ticks']}", flush=True)

    combos = [dict(zip(GRID.keys(), vals, strict=False)) for vals in product(*GRID.values())]
    print(f"Breakout grid: {len(combos)} combos", flush=True)

    results = []
    for i, params in enumerate(combos, 1):
        r = _run(
            df,
            donchian_period=params["donchian_period"],
            vol_ma_period=args.vol_ma_period,
            vol_mult=params["vol_mult"],
            stop_atr_mult=params["stop_atr_mult"],
            short_only=params["short_only"],
            spec=spec,
        )
        results.append({"params": {**params, "vol_ma_period": args.vol_ma_period}, **r})
        flag = ""
        if r["pf"] >= 1.5 and r["total_trades"] >= 20:
            flag = "  <- candidate PF>=1.5"
        elif r["pf"] >= 1.3 and r["total_trades"] >= 20:
            flag = "  <- weak-candidate PF>=1.3"
        print(
            f"[{i:3d}/{len(combos)}] don={params['donchian_period']:3d} vm={params['vol_mult']:.1f} "
            f"stop={params['stop_atr_mult']:.1f} so={params['short_only']!s:<5}  "
            f"PF={r['pf']:6.2f}  WR={r['wr']:5.1f}%  n={r['total_trades']:3d}  "
            f"ret={r['ret_pct']:+6.2f}%{flag}",
            flush=True,
        )

    results.sort(key=lambda x: (x["pf"] == 999.0, -x["pf"]))
    out_path = Path(__file__).parent / f"{symbol.lower()}_breakout_search_results.json"
    with open(out_path, "w") as f:
        json.dump({
            "symbol": symbol,
            "interval": args.interval,
            "start": args.start,
            "end": args.end,
            "spec": spec,
            "n_combos": len(combos),
            "elapsed_sec": round(time.time() - t0, 1),
            "results": results,
        }, f, indent=2)

    print(f"\nSaved {len(results)} results to {out_path}", flush=True)
    print(f"\nTOP 10 by PF ({symbol}):", flush=True)
    print(f"{'rank':>4} {'PF':>7} {'WR%':>6} {'n':>4} {'ret%':>7}  params", flush=True)
    for i, r in enumerate(results[:10], 1):
        p = r["params"]
        print(
            f"{i:>4} {r['pf']:>7.2f} {r['wr']:>6.1f} {r['total_trades']:>4d} {r['ret_pct']:>+7.2f}  "
            f"don={p['donchian_period']} vm={p['vol_mult']} stop={p['stop_atr_mult']} so={p['short_only']}",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
