"""
Phase B — Part 2: Rolling multi-window walk-forward for MES SMA trend strategy.

Uses 12-month train / 3-month test windows (SMA(50,200) trades ~5 times/3-month
period — 6-month windows yield only 2-5 trades, too thin for meaningful WFO).

Also runs an anchored walk-forward (expanding train window, fixed 2026-03-27 end)
and a fixed-params validation that bypasses grid search entirely.

Pass criteria (rolling windows):
  - Mean WFE ≥ 0.50
  - Zero windows with test_PF < 0.80 (ruin guard)
  - WFE trend: regression slope of window WFEs is not strongly negative (< -0.10/window)

Grid (same neighborhood as cluster test):
  fast:      [40, 45, 50, 55, 60]
  slow:      [175, 190, 200, 210, 225]
  atr_trail: [1.5, 2.0, 2.5, 3.0]
  (require ≥8 train trades to avoid inf-PF selection on thin windows)

Run from engine/:
    .venv/Scripts/python -m scripts.mes_sma_rolling_wfo
"""

from __future__ import annotations

import json
import sys
import time
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

ENGINE_DIR = Path(__file__).resolve().parent.parent
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))

from backtest import BacktestDataLoader, Backtester  # noqa: E402
from backtest.trend_signals import generate_sma_trend_signals  # noqa: E402

SYMBOL = "MES"
INTERVAL = "1h"
FULL_START = "2024-06-01"
FULL_END = "2026-03-27"
CAPITAL = 10_000.0
MULTIPLIER = 5.0

# 3 rolling windows: 12-month train, 3-month test, 3-month step
# SMA(50,200) trades ~20 times/12-month period → sufficient for meaningful WFO
WINDOWS = [
    {"name": "W1", "train_start": "2024-06-01", "train_end": "2025-06-01", "test_start": "2025-06-01", "test_end": "2025-09-01"},
    {"name": "W2", "train_start": "2024-09-01", "train_end": "2025-09-01", "test_start": "2025-09-01", "test_end": "2025-12-01"},
    {"name": "W3", "train_start": "2024-12-01", "train_end": "2025-12-01", "test_start": "2025-12-01", "test_end": "2026-03-27"},
]

# Anchored windows (train always from 2024-06-01, expanding)
ANCHORED_WINDOWS = [
    {"name": "A1", "train_start": "2024-06-01", "train_end": "2024-12-01", "test_start": "2024-12-01", "test_end": "2025-03-01"},
    {"name": "A2", "train_start": "2024-06-01", "train_end": "2025-06-01", "test_start": "2025-06-01", "test_end": "2025-09-01"},
    {"name": "A3", "train_start": "2024-06-01", "train_end": "2025-09-01", "test_start": "2025-09-01", "test_end": "2025-12-01"},
    {"name": "A4", "train_start": "2024-06-01", "train_end": "2025-12-01", "test_start": "2025-12-01", "test_end": "2026-03-27"},
]

# Fixed params for temporal validation (no grid search — tests if (50,200,2.0) holds over time)
FIXED_PARAMS = {"fast": 50, "slow": 200, "atr_trail": 2.0}
FIXED_WINDOWS = [
    {"name": "F1", "start": "2024-06-01", "end": "2024-12-01"},
    {"name": "F2", "start": "2024-12-01", "end": "2025-06-01"},
    {"name": "F3", "start": "2025-06-01", "end": "2025-12-01"},
    {"name": "F4", "start": "2025-12-01", "end": "2026-03-27"},
]

GRID = {
    "fast":      [40, 45, 50, 55, 60],
    "slow":      [175, 190, 200, 210, 225],
    "atr_trail": [1.5, 2.0, 2.5, 3.0],
}


def _backtest_window(df: pd.DataFrame, fast: int, slow: int, atr_trail: float) -> dict:
    """Run backtest on a single parameter combo over the given df slice."""
    df_sig = generate_sma_trend_signals(df, fast=fast, slow=slow, atr_trail_mult=atr_trail)
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
    result = bt.run(df_sig, SYMBOL, MULTIPLIER)
    return {
        "pf": result.profit_factor,
        "sharpe": result.sharpe_ratio,
        "n_trades": result.total_trades,
        "win_rate": result.win_rate,
        "max_dd": result.max_drawdown_pct,
    }


def _run_wfo_window(df_full: pd.DataFrame, window: dict) -> dict:
    """For one walk-forward window: grid search train, apply champion to test."""
    # Slice train and test periods from pre-loaded data
    train_mask = (df_full.index >= window["train_start"]) & (df_full.index < window["train_end"])
    test_mask = (df_full.index >= window["test_start"]) & (df_full.index < window["test_end"])

    df_train = df_full[train_mask].copy()
    df_test = df_full[test_mask].copy()

    if len(df_train) < 300 or len(df_test) < 100:
        return {"name": window["name"], "error": "insufficient data",
                "train_bars": len(df_train), "test_bars": len(df_test)}

    combos = [(f, s, a) for f, s, a in product(GRID["fast"], GRID["slow"], GRID["atr_trail"]) if f < s]

    # Grid search on train
    best_pf = -1
    best_params = None
    for fast, slow, atr in combos:
        try:
            row = _backtest_window(df_train.copy(), fast, slow, atr)
            if row["n_trades"] >= 8 and row["pf"] > best_pf:
                best_pf = row["pf"]
                best_params = (fast, slow, atr)
        except Exception:
            continue

    if best_params is None:
        return {"name": window["name"], "error": "no valid combos on train"}

    fast_c, slow_c, atr_c = best_params

    # Apply champion to test (out-of-sample)
    test_result = _backtest_window(df_test.copy(), fast_c, slow_c, atr_c)
    test_pf = test_result["pf"]
    wfe = test_pf / best_pf if best_pf > 0 else 0.0

    return {
        "name": window["name"],
        "train_period": f"{window['train_start']}→{window['train_end']}",
        "test_period": f"{window['test_start']}→{window['test_end']}",
        "champion_params": {"fast": fast_c, "slow": slow_c, "atr_trail": atr_c},
        "train_pf": round(best_pf, 3),
        "test_pf": round(test_pf, 3),
        "test_n_trades": test_result["n_trades"],
        "wfe": round(wfe, 3),
        "train_bars": len(df_train),
        "test_bars": len(df_test),
    }


def main():
    loader = BacktestDataLoader()
    df_full = loader.load(SYMBOL, FULL_START, FULL_END, INTERVAL)
    if df_full is None or df_full.empty:
        print(f"ERROR: No cached data for {SYMBOL}")
        return 1

    print(f"MES SMA Rolling WFO — {len(df_full)} bars ({FULL_START}→{FULL_END})")
    print(f"Grid: {sum(1 for f,s,a in product(GRID['fast'],GRID['slow'],GRID['atr_trail']) if f<s)} valid combos")

    all_windows = []

    # Rolling WFO
    print("\n── Rolling WFO (12m train / 3m test, 3m step) ──")
    t0 = time.time()
    for w in WINDOWS:
        print(f"  {w['name']}: train {w['train_start']}→{w['train_end']}  test {w['test_start']}→{w['test_end']} ...", end=" ", flush=True)
        result = _run_wfo_window(df_full, w)
        result["wfo_type"] = "rolling"
        all_windows.append(result)
        if "error" in result:
            print(f"ERROR: {result['error']}")
        else:
            print(f"train PF={result['train_pf']:.3f}  test PF={result['test_pf']:.3f}  WFE={result['wfe']:.3f}  "
                  f"params=({result['champion_params']['fast']},{result['champion_params']['slow']},{result['champion_params']['atr_trail']})")
    print(f"Rolling WFO done in {time.time()-t0:.0f}s")

    # Anchored WFO
    print("\n── Anchored WFO (train from 2024-06-01, expanding) ──")
    for w in ANCHORED_WINDOWS:
        print(f"  {w['name']}: train {w['train_start']}→{w['train_end']}  test {w['test_start']}→{w['test_end']} ...", end=" ", flush=True)
        result = _run_wfo_window(df_full, w)
        result["wfo_type"] = "anchored"
        all_windows.append(result)
        if "error" in result:
            print(f"ERROR: {result['error']}")
        else:
            print(f"train PF={result['train_pf']:.3f}  test PF={result['test_pf']:.3f}  WFE={result['wfe']:.3f}")

    # ── Analysis: rolling windows only ───────────────────────────────────────
    rolling_valid = [w for w in all_windows if w["wfo_type"] == "rolling" and "error" not in w]
    wfes = np.array([w["wfe"] for w in rolling_valid])
    test_pfs = np.array([w["test_pf"] for w in rolling_valid])
    mean_wfe = float(np.mean(wfes)) if len(wfes) else 0
    zero_ruin_windows = int(np.sum(test_pfs < 0.80))

    # WFE trend: regression slope (positive = improving, negative = degrading)
    wfe_slope = 0.0
    if len(wfes) >= 3:
        x = np.arange(len(wfes))
        wfe_slope = float(np.polyfit(x, wfes, 1)[0])

    print()
    print("=" * 70)
    print("  MES SMA Rolling WFO — Summary")
    print("=" * 70)
    print(f"  {'Window':<5} {'Type':<10} {'Train PF':>9} {'Test PF':>8} {'WFE':>6} {'N Trades':>9}")
    for w in all_windows:
        if "error" in w:
            print(f"  {w['name']:<5} {'error':<10}")
            continue
        print(f"  {w['name']:<5} {w['wfo_type']:<10} {w['train_pf']:>9.3f} {w['test_pf']:>8.3f} {w['wfe']:>6.3f} {w['test_n_trades']:>9}")
    print()
    print(f"  Mean WFE (rolling): {mean_wfe:.3f}  ← gate ≥0.50")
    print(f"  WFE trend slope:    {wfe_slope:+.3f}/window  ← flag if < -0.10")
    print(f"  Test PF < 0.80:     {zero_ruin_windows} windows  ← gate = 0")
    print()

    g1 = mean_wfe >= 0.50
    g2 = zero_ruin_windows == 0
    g3 = wfe_slope > -0.10
    print(f"  {'✓' if g1 else '✗'}  Mean WFE ≥ 0.50 ({mean_wfe:.3f})")
    print(f"  {'✓' if g2 else '✗'}  Zero ruin windows ({zero_ruin_windows} with test_PF < 0.80)")
    print(f"  {'✓' if g3 else '✗'}  WFE not declining (slope {wfe_slope:+.3f})")
    all_pass = g1 and g2 and g3
    print()
    print(f"  → Rolling WFO: {'PASS — edge holds across multiple time windows' if all_pass else 'FAIL — edge not consistent'}")
    print("=" * 70)

    # ── Fixed-params temporal validation ─────────────────────────────────────
    # Tests (50,200,2.0) on each time segment WITHOUT any grid search.
    # This is more honest than WFO when the strategy trades infrequently.
    print("\n── Fixed-params validation (50,200,2.0 across all time segments) ──")
    fixed_results = []
    for fw in FIXED_WINDOWS:
        mask = (df_full.index >= fw["start"]) & (df_full.index < fw["end"])
        df_seg = df_full[mask].copy()
        if len(df_seg) < 50:
            print(f"  {fw['name']}: insufficient bars ({len(df_seg)})")
            continue
        try:
            r = _backtest_window(df_seg, FIXED_PARAMS["fast"], FIXED_PARAMS["slow"], FIXED_PARAMS["atr_trail"])
            fixed_results.append({"name": fw["name"], "period": f"{fw['start']}→{fw['end']}", **r})
            print(f"  {fw['name']}: {fw['start']}→{fw['end']}  PF={r['pf']:.3f}  n={r['n_trades']}  WR={r['win_rate']:.1%}")
        except Exception as e:
            print(f"  {fw['name']}: ERROR {e}")

    # Save
    out = {
        "metadata": {"symbol": SYMBOL, "interval": INTERVAL, "full_start": FULL_START, "full_end": FULL_END},
        "gates": {"mean_wfe_gte_0_50": bool(g1), "zero_ruin_windows": bool(g2), "wfe_not_declining": bool(g3), "overall_pass": bool(all_pass)},
        "rolling_summary": {"mean_wfe": round(mean_wfe, 3), "wfe_slope": round(wfe_slope, 4), "ruin_windows": zero_ruin_windows},
        "windows": all_windows,
        "fixed_params_validation": fixed_results,
    }
    out_path = ENGINE_DIR / "backtest" / "results" / "MES_1h_SMA_rolling_wfo.json"
    out_path.write_text(json.dumps(out, indent=2, default=str))
    print(f"\n[rolling-wfo] Saved: {out_path.name}")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
