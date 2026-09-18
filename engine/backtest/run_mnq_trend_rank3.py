#!/usr/bin/env python
"""
MNQ Trend Gate v2 - Rank 3 Verdict

rank3 - faster SMA periods + tighter RV floor (2026-05-09)

Context:
    Rank1 (fast=[48,50,52], slow=[195,200,205]): DEGENERATE - SMA(50,200) never
    crosses in 6-month IS windows during 2024-2025 bull market. Zero IS trades.

    Rank2 (fast=[20,25,30], slow=[80,100,120]): Produces IS crossovers (2-4 per
    6-month window). Real evaluation. If FAIL, proceed here.

    Rank3 tests faster intraday-trend timescale: SMA(10-15, 40-60) operates on a
    1-3 week horizon vs. rank2's 2-6 month horizon. NQ's intraday momentum is known
    to be stronger at shorter timescales (earnings, FOMC, macro releases). Also
    raises the RV floor to 12% (vs 9%) to avoid entering during low-vol choppy
    periods where short SMAs generate false crosses.

Hypothesis:
    NQ's trend edge, if it exists in 2024-2025, concentrates at the faster
    1-3 week scale where price trends before mean-reverting. SMA(50,200) never
    fires because it tracks the multi-year bull trend, not tradeable swings.
    SMA(20,80) fires but may be too slow to survive the volatile NQ OOS regime.
    SMA(10,50) at 12% RV floor should capture trend-momentum bursts while
    filtering low-vol chop.

MNQ vs MES differences:
    point_value : $2.0  (MES is $5.0)
    tick_size   : 0.25  (same)
    commission  : $0.62/contract  (same)
    ATR scale   : MNQ raw ATR ~5x MES in index points; dollar ATR similar.
    Capital     : $10,000 base (backtest sizing only; live gate in engine routing)
    RV floor    : Raised to [0.0, 12.0] vs rank2's [0.0, 9.0] - tighter chop filter

Grid (rank3 = faster periods + raised RV floor):
    fast_period       : [10, 12, 15]
    slow_period       : [40, 50, 60]
    atr_trail_mult    : [1.5, 2.0, 2.5]
    min_rv_annualized : [0.0, 12.0]
    3 x 3 x 3 x 2 = 54 combos

WFO config (matches rank1/rank2):
    TRAIN_MONTHS = 6
    TEST_MONTHS  = 1
    STEP_MONTHS  = 1
    N_WINDOWS    = 18 (target; actual depends on data span)

Data:
    MNQ 1h, 2024-01-01 to 2026-03-28
    File: engine/backtest/cache/MNQ_2024-01-01_2026-03-28_1h.csv

Gate v2 thresholds (ALT path - $50K+ accounts):
    pf_ci_lower      >= 1.10
    p_edge           >= 0.95
    mc_95th_dd       <= 7%  (ALT ceiling)
    dsr              >= 0.30 (ALT floor)
    wfo_consistency  in [MODERATE, STRONG]
    fixed_params_min_pf >= 1.20
    cost_survives_through >= realistic

Writes: engine/data/gate_v2_verdicts/MNQ_trend_rank3.json

Usage (from engine/ directory):
    .venv/Scripts/python backtest/run_mnq_trend_rank3.py
"""
from __future__ import annotations

import itertools
import json
import sys
from collections import Counter
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

SYMBOL = "MNQ"
MULTIPLIER = 2.0  # $2 per point (Micro Nasdaq-100)
CAPITAL = 10_000.0  # backtest sizing only; live gate enforced in engine routing
TICK_SIZE = 0.25
COMMISSION = 0.62  # $/contract round-trip (IB micro futures)
SLIPPAGE_TICKS = 2.0

TRAIN_MONTHS = 6
TEST_MONTHS = 1
STEP_MONTHS = 1
N_WINDOWS = 18  # target; actual depends on data span

# Grid: faster periods than rank2 to probe shorter-timescale trend momentum.
# Raised RV floor (12% vs rank2's 9%) to filter NQ low-vol chop more aggressively.
# 3 x 3 x 3 x 2 = 54 combos
FAST_PERIOD_VALUES = [10, 12, 15]
SLOW_PERIOD_VALUES = [40, 50, 60]
ATR_TRAIL_MULT_VALUES = [1.5, 2.0, 2.5]
MIN_RV_ANNUALIZED_VALUES = [0.0, 12.0]

# Gate v2 thresholds: runner-specific ALT overrides only.
# Core thresholds imported from _gate_v2_helpers (single source of truth).

# Cost-sweep tiers
COST_SWEEP_TIERS = {
    "optimistic": {"commission": 0.31, "slippage_ticks": 1.0},
    "realistic": {"commission": 0.62, "slippage_ticks": 2.0},
    "pessimistic": {"commission": 1.24, "slippage_ticks": 3.0},
    "catastrophic": {"commission": 2.48, "slippage_ticks": 4.0},
}

# Faster SMAs generate more crosses per window; 2 trades minimum avoids
# single-trade window noise but keeps enough windows in the OOS sample.
MIN_OOS_TRADES_PER_WINDOW = 2


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


def _find_data_file(data_dir: Path) -> Path:
    """Locate the MNQ 1h cache with the latest end-date."""
    chosen = _find_latest_cache(data_dir, "MNQ")
    print(f"[MNQ-R3] Selected {chosen.name}")
    return chosen


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
    min_rv_annualized: float = 0.0,
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
        min_rv_annualized=min_rv_annualized,
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

    for fast, slow, atr_trail_mult, min_rv in grid:
        try:
            result = _run_signals_and_backtest(
                df_train, fast, slow, atr_trail_mult, min_rv_annualized=min_rv
            )
        except Exception as exc:
            print(f"    [WARN] IS error ({fast},{slow},{atr_trail_mult},rv={min_rv}): {exc}")
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
                "min_rv_annualized": min_rv,
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
from backtest._gate_v2_helpers import (  # noqa: E402
    GATE_DSR,
    GATE_DSR_ALT,
    GATE_MC_DD_ALT,
    GATE_MC_DD_CORE,
    GATE_P_EDGE,
    GATE_PF_CI_LOWER,
    _find_latest_cache,
)
from backtest._gate_v2_helpers import (
    bootstrap_pf_ci_lower as _bootstrap_pf_ci_lower,
)
from backtest._gate_v2_helpers import (
    classify_wfo_consistency as _classify_wfo_consistency,
)

# ---------------------------------------------------------------------------
# Fixed-params sweep (ALT metric: fixed_params_min_pf)
# ---------------------------------------------------------------------------


def _run_fixed_params_sweep(df: pd.DataFrame, grid: list[tuple]) -> dict:
    pfs = []
    combo_results = []
    for fast, slow, atr_trail_mult, min_rv in grid:
        try:
            result = _run_signals_and_backtest(
                df, fast, slow, atr_trail_mult, min_rv_annualized=min_rv
            )
            if result.total_trades >= MIN_OOS_TRADES_PER_WINDOW:
                pfs.append(result.profit_factor)
                combo_results.append(
                    {
                        "fast": fast,
                        "slow": slow,
                        "atr_trail_mult": atr_trail_mult,
                        "min_rv_annualized": min_rv,
                        "pf": round(result.profit_factor, 4),
                        "trades": result.total_trades,
                    }
                )
                print(
                    f"    combo ({fast:3d},{slow:3d},{atr_trail_mult:.1f},rv={min_rv:.0f}): "
                    f"PF={result.profit_factor:.4f}  trades={result.total_trades}"
                )
            else:
                print(
                    f"    combo ({fast:3d},{slow:3d},{atr_trail_mult:.1f},rv={min_rv:.0f}): "
                    f"SKIP ({result.total_trades} trades)"
                )
        except Exception as exc:
            print(
                f"  [WARN] fixed-params error ({fast},{slow},{atr_trail_mult},rv={min_rv}): {exc}"
            )

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
                min_rv_annualized=champion_params.get("min_rv_annualized", 0.0),
                commission=costs["commission"],
                slippage_ticks=costs["slippage_ticks"],
            )
            pf = result.profit_factor
            passes = pf > 1.0 and result.total_trades >= MIN_OOS_TRADES_PER_WINDOW
            results[tier] = {"pf": round(pf, 4), "trades": result.total_trades, "passes": passes}
            print(
                f"    [{tier:12s}] commission={costs['commission']:.2f}  "
                f"slip={costs['slippage_ticks']:.1f}t  PF={pf:.4f}  "
                f"trades={result.total_trades}  {'PASS' if passes else 'FAIL'}"
            )
            if passes:
                last_surviving = tier
        except Exception as exc:
            print(f"  [WARN] cost-sweep error at {tier}: {exc}")
            results[tier] = {"pf": 0.0, "trades": 0, "passes": False}
    return {"cost_survives_through": last_surviving or "none", "tier_results": results}


# ---------------------------------------------------------------------------
# Gate v2 full evaluation
# ---------------------------------------------------------------------------


def _compute_gate_v2(
    oos_results: list,
    n_grid_combos: int,
    fixed_params_metrics: dict,
    cost_sweep_metrics: dict,
) -> dict:
    from backtest._gate_v2_trade_metrics import trade_level_dsr

    oos_pfs = [r.profit_factor for r in oos_results if r.total_trades >= MIN_OOS_TRADES_PER_WINDOW]
    oos_dds = [r.max_drawdown_pct for r in oos_results]
    all_trades = sum(r.total_trades for r in oos_results)

    pf_ci_lower = _bootstrap_pf_ci_lower(oos_pfs)
    p_edge = float(sum(1 for pf in oos_pfs if pf > 1.0) / max(1, len(oos_pfs)))
    mc_95th_dd = float(np.percentile(oos_dds, 95.0)) if oos_dds else 1.0
    # DSR from the ACTUAL per-trade OOS return series, not the mean of per-window
    # Sharpes (a 1-2 trade window's giant Sharpe deflated to a fake ~1.0 and
    # auto-passed both gate floors). See _gate_v2_trade_metrics for the why.
    dsr = trade_level_dsr(oos_results, n_grid_combos=n_grid_combos, initial_capital=CAPITAL)

    wfo_consistency = _classify_wfo_consistency(oos_pfs)
    fixed_params_min_pf = fixed_params_metrics.get("fixed_params_min_pf", 0.0)
    cost_survives_through = cost_sweep_metrics.get("cost_survives_through", "none")
    cost_tier_idx = (
        COST_TIER_ORDER.index(cost_survives_through)
        if cost_survives_through in COST_TIER_ORDER
        else -1
    )
    cost_realistic_idx = COST_TIER_ORDER.index("realistic")
    cost_passes = cost_tier_idx >= cost_realistic_idx

    core_pass = (
        pf_ci_lower >= GATE_PF_CI_LOWER
        and p_edge >= GATE_P_EDGE
        and mc_95th_dd <= GATE_MC_DD_CORE
        and dsr >= GATE_DSR
    )
    alt_pass = (
        dsr >= GATE_DSR_ALT
        and wfo_consistency in GATE_WFO_CONSISTENCY_VALUES
        and fixed_params_min_pf >= GATE_FIXED_PARAMS_MIN_PF
        and cost_passes
        and mc_95th_dd <= GATE_MC_DD_ALT
    )

    def _cr(label: str, val: float, threshold: float, op: str) -> str:
        passed = (val >= threshold) if op == ">=" else (val <= threshold)
        prefix = "" if passed else "FAIL "
        return f"{prefix}{label}={val:.4f} {op} {threshold}"

    core_reasons = [
        _cr("pf_ci_lower", pf_ci_lower, GATE_PF_CI_LOWER, ">="),
        _cr("p_edge", p_edge, GATE_P_EDGE, ">="),
        _cr("mc_95th_dd_pct", mc_95th_dd * 100, GATE_MC_DD_CORE * 100, "<="),
        _cr("dsr", dsr, GATE_DSR, ">="),
    ]
    alt_reasons = [
        _cr("dsr_alt", dsr, GATE_DSR_ALT, ">="),
        f"{'FAIL ' if wfo_consistency not in GATE_WFO_CONSISTENCY_VALUES else ''}wfo_consistency={wfo_consistency}",
        _cr("fixed_params_min_pf", fixed_params_min_pf, GATE_FIXED_PARAMS_MIN_PF, ">="),
        f"{'FAIL ' if not cost_passes else ''}cost_survives_through={cost_survives_through} >= realistic",
        _cr("mc_95th_dd_pct_alt", mc_95th_dd * 100, GATE_MC_DD_ALT * 100, "<="),
    ]

    if core_pass:
        verdict, passed_via = "PASS", "core"
    elif alt_pass:
        verdict, passed_via = "PASS", "alt"
    else:
        verdict, passed_via = "FAIL", None

    return {
        "verdict": verdict,
        "passed_via": passed_via,
        "core_verdict": "PASS" if core_pass else "FAIL",
        "alt_verdict": "PASS" if alt_pass else "FAIL",
        "n_core_passed": sum(1 for r in core_reasons if not r.startswith("FAIL")),
        "n_alt_passed": sum(1 for r in alt_reasons if not r.startswith("FAIL")),
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
    data_dir = engine_root / "backtest" / "cache"
    data_file = _find_data_file(data_dir)

    print(f"[MNQ-R3] Loading {data_file.name} ...")
    df = _load_data(data_file)
    print(f"[MNQ-R3] {len(df)} bars | {df.index.min().date()} -> {df.index.max().date()}")

    windows = _generate_windows(df)
    if not windows:
        print("[MNQ-R3] ERROR: not enough data to form WFO windows.")
        return {}

    grid = list(
        itertools.product(
            FAST_PERIOD_VALUES,
            SLOW_PERIOD_VALUES,
            ATR_TRAIL_MULT_VALUES,
            MIN_RV_ANNUALIZED_VALUES,
        )
    )
    n_combos = len(grid)

    print(f"\n{'=' * 70}")
    print("=== MNQ TREND RANK 3 - FASTER PERIODS + RAISED RV FLOOR ===")
    print(
        f"Windows: {len(windows)} | Train: {TRAIN_MONTHS}mo | Test: {TEST_MONTHS}mo | Step: {STEP_MONTHS}mo"
    )
    print(f"Grid: {n_combos} combos")
    print(
        f"  fast_period       : {FAST_PERIOD_VALUES}  (rank2 used [20,25,30]; rank1 used [48,50,52])"
    )
    print(
        f"  slow_period       : {SLOW_PERIOD_VALUES}  (rank2 used [80,100,120]; 1-3 week timescale)"
    )
    print(f"  atr_trail_mult    : {ATR_TRAIL_MULT_VALUES}")
    print(
        f"  min_rv_annualized : {MIN_RV_ANNUALIZED_VALUES}  (rank2 used [0.0, 9.0]; 12% tighter chop filter)"
    )
    print(f"  capital           : ${CAPITAL:,.0f}  (backtest sizing; live gate in engine routing)")
    print(f"  multiplier        : ${MULTIPLIER:.1f}/point  (MNQ Micro Nasdaq-100)")
    print(
        f"ALT thresholds: dsr>={GATE_DSR_ALT}, wfo in {GATE_WFO_CONSISTENCY_VALUES}, "
        f"fixed>={GATE_FIXED_PARAMS_MIN_PF}, mc_dd<={GATE_MC_DD_ALT * 100:.0f}%"
    )
    print("MES R11 baseline: pf_ci_lower=2.156, dsr=1.0, wfo=STRONG, mc_dd=0.81%")
    print(f"{'=' * 70}")

    oos_results = []
    window_records = []

    for win in windows:
        wnum = win["window_num"]
        ts, te = win["train_start"], win["train_end"]
        os_, oe = win["test_start"], win["test_end"]

        print(
            f"\nWindow {wnum}: IS {ts.strftime('%Y-%m')}->{te.strftime('%Y-%m')}  "
            f"OOS {os_.strftime('%Y-%m')}->{oe.strftime('%Y-%m')}  "
            f"({win['n_train']} / {win['n_test']} bars)"
        )

        df_train = df[(df.index >= ts) & (df.index < te)].copy()
        df_test = df[(df.index >= os_) & (df.index <= oe)].copy()

        best_params, is_result = _best_is_params(df_train, grid)
        if best_params is None:
            print("  [SKIP] No valid IS params")
            continue

        print(
            f"  Best IS: fast={best_params['fast']}  slow={best_params['slow']}  "
            f"trail={best_params['atr_trail_mult']}  rv={best_params['min_rv_annualized']}  "
            f"PF={is_result.profit_factor:.2f}  trades={is_result.total_trades}"
        )

        try:
            oos_result = _run_signals_and_backtest(
                df_test,
                fast=best_params["fast"],
                slow=best_params["slow"],
                atr_trail_mult=best_params["atr_trail_mult"],
                min_rv_annualized=best_params["min_rv_annualized"],
            )
        except Exception as exc:
            print(f"  [SKIP] OOS error: {exc}")
            continue

        print(
            f"  OOS: PF={oos_result.profit_factor:.2f}  "
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
        print("\n[MNQ-R3] No OOS results - WFO aborted.")
        print(
            "[MNQ-R3] If IS windows still show 0 trades, the SMA trend family has no edge on MNQ."
        )
        print("[MNQ-R3] Consider P3-12 (HTF-conditioned mean-rev) or P3-15 (regime detector).")
        return {}

    # Fixed-params sweep
    print(f"\n[MNQ-R3] Fixed-params sweep on full dataset ({n_combos} combos)...")
    fixed_params_metrics = _run_fixed_params_sweep(df, grid)
    print(
        f"  fixed_params_min_pf  = {fixed_params_metrics['fixed_params_min_pf']:.4f}  "
        f"(need >= {GATE_FIXED_PARAMS_MIN_PF})"
    )

    # Cost sweep (most-selected champion)
    param_votes = Counter(
        (
            r["best_params"]["fast"],
            r["best_params"]["slow"],
            r["best_params"]["atr_trail_mult"],
            r["best_params"]["min_rv_annualized"],
        )
        for r in window_records
    )
    most_selected = param_votes.most_common(1)[0][0] if param_votes else (12, 50, 2.0, 0.0)
    champion_params = {
        "fast": most_selected[0],
        "slow": most_selected[1],
        "atr_trail_mult": most_selected[2],
        "min_rv_annualized": most_selected[3],
    }
    print(f"\n[MNQ-R3] Cost sweep (champion: {champion_params})...")
    cost_sweep_metrics = _run_cost_sweep(df, champion_params)
    print(
        f"  cost_survives_through = {cost_sweep_metrics['cost_survives_through']}  "
        f"(need >= 'realistic')"
    )

    # Gate v2
    gate = _compute_gate_v2(oos_results, n_combos, fixed_params_metrics, cost_sweep_metrics)

    print(f"\n{'=' * 70}")
    print(f"=== GATE v2 VERDICT: {gate['verdict']} (via {gate['passed_via'] or 'NONE'}) ===")
    print(f"  pf_ci_lower          = {gate['pf_ci_lower']:.4f}  (need >= {GATE_PF_CI_LOWER})")
    print(f"  p_edge               = {gate['p_edge']:.4f}  (need >= {GATE_P_EDGE})")
    print(
        f"  mc_95th_dd_pct       = {gate['mc_95th_dd_pct']:.4f}%  "
        f"(core <= {GATE_MC_DD_CORE*100:.0f}% / alt <= {GATE_MC_DD_ALT*100:.0f}%)"
    )
    print(
        f"  dsr                  = {gate['dsr']:.6f}  "
        f"(core >= {GATE_DSR} / alt >= {GATE_DSR_ALT})"
    )
    print(f"  wfo_consistency      = {gate['wfo_consistency']}")
    print(
        f"  fixed_params_min_pf  = {gate['fixed_params_min_pf']:.4f}  (need >= {GATE_FIXED_PARAMS_MIN_PF})"
    )
    print(f"  cost_survives_through= {gate['cost_survives_through']}")
    print(f"  core_verdict         = {gate['core_verdict']}")
    print(f"  alt_verdict          = {gate['alt_verdict']}")
    print(
        f"  OOS windows          = {gate['n_oos_windows_with_trades']} with trades / {gate['n_oos_windows']} total"
    )
    print(f"  Total OOS trades     = {gate['total_oos_trades']}")
    print(f"{'=' * 70}")

    # Write verdict JSON
    verdicts_dir = engine_root / "data" / "gate_v2_verdicts"
    verdicts_dir.mkdir(parents=True, exist_ok=True)
    verdict_file = verdicts_dir / "MNQ_trend_rank3.json"

    now_iso = datetime.now(tz=timezone.utc).isoformat()
    verdict_doc = {
        "symbol": SYMBOL,
        "family": "trend",
        "rank": 3,
        "verdict": gate["verdict"],
        "passed_via": gate["passed_via"],
        "core_verdict": gate["core_verdict"],
        "alt_verdict": gate["alt_verdict"],
        "n_core_passed": gate["n_core_passed"],
        "n_alt_passed": gate["n_alt_passed"],
        "created_at": now_iso,
        "aux_freshness": {"rolling_wfo": now_iso, "fixed_params": now_iso, "cost_sweep": now_iso},
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
            "grid_min_rv_annualized": MIN_RV_ANNUALIZED_VALUES,
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
        "champion_params": champion_params,
        "windows": window_records,
        "contract_spec": {
            "symbol": SYMBOL,
            "multiplier": MULTIPLIER,
            "tick_size": TICK_SIZE,
            "commission": COMMISSION,
            "capital": CAPITAL,
            "note": "MNQ DO_NOT_TRADE live gate enforced in engine routing; capital here is backtest-only",
        },
        "lineage": {
            "family": "trend",
            "rank": 3,
            "predecessor": "MNQ_trend_rank2",
            "rank1_verdict": "DEGENERATE",
            "rank1_reason": "SMA(50,200) never crosses in 6-month IS windows during 2024-2025 bull market",
            "rank2_grid": "[20,25,30] x [80,100,120] x [1.5,2.0,2.5] x rv=[0.0,9.0]",
            "rank3_hypothesis": "Faster 1-3 week timescale + 12% RV floor to filter chop",
            "rank3_grid": "[10,12,15] x [40,50,60] x [1.5,2.0,2.5] x rv=[0.0,12.0]",
            "mes_rank11_verdict": "PASS via alt",
            "mes_rank11_pf_ci_lower": 2.156,
            "mes_rank11_dsr": 1.0,
            "mes_rank11_wfo": "STRONG",
            "mes_rank11_mc_dd_pct": 0.81,
            "mnq_breakout_status": "EXHAUSTED - all ranks 1-7 fail gate v2 (non-stationarity)",
            "refresh_reason": "Rank2 grid produces IS crossovers; rank3 tests even faster timescale",
        },
    }

    # Provenance (2026-09-17 audit): record which cache produced this verdict.
    from backtest._gate_v2_helpers import inject_cache_provenance as _inject_prov  # noqa: E402
    verdict_doc = _inject_prov(verdict_doc, data_file)
    verdict_file.write_text(json.dumps(verdict_doc, indent=2, default=str))
    print(f"\n[MNQ-R3] Verdict written -> {verdict_file}")
    return verdict_doc


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    verdict = run_wfo()
    if not verdict:
        print("[MNQ-R3] No verdict produced.")
        print("[MNQ-R3] If IS windows show 0 trades, SMA trend has no edge on MNQ at any period.")
        print("[MNQ-R3] Next candidates: P3-12 (HTF-conditioned mean-rev), P3-15 (regime alert).")
        sys.exit(1)

    final = verdict.get("verdict", "FAIL")
    passed_via = verdict.get("passed_via")
    gate = verdict.get("gate_v2_metrics", {})

    if final == "PASS" and passed_via == "core":
        print("\n[PASS-CORE] MNQ Trend Rank 3 PASSES gate v2 (CORE path).")
        print("  ACTION: Update SMA_TREND_PARAMS['MNQ'] in trend_signals.py with champion params.")
        print("  ACTION: Remove MNQ from DO_NOT_TRADE_SYMBOLS after live-trading authorization.")
    elif final == "PASS" and passed_via == "alt":
        print("\n[PASS-ALT] MNQ Trend Rank 3 PASSES gate v2 (ALT path -- $50K+ accounts).")
        print("  ACTION: Update SMA_TREND_PARAMS['MNQ'] with champion params.")
        print("  ACTION: Remove MNQ from DO_NOT_TRADE_SYMBOLS after live-trading authorization.")
        print("  NOTE:   ALT path requires $50K+ account -- enforce in position sizer.")
    else:
        print("\n[FAIL] MNQ Trend Rank 3 FAILS gate v2.")
        fpmf = gate.get("fixed_params_min_pf", 0.0)
        if fpmf < GATE_FIXED_PARAMS_MIN_PF:
            print(
                f"  fixed_params_min_pf={fpmf:.4f} is {GATE_FIXED_PARAMS_MIN_PF - fpmf:.4f} short"
            )
        cost = gate.get("cost_survives_through", "none")
        if cost not in COST_TIER_ORDER or COST_TIER_ORDER.index(cost) < COST_TIER_ORDER.index(
            "realistic"
        ):
            print(f"  cost_survives_through={cost} does not meet 'realistic' minimum")
        dsr_val = gate.get("dsr", 0.0)
        if dsr_val < GATE_DSR_ALT:
            print(f"  dsr={dsr_val:.6f} below ALT floor {GATE_DSR_ALT}")
            print("  MNQ SMA trend family may be exhausted -- all ranks 1-3 FAIL")
            print("  Consider P3-12 (HTF-conditioned mean-rev) as the MNQ edge hypothesis")
        wfo = gate.get("wfo_consistency", "WEAK")
        if wfo not in GATE_WFO_CONSISTENCY_VALUES:
            print(f"  wfo_consistency={wfo} -- MNQ trend edge not stable across 2024-2025 regimes")


if __name__ == "__main__":
    main()
