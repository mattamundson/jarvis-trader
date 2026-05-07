"""
MCL mean-reversion grid search (2026-04-21).

Motivation: MCL trend-following (SMA crossover) failed both full-period
(top PF 1.16) and walk-forward (min_PF 1.17). Crude oil structurally
lacks the 1-directional trend persistence equity indices show, but is
known for volatility clustering — making Bollinger-Band mean reversion
the natural alternative hypothesis.

Strategy:
  - Long  entry: close crosses BELOW lower BB (std-dev band)
  - Long  exit : close crosses ABOVE middle BB (SMA of period)
  - Short entry: close crosses ABOVE upper BB
  - Short exit : close crosses BELOW middle BB
  - Hard stop : ATR * stop_mult from entry (symmetric up/down by side)
  - Time stop : max_hold_bars bars — closes at market if middle not reached

Grid: (bb_period, bb_std, atr_stop_mult, max_hold_bars) — long & short allowed.

Run from engine/:
    .venv/Scripts/python -u -m scripts.mcl_meanrev_search
    .venv/Scripts/python -u -m scripts.mcl_meanrev_search --symbol MNQ  # cross-check
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from itertools import product
from pathlib import Path

import pandas as pd

_HERE = Path(__file__).resolve().parent
_ENGINE = _HERE.parent
if str(_ENGINE) not in sys.path:
    sys.path.insert(0, str(_ENGINE))

from backtest.contract_specs import CONTRACT_SPECS  # noqa: E402
from backtest.data_loader import BacktestDataLoader  # noqa: E402

# SYMBOL_SPECS is derived from the canonical CONTRACT_SPECS source.
# See engine/backtest/contract_specs.py for the single source of truth.
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
    "bb_period":     [14, 20, 30, 50],
    "bb_std":        [1.5, 2.0, 2.5, 3.0],
    "atr_stop_mult": [1.5, 2.0, 3.0],
    "max_hold_bars": [20, 50, 100],
}


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]  # noqa: E741  # OHLC convention
    prev_c = c.shift(1)
    tr = pd.concat([(h - l), (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def _run(df: pd.DataFrame, bb_period: int, bb_std: float, atr_stop_mult: float,
         max_hold_bars: int, spec: dict) -> dict:
    mult = spec["multiplier"]
    tick_size = spec["tick_size"]
    commission = spec["commission"]
    slippage_ticks = spec.get("slippage_ticks", 1)
    slip_usd = slippage_ticks * tick_size * mult * CONTRACTS
    commission_round = commission * 2 * CONTRACTS

    sma = df["close"].rolling(bb_period).mean()
    std = df["close"].rolling(bb_period).std()
    upper = sma + bb_std * std
    lower = sma - bb_std * std
    atr = _atr(df, 14)

    in_pos = False
    side = 0       # +1 long, -1 short
    entry = 0.0
    entry_idx = 0
    stop = 0.0
    trades = []

    entry_time = None
    for i in range(len(df)):
        if pd.isna(lower.iloc[i]) or pd.isna(atr.iloc[i]):
            continue
        price = float(df["close"].iloc[i])
        prev_price = float(df["close"].iloc[i - 1]) if i > 0 else price
        bar_time = df.index[i]

        if in_pos:
            # Exit checks (order: stop → middle cross → time stop)
            if side > 0:
                if float(df["low"].iloc[i]) <= stop:
                    pnl = (stop - entry) * mult * CONTRACTS - 2 * slip_usd - commission_round
                    trades.append({"entry_time": str(entry_time), "exit_time": str(bar_time),
                                   "side": "long", "pnl": pnl, "reason": "stop"})
                    in_pos = False
                    continue
                if price >= sma.iloc[i] and prev_price < sma.iloc[i - 1]:
                    pnl = (price - entry) * mult * CONTRACTS - 2 * slip_usd - commission_round
                    trades.append({"entry_time": str(entry_time), "exit_time": str(bar_time),
                                   "side": "long", "pnl": pnl, "reason": "mid_cross"})
                    in_pos = False
                    continue
            else:
                if float(df["high"].iloc[i]) >= stop:
                    pnl = (entry - stop) * mult * CONTRACTS - 2 * slip_usd - commission_round
                    trades.append({"entry_time": str(entry_time), "exit_time": str(bar_time),
                                   "side": "short", "pnl": pnl, "reason": "stop"})
                    in_pos = False
                    continue
                if price <= sma.iloc[i] and prev_price > sma.iloc[i - 1]:
                    pnl = (entry - price) * mult * CONTRACTS - 2 * slip_usd - commission_round
                    trades.append({"entry_time": str(entry_time), "exit_time": str(bar_time),
                                   "side": "short", "pnl": pnl, "reason": "mid_cross"})
                    in_pos = False
                    continue
            # Time stop
            if i - entry_idx >= max_hold_bars:
                pnl = ((price - entry) if side > 0 else (entry - price)) * mult * CONTRACTS - 2 * slip_usd - commission_round
                trades.append({"entry_time": str(entry_time), "exit_time": str(bar_time),
                               "side": "long" if side > 0 else "short",
                               "pnl": pnl, "reason": "time_stop"})
                in_pos = False
                continue
        else:
            # Entry: close crosses outside band
            if prev_price >= lower.iloc[i - 1] and price < lower.iloc[i]:
                side = +1
                entry = price
                entry_idx = i
                entry_time = bar_time
                stop = entry - atr_stop_mult * float(atr.iloc[i])
                in_pos = True
            elif prev_price <= upper.iloc[i - 1] and price > upper.iloc[i]:
                side = -1
                entry = price
                entry_idx = i
                entry_time = bar_time
                stop = entry + atr_stop_mult * float(atr.iloc[i])
                in_pos = True

    # Close any open position at the last bar
    if in_pos:
        price = float(df["close"].iloc[-1])
        pnl = ((price - entry) if side > 0 else (entry - price)) * mult * CONTRACTS - 2 * slip_usd - commission_round
        trades.append({"entry_time": str(entry_time), "exit_time": str(df.index[-1]),
                       "side": "long" if side > 0 else "short",
                       "pnl": pnl, "reason": "end_of_data"})

    if not trades:
        return {"total_trades": 0, "pf": 0.0, "wr": 0.0, "net_pnl": 0.0, "ret_pct": 0.0}

    pnls = [t["pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    pf = gross_profit / gross_loss if gross_loss > 0 else 999.0
    wr = len(wins) / len(pnls) * 100
    net_pnl = sum(pnls)
    ret_pct = net_pnl / INITIAL_CAPITAL * 100

    return {
        "total_trades": len(trades),
        "pf": round(pf, 3),
        "wr": round(wr, 2),
        "net_pnl": round(net_pnl, 2),
        "ret_pct": round(ret_pct, 2),
        "trades": trades,  # Full per-trade list for bootstrap / MC validators
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="MCL", choices=sorted(SYMBOL_SPECS.keys()))
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

    combos = [dict(zip(GRID.keys(), vals, strict=False)) for vals in product(*GRID.values())]
    print(f"Mean-reversion grid: {len(combos)} combos", flush=True)

    results = []
    for i, p in enumerate(combos, 1):
        r = _run(df, p["bb_period"], p["bb_std"], p["atr_stop_mult"], p["max_hold_bars"], spec)
        results.append({"params": p, **r})
        flag = ""
        if r["pf"] >= 2.0 and r["total_trades"] >= 20:
            flag = "  <- WINNER PF>=2.0"
        elif r["pf"] >= 1.5 and r["total_trades"] >= 20:
            flag = "  <- backup PF>=1.5"
        print(
            f"[{i:3d}/{len(combos)}] bb={p['bb_period']:2d}x{p['bb_std']:.1f}std "
            f"stop={p['atr_stop_mult']:.1f}atr hold={p['max_hold_bars']:3d}  "
            f"PF={r['pf']:6.2f}  WR={r['wr']:5.1f}%  n={r['total_trades']:3d}  "
            f"ret={r['ret_pct']:+6.2f}%{flag}",
            flush=True,
        )

    results.sort(key=lambda x: (x["pf"] == 999.0, -x["pf"]))
    out_path = Path(__file__).parent / f"{symbol.lower()}_meanrev_search_results.json"
    with open(out_path, "w") as f:
        json.dump({
            "symbol": symbol, "interval": args.interval,
            "start": args.start, "end": args.end,
            "spec": spec, "n_combos": len(combos),
            "elapsed_sec": round(time.time() - t0, 1),
            "results": results,
        }, f, indent=2)

    print(f"\nSaved {len(results)} results to {out_path}", flush=True)
    print(f"\nTOP 10 by PF ({symbol}) — mean reversion:", flush=True)
    print(f"{'rank':>4} {'PF':>7} {'WR%':>6} {'n':>4} {'ret%':>7}  params", flush=True)
    for i, r in enumerate(results[:10], 1):
        p = r["params"]
        print(
            f"{i:>4} {r['pf']:>7.2f} {r['wr']:>6.1f} {r['total_trades']:>4d} {r['ret_pct']:>+7.2f}  "
            f"bb={p['bb_period']}x{p['bb_std']}std stop={p['atr_stop_mult']}atr hold={p['max_hold_bars']}",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
