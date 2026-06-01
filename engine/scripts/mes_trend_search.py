"""
Per-symbol trend-following grid search (2026-04-20, parameterized 2026-04-21).

Motivation: composite + ORB both returned best PF < 1.0 on MES 1h
2024-06-01 → 2026-03-27, while buy-and-hold returned +23.4%. The
entries are actively destructive. Pivot: stay LONG during uptrends
via SMA crossover, exit on trend reversal.

Strategy: when fast SMA > slow SMA, go long. Exit when fast <= slow.
No shorts. ATR trailing stop optional. EOD stays open (trend trade).
Tests a grid of (fast, slow, atr_stop) combos.

Run from engine/:
    .venv/Scripts/python -u -m scripts.mes_trend_search                # defaults MES
    .venv/Scripts/python -u -m scripts.mes_trend_search --symbol MCL   # crude
    .venv/Scripts/python -u -m scripts.mes_trend_search --symbol MNQ   # nasdaq
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

from backtest.contract_specs import CONTRACT_SPECS  # noqa: E402
from backtest.data_loader import BacktestDataLoader  # noqa: E402

# SYMBOL_SPECS is derived from the canonical CONTRACT_SPECS source so that
# commission / tick_size / multiplier / slippage never drift between research
# scripts and production Backtester. See engine/backtest/contract_specs.py.
SYMBOL_SPECS = {
    sym: {
        "multiplier": spec.multiplier,
        "tick_size": spec.tick_size,
        "commission": spec.commission,
        "slippage_ticks": spec.slippage_ticks,
    }
    for sym, spec in CONTRACT_SPECS.items()
    if sym in ("MES", "MCL", "MNQ", "MGC")
}

CONTRACTS = 1
INITIAL_CAPITAL = 10_000.0

GRID = {
    "fast": [5, 10, 20, 30, 40, 50],
    "slow": [20, 50, 100, 150, 200, 300],
    "atr_trail_mult": [0.0, 1.0, 2.0, 3.0, 5.0],  # 0.0 = no trail stop
}


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]  # noqa: E741  # OHLC convention
    prev_c = c.shift(1)
    tr = pd.concat([(h - l), (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def _run(df: pd.DataFrame, fast: int, slow: int, atr_trail_mult: float, spec: dict) -> dict:
    if fast >= slow:
        return {"skipped": "fast>=slow"}
    sma_fast = df["close"].rolling(fast).mean()
    sma_slow = df["close"].rolling(slow).mean()
    atr = _atr(df, 14)

    multiplier = spec["multiplier"]
    tick_size = spec["tick_size"]
    commission = spec["commission"]
    slippage_ticks = spec.get("slippage_ticks", 1)  # per-symbol, per canonical spec

    in_pos = False
    entry = 0.0
    trail_stop = 0.0
    entry_time = None
    trades = []

    slip_usd = slippage_ticks * tick_size * multiplier * CONTRACTS  # one leg
    commission_round = commission * 2 * CONTRACTS

    for i in range(len(df)):
        if pd.isna(sma_slow.iloc[i]):
            continue
        price = float(df["close"].iloc[i])
        bar_time = df.index[i]

        if in_pos:
            # Update trail stop
            if atr_trail_mult > 0 and not pd.isna(atr.iloc[i]):
                new_stop = price - atr_trail_mult * float(atr.iloc[i])
                if new_stop > trail_stop:
                    trail_stop = new_stop

            # Check exit: trail stop OR SMA crossover back
            stop_hit = atr_trail_mult > 0 and float(df["low"].iloc[i]) <= trail_stop
            cross_down = sma_fast.iloc[i] <= sma_slow.iloc[i]

            if stop_hit or cross_down:
                exit_price = trail_stop if stop_hit else price
                # Slippage: +1 tick on entry, -1 tick on exit
                pnl = (exit_price - entry) * multiplier * CONTRACTS - 2 * slip_usd - commission_round
                trades.append({
                    "entry_time": str(entry_time),
                    "exit_time": str(bar_time),
                    "entry": entry,
                    "exit": exit_price,
                    "pnl": pnl,
                    "reason": "trail_stop" if stop_hit else "cross_down",
                })
                in_pos = False
        else:
            # Entry: cross up
            if sma_fast.iloc[i] > sma_slow.iloc[i] and i > 0 and sma_fast.iloc[i-1] <= sma_slow.iloc[i-1]:
                entry = price
                entry_time = bar_time
                if atr_trail_mult > 0 and not pd.isna(atr.iloc[i]):
                    trail_stop = price - atr_trail_mult * float(atr.iloc[i])
                else:
                    trail_stop = 0.0
                in_pos = True

    # Force-close any open position at the last bar
    if in_pos:
        exit_price = float(df["close"].iloc[-1])
        pnl = (exit_price - entry) * multiplier * CONTRACTS - 2 * slip_usd - commission_round
        trades.append({
            "entry_time": str(entry_time),
            "exit_time": str(df.index[-1]),
            "entry": entry,
            "exit": exit_price,
            "pnl": pnl,
            "reason": "end_of_data",
        })

    if not trades:
        return {"total_trades": 0, "pf": 0.0, "wr": 0.0, "net_pnl": 0.0}

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
        "trades": trades,  # Full per-trade list for bootstrap / MC validators
        "avg_win": round(np.mean(wins), 2) if wins else 0.0,
        "avg_loss": round(np.mean(losses), 2) if losses else 0.0,
    }


def main():
    ap = argparse.ArgumentParser(description="Per-symbol SMA trend-following grid search")
    ap.add_argument("--symbol", default="MES", choices=sorted(SYMBOL_SPECS.keys()))
    ap.add_argument("--interval", default="1h")
    ap.add_argument("--start", default="2024-06-01")
    ap.add_argument("--end", default="2026-03-27")
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
          f"tick_value=${spec['multiplier']*spec['tick_size']:.2f}", flush=True)

    combos = [dict(zip(GRID.keys(), vals, strict=False)) for vals in product(*GRID.values())]
    combos = [c for c in combos if c["fast"] < c["slow"]]
    print(f"Trend grid: {len(combos)} valid combos", flush=True)

    results = []
    for i, params in enumerate(combos, 1):
        r = _run(df, params["fast"], params["slow"], params["atr_trail_mult"], spec)
        if r.get("skipped"):
            continue
        results.append({"params": params, **r})
        flag = ""
        if r["pf"] >= 2.0 and r["total_trades"] >= 10:
            flag = "  <- WINNER PF>=2.0"
        elif r["pf"] >= 1.5 and r["total_trades"] >= 10:
            flag = "  <- backup PF>=1.5"
        elif r["ret_pct"] >= 10.0:
            flag = "  <- ret>=10%"
        print(
            f"[{i:3d}/{len(combos)}] fast={params['fast']:3d} slow={params['slow']:3d} "
            f"trail={params['atr_trail_mult']:.1f}  "
            f"PF={r['pf']:6.2f}  WR={r['wr']:5.1f}%  n={r['total_trades']:3d}  "
            f"ret={r['ret_pct']:+6.2f}%{flag}",
            flush=True,
        )

    # Sort with finite PF first, infinities last (no-loss = trivial/overfit, not a real winner)
    results.sort(key=lambda x: (x["pf"] == 999.0, -x["pf"]))
    out_path = Path(__file__).parent / f"{symbol.lower()}_trend_search_results.json"
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
            f"fast={p['fast']} slow={p['slow']} trail={p['atr_trail_mult']}",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
