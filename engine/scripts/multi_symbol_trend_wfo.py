"""
Cross-instrument trend-following WFO — MES/MCL/MNQ (2026-04-20).

Validates whether the SMA(50, 200) + 2.0xATR trend edge found on MES
1h generalizes to MCL and MNQ. Runs the same walk-forward split
(train=2024-06->2025-06, test=2025-06->2026-03) with per-symbol
contract multipliers and commission/slippage.

Pass criterion: train PF >= 2.0 AND test PF >= 1.5 on each symbol with
the same config as MES winner.
"""

from __future__ import annotations

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

SYMBOLS = ["MES", "MCL", "MNQ"]
INTERVAL = "1h"
TRAIN = ("2024-06-01", "2025-06-01")
TEST = ("2025-06-01", "2026-03-27")
INITIAL_CAPITAL = 10_000.0
CONTRACTS = 1

# SPECS is derived from canonical CONTRACT_SPECS. See backtest/contract_specs.py.
SPECS = {
    sym: {
        "multiplier": CONTRACT_SPECS[sym].multiplier,
        "tick_size": CONTRACT_SPECS[sym].tick_size,
        "slip_ticks": CONTRACT_SPECS[sym].slippage_ticks,
        "commission": CONTRACT_SPECS[sym].commission,
    }
    for sym in SYMBOLS
}

# Focused grid informed by MES WFO top-6 cluster
GRID = {
    "fast": [30, 40, 50, 60],
    "slow": [150, 180, 200, 220, 300],
    "atr_trail_mult": [2.0, 2.5, 3.0, 3.5, 5.0],
}

MES_WINNER = {"fast": 50, "slow": 200, "trail": 2.0}


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]  # noqa: E741  # OHLC convention
    prev_c = c.shift(1)
    tr = pd.concat([(h - l), (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def _run(df: pd.DataFrame, symbol: str, fast: int, slow: int, trail: float) -> dict:
    if fast >= slow:
        return {"skipped": "fast>=slow"}
    spec = SPECS[symbol]
    mult = spec["multiplier"]
    slip_usd = spec["slip_ticks"] * spec["tick_size"] * mult * CONTRACTS
    commission_round = spec["commission"] * 2 * CONTRACTS

    sma_fast = df["close"].rolling(fast).mean()
    sma_slow = df["close"].rolling(slow).mean()
    atr = _atr(df, 14)

    in_pos = False
    entry = 0.0
    trail_stop = 0.0
    trades = []

    for i in range(len(df)):
        if pd.isna(sma_slow.iloc[i]):
            continue
        price = float(df["close"].iloc[i])

        if in_pos:
            if trail > 0 and not pd.isna(atr.iloc[i]):
                new_stop = price - trail * float(atr.iloc[i])
                if new_stop > trail_stop:
                    trail_stop = new_stop
            stop_hit = trail > 0 and float(df["low"].iloc[i]) <= trail_stop
            cross_down = sma_fast.iloc[i] <= sma_slow.iloc[i]
            if stop_hit or cross_down:
                exit_price = trail_stop if stop_hit else price
                pnl = (exit_price - entry) * mult * CONTRACTS - 2 * slip_usd - commission_round
                trades.append({"pnl": pnl})
                in_pos = False
        else:
            if sma_fast.iloc[i] > sma_slow.iloc[i] and i > 0 and sma_fast.iloc[i-1] <= sma_slow.iloc[i-1]:
                entry = price
                trail_stop = price - trail * float(atr.iloc[i]) if trail > 0 and not pd.isna(atr.iloc[i]) else 0.0
                in_pos = True

    if in_pos:
        exit_price = float(df["close"].iloc[-1])
        pnl = (exit_price - entry) * mult * CONTRACTS - 2 * slip_usd - commission_round
        trades.append({"pnl": pnl})

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


def _load_pair(loader, symbol):
    tr = loader.load(symbol, TRAIN[0], TRAIN[1], INTERVAL)
    te = loader.load(symbol, TEST[0], TEST[1], INTERVAL)
    return tr, te


def main():
    t0 = time.time()
    loader = BacktestDataLoader()

    summary = {}

    # --- Stage 1: MES winner applied to MCL/MNQ directly ---
    print("=" * 72, flush=True)
    print("STAGE 1: apply MES winner SMA(50,200) trail=2.0 directly to each symbol", flush=True)
    print("=" * 72, flush=True)
    for sym in SYMBOLS:
        df_tr, df_te = _load_pair(loader, sym)
        if df_tr is None or df_te is None:
            print(f"{sym}: DATA MISSING", flush=True)
            continue
        tr = _run(df_tr, sym, **MES_WINNER)
        te = _run(df_te, sym, **MES_WINNER)
        status = "PASS" if tr["pf"] >= 2.0 and te["pf"] >= 1.5 and tr["total_trades"] >= 5 and te["total_trades"] >= 5 else "FAIL"
        print(
            f"{sym}: train PF={tr['pf']:5.2f} n={tr['total_trades']:2d} ret={tr['ret_pct']:+6.1f}% | "
            f"test PF={te['pf']:5.2f} n={te['total_trades']:2d} ret={te['ret_pct']:+6.1f}%  [{status}]",
            flush=True,
        )
        summary[f"{sym}_mes_winner"] = {"train": tr, "test": te, "status": status}

    # --- Stage 2: symbol-specific WFO grid ---
    print("\n" + "=" * 72, flush=True)
    print("STAGE 2: focused WFO grid per symbol (100 combos each)", flush=True)
    print("=" * 72, flush=True)

    combos = [dict(zip(GRID.keys(), vals, strict=False)) for vals in product(*GRID.values())]
    combos = [c for c in combos if c["fast"] < c["slow"]]

    for sym in SYMBOLS:
        df_tr, df_te = _load_pair(loader, sym)
        if df_tr is None or df_te is None:
            continue
        print(f"\n-- {sym} ({len(combos)} combos) --", flush=True)

        per_sym_results = []
        for p in combos:
            tr = _run(df_tr, sym, p["fast"], p["slow"], p["atr_trail_mult"])
            te = _run(df_te, sym, p["fast"], p["slow"], p["atr_trail_mult"])
            if tr.get("skipped") or te.get("skipped"):
                continue
            if tr["total_trades"] < 5 or te["total_trades"] < 5:
                continue
            entry = {
                "params": p,
                "train_pf": tr["pf"], "train_n": tr["total_trades"], "train_ret": tr["ret_pct"],
                "test_pf":  te["pf"], "test_n":  te["total_trades"], "test_ret":  te["ret_pct"],
                "min_pf": min(tr["pf"], te["pf"]),
            }
            per_sym_results.append(entry)

        per_sym_results.sort(key=lambda x: x["min_pf"], reverse=True)
        winners = [r for r in per_sym_results if r["min_pf"] >= 1.5 and r["train_n"] >= 10 and r["test_n"] >= 10]
        print(f"  {len(winners)} WF winners (min_PF>=1.5, n>=10 each window)", flush=True)
        print("  Top 5:", flush=True)
        print(f"  {'min_PF':>7} {'tr_PF':>6} {'te_PF':>6} {'tr_n':>4} {'te_n':>4} {'tr_ret':>7} {'te_ret':>7}  params", flush=True)
        for r in per_sym_results[:5]:
            p = r["params"]
            print(
                f"  {r['min_pf']:>7.2f} {r['train_pf']:>6.2f} {r['test_pf']:>6.2f} "
                f"{r['train_n']:>4} {r['test_n']:>4} {r['train_ret']:>+7.1f} {r['test_ret']:>+7.1f}  "
                f"fast={p['fast']} slow={p['slow']} trail={p['atr_trail_mult']}",
                flush=True,
            )
        summary[f"{sym}_wfo"] = {
            "n_winners": len(winners),
            "top_5": per_sym_results[:5],
        }

    out_path = Path(__file__).parent / "multi_symbol_trend_wfo_results.json"
    with open(out_path, "w") as f:
        json.dump({
            "train": list(TRAIN),
            "test": list(TEST),
            "elapsed_sec": round(time.time() - t0, 1),
            "summary": summary,
        }, f, indent=2)

    print(f"\nSaved to {out_path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
