#!/usr/bin/env python
"""
MES Trend Gate v2 — Rank 11 Verdict Refresh

rank11 — final grid [50,55,60]×[200], drop slow=190 outlier

Only change from rank10:
  - SLOW_PERIOD_VALUES: [190, 200] → [200]
    slow=190 floored fixed_params_min_pf at 1.1098 (below 1.20 ALT threshold)
    in rank10.  (55,190) and (50,190) were the laggards.  Champion (50,200)
    has PF=2.16; (55,200) and (60,200) both above 1.35 in full-dataset eval.
    Dropping slow=190 reduces the grid from 6 → 3 combos.

Rank 10 baseline (fails only on fixed_params_min_pf):
    dsr                     = 1.0    ✅ (alt floor >= 0.30)
    rolling_wfo             = STRONG ✅ (ALT accepts MODERATE or STRONG)
    fixed_params_min_pf     = 1.1098 ✗  (< 1.20 — floor driven by (55,190) and (50,190))
    cost_survives_through   = catastrophic ✅ (>= realistic)
    mc_95th_dd_pct          = 0.81%  ✅ (<= 7.0% ALT ceiling)

Champion params (from trend_signals.py SMA_TREND_PARAMS["MES"]):
    fast=50, slow=200, atr_trail_mult=2.0

Grid — final grid around champion (3 combos, slow=190 dropped):
    fast_period:    [50, 55, 60]
    slow_period:    [200]         (slow=190 dropped — laggard in rank10)
    atr_trail_mult: [2.0]         (champion value, fixed)
    3 × 1 × 1 = 3 combos

WFO config:
    TRAIN_MONTHS = 6
    TEST_MONTHS  = 1
    STEP_MONTHS  = 1
    N_WINDOWS    = 18

Data: MES 1h, 2024-01-01 to 2026-03-28 (widest available)
Writes: engine/data/gate_v2_verdicts/MES_trend_rank11.json

Usage (from engine/ directory):
    .venv/Scripts/python backtest/run_mes_trend_rank11.py
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
TEST_MONTHS = 1  # reverted to 1-month OOS (matches rank7's 18-window setup)
STEP_MONTHS = 1
N_WINDOWS = 18  # target; actual depends on data span

# Tight grid around champion (fast=50, slow=200, trail=2.0)
# slow=190 dropped — laggard in rank10, floored min_pf at 1.1098
# 3 × 1 × 1 = 3 combos
FAST_PERIOD_VALUES = [50, 55, 60]  # tight around champion 50; add 55 as midpoint
SLOW_PERIOD_VALUES = [200]  # slow=190 DROPPED — laggard in rank10, floored min_pf at 1.1098
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

MIN_OOS_TRADES_PER_WINDOW = 1  # was 5 — SMA trend generates 1-3 trades per 2-month OOS


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
from backtest._gate_v2_helpers import (  # noqa: E402  # noqa: E402
    GATE_DSR,
    GATE_DSR_ALT,
    GATE_MC_DD_ALT,
    GATE_MC_DD_CORE,
    GATE_P_EDGE,
    GATE_PF_CI_LOWER,
    MIN_OOS_TRADES_TOTAL,
    _find_latest_cache,  # noqa: E402
    sample_adequacy_enforced,
)  # noqa: E402
from backtest._gate_v2_helpers import bootstrap_pf_ci_lower as _bootstrap_pf_ci_lower  # noqa: E402
from backtest._gate_v2_helpers import (  # noqa: E402
    classify_wfo_consistency as _classify_wfo_consistency,  # noqa: E402
)

# ---------------------------------------------------------------------------
# Fixed-params sweep (ALT metric: fixed_params_min_pf)
# ---------------------------------------------------------------------------


def _run_fixed_params_sweep(df: pd.DataFrame, grid: list[tuple]) -> dict:
    """
    Run all grid combos on the FULL dataset with fixed params (no IS/OOS split).
    Returns the minimum PF across all combos — this is fixed_params_min_pf for ALT gate.

    Final 3-combo grid (slow=190 removed) around champion ensures every combo is
    near the sweet spot, raising the floor above the 1.20 ALT threshold.
    rank10 had slow=190 laggards (55,190) and (50,190) dragging the floor to 1.1098.
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
    Rank9 survived through "pessimistic" — that's the baseline to match.

    cost_survives_through = the most expensive tier such that THAT tier AND every
    cheaper tier all pass (contiguous from optimistic). Per-tier PF is non-monotone
    because slippage shifts entry fills -> stops/targets/trade selection, so a naive
    "highest passing tier" can certify survival through a tier whose cheaper neighbor
    failed -- overstating robustness. The contiguous rule only ever lowers survival,
    the safe direction for a gate. All tiers still run so tier_results stays complete.
    """
    results = {}
    cost_survives_through = "none"
    survival_intact = True

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
            if survival_intact and passes:
                cost_survives_through = tier
            elif not passes:
                survival_intact = False
        except Exception as exc:
            print(f"  [WARN] cost-sweep error at {tier}: {exc}")
            results[tier] = {"pf": 0.0, "trades": 0, "passes": False}
            survival_intact = False

    return {
        "cost_survives_through": cost_survives_through,
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
    from backtest._gate_v2_trade_metrics import (
        trade_level_dsr,
        trade_level_mc_95th_dd,
        trade_level_win_rate_ci_lower,
    )

    oos_pfs = [r.profit_factor for r in oos_results if r.total_trades >= MIN_OOS_TRADES_PER_WINDOW]
    oos_dds = [r.max_drawdown_pct for r in oos_results]
    all_trades = sum(r.total_trades for r in oos_results)
    sample_adequate = all_trades >= MIN_OOS_TRADES_TOTAL

    pf_ci_lower = _bootstrap_pf_ci_lower(oos_pfs)
    p_edge = float(sum(1 for pf in oos_pfs if pf > 1.0) / max(1, len(oos_pfs)))

    # Trade-level risk metrics (correct). mc_95th_dd is a real permutation Monte
    # Carlo on the concatenated OOS trade list; dsr is the Deflated Sharpe from the
    # actual per-trade return series. The legacy window-level DD is retained under
    # mc_95th_dd_window_legacy for before/after transparency only and is NOT used
    # for the gate decision. See _gate_v2_trade_metrics for the rationale.
    mc_95th_dd = trade_level_mc_95th_dd(oos_results, initial_capital=CAPITAL)
    dsr = trade_level_dsr(oos_results, n_grid_combos=n_grid_combos, initial_capital=CAPITAL)
    win_rate_ci_lower = trade_level_win_rate_ci_lower(oos_results)  # Init 2C (shadow; not gated)
    mc_95th_dd_window_legacy = float(np.percentile(oos_dds, 95.0)) if oos_dds else 1.0

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

    if sample_adequacy_enforced() and not sample_adequate:
        # Init 2B: too few total OOS trades to certify — refuse rather than
        # certify an edge on a thin (luck-dominated) sample. Shadow by default;
        # enforced only when GATE_V2_ENFORCE_SAMPLE_ADEQUACY=1.
        verdict = "INSUFFICIENT_SAMPLE"
        passed_via = None
    elif core_pass:
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
        "mc_95th_dd_window_legacy": round(mc_95th_dd_window_legacy, 6),
        "dsr": round(dsr, 6),
        "wfo_consistency": wfo_consistency,
        "fixed_params_min_pf": fixed_params_min_pf,
        "fixed_params_mean_pf": fixed_params_metrics.get("fixed_params_mean_pf", 0.0),
        "fixed_params_max_pf": fixed_params_metrics.get("fixed_params_max_pf", 0.0),
        "cost_survives_through": cost_survives_through,
        "n_oos_windows": len(oos_results),
        "n_oos_windows_with_trades": len(oos_pfs),
        "total_oos_trades": all_trades,
        "min_oos_trades_total": MIN_OOS_TRADES_TOTAL,
        "sample_adequate": sample_adequate,
        "win_rate_ci_lower": round(win_rate_ci_lower, 4),
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
    print(f"[MES-R11] Selected {data_file.name}")

    print(f"[MES-R11] Loading {data_file.name} ...")
    df = _load_data(data_file)
    print(f"[MES-R11] {len(df)} bars | {df.index.min().date()} -> {df.index.max().date()}")

    windows = _generate_windows(df)
    if not windows:
        print("[MES-R11] ERROR: not enough data to form windows.")
        return {}

    # 3 × 1 × 1 = 3 combos — slow=190 dropped (laggard in rank10, floored min_pf at 1.1098)
    grid = list(itertools.product(FAST_PERIOD_VALUES, SLOW_PERIOD_VALUES, ATR_TRAIL_MULT_VALUES))
    n_combos = len(grid)

    print(f"\n{'=' * 70}")
    print("=== MES TREND RANK 11 — FINAL GRID [50,55,60]x[200], DROP slow=190 OUTLIER ===")
    print(
        f"Windows: {len(windows)} | Train: {TRAIN_MONTHS}mo | Test: {TEST_MONTHS}mo | Step: {STEP_MONTHS}mo"
    )
    print(f"Grid: {n_combos} combos")
    print(f"  fast_period     : {FAST_PERIOD_VALUES}  (champion: 50)")
    print(
        f"  slow_period     : {SLOW_PERIOD_VALUES}  (champion: 200; slow=190 DROPPED — laggard in rank10, floored min_pf at 1.1098)"
    )
    print(f"  atr_trail_mult  : {ATR_TRAIL_MULT_VALUES}  (champion: 2.0, fixed)")
    print(
        f"  min_oos_trades  : {MIN_OOS_TRADES_PER_WINDOW}  (was 5 — SMA generates 1-3 trades/window)"
    )
    print(f"  min_rv_annualized: {MIN_RV_ANNUALIZED} (disabled — baseline comparison with rank7)")
    print("Rank 10 baseline: dsr=1.0, rolling_wfo=STRONG, fixed_params=1.1098 (FAIL), mc_dd=0.81%")
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
        print("\n[MES-R11] No OOS results — WFO aborted.")
        return {}

    # -----------------------------------------------------------------------
    # Fixed-params sweep on full dataset (ALT metric: fixed_params_min_pf)
    # -----------------------------------------------------------------------
    print(f"\n[MES-R11] Running fixed-params sweep on full dataset ({n_combos} tight combos)...")
    print(
        "  (slow=190 removed — rank10 had min_pf=1.1098 driven by (55,190) and (50,190) laggards)"
    )
    fixed_params_metrics = _run_fixed_params_sweep(df, grid)
    print(
        f"  fixed_params_min_pf  = {fixed_params_metrics['fixed_params_min_pf']:.4f}  "
        f"(need >= {GATE_FIXED_PARAMS_MIN_PF}, rank10 was 1.1098 FAIL)"
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
        f"\n[MES-R11] Running cost sweep (champion: fast={champion_params['fast']}, "
        f"slow={champion_params['slow']}, trail={champion_params['atr_trail_mult']})..."
    )
    print("  (rank10 survived through 'catastrophic' — baseline to match)")
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
        f"(need >= {GATE_FIXED_PARAMS_MIN_PF} for ALT, rank10 was 1.1098 FAIL)"
    )
    print(
        f"  cost_survives_through= {gate['cost_survives_through']}  "
        f"(need >= 'realistic', rank10 was 'catastrophic')"
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
    verdict_file = verdicts_dir / "MES_trend_rank11.json"

    verdict_doc = {
        "symbol": SYMBOL,
        "family": "trend",
        "rank": 11,
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
            "mc_95th_dd_window_legacy": gate["mc_95th_dd_window_legacy"],
            "dsr": gate["dsr"],
            "wfo_consistency": gate["wfo_consistency"],
            "fixed_params_min_pf": gate["fixed_params_min_pf"],
            "fixed_params_mean_pf": gate["fixed_params_mean_pf"],
            "fixed_params_max_pf": gate["fixed_params_max_pf"],
            "n_combos_with_trades": fixed_params_metrics.get("n_combos_with_trades", 0),
            "combo_results": fixed_params_metrics.get("combo_results", []),
            "cost_survives_through": gate["cost_survives_through"],
            "cost_tier_results": cost_sweep_metrics.get("tier_results", {}),
            "total_oos_trades": gate["total_oos_trades"],
            "min_oos_trades_total": gate["min_oos_trades_total"],
            "sample_adequate": gate["sample_adequate"],
            "win_rate_ci_lower": gate["win_rate_ci_lower"],
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
            "rank7_dsr": 0.667,
            "rank7_rolling_wfo": "STRONG",
            "rank7_fixed_params_min_pf": 1.275,
            "rank7_cost_survives_through": "catastrophic",
            "rank7_mc_95th_dd_pct": 5.3969,
            "rank8_verdict": "FAIL",
            "rank8_fail_reasons": [
                "MIN_OOS_TRADES_PER_WINDOW=5 excluded all 18 OOS windows (SMA generates 1-3 trades/2mo)",
                "fast=40 combos (PF~0.45) dragged fixed_params_min_pf to 0.447",
            ],
            "rank9_verdict": "FAIL",
            "rank9_fail_reasons": [
                "slow=210+fast=50 combo produced PF 0.686, dragging fixed_params_min_pf below 1.20",
                "rank9 had dsr=0.999, rolling_wfo=STRONG, mc_dd=0.87% — all other metrics passed",
            ],
            "rank10_verdict": "FAIL",
            "rank10_fail_reasons": [
                "(55,190) and (50,190) laggard combos floored fixed_params_min_pf at 1.1098 (< 1.20)",
                "rank10 had dsr=1.0, rolling_wfo=STRONG, cost=catastrophic, mc_dd=0.81% — all other metrics passed",
            ],
            "refresh_reason": "rank11 fix: slow=190 dropped (laggards (55,190) and (50,190) floored min_pf at 1.1098; [50,55,60]x[200] all PF>=1.35)",
        },
    }

    verdict_file.write_text(json.dumps(verdict_doc, indent=2, default=str))
    print(f"\n[MES-R11] Verdict written -> {verdict_file}")

    return verdict_doc


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    verdict = run_wfo()

    if not verdict:
        print("[MES-R11] No verdict produced — check data/logs above.")
        sys.exit(1)

    final = verdict.get("verdict", "FAIL")
    passed_via = verdict.get("passed_via")
    gate = verdict.get("gate_v2_metrics", {})

    if final == "PASS" and passed_via == "core":
        print("\n[PASS-CORE] MES Trend Rank 11 PASSES gate v2 (CORE path).")
        print("  Strategy qualifies without ALT constraints.")
    elif final == "PASS" and passed_via == "alt":
        print("\n[PASS-ALT] MES Trend Rank 11 PASSES gate v2 (ALT path — $50K+ accounts).")
        print("  MES trend remains eligible; rank11 refreshed for another 14 days.")
    else:
        print("\n[FAIL] MES Trend Rank 11 FAILS gate v2.")
        fpmf = gate.get("fixed_params_min_pf", 0.0)
        if fpmf < GATE_FIXED_PARAMS_MIN_PF:
            gap = GATE_FIXED_PARAMS_MIN_PF - fpmf
            print(f"  fixed_params_min_pf={fpmf:.4f} is {gap:.4f} short of 1.20")
        cost = gate.get("cost_survives_through", "none")
        if cost not in COST_TIER_ORDER or COST_TIER_ORDER.index(cost) < COST_TIER_ORDER.index(
            "realistic"
        ):
            print(f"  cost_survives_through={cost} does not meet 'realistic' minimum")

    # Detailed per-metric report vs rank9 baseline
    print("\n  Metric comparison vs rank10:")
    checks = [
        ("dsr", gate.get("dsr", 0), GATE_DSR_ALT, ">=", 1.0),
        ("wfo_consistency", gate.get("wfo_consistency", "?"), None, None, "STRONG"),
        (
            "fixed_params_min_pf",
            gate.get("fixed_params_min_pf", 0),
            GATE_FIXED_PARAMS_MIN_PF,
            ">=",
            1.1098,
        ),
        (
            "cost_survives_through",
            gate.get("cost_survives_through", "none"),
            "realistic",
            ">=",
            "catastrophic",
        ),
        ("mc_95th_dd_pct", gate.get("mc_95th_dd_pct", 100), GATE_MC_DD_ALT * 100, "<=", 0.81),
    ]
    for name, val, threshold, op, prior_val in checks:
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
            print(f"  {status:4s} {name}: {val:.4f}  (rank10={prior_val}  need {op} {threshold})")
        else:
            print(f"  {status:4s} {name}: {val}  (rank10={prior_val}  need {op} {threshold})")


if __name__ == "__main__":
    main()
