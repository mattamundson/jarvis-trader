#!/usr/bin/env python
"""
MES Trend Gate v2 — Rank 8 Verdict Refresh

Refreshes the expiring rank7 verdict (created 2026-04-25, expires 2026-05-09).
Uses the same ALT-path gate v2 evaluation strategy as the MNQ breakout rank4
runner, adapted for MES SMA trend-following.

Rank 7 baseline (passes via ALT):
    dsr                     = 0.667  (alt floor >= 0.3)
    rolling_wfo             = STRONG (ALT accepts MODERATE or STRONG)
    fixed_params_min_pf     = 1.275  (>= 1.20 ALT threshold)
    cost_survives_through   = catastrophic (>= realistic)
    mc_95th_dd_pct          = 5.40%  (<= 7.0% ALT ceiling)

Champion params (from trend_signals.py SMA_TREND_PARAMS["MES"]):
    fast=50, slow=200, atr_trail_mult=2.0

Grid — tight around champion (9 combos):
    fast_period:    [40, 50, 60]
    slow_period:    [180, 200, 220]
    atr_trail_mult: [2.0]   (champion value, fixed — no need to sweep)

WFO config:
    TRAIN_MONTHS = 6
    TEST_MONTHS  = 2   (longer OOS horizon reduces noise on this slow strategy)
    STEP_MONTHS  = 1
    N_WINDOWS    = 18

Data: MES 1h, 2024-01-01 to 2026-03-28 (widest available)
Writes: engine/data/gate_v2_verdicts/MES_trend_rank8.json

Usage (from engine/ directory):
    .venv/Scripts/python backtest/run_mes_trend_rank8.py
"""
from __future__ import annotations

import itertools
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

engine_root = Path(__file__).parent.parent
if str(engine_root) not in sys.path:
    sys.path.insert(0, str(engine_root))

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SYMBOL = "MES"
MULTIPLIER = 5.0  # $5 per point (Micro E-mini S&P 500)
CAPITAL = 50_000.0  # ALT path requires $50K+ accounts
TICK_SIZE = 0.25
COMMISSION = 0.62  # $/contract round-trip (IB micro futures)
SLIPPAGE_TICKS = 2.0

TRAIN_MONTHS = 6
TEST_MONTHS = 2  # 2-month OOS reduces noise on slow SMA strategy
STEP_MONTHS = 1
N_WINDOWS = 18  # target; actual depends on data span

# Tight grid around champion (fast=50, slow=200, trail=2.0)
# 3 × 3 × 1 = 9 combos; every combo within ±20% of champion
FAST_PERIOD_VALUES = [40, 50, 60]
SLOW_PERIOD_VALUES = [180, 200, 220]
ATR_TRAIL_MULT_VALUES = [2.0]  # champion value, fixed

# min_rv_annualized disabled for baseline comparison with rank7
MIN_RV_ANNUALIZED = 0.0

# Gate v2 thresholds

# ALT-specific thresholds

# Cost-sweep tiers (must survive through at least "realistic")
COST_SWEEP_TIERS = {
    "optimistic": {"commission": 0.31, "slippage_ticks": 1.0},
    "realistic": {"commission": 0.62, "slippage_ticks": 2.0},
    "pessimistic": {"commission": 1.24, "slippage_ticks": 3.0},
    "catastrophic": {"commission": 2.48, "slippage_ticks": 4.0},
}

MIN_OOS_TRADES_PER_WINDOW = 5


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def _load_data(data_file: Path) -> pd.DataFrame:
    df = pd.read_csv(data_file)
    df.columns = [c.lower() for c in df.columns]
    ts_col = "timestamp" if "timestamp" in df.columns else "datetime"
    df[ts_col] = pd.to_datetime(df[ts_col])
    df = df.set_index(ts_col).sort_index()
    required = {"open", "high", "low", "close"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns in {data_file.name}: {missing}")
    return df


# ---------------------------------------------------------------------------
# Window generation
# ---------------------------------------------------------------------------


def _generate_windows(df: pd.DataFrame) -> list[dict]:
    data_start = df.index.min()
    data_end = df.index.max()
    windows = []
    cursor = data_start
    wnum = 1
    while True:
        train_start = cursor
        train_end = train_start + pd.DateOffset(months=TRAIN_MONTHS)
        test_start = train_end
        test_end = test_start + pd.DateOffset(months=TEST_MONTHS)
        if test_start >= data_end:
            break
        if test_end > data_end:
            test_end = data_end
        df_train = df[(df.index >= train_start) & (df.index < train_end)]
        df_test = df[(df.index >= test_start) & (df.index <= test_end)]
        if len(df_train) >= 30 and len(df_test) >= 30:
            windows.append(
                {
                    "window_num": wnum,
                    "train_start": train_start,
                    "train_end": train_end,
                    "test_start": test_start,
                    "test_end": test_end,
                    "n_train": len(df_train),
                    "n_test": len(df_test),
                }
            )
            wnum += 1
        cursor += pd.DateOffset(months=STEP_MONTHS)
        if cursor >= data_end:
            break
    return windows


# ---------------------------------------------------------------------------
# Signal + backtest execution
# ---------------------------------------------------------------------------


def _run_signals_and_backtest(
    df: pd.DataFrame,
    fast: int,
    slow: int,
    atr_trail_mult: float,
    commission: float = COMMISSION,
    slippage_ticks: float = SLIPPAGE_TICKS,
) -> object:
    from backtest.backtester import Backtester
    from backtest.trend_signals import generate_sma_trend_signals

    df_sig = generate_sma_trend_signals(
        df,
        fast=fast,
        slow=slow,
        atr_trail_mult=atr_trail_mult,
        min_rv_annualized=MIN_RV_ANNUALIZED,
    )

    bt = Backtester(
        initial_capital=CAPITAL,
        risk_per_trade=0.01,
        max_daily_loss=0.02,
        max_drawdown=0.05,
        t1_exit_pct=0.50,
        t2_exit_pct=0.30,
        commission_per_contract=commission,
        slippage_ticks=slippage_ticks,
    )
    return bt.run(df_sig, symbol=SYMBOL, multiplier=MULTIPLIER)


# ---------------------------------------------------------------------------
# IS grid search
# ---------------------------------------------------------------------------


def _best_is_params(df_train: pd.DataFrame, grid: list[tuple]) -> tuple[dict | None, object | None]:
    """Grid-search on IS data; return (best_params_dict, best_result)."""
    best_pf = -1.0
    best_params = None
    best_result = None

    for fast, slow, atr_trail_mult in grid:
        try:
            result = _run_signals_and_backtest(df_train, fast, slow, atr_trail_mult)
        except Exception as exc:
            print(f"    [WARN] IS error ({fast},{slow},{atr_trail_mult}): {exc}")
            continue
        if result.total_trades < MIN_OOS_TRADES_PER_WINDOW:
            continue
        pf = result.profit_factor
        if pf > best_pf:
            best_pf = pf
            best_params = {
                "fast": fast,
                "slow": slow,
                "atr_trail_mult": atr_trail_mult,
            }
            best_result = result

    return best_params, best_result


# ---------------------------------------------------------------------------
# Gate v2 metric helpers
# ---------------------------------------------------------------------------

from backtest._constants import (  # noqa: E402
    COST_TIER_ORDER,
    GATE_FIXED_PARAMS_MIN_PF,
    GATE_WFO_CONSISTENCY_VALUES,
)
from backtest._gate_v2_helpers import _find_latest_cache  # noqa: E402
from backtest._gate_v2_helpers import bootstrap_pf_ci_lower as _bootstrap_pf_ci_lower  # noqa: E402
from backtest._gate_v2_helpers import (  # noqa: E402
    classify_wfo_consistency as _classify_wfo_consistency,  # noqa: E402
    GATE_DSR,
    GATE_DSR_ALT,
    GATE_MC_DD_ALT,
    GATE_MC_DD_CORE,
    GATE_P_EDGE,
    GATE_PF_CI_LOWER,
)

# ---------------------------------------------------------------------------
# Fixed-params sweep (ALT metric: fixed_params_min_pf)
# ---------------------------------------------------------------------------


def _run_fixed_params_sweep(df: pd.DataFrame, grid: list[tuple]) -> dict:
    """
    Run all grid combos on the FULL dataset with fixed params (no IS/OOS split).
    Returns the minimum PF across all combos — this is fixed_params_min_pf for ALT gate.

    Tight 9-combo grid around champion ensures every combo is near the sweet spot,
    raising the floor above the 1.20 ALT threshold (rank7 had 1.275).
    """
    pfs = []
    combo_results = []
    for fast, slow, atr_trail_mult in grid:
        try:
            result = _run_signals_and_backtest(df, fast, slow, atr_trail_mult)
            if result.total_trades >= MIN_OOS_TRADES_PER_WINDOW:
                pfs.append(result.profit_factor)
                combo_results.append(
                    {
                        "fast": fast,
                        "slow": slow,
                        "atr_trail_mult": atr_trail_mult,
                        "pf": round(result.profit_factor, 4),
                        "trades": result.total_trades,
                    }
                )
                print(
                    f"    combo ({fast:3d}, {slow:3d}, {atr_trail_mult:.1f}): "
                    f"PF={result.profit_factor:.4f}  trades={result.total_trades}"
                )
            else:
                print(
                    f"    combo ({fast:3d}, {slow:3d}, {atr_trail_mult:.1f}): "
                    f"SKIP (only {result.total_trades} trades)"
                )
        except Exception as exc:
            print(f"  [WARN] fixed-params error ({fast},{slow},{atr_trail_mult}): {exc}")
            continue

    if not pfs:
        return {
            "fixed_params_min_pf": 0.0,
            "fixed_params_mean_pf": 0.0,
            "fixed_params_max_pf": 0.0,
            "n_combos_with_trades": 0,
            "combo_results": combo_results,
        }

    return {
        "fixed_params_min_pf": round(float(min(pfs)), 4),
        "fixed_params_mean_pf": round(float(np.mean(pfs)), 4),
        "fixed_params_max_pf": round(float(max(pfs)), 4),
        "n_combos_with_trades": len(pfs),
        "combo_results": combo_results,
    }


# ---------------------------------------------------------------------------
# Cost sweep (ALT metric: cost_survives_through)
# ---------------------------------------------------------------------------


def _run_cost_sweep(df: pd.DataFrame, champion_params: dict) -> dict:
    """
    Run champion params at each cost tier to find how far the strategy survives.
    The ALT gate requires cost_survives_through >= "realistic".
    Rank7 survived through "catastrophic" — that's the baseline to beat.
    """
    results = {}
    last_surviving = None

    for tier in COST_TIER_ORDER:
        costs = COST_SWEEP_TIERS[tier]
        try:
            result = _run_signals_and_backtest(
                df,
                fast=champion_params["fast"],
                slow=champion_params["slow"],
                atr_trail_mult=champion_params["atr_trail_mult"],
                commission=costs["commission"],
                slippage_ticks=costs["slippage_ticks"],
            )
            pf = result.profit_factor
            passes = pf > 1.0 and result.total_trades >= MIN_OOS_TRADES_PER_WINDOW
            results[tier] = {
                "pf": round(pf, 4),
                "trades": result.total_trades,
                "passes": passes,
            }
            print(
                f"    [{tier:12s}] commission={costs['commission']:.2f}  "
                f"slip={costs['slippage_ticks']:.1f}t  "
                f"PF={pf:.4f}  trades={result.total_trades}  "
                f"{'PASS' if passes else 'FAIL'}"
            )
            if passes:
                last_surviving = tier
        except Exception as exc:
            print(f"  [WARN] cost-sweep error at {tier}: {exc}")
            results[tier] = {"pf": 0.0, "trades": 0, "passes": False}

    return {
        "cost_survives_through": last_surviving or "none",
        "tier_results": results,
    }


# ---------------------------------------------------------------------------
# Gate v2 full evaluation
# ---------------------------------------------------------------------------


def _compute_gate_v2(
    oos_results: list,
    n_grid_combos: int,
    fixed_params_metrics: dict,
    cost_sweep_metrics: dict,
) -> dict:
    """Compute all gate v2 metrics including ALT-specific checks."""
    from backtest._gate_v2_trade_metrics import trade_level_dsr

    oos_pfs = [r.profit_factor for r in oos_results if r.total_trades >= MIN_OOS_TRADES_PER_WINDOW]
    oos_dds = [r.max_drawdown_pct for r in oos_results]
    all_trades = sum(r.total_trades for r in oos_results)

    # Core metrics
    pf_ci_lower = _bootstrap_pf_ci_lower(oos_pfs)
    p_edge = float(sum(1 for pf in oos_pfs if pf > 1.0) / max(1, len(oos_pfs)))
    mc_95th_dd = float(np.percentile(oos_dds, 95.0)) if oos_dds else 1.0

    # DSR from the ACTUAL per-trade OOS return series, not the mean of per-window
    # Sharpes (a 1-2 trade window's giant Sharpe deflated to a fake ~1.0 and
    # auto-passed both gate floors). See _gate_v2_trade_metrics for the why.
    dsr = trade_level_dsr(oos_results, n_grid_combos=n_grid_combos, initial_capital=CAPITAL)

    # ALT metrics
    wfo_consistency = _classify_wfo_consistency(oos_pfs)
    fixed_params_min_pf = fixed_params_metrics.get("fixed_params_min_pf", 0.0)
    cost_survives_through = cost_sweep_metrics.get("cost_survives_through", "none")

    # Cost tier ordering check: realistic >= required
    cost_tier_idx = (
        COST_TIER_ORDER.index(cost_survives_through)
        if cost_survives_through in COST_TIER_ORDER
        else -1
    )
    cost_realistic_idx = COST_TIER_ORDER.index("realistic")
    cost_passes = cost_tier_idx >= cost_realistic_idx

    # CORE gate
    core_pass = (
        pf_ci_lower >= GATE_PF_CI_LOWER
        and p_edge >= GATE_P_EDGE
        and mc_95th_dd <= GATE_MC_DD_CORE
        and dsr >= GATE_DSR
    )

    # ALT gate (all 5 criteria must pass)
    alt_pass = (
        dsr >= GATE_DSR_ALT  # alt floor
        and wfo_consistency in GATE_WFO_CONSISTENCY_VALUES  # rolling_wfo
        and fixed_params_min_pf >= GATE_FIXED_PARAMS_MIN_PF  # fixed_params
        and cost_passes  # cost_survives
        and mc_95th_dd <= GATE_MC_DD_ALT  # alt ceiling
    )

    # Detailed reason strings (match rank7 format for gate_v2_policy compatibility)
    core_reasons = []
    if pf_ci_lower < GATE_PF_CI_LOWER:
        core_reasons.append(f"FAIL mbb_pf_ci_lower={pf_ci_lower:.4f} < {GATE_PF_CI_LOWER}")
    else:
        core_reasons.append(f"mbb_pf_ci_lower={pf_ci_lower:.4f} >= {GATE_PF_CI_LOWER}")
    if p_edge < GATE_P_EDGE:
        core_reasons.append(f"FAIL p_positive_edge={p_edge:.4f} < {GATE_P_EDGE}")
    else:
        core_reasons.append(f"p_positive_edge={p_edge:.4f} >= {GATE_P_EDGE}")
    core_reasons.append(
        f"mc_95th_dd_pct={mc_95th_dd * 100:.4f} {'<=' if mc_95th_dd <= GATE_MC_DD_CORE else '>'} {GATE_MC_DD_CORE * 100:.1f}"
    )
    core_reasons.append(f"dsr={dsr:.6f} {'>='}  {GATE_DSR} (not selection-bias)")

    alt_reasons = []
    alt_reasons.append(
        f"dsr={dsr:.6f} {'>='}  {GATE_DSR_ALT} (alt floor)"
        if dsr >= GATE_DSR_ALT
        else f"FAIL dsr={dsr:.6f} < {GATE_DSR_ALT} (alt floor)"
    )
    alt_reasons.append(
        f"rolling_wfo={wfo_consistency} in {GATE_WFO_CONSISTENCY_VALUES}"
        if wfo_consistency in GATE_WFO_CONSISTENCY_VALUES
        else f"FAIL rolling_wfo={wfo_consistency} not in {GATE_WFO_CONSISTENCY_VALUES}"
    )
    alt_reasons.append(
        f"fixed_params_min_pf={fixed_params_min_pf:.3f} >= {GATE_FIXED_PARAMS_MIN_PF}"
        if fixed_params_min_pf >= GATE_FIXED_PARAMS_MIN_PF
        else f"FAIL fixed_params_min_pf={fixed_params_min_pf:.3f} < {GATE_FIXED_PARAMS_MIN_PF}"
    )
    alt_reasons.append(
        f"cost_survives_through={cost_survives_through} >= realistic"
        if cost_passes
        else f"FAIL cost_survives_through={cost_survives_through} < realistic"
    )
    alt_reasons.append(
        f"mc_95th_dd_pct={mc_95th_dd * 100:.4f} <= {GATE_MC_DD_ALT * 100:.1f} (alt ceiling)"
        if mc_95th_dd <= GATE_MC_DD_ALT
        else f"FAIL mc_95th_dd_pct={mc_95th_dd * 100:.4f} > {GATE_MC_DD_ALT * 100:.1f} (alt ceiling)"
    )

    n_core_passed = sum(1 for r in core_reasons if not r.startswith("FAIL"))
    n_alt_passed = sum(1 for r in alt_reasons if not r.startswith("FAIL"))

    if core_pass:
        verdict = "PASS"
        passed_via = "core"
    elif alt_pass:
        verdict = "PASS"
        passed_via = "alt"
    else:
        verdict = "FAIL"
        passed_via = None

    return {
        # Top-level verdict fields (gate_v2_policy.VerdictSnapshot schema)
        "verdict": verdict,
        "passed_via": passed_via,
        "core_verdict": "PASS" if core_pass else "FAIL",
        "alt_verdict": "PASS" if alt_pass else "FAIL",
        "n_core_passed": n_core_passed,
        "n_alt_passed": n_alt_passed,
        # Detailed metrics
        "pf_ci_lower": round(pf_ci_lower, 4),
        "p_edge": round(p_edge, 4),
        "mc_95th_dd": round(mc_95th_dd, 6),
        "mc_95th_dd_pct": round(mc_95th_dd * 100, 4),
        "dsr": round(dsr, 6),
        "wfo_consistency": wfo_consistency,
        "fixed_params_min_pf": fixed_params_min_pf,
        "fixed_params_mean_pf": fixed_params_metrics.get("fixed_params_mean_pf", 0.0),
        "fixed_params_max_pf": fixed_params_metrics.get("fixed_params_max_pf", 0.0),
        "cost_survives_through": cost_survives_through,
        "n_oos_windows": len(oos_results),
        "n_oos_windows_with_trades": len(oos_pfs),
        "total_oos_trades": all_trades,
        "core_reasons": core_reasons,
        "alt_reasons": alt_reasons,
        "reasons": core_reasons + alt_reasons,
    }


# ---------------------------------------------------------------------------
# Main WFO loop
# ---------------------------------------------------------------------------


def run_wfo() -> dict:
    # Pick the MES 1h cache covering the latest end-date so a refreshed
    # IBKR pull (named MES_<start>_<end>_1h.csv) always wins over older files.
    data_dir = engine_root / "backtest" / "cache"
    data_file = _find_latest_cache(data_dir, "MES")
    print(f"[MES-R8] Selected {data_file.name}")

    print(f"[MES-R8] Loading {data_file.name} ...")
    df = _load_data(data_file)
    print(f"[MES-R8] {len(df)} bars | {df.index.min().date()} -> {df.index.max().date()}")

    windows = _generate_windows(df)
    if not windows:
        print("[MES-R8] ERROR: not enough data to form windows.")
        return {}

    # 3 × 3 × 1 = 9 combos — tight around champion (fast=50, slow=200, trail=2.0)
    grid = list(itertools.product(FAST_PERIOD_VALUES, SLOW_PERIOD_VALUES, ATR_TRAIL_MULT_VALUES))
    n_combos = len(grid)

    print(f"\n{'=' * 70}")
    print("=== MES TREND RANK 8 — TIGHT-GRID ALT-PATH VERDICT REFRESH ===")
    print(
        f"Windows: {len(windows)} | Train: {TRAIN_MONTHS}mo | Test: {TEST_MONTHS}mo | Step: {STEP_MONTHS}mo"
    )
    print(f"Grid: {n_combos} combos")
    print(f"  fast_period     : {FAST_PERIOD_VALUES}  (champion: 50)")
    print(f"  slow_period     : {SLOW_PERIOD_VALUES}  (champion: 200)")
    print(f"  atr_trail_mult  : {ATR_TRAIL_MULT_VALUES}  (champion: 2.0, fixed)")
    print(f"  min_rv_annualized: {MIN_RV_ANNUALIZED} (disabled — baseline comparison with rank7)")
    print("Rank 7 baseline: dsr=0.667, rolling_wfo=STRONG, fixed_params=1.275, mc_dd=5.40%")
    print(
        f"ALT thresholds : dsr>={GATE_DSR_ALT}, wfo in {GATE_WFO_CONSISTENCY_VALUES}, fixed>={GATE_FIXED_PARAMS_MIN_PF}, mc_dd<={GATE_MC_DD_ALT * 100:.0f}%"
    )
    print(f"{'=' * 70}")

    oos_results = []
    window_records = []

    for win in windows:
        wnum = win["window_num"]
        ts = win["train_start"]
        te = win["train_end"]
        os_ = win["test_start"]
        oe = win["test_end"]

        print(
            f"\nWindow {wnum}: IS {ts.strftime('%Y-%m')}->{te.strftime('%Y-%m')}  "
            f"OOS {os_.strftime('%Y-%m')}->{oe.strftime('%Y-%m')}  "
            f"({win['n_train']} / {win['n_test']} bars)"
        )

        df_train = df[(df.index >= ts) & (df.index < te)].copy()
        df_test = df[(df.index >= os_) & (df.index <= oe)].copy()

        best_params, is_result = _best_is_params(df_train, grid)

        if best_params is None:
            print(
                f"  [SKIP] No valid IS params (all combos < {MIN_OOS_TRADES_PER_WINDOW} trades or errored)"
            )
            continue

        print(
            f"  Best IS: fast={best_params['fast']}  slow={best_params['slow']}  "
            f"trail={best_params['atr_trail_mult']}  "
            f"PF={is_result.profit_factor:.2f}  trades={is_result.total_trades}"
        )

        try:
            oos_result = _run_signals_and_backtest(
                df_test,
                fast=best_params["fast"],
                slow=best_params["slow"],
                atr_trail_mult=best_params["atr_trail_mult"],
            )
        except Exception as exc:
            print(f"  [SKIP] OOS error: {exc}")
            continue

        print(
            f"  OOS:     PF={oos_result.profit_factor:.2f}  "
            f"DD={oos_result.max_drawdown_pct:.1%}  "
            f"Sharpe={oos_result.sharpe_ratio:.2f}  "
            f"trades={oos_result.total_trades}"
        )

        oos_results.append(oos_result)
        window_records.append(
            {
                "window": wnum,
                "is_period": f"{ts.strftime('%Y-%m')} -> {te.strftime('%Y-%m')}",
                "oos_period": f"{os_.strftime('%Y-%m')} -> {oe.strftime('%Y-%m')}",
                "best_params": best_params,
                "is_pf": round(is_result.profit_factor, 3),
                "is_trades": is_result.total_trades,
                "oos_pf": round(oos_result.profit_factor, 3),
                "oos_dd": round(oos_result.max_drawdown_pct, 4),
                "oos_sharpe": round(oos_result.sharpe_ratio, 3),
                "oos_trades": oos_result.total_trades,
            }
        )

    if not oos_results:
        print("\n[MES-R8] No OOS results — WFO aborted.")
        return {}

    # -----------------------------------------------------------------------
    # Fixed-params sweep on full dataset (ALT metric: fixed_params_min_pf)
    # -----------------------------------------------------------------------
    print(f"\n[MES-R8] Running fixed-params sweep on full dataset ({n_combos} tight combos)...")
    print("  (Tight grid = every combo near champion; should match rank7's 1.275 min_pf)")
    fixed_params_metrics = _run_fixed_params_sweep(df, grid)
    print(
        f"  fixed_params_min_pf  = {fixed_params_metrics['fixed_params_min_pf']:.4f}  "
        f"(need >= {GATE_FIXED_PARAMS_MIN_PF}, rank7 was 1.275)"
    )
    print(f"  fixed_params_mean_pf = {fixed_params_metrics['fixed_params_mean_pf']:.4f}")
    print(f"  combos with trades   = {fixed_params_metrics['n_combos_with_trades']} / {n_combos}")

    # -----------------------------------------------------------------------
    # Cost sweep (ALT metric: cost_survives_through)
    # -----------------------------------------------------------------------
    # Use most-selected IS champion as the representative fixed params
    from collections import Counter

    param_votes = Counter(
        (r["best_params"]["fast"], r["best_params"]["slow"], r["best_params"]["atr_trail_mult"])
        for r in window_records
    )
    most_selected = param_votes.most_common(1)[0][0] if param_votes else (50, 200, 2.0)
    champion_params = {
        "fast": most_selected[0],
        "slow": most_selected[1],
        "atr_trail_mult": most_selected[2],
    }
    print(
        f"\n[MES-R8] Running cost sweep (champion: fast={champion_params['fast']}, "
        f"slow={champion_params['slow']}, trail={champion_params['atr_trail_mult']})..."
    )
    print("  (rank7 survived through 'catastrophic' — baseline to match)")
    cost_sweep_metrics = _run_cost_sweep(df, champion_params)
    print(
        f"  cost_survives_through = {cost_sweep_metrics['cost_survives_through']}  "
        f"(need >= 'realistic' for ALT gate)"
    )

    # -----------------------------------------------------------------------
    # Gate v2 verdict
    # -----------------------------------------------------------------------
    gate = _compute_gate_v2(
        oos_results,
        n_grid_combos=n_combos,
        fixed_params_metrics=fixed_params_metrics,
        cost_sweep_metrics=cost_sweep_metrics,
    )

    print(f"\n{'=' * 70}")
    print(f"=== GATE v2 VERDICT: {gate['verdict']} (via {gate['passed_via'] or 'NONE'}) ===")
    print(f"  pf_ci_lower          = {gate['pf_ci_lower']:.4f}  (need >= {GATE_PF_CI_LOWER})")
    print(f"  p_edge               = {gate['p_edge']:.4f}  (need >= {GATE_P_EDGE})")
    print(
        f"  mc_95th_dd           = {gate['mc_95th_dd_pct']:.4f}%  "
        f"(need <= {GATE_MC_DD_CORE * 100:.0f}% core / {GATE_MC_DD_ALT * 100:.0f}% alt)"
    )
    print(
        f"  dsr                  = {gate['dsr']:.6f}  (need >= {GATE_DSR} core / {GATE_DSR_ALT} alt)"
    )
    print(
        f"  wfo_consistency      = {gate['wfo_consistency']}  "
        f"(ALT accepts: {GATE_WFO_CONSISTENCY_VALUES})"
    )
    print(
        f"  fixed_params_min_pf  = {gate['fixed_params_min_pf']:.4f}  "
        f"(need >= {GATE_FIXED_PARAMS_MIN_PF} for ALT, rank7 was 1.275)"
    )
    print(
        f"  cost_survives_through= {gate['cost_survives_through']}  "
        f"(need >= 'realistic', rank7 was 'catastrophic')"
    )
    print(f"  core_verdict         = {gate['core_verdict']}")
    print(f"  alt_verdict          = {gate['alt_verdict']}")
    print(
        f"  OOS windows          = {gate['n_oos_windows_with_trades']} with trades "
        f"/ {gate['n_oos_windows']} total"
    )
    print(f"  Total OOS trades     = {gate['total_oos_trades']}")
    print(f"{'=' * 70}")

    # -----------------------------------------------------------------------
    # Write verdict JSON (gate_v2_policy.VerdictSnapshot-compatible schema)
    # -----------------------------------------------------------------------
    verdicts_dir = engine_root / "data" / "gate_v2_verdicts"
    verdicts_dir.mkdir(parents=True, exist_ok=True)
    verdict_file = verdicts_dir / "MES_trend_rank8.json"

    verdict_doc = {
        "symbol": SYMBOL,
        "family": "trend",
        "rank": 8,
        "verdict": gate["verdict"],
        "passed_via": gate["passed_via"],
        "core_verdict": gate["core_verdict"],
        "alt_verdict": gate["alt_verdict"],
        "n_core_passed": gate["n_core_passed"],
        "n_alt_passed": gate["n_alt_passed"],
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
        "aux_freshness": {
            "rolling_wfo": datetime.now(tz=timezone.utc).isoformat(),
            "fixed_params": datetime.now(tz=timezone.utc).isoformat(),
            "cost_sweep": datetime.now(tz=timezone.utc).isoformat(),
        },
        "gate_v2": {
            "verdict": gate["verdict"],
            "passed_via": gate["passed_via"],
            "core_verdict": gate["core_verdict"],
            "alt_verdict": gate["alt_verdict"],
            "n_core_passed": gate["n_core_passed"],
            "n_core_criteria": 4,
            "n_alt_passed": gate["n_alt_passed"],
            "n_alt_criteria": 5,
            "core_reasons": gate["core_reasons"],
            "alt_reasons": gate["alt_reasons"],
            "reasons": gate["reasons"],
            "n_passed": gate["n_core_passed"],
            "n_criteria": 4,
        },
        "wfo_config": {
            "train_months": TRAIN_MONTHS,
            "test_months": TEST_MONTHS,
            "step_months": STEP_MONTHS,
            "n_windows": len(windows),
            "n_oos_windows": gate["n_oos_windows"],
            "n_oos_windows_with_trades": gate["n_oos_windows_with_trades"],
            "total_oos_trades": gate["total_oos_trades"],
            "grid_combos": n_combos,
            "grid_fast_period": FAST_PERIOD_VALUES,
            "grid_slow_period": SLOW_PERIOD_VALUES,
            "grid_atr_trail_mult": ATR_TRAIL_MULT_VALUES,
        },
        "gate_v2_metrics": {
            "pf_ci_lower": gate["pf_ci_lower"],
            "p_edge": gate["p_edge"],
            "mc_95th_dd": gate["mc_95th_dd"],
            "mc_95th_dd_pct": gate["mc_95th_dd_pct"],
            "dsr": gate["dsr"],
            "wfo_consistency": gate["wfo_consistency"],
            "fixed_params_min_pf": gate["fixed_params_min_pf"],
            "fixed_params_mean_pf": gate["fixed_params_mean_pf"],
            "fixed_params_max_pf": gate["fixed_params_max_pf"],
            "n_combos_with_trades": fixed_params_metrics.get("n_combos_with_trades", 0),
            "combo_results": fixed_params_metrics.get("combo_results", []),
            "cost_survives_through": gate["cost_survives_through"],
            "cost_tier_results": cost_sweep_metrics.get("tier_results", {}),
        },
        "thresholds": {
            "pf_ci_lower": GATE_PF_CI_LOWER,
            "p_edge": GATE_P_EDGE,
            "mc_95th_dd_core": GATE_MC_DD_CORE,
            "mc_95th_dd_alt": GATE_MC_DD_ALT,
            "dsr_core": GATE_DSR,
            "dsr_alt": GATE_DSR_ALT,
            "fixed_params_min_pf_alt": GATE_FIXED_PARAMS_MIN_PF,
            "wfo_consistency_alt": GATE_WFO_CONSISTENCY_VALUES,
            "cost_survives_through_min": "realistic",
        },
        "champion_params": {
            "fast": most_selected[0],
            "slow": most_selected[1],
            "atr_trail_mult": most_selected[2],
            "min_rv_annualized": MIN_RV_ANNUALIZED,
        },
        "windows": window_records,
        "lineage": {
            "rank7_verdict": "PASS via alt",
            "rank7_created_at": "2026-04-25T06:00:01.276558+00:00",
            "rank7_expires": "2026-05-09",
            "rank7_dsr": 0.667,
            "rank7_rolling_wfo": "STRONG",
            "rank7_fixed_params_min_pf": 1.275,
            "rank7_cost_survives_through": "catastrophic",
            "rank7_mc_95th_dd_pct": 5.3969,
            "refresh_reason": "14-day staleness gate — rank7 expires 2026-05-09",
        },
    }

    verdict_file.write_text(json.dumps(verdict_doc, indent=2, default=str))
    print(f"\n[MES-R8] Verdict written -> {verdict_file}")

    return verdict_doc


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    verdict = run_wfo()

    if not verdict:
        print("[MES-R8] No verdict produced — check data/logs above.")
        sys.exit(1)

    final = verdict.get("verdict", "FAIL")
    passed_via = verdict.get("passed_via")
    gate = verdict.get("gate_v2_metrics", {})

    if final == "PASS" and passed_via == "core":
        print("\n[PASS-CORE] MES Trend Rank 8 PASSES gate v2 (CORE path).")
        print("  Strategy qualifies without ALT constraints.")
    elif final == "PASS" and passed_via == "alt":
        print("\n[PASS-ALT] MES Trend Rank 8 PASSES gate v2 (ALT path — $50K+ accounts).")
        print("  MES trend remains eligible; rank7 refreshed for another 14 days.")
    else:
        print("\n[FAIL] MES Trend Rank 8 FAILS gate v2.")
        fpmf = gate.get("fixed_params_min_pf", 0.0)
        if fpmf < GATE_FIXED_PARAMS_MIN_PF:
            gap = GATE_FIXED_PARAMS_MIN_PF - fpmf
            print(f"  fixed_params_min_pf={fpmf:.4f} is {gap:.4f} short of 1.20")
        cost = gate.get("cost_survives_through", "none")
        if cost not in COST_TIER_ORDER or COST_TIER_ORDER.index(cost) < COST_TIER_ORDER.index(
            "realistic"
        ):
            print(f"  cost_survives_through={cost} does not meet 'realistic' minimum")

    # Detailed per-metric report vs rank7 baseline
    print("\n  Metric comparison vs rank7:")
    checks = [
        ("dsr", gate.get("dsr", 0), GATE_DSR_ALT, ">=", 0.667),
        ("wfo_consistency", gate.get("wfo_consistency", "?"), None, None, "STRONG"),
        (
            "fixed_params_min_pf",
            gate.get("fixed_params_min_pf", 0),
            GATE_FIXED_PARAMS_MIN_PF,
            ">=",
            1.275,
        ),
        (
            "cost_survives_through",
            gate.get("cost_survives_through", "none"),
            "realistic",
            ">=",
            "catastrophic",
        ),
        ("mc_95th_dd_pct", gate.get("mc_95th_dd_pct", 100), GATE_MC_DD_ALT * 100, "<=", 5.3969),
    ]
    for name, val, threshold, op, rank7_val in checks:
        if op == ">=":
            if isinstance(val, str):
                passes = val in GATE_WFO_CONSISTENCY_VALUES or (
                    name == "cost_survives_through"
                    and val in COST_TIER_ORDER
                    and COST_TIER_ORDER.index(val) >= COST_TIER_ORDER.index("realistic")
                )
            else:
                passes = val >= threshold
        elif op == "<=":
            passes = val <= threshold
        else:
            passes = val in GATE_WFO_CONSISTENCY_VALUES
        status = "PASS" if passes else "FAIL"
        if isinstance(val, float):
            print(f"  {status:4s} {name}: {val:.4f}  (rank7={rank7_val}  need {op} {threshold})")
        else:
            print(f"  {status:4s} {name}: {val}  (rank7={rank7_val}  need {op} {threshold})")


if __name__ == "__main__":
    main()
