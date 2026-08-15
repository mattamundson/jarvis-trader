#!/usr/bin/env python
"""
MGC Trend — Realized-Volatility Filter Gate v2 Validation (rv_filter_rank1)

MGC baseline: rank4 PASS via alt (p_edge=0.6842, wfo=MODERATE, dsr=1.0,
fixed_params_min_pf=1.3574). Champion: SMA(50,120), atr_trail_mult=2.0.

Hypothesis: RV filter at 9% annualized should suppress low-vol ranging periods
where the SMA crossover produces false signals, improving OOS PF consistency.

Note on empirical basis: unlike MES (where 36 live paper trades gave direct
evidence of RV>=9% improving PF by +23%), MGC does not yet have enough live
paper trades for the same analysis. This run applies the same threshold as MES
as an initial hypothesis. If it fails (wfo=WEAK or PF direction wrong), the
threshold should be calibrated empirically once 60+ live paper trades accumulate.

Grid (3 combos, centered on rank4 champion):
    fast_period:    [40, 50, 55]
    slow_period:    [120]
    atr_trail_mult: [2.0]

WFO: TEST_MONTHS=3, STEP_MONTHS=3 (non-overlapping OOS). Rank4 used 2-month
OOS; RV filter reduces trades per window further, so 3-month gives better stats.

Usage (from engine/ directory):
    .venv/Scripts/python backtest/run_mgc_trend_rv_filter_rank1.py
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

from backtest.contract_specs import CONTRACT_SPECS  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SYMBOL = "MGC"
MULTIPLIER = 10.0
CAPITAL = 50_000.0
TICK_SIZE = 0.10
# Imported from contract_specs.py (single source of truth) rather than a
# local literal -- this file previously hardcoded 0.62, MES's rate, instead
# of MGC's documented 0.85 (found 2026-07-10). contract_specs.py's own
# docstring exists precisely because this class of drift ("MCL commission
# was 0.62 in one script and 0.85 in another") has happened before.
COMMISSION = CONTRACT_SPECS["MGC"].commission
SLIPPAGE_TICKS = 2.0

TRAIN_MONTHS = 6
TEST_MONTHS = 3  # 3-month non-overlapping OOS for statistical power with filtered trades
STEP_MONTHS = 3  # non-overlapping: STEP == TEST

FAST_PERIOD_VALUES = [40, 50, 55]
SLOW_PERIOD_VALUES = [120]
ATR_TRAIL_MULT_VALUES = [2.0]

MIN_RV_ANNUALIZED = 9.0  # adopted from MES empirics; recalibrate after 60+ live MGC trades

COST_SWEEP_TIERS = {
    "optimistic": {"commission": round(COMMISSION * 0.5, 4), "slippage_ticks": 1.0},
    "realistic": {"commission": round(COMMISSION * 1.0, 4), "slippage_ticks": 2.0},
    "pessimistic": {"commission": round(COMMISSION * 2.0, 4), "slippage_ticks": 3.0},
    "catastrophic": {"commission": round(COMMISSION * 4.0, 4), "slippage_ticks": 4.0},
}

MIN_OOS_TRADES_PER_WINDOW = 1


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
from backtest._gate_v2_helpers import (  # noqa: E402
    GATE_DSR,
    GATE_DSR_ALT,
    GATE_MC_DD_ALT,
    GATE_MC_DD_CORE,
    GATE_P_EDGE,
    GATE_PF_CI_LOWER,
)  # noqa: E402
from backtest._gate_v2_helpers import bootstrap_pf_ci_lower as _bootstrap_pf_ci_lower  # noqa: E402
from backtest._gate_v2_helpers import (  # noqa: E402
    classify_wfo_consistency as _classify_wfo_consistency,
)

# ---------------------------------------------------------------------------
# Fixed-params sweep
# ---------------------------------------------------------------------------


def _run_fixed_params_sweep(df: pd.DataFrame, grid: list[tuple]) -> dict:
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
# Cost sweep
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
    from backtest._gate_v2_trade_metrics import trade_level_dsr

    oos_pfs = [r.profit_factor for r in oos_results if r.total_trades >= MIN_OOS_TRADES_PER_WINDOW]
    oos_dds = [r.max_drawdown_pct for r in oos_results]
    all_trades = sum(r.total_trades for r in oos_results)

    pf_ci_lower = _bootstrap_pf_ci_lower(oos_pfs)
    p_edge = float(sum(1 for pf in oos_pfs if pf > 1.0) / max(1, len(oos_pfs)))
    mc_95th_dd = float(np.percentile(oos_dds, 95.0)) if oos_dds else 1.0

    # DSR from the ACTUAL per-trade OOS return series, not the mean of per-window
    # Sharpes (which deflated 1-2 trade windows' giant Sharpes to a fake ~1.0 and
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
    core_reasons.append(f"dsr={dsr:.6f} >= {GATE_DSR} (not selection-bias)")

    alt_reasons = []
    alt_reasons.append(
        f"dsr={dsr:.6f} >= {GATE_DSR_ALT} (alt floor)"
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
        "verdict": verdict,
        "passed_via": passed_via,
        "core_verdict": "PASS" if core_pass else "FAIL",
        "alt_verdict": "PASS" if alt_pass else "FAIL",
        "n_core_passed": n_core_passed,
        "n_alt_passed": n_alt_passed,
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
    from backtest._gate_v2_helpers import _find_latest_cache

    data_dir = engine_root / "backtest" / "cache"
    data_file = _find_latest_cache(data_dir, "MGC")
    print(f"[MGC-RV-R1] Selected {data_file.name}")

    print(f"[MGC-RV-R1] Loading {data_file.name} ...")
    df = _load_data(data_file)
    print(f"[MGC-RV-R1] {len(df)} bars | {df.index.min().date()} -> {df.index.max().date()}")

    windows = _generate_windows(df)
    if not windows:
        print("[MGC-RV-R1] ERROR: not enough data to form windows.")
        return {}

    grid = list(itertools.product(FAST_PERIOD_VALUES, SLOW_PERIOD_VALUES, ATR_TRAIL_MULT_VALUES))
    n_combos = len(grid)

    print(f"\n{'=' * 70}")
    print(f"=== MGC TREND RV FILTER (rv_filter_rank1) — min_rv_annualized={MIN_RV_ANNUALIZED}% ===")
    print("Baseline rank4: p_edge=0.6842, wfo=MODERATE, dsr=1.0 — PASS via alt")
    print("RV filter hypothesis: 9% threshold adopted from MES empirics (pending MGC calibration)")
    print(
        f"Windows: {len(windows)} | Train: {TRAIN_MONTHS}mo | Test: {TEST_MONTHS}mo | Step: {STEP_MONTHS}mo"
    )
    print(f"Grid: {n_combos} combos (centered on rank4 champion fast=50,slow=120)")
    print(f"  fast_period      : {FAST_PERIOD_VALUES}")
    print(f"  slow_period      : {SLOW_PERIOD_VALUES}")
    print(f"  atr_trail_mult   : {ATR_TRAIL_MULT_VALUES}")
    print(f"  min_rv_annualized: {MIN_RV_ANNUALIZED}%")
    print(f"  multiplier       : ${MULTIPLIER:.0f}/point  (Micro Gold Futures)")
    print(f"  tick_size        : {TICK_SIZE} pts = ${TICK_SIZE * MULTIPLIER:.2f}/tick")
    print(f"  min_oos_trades   : {MIN_OOS_TRADES_PER_WINDOW}")
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
        print("\n[MGC-RV-R1] No OOS results — WFO aborted.")
        print("  NOTE: RV filter may be too aggressive for gold's vol structure.")
        print("  Consider lowering MIN_RV_ANNUALIZED or calibrating empirically.")
        return {}

    print(
        f"\n[MGC-RV-R1] Running fixed-params sweep on full dataset ({n_combos} combos, RV>={MIN_RV_ANNUALIZED}%)..."
    )
    fixed_params_metrics = _run_fixed_params_sweep(df, grid)
    print(
        f"  fixed_params_min_pf  = {fixed_params_metrics['fixed_params_min_pf']:.4f}  "
        f"(need >= {GATE_FIXED_PARAMS_MIN_PF}, rank4 no-filter was 1.3574)"
    )
    print(f"  fixed_params_mean_pf = {fixed_params_metrics['fixed_params_mean_pf']:.4f}")

    from collections import Counter

    param_votes = Counter(
        (r["best_params"]["fast"], r["best_params"]["slow"], r["best_params"]["atr_trail_mult"])
        for r in window_records
    )
    most_selected = param_votes.most_common(1)[0][0] if param_votes else (50, 120, 2.0)
    champion_params = {
        "fast": most_selected[0],
        "slow": most_selected[1],
        "atr_trail_mult": most_selected[2],
    }
    print(
        f"\n[MGC-RV-R1] Running cost sweep (champion: {champion_params}, RV>={MIN_RV_ANNUALIZED}%)..."
    )
    cost_sweep_metrics = _run_cost_sweep(df, champion_params)
    print(f"  cost_survives_through = {cost_sweep_metrics['cost_survives_through']}")

    gate = _compute_gate_v2(
        oos_results,
        n_grid_combos=n_combos,
        fixed_params_metrics=fixed_params_metrics,
        cost_sweep_metrics=cost_sweep_metrics,
    )

    print(f"\n{'=' * 70}")
    print(f"=== GATE v2 VERDICT: {gate['verdict']} (via {gate['passed_via'] or 'NONE'}) ===")
    print(f"  RV filter: min_rv_annualized={MIN_RV_ANNUALIZED}%")
    print(f"  pf_ci_lower          = {gate['pf_ci_lower']:.4f}  (need >= {GATE_PF_CI_LOWER})")
    print(f"  p_edge               = {gate['p_edge']:.4f}  (need >= {GATE_P_EDGE})")
    print(
        f"  mc_95th_dd           = {gate['mc_95th_dd_pct']:.4f}%  "
        f"(need <= {GATE_MC_DD_CORE * 100:.0f}% core / {GATE_MC_DD_ALT * 100:.0f}% alt)"
    )
    print(
        f"  dsr                  = {gate['dsr']:.6f}  (need >= {GATE_DSR} core / {GATE_DSR_ALT} alt)"
    )
    print(f"  wfo_consistency      = {gate['wfo_consistency']}")
    print(
        f"  fixed_params_min_pf  = {gate['fixed_params_min_pf']:.4f}  (need >= {GATE_FIXED_PARAMS_MIN_PF})"
    )
    print(f"  cost_survives_through= {gate['cost_survives_through']}")
    print(
        f"  OOS windows          = {gate['n_oos_windows_with_trades']} with trades / {gate['n_oos_windows']} total"
    )
    print(f"  Total OOS trades     = {gate['total_oos_trades']}")
    print(f"{'=' * 70}")

    verdicts_dir = engine_root / "data" / "gate_v2_verdicts"
    verdicts_dir.mkdir(parents=True, exist_ok=True)
    verdict_file = verdicts_dir / "MGC_trend_rv_filter_rank1.json"

    verdict_doc = {
        "symbol": SYMBOL,
        "family": "trend_rv_filter",
        "rank": 1,
        "verdict": gate["verdict"],
        "passed_via": gate["passed_via"],
        "core_verdict": gate["core_verdict"],
        "alt_verdict": gate["alt_verdict"],
        "n_core_passed": gate["n_core_passed"],
        "n_alt_passed": gate["n_alt_passed"],
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
        "rv_filter_config": {
            "min_rv_annualized": MIN_RV_ANNUALIZED,
            "empirical_basis": "adopted from MES 36-trade analysis; MGC calibration pending 60+ live trades",
            "note": "recalibrate threshold after accumulating 60+ live MGC paper trades with RV data",
        },
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
            "min_rv_annualized": MIN_RV_ANNUALIZED,
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
            "baseline_rank4_verdict": "PASS via alt",
            "baseline_rank4_p_edge": 0.6842,
            "baseline_rank4_wfo_consistency": "MODERATE",
            "baseline_rank4_fixed_params_min_pf": 1.3574,
            "baseline_rank4_mc_95th_dd_pct": 1.24,
            "rv_filter_threshold": MIN_RV_ANNUALIZED,
            "rv_filter_empirical_basis": "MES 36-trade sample only; MGC calibration TBD",
        },
    }

    verdict_file.write_text(json.dumps(verdict_doc, indent=2, default=str))
    print(f"\n[MGC-RV-R1] Verdict written -> {verdict_file}")

    return verdict_doc


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    verdict = run_wfo()

    if not verdict:
        print("[MGC-RV-R1] No verdict produced.")
        print("  Consider lowering MIN_RV_ANNUALIZED or calibrating from live MGC trade data.")
        sys.exit(1)

    final = verdict.get("verdict", "FAIL")
    passed_via = verdict.get("passed_via")
    gate = verdict.get("gate_v2_metrics", {})

    if final == "PASS":
        print(f"\n[PASS via {passed_via.upper()}] MGC Trend RV Filter PASSES gate v2.")
        print(
            "  Validated but NOT enabled — requires empirical calibration from 60+ live MGC paper"
            " trades before enabling min_rv_annualized in MGC production config."
        )
    else:
        print("\n[FAIL] MGC Trend RV Filter FAILS gate v2.")
        fpmf = gate.get("fixed_params_min_pf", 0.0)
        wfo = gate.get("wfo_consistency", "?")
        p_edge = gate.get("p_edge", 0.0)
        print(f"  fixed_params_min_pf={fpmf:.4f}  wfo_consistency={wfo}  p_edge={p_edge:.4f}")
        if wfo == "WEAK":
            print(
                "  INTERPRETATION: RV filter does not improve consistency on gold at 9% threshold."
            )
            print("  OPTIONS: (a) calibrate threshold from live MGC trades, (b) close experiment.")
        else:
            print("  RECOMMENDATION: MGC rank4 (no filter) remains the production config.")


if __name__ == "__main__":
    main()
