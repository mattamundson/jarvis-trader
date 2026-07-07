"""
MES profitability search — throwaway scratch script (2026-04-20).

Goal: find a composite (STC+ORB+VWAP) configuration with PF >= 1.5 on
cached MES 1h data over the 2024-06-01 → 2026-03-27 window.

Strategy: in-process random search. Calls generate_composite_signals +
Backtester directly (no subprocess overhead). Records PF / WR / trades
for each candidate. Caches the loaded OHLC once and re-uses it.

Run from engine/:
    .venv/Scripts/python -m scripts.mes_search
"""

from __future__ import annotations

import json
import logging
import os
import random
import sys
import time
from pathlib import Path

# Quiet the noisy composite_signals logger
logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
for name in ("composite_signals", "run_composite_backtest"):
    logging.getLogger(name).setLevel(logging.WARNING)

# Ensure we can import as `backtest.*`
_HERE = Path(__file__).resolve().parent
_ENGINE = _HERE.parent
if str(_ENGINE) not in sys.path:
    sys.path.insert(0, str(_ENGINE))

from backtest.backtester import Backtester  # noqa: E402
from backtest.composite_signals import generate_composite_signals  # noqa: E402
from backtest.data_loader import BacktestDataLoader  # noqa: E402

SYMBOL = "MES"
INTERVAL = "1h"
START = "2024-06-01"
END = "2026-03-27"
CAPITAL = 10_000.0
RISK = 0.01

# Search space — updated 2026-04-20 after fix(composite) 3d5996b wired
# stop_atr_mult / t1_atr_mult through to the previously-hardcoded constants.
SPACE = {
    "threshold": [0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50, 0.60],
    "stc_os": [10, 15, 20, 25],
    "stc_ob": [70, 75, 80, 83, 88, 92],
    "stop_atr_mult": [0.5, 0.75, 1.0, 1.5, 2.0],     # composite stop (LIVE axis post 3d5996b)
    "t1_atr_mult": [1.5, 2.0, 2.5, 3.0, 4.0],        # composite T1 target (LIVE axis post 3d5996b)
    "band_mult": [1.0, 1.2, 1.5, 2.0, 2.5],
}


def _score(result, min_trades=30):
    """PF-first score. Penalize low-trade-count configs."""
    if result is None:
        return 0.0
    if result.total_trades < min_trades:
        return 0.0
    # Treat PF==inf as 999
    pf = result.profit_factor
    if pf == float("inf"):
        pf = 999.0
    return pf


def _run_one(df_base, multiplier, params):
    df = df_base.copy()
    try:
        df_sig = generate_composite_signals(
            df,
            symbol=SYMBOL,
            band_mult=params["band_mult"],
            entry_threshold=params["threshold"],
            stc_oversold=params["stc_os"],
            stc_overbought=params["stc_ob"],
            stop_atr_mult=params["stop_atr_mult"],
            t1_atr_mult=params["t1_atr_mult"],
        )
    except Exception as exc:
        return None, f"signal_error: {exc}"

    try:
        bt = Backtester(
            initial_capital=CAPITAL,
            risk_per_trade=RISK,
            max_daily_loss=0.02,
            max_drawdown=0.05,
            commission_per_contract=2.50,
            slippage_ticks=1,
        )
        result = bt.run(df_sig, SYMBOL, multiplier)
    except Exception as exc:
        return None, f"backtest_error: {exc}"
    return result, None


def main():
    t0 = time.time()
    loader = BacktestDataLoader()
    df_base = loader.load(SYMBOL, START, END, INTERVAL)
    if df_base is None or df_base.empty:
        print("[ERROR] No data loaded")
        return 1
    multiplier = loader.get_multiplier(SYMBOL)
    print(f"Loaded {len(df_base)} bars for {SYMBOL} {INTERVAL} {START}→{END}")

    # Budget: ~60 samples @ 25s each = 25min. Leave time for OOS.
    n_samples = int(os.environ.get("MES_SEARCH_N", "60"))
    print(f"Random search: {n_samples} samples")

    rng = random.Random(42)

    # Default anchor = prior-hardcoded values so we confirm repro; then sweep.
    anchors = [
        {"threshold": 0.35, "stc_os": 15, "stc_ob": 83, "stop_atr_mult": 1.00, "t1_atr_mult": 2.50, "band_mult": 2.5},  # prior hardcoded defaults
        {"threshold": 0.40, "stc_os": 15, "stc_ob": 83, "stop_atr_mult": 0.75, "t1_atr_mult": 3.00, "band_mult": 1.2},  # tighter stop, wider target
        {"threshold": 0.50, "stc_os": 20, "stc_ob": 80, "stop_atr_mult": 1.00, "t1_atr_mult": 2.00, "band_mult": 1.5},
        {"threshold": 0.60, "stc_os": 25, "stc_ob": 75, "stop_atr_mult": 0.50, "t1_atr_mult": 4.00, "band_mult": 1.0},  # aggressive R:R
        {"threshold": 0.30, "stc_os": 10, "stc_ob": 92, "stop_atr_mult": 1.50, "t1_atr_mult": 3.00, "band_mult": 2.0},  # loose stop + wide target
        {"threshold": 0.25, "stc_os": 20, "stc_ob": 83, "stop_atr_mult": 0.75, "t1_atr_mult": 2.50, "band_mult": 1.5},
    ]

    def sample():
        return {k: rng.choice(v) for k, v in SPACE.items()}

    samples = anchors + [sample() for _ in range(n_samples - len(anchors))]

    results = []
    for i, params in enumerate(samples, 1):
        r, err = _run_one(df_base, multiplier, params)
        if r is None:
            print(f"[{i:3d}/{n_samples}] ERR params={params}  err={err}")
            continue
        pf = r.profit_factor if r.profit_factor != float("inf") else 999.0
        wr = r.win_rate  # already in %, e.g. 11.1
        nt = r.total_trades
        ret = r.total_return_pct
        sc = _score(r, min_trades=30)
        results.append({
            "params": params,
            "pf": round(pf, 3),
            "wr": round(wr, 2),
            "trades": nt,
            "ret": round(ret, 2),
            "score": round(sc, 3),
        })
        flag = ""
        if pf >= 2.0 and nt >= 50:
            flag = "  <- WINNER PF>=2.0"
        elif pf >= 1.5 and nt >= 100:
            flag = "  <- backup PF>=1.5"
        print(
            f"[{i:3d}/{n_samples}] "
            f"thr={params['threshold']:.2f} "
            f"os={params['stc_os']} ob={params['stc_ob']} "
            f"sl={params['stop_atr_mult']:.2f} t1={params['t1_atr_mult']:.2f} "
            f"band={params['band_mult']:.1f}  "
            f"PF={pf:6.2f}  WR={wr:5.1f}%  n={nt:4d}  ret={ret:+.1f}%{flag}"
        )
        # Abort fast if a strong winner shows up — user allowed this
        if pf >= 2.5 and nt >= 50:
            print("  >>> PF>=2.5 found, stopping search")
            break

    # Sort by PF (primary) then by trades (secondary)
    results.sort(key=lambda x: (x["pf"], x["trades"]), reverse=True)

    out_path = Path(__file__).parent / "mes_search_results.json"
    with open(out_path, "w") as f:
        json.dump({
            "symbol": SYMBOL,
            "interval": INTERVAL,
            "start": START,
            "end": END,
            "n_samples": len(samples),
            "elapsed_sec": round(time.time() - t0, 1),
            "results": results,
        }, f, indent=2)

    print(f"\nSaved {len(results)} results to {out_path}")
    print("\nTOP 10 by PF:")
    print(f"{'rank':>4} {'PF':>7} {'WR%':>6} {'trades':>6} {'ret%':>7}  params")
    for i, r in enumerate(results[:10], 1):
        p = r["params"]
        print(
            f"{i:>4} {r['pf']:>7.2f} {r['wr']:>6.1f} {r['trades']:>6d} {r['ret']:>+7.1f}  "
            f"thr={p['threshold']:.2f} os={p['stc_os']} ob={p['stc_ob']} "
            f"sl={p['stop_atr_mult']:.2f} t1={p['t1_atr_mult']:.2f} band={p['band_mult']:.1f}"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
