"""
Shared walk-forward evaluation lifecycle for all backtest runners.

Extracts the duplicated WFO loop, IS grid search, OOS evaluation, fixed-params
sweep, cost sweep, and gate v2 computation that previously lived as private
functions in each runner file (e.g. run_mgc_trend_rank4.py).

Note: verdict_lifecycle.py handles the *commit* pipeline (archive → write →
compare → journal). This module handles the *computation* pipeline (windows →
IS search → OOS eval → gate v2).

Usage pattern in a runner
--------------------------
    from backtest.wfo_lifecycle import (
        WFOConfig, OOSResult,
        generate_windows, grid_search_is, run_oos_window,
        run_fixed_params_sweep, run_cost_sweep, compute_gate_v2, run_wfo,
    )

    def _run_fn(df: pd.DataFrame, params: dict) -> BacktestResult:
        sig = generate_sma_trend_signals(
            df,
            fast=params["fast"],
            slow=params["slow"],
            atr_trail_mult=params.get("atr_trail_mult", 2.0),
        )
        commission     = params.get("commission", COMMISSION)
        slippage_ticks = params.get("slippage_ticks", SLIPPAGE_TICKS)
        bt = Backtester(
            initial_capital=CAPITAL,
            commission_per_contract=commission,
            slippage_ticks=slippage_ticks,
        )
        return bt.run(sig, symbol=SYMBOL, multiplier=MULTIPLIER)

    cfg = WFOConfig(
        train_len=pd.DateOffset(months=6),
        test_len=pd.DateOffset(months=2),
        step_len=pd.DateOffset(months=1),
    )
    grid = [{"fast": f, "slow": s, "atr_trail_mult": a} for f, s, a in product(...)]
    oos_results, window_records = run_wfo(df, grid, _run_fn, cfg)
    fixed = run_fixed_params_sweep(df, grid, _run_fn)
    cost  = run_cost_sweep(df, champion_params, COST_SWEEP_TIERS, _run_fn)
    gate  = compute_gate_v2(oos_results, len(grid), fixed, cost)

Design notes
------------
- RunFn signature: Callable[[pd.DataFrame, dict], BacktestResult]
  The dict holds signal params AND optionally commission/slippage_ticks so the
  same run_fn can serve both IS search and cost-sweep calls without branching.
- Window generation: int train_len/test_len/step_len → bar-count slicing;
  pd.DateOffset → calendar-date slicing. Production runners use DateOffset;
  tests typically use int for determinism and speed.
- compute_gate_v2 is the canonical dual-path (core + ALT) logic extracted from
  every runner's private _compute_gate_v2; it is functionally identical.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd

from backtest._constants import (
    COST_TIER_ORDER,
    GATE_FIXED_PARAMS_MIN_PF,
    GATE_WFO_CONSISTENCY_VALUES,
)
from backtest._gate_v2_helpers import (
    GATE_DSR,
    GATE_DSR_ALT,
    GATE_MC_DD_ALT,
    GATE_MC_DD_CORE,
    GATE_P_EDGE,
    GATE_PF_CI_LOWER,
    bootstrap_pf_ci_lower,
    classify_wfo_consistency,
)

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

RunFn = Callable[["pd.DataFrame", dict], object]
"""(df, params) -> BacktestResult.
params may include 'commission' and 'slippage_ticks' for cost-sweep calls.
"""


@dataclass
class WFOConfig:
    """Walk-forward window parameters."""

    train_len: "int | pd.DateOffset"
    test_len: "int | pd.DateOffset"
    step_len: "int | pd.DateOffset"
    min_bars: int = 30


@dataclass
class OOSResult:
    """Outcome of a single OOS evaluation window."""

    window_idx: int
    best_params: dict
    profit_factor: float
    max_drawdown_pct: float
    sharpe_ratio: float
    total_trades: int
    is_pf: float = 0.0
    is_trades: int = 0


# ---------------------------------------------------------------------------
# Window generation
# ---------------------------------------------------------------------------


def generate_windows(df: pd.DataFrame, cfg: WFOConfig) -> list[dict]:
    """Slice df into walk-forward windows per cfg.

    Returns a list of dicts with keys:
        window_num, train_start, train_end, test_start, test_end,
        n_train, n_test, df_train, df_test

    cfg.train_len/test_len/step_len as int  -> bar-count slicing.
    cfg.train_len/test_len/step_len as DateOffset -> calendar-date slicing.
    Windows with fewer than cfg.min_bars in either split are skipped.
    """
    if isinstance(cfg.train_len, int):
        return _windows_by_bars(df, cfg)
    return _windows_by_offset(df, cfg)


def _windows_by_bars(df: pd.DataFrame, cfg: WFOConfig) -> list[dict]:
    total = len(df)
    windows = []
    cursor = 0
    wnum = 1
    while cursor + cfg.train_len + cfg.test_len <= total:  # type: ignore[operator]
        t_end = cursor + cfg.train_len  # type: ignore[operator]
        os_end = min(t_end + cfg.test_len, total)  # type: ignore[operator]
        df_train = df.iloc[cursor:t_end]
        df_test = df.iloc[t_end:os_end]
        if len(df_train) >= cfg.min_bars and len(df_test) >= cfg.min_bars:
            windows.append(
                {
                    "window_num": wnum,
                    "train_start": df_train.index.min(),
                    "train_end": df_train.index.max(),
                    "test_start": df_test.index.min(),
                    "test_end": df_test.index.max(),
                    "n_train": len(df_train),
                    "n_test": len(df_test),
                    "df_train": df_train,
                    "df_test": df_test,
                }
            )
            wnum += 1
        cursor += cfg.step_len  # type: ignore[operator]
    return windows


def _windows_by_offset(df: pd.DataFrame, cfg: WFOConfig) -> list[dict]:
    data_start = df.index.min()
    data_end = df.index.max()
    windows = []
    cursor = data_start
    wnum = 1
    while True:
        train_end = cursor + cfg.train_len
        test_start = train_end
        test_end = test_start + cfg.test_len
        if test_start >= data_end:
            break
        if test_end > data_end:
            test_end = data_end
        df_train = df[(df.index >= cursor) & (df.index < train_end)]
        df_test = df[(df.index >= test_start) & (df.index <= test_end)]
        if len(df_train) >= cfg.min_bars and len(df_test) >= cfg.min_bars:
            windows.append(
                {
                    "window_num": wnum,
                    "train_start": cursor,
                    "train_end": train_end,
                    "test_start": test_start,
                    "test_end": test_end,
                    "n_train": len(df_train),
                    "n_test": len(df_test),
                    "df_train": df_train,
                    "df_test": df_test,
                }
            )
            wnum += 1
        cursor += cfg.step_len
        if cursor >= data_end:
            break
    return windows


# ---------------------------------------------------------------------------
# IS grid search
# ---------------------------------------------------------------------------


def grid_search_is(
    df_train: pd.DataFrame,
    grid: list[dict],
    run_fn: RunFn,
    min_trades: int = 1,
) -> tuple[dict | None, object | None]:
    """Find best IS params by profit factor.

    Returns (best_params, best_result) or (None, None) when all combos fail
    or produce fewer than min_trades trades.
    """
    best_pf = -1.0
    best_params = None
    best_result = None
    for params in grid:
        try:
            result = run_fn(df_train, params)
        except Exception:
            continue
        if result.total_trades < min_trades:  # type: ignore[union-attr]
            continue
        pf = result.profit_factor  # type: ignore[union-attr]
        if pf > best_pf:
            best_pf = pf
            best_params = params
            best_result = result
    return best_params, best_result


# ---------------------------------------------------------------------------
# Single OOS evaluation
# ---------------------------------------------------------------------------


def run_oos_window(
    df_test: pd.DataFrame,
    params: dict,
    run_fn: RunFn,
    window_idx: int,
    is_pf: float = 0.0,
    is_trades: int = 0,
) -> OOSResult | None:
    """Run one OOS window. Returns None on exception (window is silently skipped)."""
    try:
        result = run_fn(df_test, params)
        return OOSResult(
            window_idx=window_idx,
            best_params=params,
            profit_factor=result.profit_factor,  # type: ignore[union-attr]
            max_drawdown_pct=result.max_drawdown_pct,  # type: ignore[union-attr]
            sharpe_ratio=result.sharpe_ratio,  # type: ignore[union-attr]
            total_trades=result.total_trades,  # type: ignore[union-attr]
            is_pf=is_pf,
            is_trades=is_trades,
        )
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Fixed-params sweep
# ---------------------------------------------------------------------------


def run_fixed_params_sweep(
    df: pd.DataFrame,
    grid: list[dict],
    run_fn: RunFn,
    min_trades: int = 1,
) -> dict:
    """Run all grid combos on the full dataset (no IS/OOS split).

    Returns fixed_params_min_pf, mean_pf, max_pf, n_combos_with_trades,
    and combo_results (list of per-combo summary dicts).
    """
    pfs: list[float] = []
    combo_results: list[dict] = []
    for params in grid:
        try:
            result = run_fn(df, params)
            if result.total_trades >= min_trades:  # type: ignore[union-attr]
                pf = result.profit_factor  # type: ignore[union-attr]
                pfs.append(pf)
                combo_results.append(
                    {
                        **params,
                        "pf": round(pf, 4),
                        "trades": result.total_trades,  # type: ignore[union-attr]
                    }
                )
        except Exception:
            pass
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


def run_cost_sweep(
    df: pd.DataFrame,
    champion_params: dict,
    cost_tiers: dict,
    run_fn: RunFn,
    min_trades: int = 1,
) -> dict:
    """Sweep cost tiers (optimistic → catastrophic) using champion_params.

    cost_tiers format:
        {"optimistic": {"commission": 0.31, "slippage_ticks": 1.0}, ...}

    Each tier's cost values are merged into champion_params before run_fn is
    called, so run_fn must read commission/slippage_ticks from params via .get().

    Returns cost_survives_through (highest tier with PF > 1.0) and tier_results.
    """
    results: dict = {}
    last_surviving: str | None = None
    for tier in COST_TIER_ORDER:
        costs = cost_tiers.get(tier)
        if costs is None:
            continue
        merged = {**champion_params, **costs}
        try:
            result = run_fn(df, merged)
            pf = result.profit_factor  # type: ignore[union-attr]
            passes = pf > 1.0 and result.total_trades >= min_trades  # type: ignore[union-attr]
            results[tier] = {
                "pf": round(pf, 4),
                "trades": result.total_trades,  # type: ignore[union-attr]
                "passes": passes,
            }
            if passes:
                last_surviving = tier
        except Exception:
            results[tier] = {"pf": 0.0, "trades": 0, "passes": False}
    return {
        "cost_survives_through": last_surviving or "none",
        "tier_results": results,
    }


# ---------------------------------------------------------------------------
# Gate v2 — dual-path computation
# ---------------------------------------------------------------------------


def compute_gate_v2(
    oos_results: list[OOSResult],
    n_grid_combos: int,
    fixed_params_metrics: dict,
    cost_sweep_metrics: dict,
    min_trades: int = 1,
) -> dict:
    """Compute gate v2 PASS/FAIL from OOS results and auxiliary sweep outputs.

    Implements the dual-path (core + ALT) decision logic extracted from every
    runner's private _compute_gate_v2 function. Functionally identical to those
    copies.

    Core path:  pf_ci_lower >= 1.10
                AND p_edge >= 0.95
                AND mc_95th_dd <= 5%
                AND dsr >= 0.10

    ALT path:   dsr >= 0.30
                AND wfo_consistency in [MODERATE, STRONG]
                AND fixed_params_min_pf >= 1.20
                AND cost_survives_through >= realistic
                AND mc_95th_dd <= 4%
    """
    from backtest.deflated_sharpe import deflated_sharpe_ratio

    qualified = [r for r in oos_results if r.total_trades >= min_trades]
    oos_pfs = [r.profit_factor for r in qualified]
    oos_dds = [r.max_drawdown_pct for r in oos_results]
    oos_sharpes = [r.sharpe_ratio for r in qualified]
    all_trades = sum(r.total_trades for r in oos_results)

    pf_ci_lower = bootstrap_pf_ci_lower(oos_pfs) if oos_pfs else 0.0
    p_edge = float(sum(1 for pf in oos_pfs if pf > 1.0) / max(1, len(oos_pfs)))
    mc_95th_dd = float(np.percentile(oos_dds, 95.0)) if oos_dds else 1.0
    mean_sharpe = float(np.mean(oos_sharpes)) if oos_sharpes else 0.0
    n_obs = max(all_trades, 30)

    dsr_raw = deflated_sharpe_ratio(sharpe=mean_sharpe, n_trials=n_grid_combos, n_obs=n_obs)
    dsr = dsr_raw.get("dsr", 0.0) if isinstance(dsr_raw, dict) else float(dsr_raw)

    wfo_consistency = classify_wfo_consistency(oos_pfs)
    fixed_min_pf = fixed_params_metrics.get("fixed_params_min_pf", 0.0)
    cost_via = cost_sweep_metrics.get("cost_survives_through", "none")
    cost_tier_idx = COST_TIER_ORDER.index(cost_via) if cost_via in COST_TIER_ORDER else -1
    cost_passes = cost_tier_idx >= COST_TIER_ORDER.index("realistic")

    core_pass = (
        pf_ci_lower >= GATE_PF_CI_LOWER
        and p_edge >= GATE_P_EDGE
        and mc_95th_dd <= GATE_MC_DD_CORE
        and dsr >= GATE_DSR
    )
    alt_pass = (
        dsr >= GATE_DSR_ALT
        and wfo_consistency in GATE_WFO_CONSISTENCY_VALUES
        and fixed_min_pf >= GATE_FIXED_PARAMS_MIN_PF
        and cost_passes
        and mc_95th_dd <= GATE_MC_DD_ALT
    )

    if core_pass:
        verdict, passed_via = "PASS", "core"
    elif alt_pass:
        verdict, passed_via = "PASS", "alt"
    else:
        verdict, passed_via = "FAIL", None

    core_reasons = [
        f"{'FAIL ' if pf_ci_lower < GATE_PF_CI_LOWER else ''}pf_ci_lower={pf_ci_lower:.4f} >= {GATE_PF_CI_LOWER}",
        f"{'FAIL ' if p_edge < GATE_P_EDGE else ''}p_edge={p_edge:.4f} >= {GATE_P_EDGE}",
        f"{'FAIL ' if mc_95th_dd > GATE_MC_DD_CORE else ''}mc_95th_dd_pct={mc_95th_dd*100:.4f} {'<=' if mc_95th_dd <= GATE_MC_DD_CORE else '>'} {GATE_MC_DD_CORE*100:.1f}",
        f"{'FAIL ' if dsr < GATE_DSR else ''}dsr={dsr:.6f} >= {GATE_DSR}",
    ]
    alt_reasons = [
        f"{'FAIL ' if dsr < GATE_DSR_ALT else ''}dsr={dsr:.6f} >= {GATE_DSR_ALT} (alt floor)",
        f"{'FAIL ' if wfo_consistency not in GATE_WFO_CONSISTENCY_VALUES else ''}rolling_wfo={wfo_consistency} in {GATE_WFO_CONSISTENCY_VALUES}",
        f"{'FAIL ' if fixed_min_pf < GATE_FIXED_PARAMS_MIN_PF else ''}fixed_params_min_pf={fixed_min_pf:.3f} >= {GATE_FIXED_PARAMS_MIN_PF}",
        f"{'FAIL ' if not cost_passes else ''}cost_survives_through={cost_via} >= realistic",
        f"{'FAIL ' if mc_95th_dd > GATE_MC_DD_ALT else ''}mc_95th_dd_pct={mc_95th_dd*100:.4f} <= {GATE_MC_DD_ALT*100:.1f} (alt ceiling)",
    ]

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
        "fixed_params_min_pf": fixed_params_metrics.get("fixed_params_min_pf", 0.0),
        "fixed_params_mean_pf": fixed_params_metrics.get("fixed_params_mean_pf", 0.0),
        "fixed_params_max_pf": fixed_params_metrics.get("fixed_params_max_pf", 0.0),
        "cost_survives_through": cost_via,
        "n_oos_windows": len(oos_results),
        "n_oos_windows_with_trades": len(qualified),
        "total_oos_trades": all_trades,
        "core_reasons": core_reasons,
        "alt_reasons": alt_reasons,
        "reasons": core_reasons + alt_reasons,
    }


# ---------------------------------------------------------------------------
# Full WFO orchestrator
# ---------------------------------------------------------------------------


def run_wfo(
    df: pd.DataFrame,
    grid: list[dict],
    run_fn: RunFn,
    cfg: WFOConfig,
    min_trades: int = 1,
) -> tuple[list[OOSResult], list[dict]]:
    """Full walk-forward evaluation: windows → IS search → OOS eval.

    Does NOT run fixed-params sweep, cost sweep, or gate v2 — those are
    optional and caller-controlled. Call run_fixed_params_sweep(),
    run_cost_sweep(), and compute_gate_v2() separately on the returned results.

    Returns:
        oos_results:    list[OOSResult]  — one entry per successful OOS window
        window_records: list[dict]       — per-window summary for logging/JSON
    """
    windows = generate_windows(df, cfg)
    oos_results: list[OOSResult] = []
    window_records: list[dict] = []

    for win in windows:
        wnum = win["window_num"]
        df_train = win["df_train"]
        df_test = win["df_test"]

        best_params, is_result = grid_search_is(df_train, grid, run_fn, min_trades)
        if best_params is None:
            continue

        is_pf = is_result.profit_factor if is_result else 0.0  # type: ignore[union-attr]
        is_trades = is_result.total_trades if is_result else 0  # type: ignore[union-attr]

        oos = run_oos_window(
            df_test,
            best_params,
            run_fn,
            wnum,
            is_pf=is_pf,
            is_trades=is_trades,
        )
        if oos is None:
            continue

        oos_results.append(oos)
        window_records.append(
            {
                "window": wnum,
                "best_params": best_params,
                "is_pf": round(oos.is_pf, 3),
                "is_trades": oos.is_trades,
                "oos_pf": round(oos.profit_factor, 3),
                "oos_dd": round(oos.max_drawdown_pct, 4),
                "oos_sharpe": round(oos.sharpe_ratio, 3),
                "oos_trades": oos.total_trades,
            }
        )

    return oos_results, window_records
