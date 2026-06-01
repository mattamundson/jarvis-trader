"""
Phase B — Part 1: Parameter cluster robustness test for MES SMA trend strategy.

Tests the 50-combo neighborhood of the WFO champion (fast=50, slow=200, trail=2.0)
to determine if the champion sits on a broad plateau (real edge) or a sharp peak
(lucky parameter selection).

Pass criterion:
  - ≥70% of cluster combos produce PF > 1.3
  - Champion PF is NOT >2× the cluster median PF (no lucky outlier)
  - Stability score = 100 − (std(PF) / mean(PF)) × 100 ≥ 60

Run from engine/:
    .venv/Scripts/python -m scripts.mes_sma_cluster_test
"""

from __future__ import annotations

import json
import sys
import time
from itertools import product
from pathlib import Path

import numpy as np

ENGINE_DIR = Path(__file__).resolve().parent.parent
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))

from backtest import BacktestDataLoader, Backtester  # noqa: E402
from backtest.trend_signals import generate_sma_trend_signals  # noqa: E402

SYMBOL = "MES"
INTERVAL = "1h"
START = "2024-06-01"
END = "2026-03-27"
CAPITAL = 10_000.0
MULTIPLIER = 5.0  # MES: $5/point

# WFO champion neighborhood (50 combos)
GRID = {
    "fast":      [40, 45, 50, 55, 60],
    "slow":      [175, 190, 200, 210, 225],
    "atr_trail": [1.5, 2.0, 2.5, 3.0],
}


def _run_combo(df_raw, fast: int, slow: int, atr_trail: float) -> dict:
    df = generate_sma_trend_signals(df_raw, fast=fast, slow=slow, atr_trail_mult=atr_trail)
    bt = Backtester(
        initial_capital=CAPITAL,
        trailing_stop=True,
        trailing_atr_mult=atr_trail,
        t1_exit_pct=1.0,
        t2_exit_pct=0.0,
        strict_trailing=True,
        eod_close=False,
        use_targets=False,
        fixed_contracts=1,
        max_drawdown=0.99,
        max_daily_loss=0.99,
    )
    result = bt.run(df, SYMBOL, MULTIPLIER)
    return {
        "fast": fast,
        "slow": slow,
        "atr_trail": atr_trail,
        "n_trades": result.total_trades,
        "pf": round(result.profit_factor, 3),
        "sharpe": round(result.sharpe_ratio, 3),
        "win_rate": round(result.win_rate, 3),
        "max_dd_pct": round(result.max_drawdown_pct, 3),
        "total_return_pct": round(result.total_return_pct, 3),
    }


def main():
    loader = BacktestDataLoader()
    df_raw = loader.load(SYMBOL, START, END, INTERVAL)
    if df_raw is None or df_raw.empty:
        print(f"ERROR: No cached data for {SYMBOL}")
        return 1

    combos = list(product(GRID["fast"], GRID["slow"], GRID["atr_trail"]))
    # Filter invalid (fast >= slow)
    combos = [(f, s, a) for f, s, a in combos if f < s]
    print(f"Running {len(combos)} valid combos on {SYMBOL} {INTERVAL} {START}→{END}")

    results = []
    t0 = time.time()
    for i, (fast, slow, atr) in enumerate(combos):
        row = _run_combo(df_raw.copy(), fast, slow, atr)
        results.append(row)
        if (i + 1) % 10 == 0:
            elapsed = time.time() - t0
            print(f"  {i+1}/{len(combos)} combos done ({elapsed:.0f}s)")

    elapsed = time.time() - t0
    print(f"\nCompleted {len(combos)} combos in {elapsed:.1f}s")

    # ── Analysis ─────────────────────────────────────────────────────────────
    pfs = np.array([r["pf"] for r in results])
    champion = next((r for r in results if r["fast"] == 50 and r["slow"] == 200 and r["atr_trail"] == 2.0), None)
    champion_pf = champion["pf"] if champion else max(pfs)

    pct_above_threshold = 100 * np.mean(pfs > 1.3)
    median_pf = float(np.median(pfs))
    mean_pf = float(np.mean(pfs))
    std_pf = float(np.std(pfs))
    stability_score = max(0, 100 - (std_pf / mean_pf * 100)) if mean_pf > 0 else 0
    champion_vs_median = champion_pf / median_pf if median_pf > 0 else float("inf")

    # Sort by PF descending
    results_sorted = sorted(results, key=lambda x: x["pf"], reverse=True)

    print()
    print("=" * 70)
    print("  MES SMA Cluster Test — Parameter Robustness")
    print("=" * 70)
    print(f"  Champion: fast={champion['fast'] if champion else 50}, "
          f"slow={champion['slow'] if champion else 200}, "
          f"trail={champion['atr_trail'] if champion else 2.0}  →  PF {champion_pf:.3f}")
    print()
    print(f"  PF distribution:  min={pfs.min():.3f}  p25={np.percentile(pfs,25):.3f}  "
          f"median={median_pf:.3f}  p75={np.percentile(pfs,75):.3f}  max={pfs.max():.3f}")
    print(f"  Mean±std:         {mean_pf:.3f} ± {std_pf:.3f}")
    print(f"  Stability score:  {stability_score:.1f}  ← gate ≥60")
    print(f"  % combos PF>1.3:  {pct_above_threshold:.1f}%  ← gate ≥70%")
    print(f"  Champion/median:  {champion_vs_median:.2f}×  ← gate ≤2×")
    print()

    # Gate checks
    g1 = pct_above_threshold >= 70
    g2 = champion_vs_median <= 2.0
    g3 = stability_score >= 60
    print(f"  {'✓' if g1 else '✗'}  % combos PF>1.3 ≥ 70% ({pct_above_threshold:.1f}%)")
    print(f"  {'✓' if g2 else '✗'}  Champion ≤ 2× median PF ({champion_vs_median:.2f}×)")
    print(f"  {'✓' if g3 else '✗'}  Stability score ≥ 60 ({stability_score:.1f})")

    all_pass = g1 and g2 and g3
    print()
    print(f"  → Cluster test: {'PASS — broad plateau, edge is robust' if all_pass else 'FAIL — investigate concentration'}")

    # Top 10 combos
    print()
    print("  Top 10 combos by PF:")
    print(f"  {'fast':>5} {'slow':>6} {'trail':>6} {'n_tr':>5} {'PF':>7} {'Sharpe':>8} {'WR%':>6} {'MaxDD%':>7}")
    for r in results_sorted[:10]:
        star = " ★" if r["fast"] == 50 and r["slow"] == 200 and r["atr_trail"] == 2.0 else ""
        print(f"  {r['fast']:>5} {r['slow']:>6} {r['atr_trail']:>6.1f} {r['n_trades']:>5} "
              f"{r['pf']:>7.3f} {r['sharpe']:>8.3f} {r['win_rate']*100:>6.1f}% {r['max_dd_pct']*100:>7.2f}%{star}")

    print("=" * 70)

    # Save results
    out = {
        "metadata": {
            "symbol": SYMBOL, "interval": INTERVAL, "start": START, "end": END,
            "n_combos": len(combos),
        },
        "summary": {
            "champion_pf": champion_pf,
            "median_pf": median_pf,
            "mean_pf": mean_pf,
            "std_pf": std_pf,
            "stability_score": round(stability_score, 2),
            "pct_above_1_3": round(pct_above_threshold, 2),
            "champion_vs_median": round(champion_vs_median, 3),
        },
        "gates": {
            "pct_combos_gt_1_3": bool(g1),
            "champion_lte_2x_median": bool(g2),
            "stability_gte_60": bool(g3),
            "overall_pass": bool(all_pass),
        },
        "all_results": results_sorted,
    }
    out_path = ENGINE_DIR / "backtest" / "results" / "MES_1h_SMA_cluster_test.json"
    out_path.write_text(json.dumps(out, indent=2, default=str))
    print(f"\n[cluster] Saved: {out_path.name}")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
