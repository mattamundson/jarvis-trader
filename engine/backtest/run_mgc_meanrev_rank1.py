#!/usr/bin/env python
"""
MGC Mean-Reversion Gate v2 -- Rank 1 (Bollinger + RSI on 1h bars)

Hypothesis (from NEXT_STRATEGY_HUNT_2026-05-06.md, Top-1 candidate):
    Gold (MGC, $10/pt) exhibits two-regime behavior. Macro-day shocks send
    price 1-2 ATR off the median, then it reverts to the BB midband over
    8-24h. The Bollinger+RSI signal generator (already validated as the
    MCL hyp-C template) targets exactly the "extreme dislocation + RSI
    exhaustion" setup. MGC's narrower distribution kurtosis vs crude should
    make BB-band breaches less correlated with trend continuation.

Approach (Option A from build plan -- baseline first):
    Run the *unfiltered* Bollinger+RSI signal across a 9-combo BB grid
    (BB_period × BB_std × stop_atr_mult). RSI thresholds fixed at
    standard 30/70. No regime gate (rank1 baseline). If FAIL, rank2
    layers rv_band gate (mirrors MCL hyp-C lineage).

Gate v2 ALT path is the realistic target (consistent with MES rank11 and
MGC trend rank4 PASS verdicts). Required:

    dsr                  >= 0.30          (alt floor)
    wfo_consistency      in {MODERATE, STRONG}  (>=55% OOS PF>1.0)
    fixed_params_min_pf  >= 1.20          (worst combo on full dataset)
    cost_survives_through >= "realistic"  ($0.62 commission, 2-tick slip)
    mc_95th_dd_pct       <= 7.0           (alt ceiling)

WFO config (matches MGC trend rank4):
    TRAIN_MONTHS = 6
    TEST_MONTHS  = 2
    STEP_MONTHS  = 1
    N_WINDOWS    = 18 (target; actual = data-bound)

Contract specs:
    Multiplier : $10/point  (Micro Gold, 10 oz)
    Tick size  : 0.10 points = $1.00/tick
    Commission : $0.62/contract round-trip (IB micro futures typical)
    Slippage   : 2 ticks
    Capital    : $50,000  (ALT path)

Data: MGC 1h, latest cache (auto-selected via _find_data_file)
Writes: engine/data/gate_v2_verdicts/MGC_meanrev_rank1.json

Usage (from engine/ directory):
    .venv/Scripts/python backtest/run_mgc_meanrev_rank1.py
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

# Ensure engine root is on sys.path when called as a script
engine_root = Path(__file__).parent.parent
if str(engine_root) not in sys.path:
    sys.path.insert(0, str(engine_root))

from backtest.contract_specs import CONTRACT_SPECS  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SYMBOL = "MGC"
MULTIPLIER = 10.0  # $10/point (Micro Gold)
CAPITAL = 50_000.0  # ALT path
TICK_SIZE = 0.10
# Imported from contract_specs.py (single source of truth) rather than a
# local literal -- this file previously hardcoded 0.62, MES's rate, instead
# of MGC's documented 0.85 (found 2026-07-10). contract_specs.py's own
# docstring exists precisely because this class of drift ("MCL commission
# was 0.62 in one script and 0.85 in another") has happened before.
COMMISSION = CONTRACT_SPECS["MGC"].commission
SLIPPAGE_TICKS = 2.0

TRAIN_MONTHS = 6
TEST_MONTHS = 2
STEP_MONTHS = 1
N_WINDOWS = 18

# Rank 1 grid: BB_period x BB_std x stop_atr_mult (3 x 3 x 1 = 9 combos)
# RSI thresholds fixed at 30/70 (standard) -- they're not the binding lever
# for mean-rev edge; BB tightness and stop width are.
BB_PERIOD_VALUES = [15, 20, 25]
BB_STD_VALUES = [1.8, 2.0, 2.2]
STOP_ATR_MULT_VALUES = [1.5]
RSI_PERIOD = 14
RSI_LONG = 30.0
RSI_SHORT = 70.0

# Gate v2 thresholds

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


def _find_data_file(data_dir: Path) -> Path:
    """Pick the MGC 1h cache covering the latest end-date so a refreshed
    IBKR pull (named MGC_<start>_<end>_1h.csv) always wins over older files.
    Delegates to the shared helper for the canonical "latest end-date" rule.
    """
    chosen = _find_latest_cache(data_dir, "MGC")
    print(f"[MGC-MR1] Selected {chosen.name}")
    return chosen


# ---------------------------------------------------------------------------
# Window generation (match MGC trend rank4 cadence: 6/2/1)
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
    bb_period: int,
    bb_std: float,
    stop_atr_mult: float,
    commission: float = COMMISSION,
    slippage_ticks: float = SLIPPAGE_TICKS,
) -> object:
    from backtest.backtester import Backtester
    from backtest.meanrev_signals import generate_bollinger_rsi_signals

    df_sig = generate_bollinger_rsi_signals(
        df,
        bb_period=bb_period,
        bb_std=bb_std,
        rsi_period=RSI_PERIOD,
        rsi_long=RSI_LONG,
        rsi_short=RSI_SHORT,
        stop_atr_mult=stop_atr_mult,
        regime_filter_mode="none",  # rank1 baseline -- no regime gate
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

    for bb_period, bb_std, stop_atr_mult in grid:
        try:
            result = _run_signals_and_backtest(df_train, bb_period, bb_std, stop_atr_mult)
        except Exception as exc:
            print(f"    [WARN] IS error ({bb_period},{bb_std},{stop_atr_mult}): {exc}")
            continue
        if result.total_trades < MIN_OOS_TRADES_PER_WINDOW:
            continue
        pf = result.profit_factor
        if pf > best_pf:
            best_pf = pf
            best_params = {"bb_period": bb_period, "bb_std": bb_std, "stop_atr_mult": stop_atr_mult}
            best_result = result

    return best_params, best_result


# ---------------------------------------------------------------------------
# Gate v2 metric helpers (shared)
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
    _find_latest_cache,  # noqa: E402
)  # noqa: E402
from backtest._gate_v2_helpers import bootstrap_pf_ci_lower as _bootstrap_pf_ci_lower  # noqa: E402
from backtest._gate_v2_helpers import (  # noqa: E402
    classify_wfo_consistency as _classify_wfo_consistency,  # noqa: E402
)

# ---------------------------------------------------------------------------
# Fixed-params sweep
# ---------------------------------------------------------------------------


def _run_fixed_params_sweep(df: pd.DataFrame, grid: list[tuple]) -> dict:
    pfs = []
    combo_results = []
    for bb_period, bb_std, stop_atr_mult in grid:
        try:
            result = _run_signals_and_backtest(df, bb_period, bb_std, stop_atr_mult)
            if result.total_trades >= MIN_OOS_TRADES_PER_WINDOW:
                pfs.append(result.profit_factor)
                combo_results.append(
                    {
                        "bb_period": bb_period,
                        "bb_std": bb_std,
                        "stop_atr_mult": stop_atr_mult,
                        "pf": round(result.profit_factor, 4),
                        "trades": result.total_trades,
                    }
                )
                print(
                    f"    combo (bb={bb_period:2d},std={bb_std:.1f},stop={stop_atr_mult:.1f}): "
                    f"PF={result.profit_factor:.4f}  trades={result.total_trades}"
                )
            else:
                print(
                    f"    combo (bb={bb_period:2d},std={bb_std:.1f},stop={stop_atr_mult:.1f}): "
                    f"SKIP ({result.total_trades} trades)"
                )
        except Exception as exc:
            print(f"  [WARN] fixed-params error ({bb_period},{bb_std},{stop_atr_mult}): {exc}")

    if not pfs:
        return {
            "fixed_params_min_pf": 0.0,
            "fixed_params_mean_pf": 0.0,
            "fixed_params_max_pf": 0.0,
            "n_combos_with_trades": 0,
            "combo_results": combo_results,
        }

    # Cap inf for sane min/mean/max (mirrors bootstrap helper convention)
    capped = [
        (
            min(max(pf, 0.0), 5.0)
            if not (pf == float("inf") or pf == float("-inf"))
            else (5.0 if pf == float("inf") else 0.0)
        )
        for pf in pfs
    ]
    return {
        "fixed_params_min_pf": round(float(min(capped)), 4),
        "fixed_params_mean_pf": round(float(np.mean(capped)), 4),
        "fixed_params_max_pf": round(float(max(capped)), 4),
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
                bb_period=champion_params["bb_period"],
                bb_std=champion_params["bb_std"],
                stop_atr_mult=champion_params["stop_atr_mult"],
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

    core_reasons = []
    core_reasons.append(
        f"{'FAIL ' if pf_ci_lower < GATE_PF_CI_LOWER else ''}mbb_pf_ci_lower={pf_ci_lower:.4f} >= {GATE_PF_CI_LOWER}"
    )
    core_reasons.append(
        f"{'FAIL ' if p_edge < GATE_P_EDGE else ''}p_positive_edge={p_edge:.4f} >= {GATE_P_EDGE}"
    )
    core_reasons.append(
        f"mc_95th_dd_pct={mc_95th_dd*100:.4f} {'<=' if mc_95th_dd<=GATE_MC_DD_CORE else '>'} {GATE_MC_DD_CORE*100:.1f}"
    )
    core_reasons.append(f"dsr={dsr:.6f} >= {GATE_DSR} (not selection-bias)")

    alt_reasons = []
    alt_reasons.append(
        f"{'FAIL ' if dsr < GATE_DSR_ALT else ''}dsr={dsr:.6f} >= {GATE_DSR_ALT} (alt floor)"
    )
    alt_reasons.append(
        f"{'FAIL ' if wfo_consistency not in GATE_WFO_CONSISTENCY_VALUES else ''}rolling_wfo={wfo_consistency} in {GATE_WFO_CONSISTENCY_VALUES}"
    )
    alt_reasons.append(
        f"{'FAIL ' if fixed_params_min_pf < GATE_FIXED_PARAMS_MIN_PF else ''}fixed_params_min_pf={fixed_params_min_pf:.3f} >= {GATE_FIXED_PARAMS_MIN_PF}"
    )
    alt_reasons.append(
        f"{'FAIL ' if not cost_passes else ''}cost_survives_through={cost_survives_through} >= realistic"
    )
    alt_reasons.append(
        f"{'FAIL ' if mc_95th_dd > GATE_MC_DD_ALT else ''}mc_95th_dd_pct={mc_95th_dd*100:.4f} <= {GATE_MC_DD_ALT*100:.1f} (alt ceiling)"
    )

    n_core_passed = sum(1 for r in core_reasons if not r.startswith("FAIL"))
    n_alt_passed = sum(1 for r in alt_reasons if not r.startswith("FAIL"))

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
    data_dir = engine_root / "backtest" / "cache"
    data_file = _find_data_file(data_dir)

    print(f"[MGC-MR1] Loading {data_file.name} ...")
    df = _load_data(data_file)
    print(f"[MGC-MR1] {len(df)} bars | {df.index.min().date()} -> {df.index.max().date()}")

    windows = _generate_windows(df)
    if not windows:
        print("[MGC-MR1] ERROR: not enough data to form WFO windows.")
        return {}

    grid = list(itertools.product(BB_PERIOD_VALUES, BB_STD_VALUES, STOP_ATR_MULT_VALUES))
    n_combos = len(grid)

    print(f"\n{'=' * 70}")
    print("=== MGC MEAN-REV RANK 1 -- BB+RSI BASELINE, NO REGIME GATE ===")
    print(
        f"Windows: {len(windows)} | Train: {TRAIN_MONTHS}mo | Test: {TEST_MONTHS}mo | Step: {STEP_MONTHS}mo"
    )
    print(f"Grid: {n_combos} combos")
    print(f"  bb_period       : {BB_PERIOD_VALUES}")
    print(f"  bb_std          : {BB_STD_VALUES}")
    print(f"  stop_atr_mult   : {STOP_ATR_MULT_VALUES}")
    print(f"  rsi_long/short  : {RSI_LONG}/{RSI_SHORT} (fixed)")
    print(f"  capital         : ${CAPITAL:,.0f}  (ALT path, $50K+ accounts)")
    print(f"  multiplier      : ${MULTIPLIER:.0f}/point  (Micro Gold)")
    print(f"  tick_size       : {TICK_SIZE} pts = ${TICK_SIZE*MULTIPLIER:.2f}/tick")
    print(f"  TEST_MONTHS     : {TEST_MONTHS}  (matches MGC trend rank4)")
    print(
        f"ALT thresholds : dsr>={GATE_DSR_ALT}, wfo in {GATE_WFO_CONSISTENCY_VALUES}, "
        f"fixed>={GATE_FIXED_PARAMS_MIN_PF}, mc_dd<={GATE_MC_DD_ALT*100:.0f}%"
    )
    print("Lineage: rank1 baseline (no gate). If FAIL, rank2 layers rv_band per MCL hyp-C.")
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
            f"  Best IS: bb={best_params['bb_period']}  std={best_params['bb_std']}  "
            f"stop={best_params['stop_atr_mult']}  "
            f"PF={is_result.profit_factor:.2f}  trades={is_result.total_trades}"
        )

        try:
            oos_result = _run_signals_and_backtest(
                df_test,
                bb_period=best_params["bb_period"],
                bb_std=best_params["bb_std"],
                stop_atr_mult=best_params["stop_atr_mult"],
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
        print("\n[MGC-MR1] No OOS results -- WFO aborted.")
        return {}

    # Fixed-params sweep
    print(f"\n[MGC-MR1] Fixed-params sweep on full dataset ({n_combos} combos)...")
    fixed_params_metrics = _run_fixed_params_sweep(df, grid)
    print(
        f"  fixed_params_min_pf = {fixed_params_metrics['fixed_params_min_pf']:.4f}  "
        f"(need >= {GATE_FIXED_PARAMS_MIN_PF})"
    )

    # Cost sweep (most-selected IS champion)
    param_votes = Counter(
        (
            r["best_params"]["bb_period"],
            r["best_params"]["bb_std"],
            r["best_params"]["stop_atr_mult"],
        )
        for r in window_records
    )
    most_selected = param_votes.most_common(1)[0][0] if param_votes else (20, 2.0, 1.5)
    champion_params = {
        "bb_period": most_selected[0],
        "bb_std": most_selected[1],
        "stop_atr_mult": most_selected[2],
    }
    print(f"\n[MGC-MR1] Cost sweep (champion: {champion_params})...")
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

    verdicts_dir = engine_root / "data" / "gate_v2_verdicts"
    verdicts_dir.mkdir(parents=True, exist_ok=True)
    verdict_file = verdicts_dir / "MGC_meanrev_rank1.json"

    now_iso = datetime.now(tz=timezone.utc).isoformat()
    verdict_doc = {
        "symbol": SYMBOL,
        "family": "mean_reversion",
        "rank": 1,
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
            "grid_bb_period": BB_PERIOD_VALUES,
            "grid_bb_std": BB_STD_VALUES,
            "grid_stop_atr_mult": STOP_ATR_MULT_VALUES,
            "rsi_period": RSI_PERIOD,
            "rsi_long": RSI_LONG,
            "rsi_short": RSI_SHORT,
            "regime_filter_mode": "none",
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
            "note": "MGC mean-rev rank1 -- pending gate v2 verdict",
        },
        "lineage": {
            "family": "mean_reversion",
            "rank": 1,
            "hypothesis": (
                "Bollinger+RSI baseline on MGC 1h. Test whether MGC's "
                "macro-day overshoot-then-revert behavior produces edge "
                "without regime gating. Lineage: MCL hyp-C template, "
                "MGC trend rank4 PASS-alt symbol diversification target."
            ),
            "build_plan_ref": "~/.claude/handoffs/NEXT_STRATEGY_HUNT_2026-05-06.md candidate #1",
        },
    }

<<<<<<< HEAD
=======
    # Provenance (2026-09-17 audit): record which cache produced this verdict.
    from backtest._gate_v2_helpers import inject_cache_provenance as _inject_prov  # noqa: E402
    verdict_doc = _inject_prov(verdict_doc, data_file)
>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2
    verdict_file.write_text(json.dumps(verdict_doc, indent=2, default=str))
    print(f"\n[MGC-MR1] Verdict written -> {verdict_file}")
    return verdict_doc


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    verdict = run_wfo()
    if not verdict:
        print("[MGC-MR1] No verdict produced.")
        sys.exit(1)

    final = verdict.get("verdict", "FAIL")
    passed_via = verdict.get("passed_via")
    gate = verdict.get("gate_v2_metrics", {})

    if final == "PASS" and passed_via == "core":
        print("\n[PASS-CORE] MGC Mean-Rev Rank1 PASSES gate v2 (CORE path).")
        print("  ACTION: Add MEANREV_PARAMS['MGC'] to meanrev_signals.py with champion params.")
        print("  ACTION: Wire MGC_MEANREV_PAPER_CONFIG into paper_config.py.")
    elif final == "PASS" and passed_via == "alt":
        print("\n[PASS-ALT] MGC Mean-Rev Rank1 PASSES gate v2 (ALT path -- $50K+ accounts).")
        print("  ACTION: Add MEANREV_PARAMS['MGC'] to meanrev_signals.py with champion params.")
        print(
            "  ACTION: Wire MGC_MEANREV_PAPER_CONFIG into paper_config.py (separate from MGC trend)."
        )
        print("  NOTE:   ALT path requires $50K+ account -- enforce in position sizer.")
    else:
        print("\n[FAIL] MGC Mean-Rev Rank1 FAILS gate v2.")
        dsr_val = gate.get("dsr", 0.0)
        p_edge_val = gate.get("p_edge", 0.0)
        n_trades = gate.get("total_oos_trades", 0)
        wfo = gate.get("wfo_consistency", "WEAK")
        n_oos_with_trades = gate.get("n_oos_windows_with_trades", 0)
        fixed_pf = gate.get("fixed_params_min_pf", 0.0)
        mc_dd_pct = gate.get("mc_95th_dd_pct", 0.0)

        if n_trades == 0:
            print("  0 OOS trades -- BB+RSI signal didn't fire on MGC 1h.")
        elif p_edge_val < GATE_P_EDGE:
            print(
                f"  p_edge={p_edge_val:.4f}: {n_oos_with_trades}/{gate.get('n_oos_windows',0)} OOS windows had trades"
            )
        if dsr_val < GATE_DSR_ALT:
            print(
                f"  dsr={dsr_val:.6f} below ALT floor {GATE_DSR_ALT} -- "
                f"multiple testing deflated edge."
            )
        if fixed_pf < GATE_FIXED_PARAMS_MIN_PF:
            print(f"  fixed_params_min_pf={fixed_pf:.4f} -- worst combo failing on full dataset.")
        if mc_dd_pct > GATE_MC_DD_ALT * 100:
            print(f"  mc_95th_dd_pct={mc_dd_pct:.4f}% > {GATE_MC_DD_ALT*100:.0f}% (ALT ceiling).")
        print(f"  wfo_consistency={wfo}")
        print("  Next step: rank2 layers rv_band regime gate (mirror MCL hyp-C lineage).")


if __name__ == "__main__":
    main()
