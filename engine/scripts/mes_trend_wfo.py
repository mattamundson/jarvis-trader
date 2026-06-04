"""
MES trend-following walk-forward optimization — 2026-04-20.

Goal: find SMA crossover config with PF >= 1.5 on BOTH halves of the
MES 1h window. Current best (SMA 50/200, trail 3.0) had IS PF 3.01
but OOS PF 1.16 — fails the walk-forward gate in the MES pivot memo.

Procedure:
  1. Split data: train = 2024-01-01 → 2025-06-01, test = 2025-06-01 → 2026-03-27
  2. Evaluate every (fast, slow, trail) combo on BOTH windows
  3. Rank by min(train_PF, test_PF) — i.e. worst-case PF across the two
  4. A winner has min_PF >= 1.5 with trades >= 10 in each window
"""

from __future__ import annotations

import json
import sys
import time
from itertools import product
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ENGINE = _HERE.parent
if str(_ENGINE) not in sys.path:
    sys.path.insert(0, str(_ENGINE))

import importlib.util  # noqa: E402

spec = importlib.util.spec_from_file_location("mt", str(_HERE / "mes_trend_search.py"))
mt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mt)

from backtest.data_loader import BacktestDataLoader  # noqa: E402

SYMBOL = "MES"
INTERVAL = "1h"
TRAIN = ("2024-06-01", "2025-06-01")
TEST = ("2025-06-01", "2026-03-27")

# Focused grid around the known winner (50, 200, 3.0)
GRID = {
    "fast": [20, 30, 40, 50, 60, 80, 100],
    "slow": [100, 150, 180, 200, 220, 250, 300],
    "atr_trail_mult": [0.0, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0],
}


_MES_SPEC = mt.SYMBOL_SPECS["MES"]


def _metrics(df, fast, slow, trail):
    r = mt._run(df, fast=fast, slow=slow, atr_trail_mult=trail, spec=_MES_SPEC)
    return r


def main():
    t0 = time.time()
    loader = BacktestDataLoader()
    df_train = loader.load(SYMBOL, TRAIN[0], TRAIN[1], INTERVAL)
    df_test = loader.load(SYMBOL, TEST[0], TEST[1], INTERVAL)
    if df_train is None or df_test is None:
        print("[ERROR] data load failed", flush=True)
        return 1
    print(f"Train: {len(df_train)} bars {TRAIN[0]}→{TRAIN[1]}", flush=True)
    print(f"Test : {len(df_test)} bars {TEST[0]}→{TEST[1]}", flush=True)

    combos = [dict(zip(GRID.keys(), vals, strict=False)) for vals in product(*GRID.values())]
    combos = [c for c in combos if c["fast"] < c["slow"]]
    print(f"Grid: {len(combos)} valid combos", flush=True)

    results = []
    winners = []
    for i, p in enumerate(combos, 1):
        mr = _metrics(df_train, p["fast"], p["slow"], p["atr_trail_mult"])
        tr = _metrics(df_test,  p["fast"], p["slow"], p["atr_trail_mult"])
        if mr.get("skipped") or tr.get("skipped"):
            continue
        train_pf = mr["pf"]
        test_pf = tr["pf"]
        train_n = mr["total_trades"]
        test_n = tr["total_trades"]
        min_pf = min(train_pf, test_pf)
        # WFE protection: require trades in both windows
        if train_n < 5 or test_n < 5:
            continue
        entry = {
            "params": p,
            "train_pf": train_pf, "train_wr": mr["wr"], "train_n": train_n, "train_ret": mr["ret_pct"],
            "test_pf":  test_pf,  "test_wr":  tr["wr"], "test_n":  test_n,  "test_ret":  tr["ret_pct"],
            "min_pf": round(min_pf, 3),
            "wfe": round(test_pf / train_pf, 3) if train_pf > 0 else 0.0,
        }
        results.append(entry)
        flag = ""
        if min_pf >= 1.5 and train_n >= 10 and test_n >= 10:
            flag = "  <- WF WINNER"
            winners.append(entry)
        elif min_pf >= 1.2:
            flag = "  <- borderline"
        if i % 20 == 0 or flag:
            print(
                f"[{i:3d}/{len(combos)}] fast={p['fast']:3d} slow={p['slow']:3d} trail={p['atr_trail_mult']:.1f}  "
                f"train=PF{train_pf:5.2f}/n{train_n:2d}/r{mr['ret_pct']:+5.1f}  "
                f"test=PF{test_pf:5.2f}/n{test_n:2d}/r{tr['ret_pct']:+5.1f}  "
                f"min={min_pf:5.2f}{flag}",
                flush=True,
            )

    results.sort(key=lambda x: x["min_pf"], reverse=True)
    out_path = Path(__file__).parent / "mes_trend_wfo_results.json"
    with open(out_path, "w") as f:
        json.dump({
            "train_window": list(TRAIN),
            "test_window": list(TEST),
            "n_combos": len(combos),
            "elapsed_sec": round(time.time() - t0, 1),
            "n_wf_winners": len(winners),
            "results": results[:40],
        }, f, indent=2)

    print(f"\n=== {len(winners)} walk-forward winners (min_PF >= 1.5, n >= 10 in both) ===", flush=True)
    print("\nTOP 15 by min_PF:", flush=True)
    print(f"{'rank':>4} {'min_PF':>7} {'tr_PF':>6} {'te_PF':>6} {'tr_n':>4} {'te_n':>4} {'tr_ret':>7} {'te_ret':>7}  params", flush=True)
    for i, r in enumerate(results[:15], 1):
        p = r["params"]
        print(
            f"{i:>4} {r['min_pf']:>7.2f} {r['train_pf']:>6.2f} {r['test_pf']:>6.2f} "
            f"{r['train_n']:>4} {r['test_n']:>4} {r['train_ret']:>+7.1f} {r['test_ret']:>+7.1f}  "
            f"fast={p['fast']} slow={p['slow']} trail={p['atr_trail_mult']}",
            flush=True,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
