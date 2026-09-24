#!/usr/bin/env python
"""
MCL Gate v2 — Hypothesis F: HTF-Conditioned Mean-Reversion (Rank 1 baseline)

Motivation:
    Hypotheses A-E exhausted the "flat" mean-rev and trend approaches on MCL:
        A: baseline BB+RSI — PF 0.855; 254 trades; killed by trend-day chop.
        B: sentiment overlay — Corey never selected over baseline (18/18 IS).
        C: RV-band gate — pf_ci=0.284, p_edge=0.000; vol filter can't rescue
           a broken edge.
        D: SMA trend (1h) — pf_ci=7.14 (strong!), dsr=0.286 (ALT floor 0.30),
           only 4/18 OOS windows had trades; OOS coverage failure.
        E: SMA trend (1d) — daily bars fix OOS coverage; result pending.

    Root diagnosis: MCL mean-rev DOES exist intraday (Hyp-A produces 254 trades)
    but is annihilated by multi-day trending regimes (OPEC shocks, tariff-driven
    macro moves). The ADX/bbwidth/keltner regime filters (Hyp-C variants) were
    too blunt — they operate at 1h frequency and can't distinguish "trending on
    the daily chart" from "volatile ranging on the 1h."

    HTF RSI conditioning targets this gap directly: before taking a 1h mean-rev
    entry, check whether the daily chart is overbought (RSI >= upper threshold)
    or oversold (RSI <= lower threshold). If yes, the intraday dip/bounce is a
    pullback IN the daily trend — skip it. Only enter when the daily chart is in
    a neutral/ranging zone where mean-reversion setups have edge.

    The mechanism (resampling 1h closes to daily bars, computing Wilder RSI on
    daily bars, forward-filling back to 1h index) is implemented in
    generate_bollinger_rsi_signals() as htf_rsi_period/htf_rsi_upper/htf_rsi_lower.

Grid (MCL HTF mean-rev rank 1):
    htf_rsi_period: [0, 14]          -- 0=disabled (baseline), 14=Wilder on daily
    htf_rsi_upper : [55.0, 60.0, 65.0] -- max daily RSI for LONG entries
    htf_rsi_lower : [35.0, 40.0, 45.0] -- min daily RSI for SHORT entries
    stop_atr_mult : [1.5, 2.0, 2.5]
    bb_period     : 20  (fixed)
    bb_std        : 2.0 (fixed)
    rsi_period    : 14  (fixed Wilder on 1h)

    When htf_rsi_period=0, upper/lower are irrelevant — the baseline is covered
    by a single (period=0, upper=60, lower=40, stop=1.5) combo. Total combos
    with itertools.product: 2 × 3 × 3 × 3 = 54.

    The baseline (period=0) provides an internal control: if HTF conditioning
    improves p_edge and pf_ci_lower vs. the no-filter baseline across WFO
    windows, the DSR deflation penalty from 54 trials is worth paying.

WFO config (matches MCL Hyp-A through C):
    TRAIN_MONTHS = 6
    TEST_MONTHS  = 1
    STEP_MONTHS  = 1

Data:
    MCL 1h, 2024-01-01 onward
    File: engine/backtest/cache/MCL_<start>_<end>_1h.csv (latest selected)

Contract specs:
    Multiplier : $100/point (100 barrels × $1/barrel/point)
    Tick size  : $0.01/barrel = $1/contract
    Commission : $0.85/contract round-trip (IB micro crude oil)
    Capital    : $10,000

Gate v2 thresholds (ALT path — matches prior MCL hypotheses):
    pf_ci_lower      >= 1.10
    p_edge           >= 0.95
    mc_95th_dd       <= 4%  (ALT ceiling tightened 2026-05-09)
    dsr              >= 0.30 (ALT floor)
    wfo_consistency  in [MODERATE, STRONG]
    fixed_params_min_pf >= 1.20
    cost_survives_through >= realistic

Writes: engine/data/gate_v2_verdicts/MCL_htf_meanrev_rank1.json

Usage (from engine/ directory):
    .venv/Scripts/python backtest/run_mcl_htf_meanrev_rank1.py
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

SYMBOL = "MCL"
MULTIPLIER = 100.0
CAPITAL = 10_000.0
TICK_SIZE = 0.01
COMMISSION = 0.85
SLIPPAGE_TICKS = 1.0

TRAIN_MONTHS = 6
TEST_MONTHS = 1
STEP_MONTHS = 1

# Fixed 1h baseline params — only HTF + stop dimensions are swept.
BB_PERIOD = 20
BB_STD = 2.0
RSI_PERIOD = 14  # Wilder RSI on 1h bars

# Grid: 2 × 3 × 3 × 3 = 54 combos
HTF_RSI_PERIOD_VALUES = [0, 14]  # 0 = disabled (baseline), 14 = Wilder daily
HTF_RSI_UPPER_VALUES = [55.0, 60.0, 65.0]  # max daily RSI for LONG filter
HTF_RSI_LOWER_VALUES = [35.0, 40.0, 45.0]  # min daily RSI for SHORT filter
STOP_ATR_MULT_VALUES = [1.5, 2.0, 2.5]


MIN_OOS_TRADES_PER_WINDOW = 2

COST_SWEEP_TIERS = {
    "optimistic": {"commission": 0.43, "slippage_ticks": 0.5},
    "realistic": {"commission": 0.85, "slippage_ticks": 1.0},
    "pessimistic": {"commission": 1.70, "slippage_ticks": 2.0},
    "catastrophic": {"commission": 3.40, "slippage_ticks": 3.0},
}

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
    chosen = _find_latest_cache(data_dir, "MCL", "_1h.csv")
    print(f"[MCL-F] Selected {chosen.name}")
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
        if len(df_train) >= 50 and len(df_test) >= 20:
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
    htf_rsi_period: int,
    htf_rsi_upper: float,
    htf_rsi_lower: float,
    stop_atr_mult: float,
    commission: float = COMMISSION,
    slippage_ticks: float = SLIPPAGE_TICKS,
) -> object:
    from backtest.backtester import Backtester
    from backtest.meanrev_signals import generate_bollinger_rsi_signals

    df_sig = generate_bollinger_rsi_signals(
        df,
        bb_period=BB_PERIOD,
        bb_std=BB_STD,
        rsi_period=RSI_PERIOD,
        stop_atr_mult=stop_atr_mult,
        signal_direction="both",
        regime_filter_mode="none",
        htf_rsi_period=htf_rsi_period,
        htf_rsi_upper=htf_rsi_upper,
        htf_rsi_lower=htf_rsi_lower,
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
        fixed_contracts=1,
    )
    return bt.run(df_sig, symbol=SYMBOL, multiplier=MULTIPLIER)


# ---------------------------------------------------------------------------
# IS grid search
# ---------------------------------------------------------------------------


def _best_is_params(df_train: pd.DataFrame, grid: list[tuple]) -> tuple[dict | None, object | None]:
    best_pf = -1.0
    best_params = None
    best_result = None

    for htf_period, htf_upper, htf_lower, stop_mult in grid:
        try:
            result = _run_signals_and_backtest(
                df_train,
                htf_rsi_period=htf_period,
                htf_rsi_upper=htf_upper,
                htf_rsi_lower=htf_lower,
                stop_atr_mult=stop_mult,
            )
        except Exception as exc:
            print(
                f"    [WARN] IS error (htf={htf_period},up={htf_upper},"
                f"lo={htf_lower},stop={stop_mult}): {exc}"
            )
            continue
        if result.total_trades < MIN_OOS_TRADES_PER_WINDOW:
            continue
        pf = result.profit_factor
        if pf > best_pf:
            best_pf = pf
            best_params = {
                "htf_rsi_period": htf_period,
                "htf_rsi_upper": htf_upper,
                "htf_rsi_lower": htf_lower,
                "stop_atr_mult": stop_mult,
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
from backtest._gate_v2_helpers import bootstrap_pf_ci_lower as _bootstrap_pf_ci_lower
from backtest._gate_v2_helpers import classify_wfo_consistency as _classify_wfo_consistency

# ---------------------------------------------------------------------------
# Fixed-params sweep
# ---------------------------------------------------------------------------


def _run_fixed_params_sweep(df: pd.DataFrame, grid: list[tuple]) -> dict:
    pfs = []
    combo_results = []
    for htf_period, htf_upper, htf_lower, stop_mult in grid:
        try:
            result = _run_signals_and_backtest(
                df,
                htf_rsi_period=htf_period,
                htf_rsi_upper=htf_upper,
                htf_rsi_lower=htf_lower,
                stop_atr_mult=stop_mult,
            )
            if result.total_trades >= MIN_OOS_TRADES_PER_WINDOW:
                pfs.append(result.profit_factor)
                combo_results.append(
                    {
                        "htf_rsi_period": htf_period,
                        "htf_rsi_upper": htf_upper,
                        "htf_rsi_lower": htf_lower,
                        "stop_atr_mult": stop_mult,
                        "pf": round(result.profit_factor, 4),
                        "trades": result.total_trades,
                    }
                )
                htf_tag = f"htf={htf_period}|up={htf_upper}|lo={htf_lower}"
                print(
                    f"    combo ({htf_tag},stop={stop_mult}): "
                    f"PF={result.profit_factor:.4f}  trades={result.total_trades}"
                )
            else:
                htf_tag = f"htf={htf_period}|up={htf_upper}|lo={htf_lower}"
                print(
                    f"    combo ({htf_tag},stop={stop_mult}): "
                    f"SKIP ({result.total_trades} trades)"
                )
        except Exception as exc:
            print(f"  [WARN] fixed-params error: {exc}")

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
                htf_rsi_period=champion_params["htf_rsi_period"],
                htf_rsi_upper=champion_params["htf_rsi_upper"],
                htf_rsi_lower=champion_params["htf_rsi_lower"],
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

    def _cr(label, val, threshold, op):
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

    print(f"[MCL-F] Loading {data_file.name} ...")
    df = _load_data(data_file)
    print(f"[MCL-F] {len(df)} bars | {df.index.min().date()} -> {df.index.max().date()}")

    windows = _generate_windows(df)
    if not windows:
        print("[MCL-F] ERROR: not enough data to form WFO windows.")
        return {}

    grid = list(
        itertools.product(
            HTF_RSI_PERIOD_VALUES,
            HTF_RSI_UPPER_VALUES,
            HTF_RSI_LOWER_VALUES,
            STOP_ATR_MULT_VALUES,
        )
    )
    n_combos = len(grid)

    print(f"\n{'=' * 72}")
    print("=== MCL MEAN-REV HYP-F — HTF RSI-CONDITIONED (RANK 1 BASELINE) ===")
    print(
        f"Windows: {len(windows)} | Train: {TRAIN_MONTHS}mo | Test: {TEST_MONTHS}mo | Step: {STEP_MONTHS}mo"
    )
    print(f"Grid: {n_combos} combos")
    print(f"  htf_rsi_period : {HTF_RSI_PERIOD_VALUES}  (0=disabled/baseline, 14=Wilder on daily)")
    print(f"  htf_rsi_upper  : {HTF_RSI_UPPER_VALUES}  (max daily RSI for LONG filter)")
    print(f"  htf_rsi_lower  : {HTF_RSI_LOWER_VALUES}  (min daily RSI for SHORT filter)")
    print(f"  stop_atr_mult  : {STOP_ATR_MULT_VALUES}")
    print("  bb_period=20, bb_std=2.0, rsi_period=14  (fixed)")
    print(f"  capital        : ${CAPITAL:,.0f}  (backtest sizing only)")
    print(f"  multiplier     : ${MULTIPLIER:.0f}/point (MCL Micro Crude 100bbl)")
    print(
        f"ALT thresholds: dsr>={GATE_DSR_ALT}, wfo in {GATE_WFO_CONSISTENCY_VALUES}, "
        f"fixed>={GATE_FIXED_PARAMS_MIN_PF}, mc_dd<={GATE_MC_DD_ALT * 100:.0f}%"
    )
    print("Lineage: A(PF0.855) B(Corey=noop) C(RV gate FAIL) D(SMA1h dsr miss) E(SMA1d)")
    print(f"{'=' * 72}")

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
            f"  Best IS: htf={best_params['htf_rsi_period']}  "
            f"up={best_params['htf_rsi_upper']}  lo={best_params['htf_rsi_lower']}  "
            f"stop={best_params['stop_atr_mult']}  "
            f"PF={is_result.profit_factor:.2f}  trades={is_result.total_trades}"
        )

        try:
            oos_result = _run_signals_and_backtest(
                df_test,
                htf_rsi_period=best_params["htf_rsi_period"],
                htf_rsi_upper=best_params["htf_rsi_upper"],
                htf_rsi_lower=best_params["htf_rsi_lower"],
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
        print("\n[MCL-F] No OOS results — WFO aborted.")
        print("[MCL-F] 0 trades across all windows suggests:")
        print("[MCL-F]   a) HTF filter too restrictive (daily rarely in neutral zone)")
        print("[MCL-F]   b) Data coverage too short for 6mo IS windows")
        return {}

    # Fixed-params sweep
    print(f"\n[MCL-F] Fixed-params sweep on full dataset ({n_combos} combos)...")
    fixed_params_metrics = _run_fixed_params_sweep(df, grid)
    print(
        f"  fixed_params_min_pf  = {fixed_params_metrics['fixed_params_min_pf']:.4f}  "
        f"(need >= {GATE_FIXED_PARAMS_MIN_PF})"
    )

    # Cost sweep — most frequently selected IS champion
    param_votes = Counter(
        (
            r["best_params"]["htf_rsi_period"],
            r["best_params"]["htf_rsi_upper"],
            r["best_params"]["htf_rsi_lower"],
            r["best_params"]["stop_atr_mult"],
        )
        for r in window_records
    )
    most_selected = param_votes.most_common(1)[0][0] if param_votes else (14, 60.0, 40.0, 2.0)
    champion_params = {
        "htf_rsi_period": most_selected[0],
        "htf_rsi_upper": most_selected[1],
        "htf_rsi_lower": most_selected[2],
        "stop_atr_mult": most_selected[3],
    }
    print(f"\n[MCL-F] Cost sweep (champion: {champion_params})...")
    cost_sweep_metrics = _run_cost_sweep(df, champion_params)
    print(
        f"  cost_survives_through = {cost_sweep_metrics['cost_survives_through']}  "
        f"(need >= 'realistic')"
    )

    # Gate v2
    gate = _compute_gate_v2(oos_results, n_combos, fixed_params_metrics, cost_sweep_metrics)

    print(f"\n{'=' * 72}")
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
    print(f"{'=' * 72}")

    # Write verdict JSON
    verdicts_dir = engine_root / "data" / "gate_v2_verdicts"
    verdicts_dir.mkdir(parents=True, exist_ok=True)
    verdict_file = verdicts_dir / "MCL_htf_meanrev_rank1.json"

    now_iso = datetime.now(tz=timezone.utc).isoformat()
    verdict_doc = {
        "symbol": SYMBOL,
        "family": "htf_meanrev",
        "hypothesis": "F",
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
            "grid_htf_rsi_period": HTF_RSI_PERIOD_VALUES,
            "grid_htf_rsi_upper": HTF_RSI_UPPER_VALUES,
            "grid_htf_rsi_lower": HTF_RSI_LOWER_VALUES,
            "grid_stop_atr_mult": STOP_ATR_MULT_VALUES,
            "fixed_bb_period": BB_PERIOD,
            "fixed_bb_std": BB_STD,
            "fixed_rsi_period": RSI_PERIOD,
            "timeframe": "1h",
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
            "note": "MCL DO_NOT_TRADE live gate enforced in engine routing",
        },
        "lineage": {
            "family": "htf_meanrev",
            "hypothesis": "F",
            "mcl_meanrev_hyp_a": "FAIL — PF 0.855/254 trades; trend-day chop",
            "mcl_meanrev_hyp_b": "FAIL — Corey never selected over baseline (18/18 IS)",
            "mcl_meanrev_hyp_c": "FAIL — pf_ci=0.284, p_edge=0.000; RV gate useless",
            "mcl_trend_hyp_d": "FAIL — pf_ci=7.14, dsr=0.286 (missed ALT 0.30), 4/18 OOS windows",
            "mcl_trend_hyp_e": "pending (daily SMA trend)",
            "hyp_f_hypothesis": (
                "Daily RSI gate on 1h mean-rev entries. Before taking an "
                "oversold 1h LONG, verify daily RSI < upper threshold (daily "
                "not overbought). Before taking an overbought 1h SHORT, verify "
                "daily RSI > lower threshold (daily not oversold). Isolates "
                "intraday mean-rev edge from multi-day trending regime."
            ),
        },
    }

    # Provenance (2026-09-17 audit): record which cache produced this verdict.
    from backtest._gate_v2_helpers import inject_cache_provenance as _inject_prov  # noqa: E402
    verdict_doc = _inject_prov(verdict_doc, data_file)
    verdict_file.write_text(json.dumps(verdict_doc, indent=2, default=str))
    print(f"\n[MCL-F] Verdict written -> {verdict_file}")
    return verdict_doc


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    verdict = run_wfo()
    if not verdict:
        print("[MCL-F] No verdict produced.")
        sys.exit(1)

    final = verdict.get("verdict", "FAIL")
    passed_via = verdict.get("passed_via")
    gate = verdict.get("gate_v2_metrics", {})

    if final == "PASS" and passed_via == "core":
        print("\n[PASS-CORE] MCL HTF Mean-Rev Rank1 PASSES gate v2 (CORE path).")
        print("  ACTION: Add HTF_MEANREV_PARAMS['MCL'] to meanrev_signals.py champion block.")
        print("  ACTION: Remove MCL from DO_NOT_TRADE_SYMBOLS after live-trading authorization.")
    elif final == "PASS" and passed_via == "alt":
        print("\n[PASS-ALT] MCL HTF Mean-Rev Rank1 PASSES gate v2 (ALT — $50K+ accounts).")
        print("  ACTION: Add HTF_MEANREV_PARAMS['MCL'] with champion params.")
        print("  NOTE:   ALT path requires $50K+ account.")
    else:
        print("\n[FAIL] MCL HTF Mean-Rev Rank1 FAILS gate v2.")
        pf_ci = gate.get("pf_ci_lower", 0.0)
        dsr_val = gate.get("dsr", 0.0)
        p_edge_val = gate.get("p_edge", 0.0)
        n_trades = gate.get("total_oos_trades", 0)
        n_oos_with_trades = gate.get("n_oos_windows_with_trades", 0)
        n_oos_total = gate.get("n_oos_windows", 0)
        if n_trades == 0:
            print("  0 OOS trades — HTF filter may be too tight or data span insufficient.")
        elif p_edge_val < GATE_P_EDGE:
            print(
                f"  p_edge={p_edge_val:.4f} (need {GATE_P_EDGE}) — "
                f"{n_oos_with_trades}/{n_oos_total} OOS windows had trades."
            )
        if dsr_val < GATE_DSR_ALT:
            print(
                f"  dsr={dsr_val:.6f} below ALT floor {GATE_DSR_ALT}. "
                f"54 combos requires high OOS trade count to survive deflation."
            )
        if pf_ci >= GATE_PF_CI_LOWER and p_edge_val < GATE_P_EDGE:
            print(
                f"  pf_ci={pf_ci:.4f} (signal present) — consider rank2 with tighter HTF thresholds."
            )
        print("  Hypothesis G suggestion: HTF + ADX (dual-gate — daily RSI + 1h ADX).")


if __name__ == "__main__":
    main()
