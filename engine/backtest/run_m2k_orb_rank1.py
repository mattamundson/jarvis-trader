#!/usr/bin/env python
"""
M2K ORB Gate v2 — Rank 1 Verdict

Opening Range Breakout strategy for M2K (Micro Russell 2000).

Strategy: same ORB structure as MES/MNQ runners. RTH OR breakout, opposite-side
stop, 50% partial at T1 (1x OR), 50% at T2 (2x OR) or EOD close.

Context — M2K is the LAST untested ORB symbol:
    MES ORB rank1 FAILED (p_edge=0.18, dsr=0.0) despite favorable ATR/OR ratio
    of 2-3x. MNQ ORB rank1 also FAILED with ATR/OR ratio 5-8x. M2K has the
    BEST geometric ratio of all (~1.5-2.5x) per session 6 analysis, but the
    MES failure suggests the ORB family lacks edge in the 2024-2025 regime
    REGARDLESS of underlying geometry.

    M2K-specific factors:
      - Russell 2000 is rate-sensitive — Fed cut/hike whipsaws may help or
        hurt opening-range continuation patterns differently from large-cap.
      - Small-cap tracks economic fundamentals (CPI, payrolls) more directly
        than S&P/Nasdaq, which can cause sharp gap reversals after RTH open.
      - Higher beta to credit conditions — wider intraday ranges, more
        breakout signals fire, but more reversion fakes too.

    This is a low-prior-probability hypothesis. Running it primarily to:
    (a) close the ORB question across all portfolio symbols
    (b) collect M2K vol/regime statistics for future hypotheses
    (c) demonstrate ORB family is parked with full evidence trail

Parameter grid (16 combos = 2x2x4): identical to MES/MNQ ORB rank1 for
diagnostic comparison.

M2K contract specs:
    multiplier : $5.0/point  (Micro Russell 2000)
    tick_size  : 0.10 pts = $0.50 per tick
    commission : $0.62/contract/side (IB Tiered micro)
    slippage   : 1 tick ($0.50) each way

Gate v2 thresholds: same as MES ORB rank1 (ALT path, $50K accounts).

Data:   M2K_2024-01-01_2026-03-28_1h.csv
Writes: engine/data/gate_v2_verdicts/M2K_orb_rank1.json

Usage (from engine/ directory):
    .venv/Scripts/python backtest/run_m2k_orb_rank1.py
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

SYMBOL = "M2K"
MULTIPLIER = 5.0  # $5.00 per point (Micro Russell 2000)
CAPITAL = 50_000.0  # ALT path uses $50K accounts
TICK_SIZE = 0.10  # M2K tick is 0.10 (vs 0.25 for MES/MNQ)
COMMISSION = 0.62  # $/contract/side - IB Tiered micro futures
SLIPPAGE_TICKS = 1.0  # 1 tick each way

TRAIN_MONTHS = 6
TEST_MONTHS = 1
STEP_MONTHS = 1

# Grid: 2 x 2 x 4 = 16 combos
# Same grid as MNQ ORB rank1 - diagnostic comparison across symbols
VOLUME_FILTER_VALUES = [True, False]
REGIME_FILTER_VALUES = [False, True]
MIN_OR_RANGE_PCT_VALUES = [0.0005, 0.0008, 0.0012, 0.0015]

# Gate v2 thresholds (ALT path - matches MES rank11 / MNQ ORB rank1)

# Cost tiers (same structure as MNQ ORB for cross-symbol consistency)

MIN_OOS_TRADES_PER_WINDOW = 5  # ORB fires ~21-42/month; 5 is a soft sanity floor


# ---------------------------------------------------------------------------
# ORB result wrapper - adapts ORBBacktestResult.summary() to gate v2 interface
# ---------------------------------------------------------------------------


class _ORBResultWrapper:
    """Thin adapter so gate v2 functions can treat ORB results like Backtester results."""

    def __init__(self, summary: dict):
        self.total_trades = summary.get("total_trades", 0)
        self.profit_factor = summary.get("profit_factor", 0.0)
        self.sharpe_ratio = summary.get("sharpe", 0.0)
        # ORBBacktestResult.summary() returns max_drawdown in dollars; convert to fraction
        self.max_drawdown_pct = summary.get("max_drawdown", 0.0) / CAPITAL
        self._summary = summary

    def __repr__(self):
        return (
            f"ORB(trades={self.total_trades}, pf={self.profit_factor:.3f}, "
            f"dd={self.max_drawdown_pct:.2%}, sharpe={self.sharpe_ratio:.2f})"
        )


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def _load_data(data_file: Path) -> pd.DataFrame:
    df = pd.read_csv(data_file)
    df.columns = [c.lower() for c in df.columns]
    ts_col = "timestamp" if "timestamp" in df.columns else "datetime"
    # IBKR cache timestamps are naive UTC. orb_signals.py expects Eastern Time
    # (hour==9 for RTH open bar). Localize then convert so _detect_rth_open_bar()
    # finds the correct 09:00-10:00 ET bar (13:00 UTC during EDT, 14:00 during EST).
    ts = pd.to_datetime(df[ts_col])
    if ts.dt.tz is None:
        ts = ts.dt.tz_localize("UTC").dt.tz_convert("America/New_York")
    df[ts_col] = ts
    df = df.set_index(ts_col).sort_index()
    required = {"open", "high", "low", "close"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns in {data_file.name}: {missing}")
    return df


def _find_data_file(data_dir: Path) -> Path:
    """Locate the M2K 1h cache with the latest end-date."""
    # Pick the cache covering the latest end-date so a refreshed IBKR pull
    # (named M2K_<start>_<end>_1h.csv) always wins over older files.
    chosen = _find_latest_cache(data_dir, "M2K")
    print(f"[M2K-ORB-R1] Selected {chosen.name}")
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
# ORB execution (with optional cost override)
# ---------------------------------------------------------------------------


def _run_orb(
    df: pd.DataFrame,
    volume_filter: bool,
    regime_filter: bool,
    min_or_range_pct: float,
    commission: float = COMMISSION,
    slippage_ticks: float = SLIPPAGE_TICKS,
) -> _ORBResultWrapper:
    import backtest.orb_backtester as orb_bt

    # Temporarily override MES spec to inject cost-sweep values
    orig_spec = dict(orb_bt.CONTRACT_SPECS.get(SYMBOL, orb_bt.DEFAULT_SPEC))
    orb_bt.CONTRACT_SPECS[SYMBOL] = {
        **orig_spec,
        "commission": commission,
        "slippage_ticks": slippage_ticks,
    }
    try:
        result = orb_bt.run_orb_backtest(
            df,
            symbol=SYMBOL,
            contracts=1,
            volume_filter=volume_filter,
            regime_filter=regime_filter,
            min_or_range_pct=min_or_range_pct,
        )
    finally:
        orb_bt.CONTRACT_SPECS[SYMBOL] = orig_spec  # always restore

    return _ORBResultWrapper(result.summary())


# ---------------------------------------------------------------------------
# IS grid search
# ---------------------------------------------------------------------------


def _best_is_params(df_train: pd.DataFrame, grid: list[tuple]) -> tuple:
    best_score = -1.0
    best_params = None
    best_result = None

    for vol_f, reg_f, min_or in grid:
        try:
            r = _run_orb(df_train, vol_f, reg_f, min_or)
        except Exception as exc:
            print(f"    [WARN] IS error (vol={vol_f}, reg={reg_f}, or={min_or}): {exc}")
            continue
        if r.total_trades < MIN_OOS_TRADES_PER_WINDOW:
            continue
        # Score: profit factor (capped at 5 to prevent inf domination)
        pf_capped = min(r.profit_factor, 5.0) if r.profit_factor != float("inf") else 5.0
        score = pf_capped
        if score > best_score:
            best_score = score
            best_params = {
                "volume_filter": vol_f,
                "regime_filter": reg_f,
                "min_or_range_pct": min_or,
            }
            best_result = r

    return best_params, best_result


# ---------------------------------------------------------------------------
# Gate v2 metric helpers
# ---------------------------------------------------------------------------

from backtest._constants import (  # noqa: E402
    GATE_FIXED_PARAMS_MIN_PF,
    GATE_WFO_CONSISTENCY_VALUES,
)
from backtest._gate_v2_helpers import (  # noqa: E402  # noqa: E402
    COST_SWEEP_TIERS,
    COST_TIER_ORDER,
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
    for vol_f, reg_f, min_or in grid:
        try:
            r = _run_orb(df, vol_f, reg_f, min_or)
            if r.total_trades >= MIN_OOS_TRADES_PER_WINDOW:
                pf_val = r.profit_factor if r.profit_factor != float("inf") else 99.0
                pfs.append(r.profit_factor)
                combo_results.append(
                    {
                        "volume_filter": vol_f,
                        "regime_filter": reg_f,
                        "min_or_range_pct": min_or,
                        "pf": round(pf_val, 4),
                        "trades": r.total_trades,
                    }
                )
                pf_disp = f"{r.profit_factor:.4f}" if r.profit_factor != float("inf") else "inf"
                print(
                    f"    combo (vol={vol_f!s:5s}, reg={reg_f!s:5s}, or={min_or:.4f}): "
                    f"PF={pf_disp}  trades={r.total_trades}"
                )
            else:
                print(
                    f"    combo (vol={vol_f!s:5s}, reg={reg_f!s:5s}, or={min_or:.4f}): "
                    f"SKIP ({r.total_trades} trades)"
                )
        except Exception as exc:
            print(f"  [WARN] fixed-params error (vol={vol_f}, reg={reg_f}, or={min_or}): {exc}")

    if not pfs:
        return {
            "fixed_params_min_pf": 0.0,
            "fixed_params_mean_pf": 0.0,
            "fixed_params_max_pf": 0.0,
            "n_combos_with_trades": 0,
            "combo_results": combo_results,
        }

    finite_pfs = [p for p in pfs if p != float("inf")]
    return {
        "fixed_params_min_pf": round(float(min(finite_pfs)) if finite_pfs else 0.0, 4),
        "fixed_params_mean_pf": round(float(np.mean(finite_pfs)) if finite_pfs else 0.0, 4),
        "fixed_params_max_pf": round(float(max(pfs)) if pfs else 0.0, 4),
        "n_combos_with_trades": len(pfs),
        "combo_results": combo_results,
    }


# ---------------------------------------------------------------------------
# Cost sweep
# ---------------------------------------------------------------------------


def _run_cost_sweep(df: pd.DataFrame, champion_params: dict) -> dict:
    results = {}
    last_passing = None
    vol_f = champion_params["volume_filter"]
    reg_f = champion_params["regime_filter"]
    min_or = champion_params["min_or_range_pct"]

    for tier in COST_TIER_ORDER:
        costs = COST_SWEEP_TIERS[tier]
        try:
            r = _run_orb(
                df,
                vol_f,
                reg_f,
                min_or,
                commission=costs["commission"],
                slippage_ticks=costs["slippage_ticks"],
            )
            pf = r.profit_factor
            passes = pf > 1.0 and r.total_trades >= MIN_OOS_TRADES_PER_WINDOW
            results[tier] = {"pf": round(pf, 4), "trades": r.total_trades, "passes": passes}
            pf_disp = f"{pf:.4f}" if pf != float("inf") else "inf"
            print(
                f"    [{tier:12s}] commission={costs['commission']:.2f}  "
                f"slip={costs['slippage_ticks']:.1f}t  PF={pf_disp}  "
                f"trades={r.total_trades}  {'PASS' if passes else 'FAIL'}"
            )
            if passes:
                last_passing = tier
        except Exception as exc:
            print(f"  [WARN] cost-sweep error at {tier}: {exc}")
            results[tier] = {"pf": 0.0, "trades": 0, "passes": False}

    return {"cost_survives_through": last_passing or "none", "tier_results": results}


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

    print(f"[M2K-ORB-R1] Loading {data_file.name} ...")
    df = _load_data(data_file)
    print(f"[M2K-ORB-R1] {len(df)} bars | {df.index.min().date()} -> {df.index.max().date()}")

    windows = _generate_windows(df)
    if not windows:
        print("[M2K-ORB-R1] ERROR: not enough data to form WFO windows.")
        return {}

    grid = list(
        itertools.product(
            VOLUME_FILTER_VALUES,
            REGIME_FILTER_VALUES,
            MIN_OR_RANGE_PCT_VALUES,
        )
    )
    n_combos = len(grid)  # = 16

    print(f"\n{'=' * 70}")
    print("=== M2K ORB RANK 1 - LAST UNTESTED ORB SYMBOL (LOW PRIOR) ===")
    print(
        f"Windows: {len(windows)} | Train: {TRAIN_MONTHS}mo | Test: {TEST_MONTHS}mo | Step: {STEP_MONTHS}mo"
    )
    print(f"Grid: {n_combos} combos")
    print(f"  volume_filter     : {VOLUME_FILTER_VALUES}")
    print(f"  regime_filter     : {REGIME_FILTER_VALUES}")
    print(f"  min_or_range_pct  : {MIN_OR_RANGE_PCT_VALUES}")
    print(f"  capital           : ${CAPITAL:,.0f}  (ALT path - matches MES rank11 paper config)")
    print(f"  multiplier        : ${MULTIPLIER:.1f}/point  (M2K Micro Russell 2000)")
    print("  signal frequency  : ~1-2 per RTH day (~21-42 per 1-month OOS window)")
    print(
        f"ALT thresholds: dsr>={GATE_DSR_ALT}, wfo in {GATE_WFO_CONSISTENCY_VALUES}, "
        f"fixed>={GATE_FIXED_PARAMS_MIN_PF}, mc_dd<={GATE_MC_DD_ALT * 100:.0f}%"
    )
    print("PRIOR ORB results:")
    print("  MNQ ORB R1 (FAIL): pf_ci=NaN, p_edge=0.18, dsr=0.0, mc_dd=28.15% (ATR/OR=5-8x)")
    print("  MES ORB R1 (FAIL): pf_ci=0.52, p_edge=0.18, dsr=0.0, mc_dd=3.37%  (ATR/OR=2-3x)")
    print("  M2K geometry:      ATR/OR ratio ~1.5-2.5x -- BEST in portfolio, but ORB family")
    print("  itself appears to lack edge in 2024-2025 regime regardless of underlying.")
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
            print(f"  [SKIP] No valid IS params (all combos < {MIN_OOS_TRADES_PER_WINDOW} trades)")
            continue

        pf_disp = (
            f"{is_result.profit_factor:.2f}" if is_result.profit_factor != float("inf") else "inf"
        )
        print(
            f"  Best IS: vol={best_params['volume_filter']}  "
            f"reg={best_params['regime_filter']}  "
            f"or={best_params['min_or_range_pct']:.4f}  "
            f"PF={pf_disp}  trades={is_result.total_trades}"
        )

        try:
            oos_result = _run_orb(
                df_test,
                volume_filter=best_params["volume_filter"],
                regime_filter=best_params["regime_filter"],
                min_or_range_pct=best_params["min_or_range_pct"],
            )
        except Exception as exc:
            print(f"  [SKIP] OOS error: {exc}")
            continue

        pf_oos = oos_result.profit_factor
        pf_oos_disp = f"{pf_oos:.2f}" if pf_oos != float("inf") else "inf"
        print(
            f"  OOS: PF={pf_oos_disp}  "
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
                "is_pf": (
                    is_result.profit_factor if is_result.profit_factor != float("inf") else 99.0
                ),
                "is_trades": is_result.total_trades,
                "oos_pf": round(pf_oos, 3) if pf_oos != float("inf") else 99.0,
                "oos_dd": round(oos_result.max_drawdown_pct, 4),
                "oos_sharpe": round(oos_result.sharpe_ratio, 3),
                "oos_trades": oos_result.total_trades,
            }
        )

    if not oos_results:
        print("\n[M2K-ORB-R1] No OOS results - WFO aborted.")
        print("[M2K-ORB-R1] Unexpected: ORB should produce trades in every 1-month window.")
        print("[M2K-ORB-R1] Check data timezone; ensure RTH bars are present in test windows.")
        return {}

    # Fixed-params sweep on full dataset
    print(f"\n[M2K-ORB-R1] Fixed-params sweep on full dataset ({n_combos} combos)...")
    fixed_params_metrics = _run_fixed_params_sweep(df, grid)
    print(
        f"  fixed_params_min_pf  = {fixed_params_metrics['fixed_params_min_pf']:.4f}  "
        f"(need >= {GATE_FIXED_PARAMS_MIN_PF})"
    )

    # Cost sweep using most-selected champion params
    param_votes = Counter(
        (
            r["best_params"]["volume_filter"],
            r["best_params"]["regime_filter"],
            r["best_params"]["min_or_range_pct"],
        )
        for r in window_records
    )
    most_selected = param_votes.most_common(1)[0][0] if param_votes else (True, False, 0.0008)
    champion_params = {
        "volume_filter": most_selected[0],
        "regime_filter": most_selected[1],
        "min_or_range_pct": most_selected[2],
    }
    print(f"\n[M2K-ORB-R1] Cost sweep (champion: {champion_params})...")
    cost_sweep_metrics = _run_cost_sweep(df, champion_params)
    print(
        f"  cost_survives_through = {cost_sweep_metrics['cost_survives_through']}  "
        f"(need >= 'realistic')"
    )

    # Gate v2 evaluation
    gate = _compute_gate_v2(oos_results, n_combos, fixed_params_metrics, cost_sweep_metrics)

    print(f"\n{'=' * 70}")
    print(f"=== GATE v2 VERDICT: {gate['verdict']} (via {gate['passed_via'] or 'NONE'}) ===")
    print(f"  pf_ci_lower          = {gate['pf_ci_lower']:.4f}  (need >= {GATE_PF_CI_LOWER})")
    print(f"  p_edge               = {gate['p_edge']:.4f}  (need >= {GATE_P_EDGE})")
    print(
        f"  mc_95th_dd_pct       = {gate['mc_95th_dd_pct']:.4f}%  "
        f"(core <= {GATE_MC_DD_CORE * 100:.0f}% / alt <= {GATE_MC_DD_ALT * 100:.0f}%)"
    )
    print(
        f"  dsr                  = {gate['dsr']:.6f}  (core >= {GATE_DSR} / alt >= {GATE_DSR_ALT})"
    )
    print(f"  wfo_consistency      = {gate['wfo_consistency']}")
    print(
        f"  fixed_params_min_pf  = {gate['fixed_params_min_pf']:.4f}  "
        f"(need >= {GATE_FIXED_PARAMS_MIN_PF})"
    )
    print(f"  cost_survives_through= {gate['cost_survives_through']}")
    print(f"  core_verdict         = {gate['core_verdict']}")
    print(f"  alt_verdict          = {gate['alt_verdict']}")
    print(
        f"  OOS windows          = {gate['n_oos_windows_with_trades']} with trades / "
        f"{gate['n_oos_windows']} total"
    )
    print(f"  Total OOS trades     = {gate['total_oos_trades']}")
    print(f"{'=' * 70}")

    # Write gate v2 verdict JSON
    verdicts_dir = engine_root / "data" / "gate_v2_verdicts"
    verdicts_dir.mkdir(parents=True, exist_ok=True)
    verdict_file = verdicts_dir / "M2K_orb_rank1.json"

    now_iso = datetime.now(tz=timezone.utc).isoformat()
    verdict_doc = {
        "symbol": SYMBOL,
        "family": "orb",
        "hypothesis": "rank1",
        "verdict": gate["verdict"],
        "passed_via": gate["passed_via"],
        "core_verdict": gate["core_verdict"],
        "alt_verdict": gate["alt_verdict"],
        "n_core_passed": gate["n_core_passed"],
        "n_alt_passed": gate["n_alt_passed"],
        "created_at": now_iso,
        "aux_freshness": {
            "rolling_wfo": now_iso,
            "fixed_params": now_iso,
            "cost_sweep": now_iso,
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
            "grid_volume_filter": VOLUME_FILTER_VALUES,
            "grid_regime_filter": REGIME_FILTER_VALUES,
            "grid_min_or_range_pct": MIN_OR_RANGE_PCT_VALUES,
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
            "slippage_ticks": SLIPPAGE_TICKS,
            "capital": CAPITAL,
            "note": "M2K is rate-sensitive small-cap; backtest sizing only",
        },
        "lineage": {
            "family": "orb",
            "rank": 1,
            "predecessor": None,
            "rationale": "Last untested ORB symbol. M2K has best ATR/OR ratio (~1.5-2.5x) but MES ORB rank1 FAIL (with ratio 2-3x) suggests ORB family has no edge in 2024-2025 regime regardless of geometry.",
            "m2k_trend_status": "EXHAUSTED - ranks 1-2 FAIL (rate-sensitivity whipsaws)",
            "mes_orb_status": "FAIL rank1 (p_edge=0.18, dsr=0.0)",
            "mnq_orb_status": "FAIL rank1 (p_edge=0.18, dsr=0.0, ATR/OR too high)",
            "mes_trend_status": "PASS via alt (rank11) - portfolio anchor",
            "mgc_trend_status": "PASS via alt (rank4)  - portfolio anchor",
        },
    }

    # Provenance (2026-09-17 audit): record which cache produced this verdict.
    from backtest._gate_v2_helpers import inject_cache_provenance as _inject_prov  # noqa: E402
    verdict_doc = _inject_prov(verdict_doc, data_file)
    verdict_file.write_text(json.dumps(verdict_doc, indent=2, default=str))
    print(f"\n[M2K-ORB-R1] Verdict written -> {verdict_file}")
    return verdict_doc


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    verdict = run_wfo()
    if not verdict:
        print("[M2K-ORB-R1] No verdict produced.")
        sys.exit(1)

    final = verdict.get("verdict", "FAIL")
    passed_via = verdict.get("passed_via")
    gate = verdict.get("gate_v2_metrics", {})

    if final == "PASS" and passed_via == "core":
        print("\n[PASS-CORE] M2K ORB Rank 1 PASSES gate v2 (CORE path).")
        print("  SURPRISE: ORB family alive on small-cap despite MES/MNQ FAILs.")
        print("  ACTION: Add M2K to paper_config.py with ORB champion params.")
        print("  ACTION: Add M2K to ACTIVE_INSTRUMENTS; remove from DO_NOT_TRADE_SYMBOLS.")
        champ = verdict.get("champion_params", {})
        print(
            f"  CHAMPION: vol={champ.get('volume_filter')}  "
            f"reg={champ.get('regime_filter')}  or={champ.get('min_or_range_pct')}"
        )
    elif final == "PASS" and passed_via == "alt":
        print("\n[PASS-ALT] M2K ORB Rank 1 PASSES gate v2 (ALT path - $50K+ accounts).")
        print("  SURPRISE: ORB family alive on small-cap despite MES/MNQ FAILs.")
        print("  ACTION: Add M2K to paper_config.py; ALT path -> $50K+ account required.")
        champ = verdict.get("champion_params", {})
        print(
            f"  CHAMPION: vol={champ.get('volume_filter')}  "
            f"reg={champ.get('regime_filter')}  or={champ.get('min_or_range_pct')}"
        )
    else:
        print("\n[FAIL] M2K ORB Rank 1 FAILS gate v2.")
        dsr_val = gate.get("dsr", 0.0)
        p_edge = gate.get("p_edge", 0.0)
        pf_ci = gate.get("pf_ci_lower", 0.0)
        wfo = gate.get("wfo_consistency", "WEAK")
        fpmf = gate.get("fixed_params_min_pf", 0.0)

        if pf_ci < GATE_PF_CI_LOWER:
            print(
                f"  pf_ci_lower={pf_ci:.4f} below {GATE_PF_CI_LOWER} - OOS profit factor too variable"
            )
        if p_edge < GATE_P_EDGE:
            print(
                f"  p_edge={p_edge:.4f} below {GATE_P_EDGE} - fewer than 95% of OOS windows profitable"
            )
        if dsr_val < GATE_DSR_ALT:
            print(f"  dsr={dsr_val:.6f} below ALT floor {GATE_DSR_ALT}")
        if wfo not in GATE_WFO_CONSISTENCY_VALUES:
            print(f"  wfo_consistency={wfo} - M2K ORB shows regime instability")
            print("  Consider: ORB family is parked across portfolio; pivot to mean-reversion")
        if fpmf < GATE_FIXED_PARAMS_MIN_PF:
            print(
                f"  fixed_params_min_pf={fpmf:.4f} - no parameter set wins consistently on full dataset"
            )
        print("  ORB family fully evaluated across portfolio: MNQ FAIL, MES FAIL, M2K FAIL.")
        print("  Next direction: MES Mean-Reversion 1h, or accelerate to live trading on")
        print("  the 2 PASS strategies (MES trend + MGC trend).")


if __name__ == "__main__":
    main()
