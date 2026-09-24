#!/usr/bin/env python
"""
MES VWAP Reversion Gate v2 -- Rank 1 Verdict

VWAP Deviation Reversion strategy for MES (Micro E-mini S&P 500) on 1h bars.

Strategy: session VWAP (reset 09:30 ET); bands at VWAP +/- band_mult*ATR.
LONG when close < lower band with 1-bar reversal up; SHORT when close > upper
band with 1-bar reversal down. Stop = entry +/- stop_mult*ATR. T1 = VWAP,
T2 = opposite band. Full exit (no partials). EOD force-close at 15:xx ET.

Context -- this closes the VWAP-reversion question under gate v2:
    The legacy WFE validator (backtest/vwap_walk_forward.py, run 2026-04-02,
    36-combo grid, 6mo train / 3mo test) REJECTED VWAP@MES with WFE=0.0196,
    only 2/5 OOS windows profitable (OOS PFs 0.71, 1.21, 0.61, 2.78, 0.53;
    mostly negative OOS Sharpe). That methodology predates gate v2, so no
    gate_v2_verdicts/MES_vwap_rank1.json existed. This runner produces the
    comparable gate-v2 verdict so the candidate is closed with a documented
    audit trail (kill reasons are first-class in the funnel).

    Prior expectation: p_edge ~0.40 << 0.95 floor -> CORE FAIL near-certain.
    Running it anyway to (a) make VWAP comparable to the M2K Donchian/ORB
    gate-v2 verdicts run alongside it, (b) refresh on data through 2026-06-25.

Parameter grid (36 combos = 3 x 3 x 2 x 2): identical to the legacy VWAP WFE
grid for diagnostic continuity.
    band_mult            : 1.5, 2.0, 2.5
    stop_mult            : 0.25, 0.50, 0.75
    require_reversal_bar : True, False
    regime_filter        : True, False

MES contract specs:
    multiplier : $5.0/point  (Micro E-mini S&P 500)
    tick_size  : 0.25 pts = $1.25 per tick
    commission : $0.62/contract/side (IB Tiered micro)
    slippage   : 1 tick ($1.25) each way

Gate v2 thresholds: same as MES rank11 (ALT path, $50K accounts).

Data:   MES_*_1h.csv (latest end-date cache, picked by _find_latest_cache)
Writes: engine/data/gate_v2_verdicts/MES_vwap_rank1.json

Usage (from engine/ directory):
    .venv/Scripts/python backtest/run_mes_vwap_rank1.py
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

SYMBOL = "MES"
MULTIPLIER = 5.0  # $5.00 per point (Micro E-mini S&P 500)
CAPITAL = 50_000.0  # ALT path uses $50K accounts
TICK_SIZE = 0.25  # MES tick is 0.25
COMMISSION = 0.62  # $/contract/side - IB Tiered micro futures
SLIPPAGE_TICKS = 1.0  # 1 tick each way

TRAIN_MONTHS = 6
TEST_MONTHS = 3
STEP_MONTHS = 3

# Grid: 3 x 3 x 2 x 2 = 36 combos (matches legacy vwap_walk_forward.py)
BAND_MULT_VALUES = [1.5, 2.0, 2.5]
STOP_MULT_VALUES = [0.25, 0.50, 0.75]
REQUIRE_REVERSAL_VALUES = [True, False]
REGIME_FILTER_VALUES = [True, False]

MIN_OOS_TRADES_PER_WINDOW = 5  # soft sanity floor


# ---------------------------------------------------------------------------
# VWAP result wrapper - adapts VWAPBacktestResult.summary() to gate v2 interface
# ---------------------------------------------------------------------------


class _VWAPResultWrapper:
    """Thin adapter so gate v2 functions can treat VWAP results like Backtester results."""

    def __init__(self, summary: dict, trades=None):
        self.total_trades = summary.get("total_trades", 0)
        self.profit_factor = summary.get("profit_factor", 0.0)
        self.sharpe_ratio = summary.get("sharpe", 0.0)
        # VWAPBacktestResult.summary() returns max_drawdown in dollars; convert to fraction
        self.max_drawdown_pct = summary.get("max_drawdown", 0.0) / CAPITAL
        # Raw per-trade objects (each with .pnl) so the centralized trade-level
        # DSR/MC-DD metrics can flatten them. Without this the trade-level DSR
        # fail-safes to 0.0. See _gate_v2_trade_metrics.concat_oos_trade_pnls.
        self.trades = trades or []
        self._summary = summary

    def __repr__(self):
        return (
            f"VWAP(trades={self.total_trades}, pf={self.profit_factor:.3f}, "
            f"dd={self.max_drawdown_pct:.2%}, sharpe={self.sharpe_ratio:.2f})"
        )


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def _load_data(data_file: Path) -> pd.DataFrame:
    df = pd.read_csv(data_file)
    df.columns = [c.lower() for c in df.columns]
    ts_col = "timestamp" if "timestamp" in df.columns else "datetime"
    # IBKR cache timestamps are naive UTC. vwap_signals.py expects Eastern Time
    # (hour==9 for RTH open bar, hour>=15 to block late entries). Localize then
    # convert so the session VWAP reset and EOD logic find the correct ET bars.
    ts = pd.to_datetime(df[ts_col])
    if ts.dt.tz is None:
        ts = ts.dt.tz_localize("UTC").dt.tz_convert("America/New_York")
    df[ts_col] = ts
    df = df.set_index(ts_col).sort_index()
    required = {"open", "high", "low", "close", "volume"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns in {data_file.name}: {missing}")
    return df


def _find_data_file(data_dir: Path) -> Path:
    """Locate the MES 1h cache with the latest end-date."""
    chosen = _find_latest_cache(data_dir, "MES")
    print(f"[MES-VWAP-R1] Selected {chosen.name}")
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
        if len(df_train) >= 200 and len(df_test) >= 50:
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
# VWAP execution (with optional cost override)
# ---------------------------------------------------------------------------


def _run_vwap(
    df: pd.DataFrame,
    band_mult: float,
    stop_mult: float,
    require_reversal_bar: bool,
    regime_filter: bool,
    commission: float = COMMISSION,
    slippage_ticks: float = SLIPPAGE_TICKS,
    sota_hardening: bool = False,
) -> _VWAPResultWrapper:
    import backtest.vwap_backtester as vwap_bt

    # Temporarily override MES spec to inject cost-sweep values
    orig_spec = dict(vwap_bt.CONTRACT_SPECS.get(SYMBOL, vwap_bt.DEFAULT_SPEC))
    vwap_bt.CONTRACT_SPECS[SYMBOL] = {
        **orig_spec,
        "commission": commission,
        "slippage_ticks": slippage_ticks,
    }
    try:
        result = vwap_bt.run_vwap_backtest(
            df,
            symbol=SYMBOL,
            contracts=1,
            band_mult=band_mult,
            stop_mult=stop_mult,
            require_reversal_bar=require_reversal_bar,
            regime_filter=regime_filter,
            # SOTA execution-realism hardening (PR #592). Opt-in: baseline runs
            # leave all flags at defaults (False/None) so the non-SOTA
            # invocation is byte-identical to pre-hardening behavior.
            **(
                {
                    "pessimistic_tie_breaker": True,
                    "gap_stop_worst_fill": True,
                    "volatility_scaled_slippage": True,
                    "max_volume_pct": 0.10,
                    "initial_margin_per_contract": 1500.0,
                    "initial_capital": CAPITAL,
                }
                if sota_hardening
                else {}
            )
        )
    finally:
        vwap_bt.CONTRACT_SPECS[SYMBOL] = orig_spec  # always restore

    return _VWAPResultWrapper(result.summary(), trades=result.trades)


# ---------------------------------------------------------------------------
# IS grid search
# ---------------------------------------------------------------------------


def _best_is_params(
    df_train: pd.DataFrame, grid: list[tuple], sota_hardening: bool = False
) -> tuple:
    best_score = -1.0
    best_params = None
    best_result = None

    for band, stop, reversal, regime in grid:
        try:
            r = _run_vwap(df_train, band, stop, reversal, regime, sota_hardening=sota_hardening)
        except Exception as exc:
            print(
                f"    [WARN] IS error (band={band}, stop={stop}, rev={reversal}, "
                f"reg={regime}): {exc}"
            )
            continue
        if r.total_trades < MIN_OOS_TRADES_PER_WINDOW:
            continue
        # Score: profit factor (capped at 5 to prevent inf domination)
        pf_capped = min(r.profit_factor, 5.0) if r.profit_factor != float("inf") else 5.0
        score = pf_capped
        if score > best_score:
            best_score = score
            best_params = {
                "band_mult": band,
                "stop_mult": stop,
                "require_reversal_bar": reversal,
                "regime_filter": regime,
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
from backtest._gate_v2_helpers import (  # noqa: E402
    COST_SWEEP_TIERS,
    COST_TIER_ORDER,
    GATE_DSR,
    GATE_DSR_ALT,
    GATE_MC_DD_ALT,
    GATE_MC_DD_CORE,
    GATE_P_EDGE,
    GATE_PF_CI_LOWER,
    _find_latest_cache,
)
from backtest._gate_v2_helpers import bootstrap_pf_ci_lower as _bootstrap_pf_ci_lower  # noqa: E402
from backtest._gate_v2_helpers import (  # noqa: E402
    classify_wfo_consistency as _classify_wfo_consistency,
)

# ---------------------------------------------------------------------------
# Fixed-params sweep
# ---------------------------------------------------------------------------


def _run_fixed_params_sweep(
    df: pd.DataFrame, grid: list[tuple], sota_hardening: bool = False
) -> dict:
    pfs = []
    combo_results = []
    for band, stop, reversal, regime in grid:
        try:
            r = _run_vwap(df, band, stop, reversal, regime, sota_hardening=sota_hardening)
            if r.total_trades >= MIN_OOS_TRADES_PER_WINDOW:
                pf_val = r.profit_factor if r.profit_factor != float("inf") else 99.0
                pfs.append(r.profit_factor)
                combo_results.append(
                    {
                        "band_mult": band,
                        "stop_mult": stop,
                        "require_reversal_bar": reversal,
                        "regime_filter": regime,
                        "pf": round(pf_val, 4),
                        "trades": r.total_trades,
                    }
                )
                pf_disp = f"{r.profit_factor:.4f}" if r.profit_factor != float("inf") else "inf"
                print(
                    f"    combo (band={band:.1f}, stop={stop:.2f}, rev={reversal!s:5s}, "
                    f"reg={regime!s:5s}): PF={pf_disp}  trades={r.total_trades}"
                )
            else:
                print(
                    f"    combo (band={band:.1f}, stop={stop:.2f}, rev={reversal!s:5s}, "
                    f"reg={regime!s:5s}): SKIP ({r.total_trades} trades)"
                )
        except Exception as exc:
            print(
                f"  [WARN] fixed-params error (band={band}, stop={stop}, rev={reversal}, "
                f"reg={regime}): {exc}"
            )

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


def _run_cost_sweep(
    df: pd.DataFrame, champion_params: dict, sota_hardening: bool = False
) -> dict:
    results = {}
    last_passing = None
    band = champion_params["band_mult"]
    stop = champion_params["stop_mult"]
    reversal = champion_params["require_reversal_bar"]
    regime = champion_params["regime_filter"]

    for tier in COST_TIER_ORDER:
        costs = COST_SWEEP_TIERS[tier]
        try:
            r = _run_vwap(
                df,
                band,
                stop,
                reversal,
                regime,
                commission=costs["commission"],
                slippage_ticks=costs["slippage_ticks"],
                sota_hardening=sota_hardening,
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
    # CRITICAL: DSR and MC-DD use the centralized TRADE-LEVEL metrics, NOT the
    # legacy window-level shortcuts. Feeding the mean of per-window (annualized)
    # Sharpes to the deflation produces a fake dsr~1.0 that auto-passes the ALT
    # floor -- the exact mis-certification fixed engine-wide on 2026-06-26
    # (deflated_sharpe degenerate fix + _gate_v2_trade_metrics migration).
    # trade_level_dsr deflates the actual per-trade return series; trade_level_
    # mc_95th_dd runs a permutation MC on the concatenated OOS trade PnLs.
    from backtest._gate_v2_trade_metrics import trade_level_dsr, trade_level_mc_95th_dd

    oos_pfs = [r.profit_factor for r in oos_results if r.total_trades >= MIN_OOS_TRADES_PER_WINDOW]
    all_trades = sum(r.total_trades for r in oos_results)

    pf_ci_lower = _bootstrap_pf_ci_lower(oos_pfs)
    p_edge = float(sum(1 for pf in oos_pfs if pf > 1.0) / max(1, len(oos_pfs)))
    mc_95th_dd = trade_level_mc_95th_dd(oos_results, initial_capital=CAPITAL)
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


def run_wfo(sota_hardening: bool = False) -> dict:
    if sota_hardening:
        print("[MES-VWAP-R1] SOTA EXECUTION-REALISM HARDENING ENABLED (gap stops, pessimistic "
              "tie-break, vol-scaled slippage, POV impact, margin cap).")
    data_dir = engine_root / "backtest" / "cache"
    data_file = _find_data_file(data_dir)

    print(f"[MES-VWAP-R1] Loading {data_file.name} ...")
    df = _load_data(data_file)
    print(f"[MES-VWAP-R1] {len(df)} bars | {df.index.min().date()} -> {df.index.max().date()}")

    windows = _generate_windows(df)
    if not windows:
        print("[MES-VWAP-R1] ERROR: not enough data to form WFO windows.")
        return {}

    grid = list(
        itertools.product(
            BAND_MULT_VALUES,
            STOP_MULT_VALUES,
            REQUIRE_REVERSAL_VALUES,
            REGIME_FILTER_VALUES,
        )
    )
    n_combos = len(grid)  # = 36

    print(f"\n{'=' * 70}")
    print("=== MES VWAP REVERSION RANK 1 - GATE v2 (legacy WFE REJECTED, WFE=0.02) ===")
    print(
        f"Windows: {len(windows)} | Train: {TRAIN_MONTHS}mo | Test: {TEST_MONTHS}mo | Step: {STEP_MONTHS}mo"
    )
    print(f"Grid: {n_combos} combos")
    print(f"  band_mult            : {BAND_MULT_VALUES}")
    print(f"  stop_mult            : {STOP_MULT_VALUES}")
    print(f"  require_reversal_bar : {REQUIRE_REVERSAL_VALUES}")
    print(f"  regime_filter        : {REGIME_FILTER_VALUES}")
    print(f"  capital              : ${CAPITAL:,.0f}  (ALT path - matches MES rank11 paper config)")
    print(f"  multiplier           : ${MULTIPLIER:.1f}/point  (MES Micro E-mini S&P 500)")
    print(
        f"ALT thresholds: dsr>={GATE_DSR_ALT}, wfo in {GATE_WFO_CONSISTENCY_VALUES}, "
        f"fixed>={GATE_FIXED_PARAMS_MIN_PF}, mc_dd<={GATE_MC_DD_ALT * 100:.0f}%"
    )
    print("PRIOR VWAP result (legacy WFE, 2026-04-02):")
    print("  REJECTED  WFE=0.0196  2/5 OOS windows profitable  avg OOS PF=1.167")
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

        best_params, is_result = _best_is_params(df_train, grid, sota_hardening=sota_hardening)
        if best_params is None:
            print(f"  [SKIP] No valid IS params (all combos < {MIN_OOS_TRADES_PER_WINDOW} trades)")
            continue

        pf_disp = (
            f"{is_result.profit_factor:.2f}" if is_result.profit_factor != float("inf") else "inf"
        )
        print(
            f"  Best IS: band={best_params['band_mult']}  "
            f"stop={best_params['stop_mult']}  "
            f"rev={best_params['require_reversal_bar']}  "
            f"reg={best_params['regime_filter']}  "
            f"PF={pf_disp}  trades={is_result.total_trades}"
        )

        try:
            oos_result = _run_vwap(
                df_test,
                band_mult=best_params["band_mult"],
                stop_mult=best_params["stop_mult"],
                require_reversal_bar=best_params["require_reversal_bar"],
                regime_filter=best_params["regime_filter"],
                sota_hardening=sota_hardening,
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
        print("\n[MES-VWAP-R1] No OOS results - WFO aborted.")
        return {}

    # Fixed-params sweep on full dataset
    print(f"\n[MES-VWAP-R1] Fixed-params sweep on full dataset ({n_combos} combos)...")
    fixed_params_metrics = _run_fixed_params_sweep(df, grid, sota_hardening=sota_hardening)
    print(
        f"  fixed_params_min_pf  = {fixed_params_metrics['fixed_params_min_pf']:.4f}  "
        f"(need >= {GATE_FIXED_PARAMS_MIN_PF})"
    )

    # Cost sweep using most-selected champion params
    param_votes = Counter(
        (
            r["best_params"]["band_mult"],
            r["best_params"]["stop_mult"],
            r["best_params"]["require_reversal_bar"],
            r["best_params"]["regime_filter"],
        )
        for r in window_records
    )
    most_selected = param_votes.most_common(1)[0][0] if param_votes else (2.5, 0.5, False, True)
    champion_params = {
        "band_mult": most_selected[0],
        "stop_mult": most_selected[1],
        "require_reversal_bar": most_selected[2],
        "regime_filter": most_selected[3],
    }
    print(f"\n[MES-VWAP-R1] Cost sweep (champion: {champion_params})...")
    cost_sweep_metrics = _run_cost_sweep(df, champion_params, sota_hardening=sota_hardening)
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
    verdict_file = verdicts_dir / "MES_vwap_rank1.json"

    now_iso = datetime.now(tz=timezone.utc).isoformat()
    verdict_doc = {
        "symbol": SYMBOL,
        "family": "vwap",
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
            "grid_band_mult": BAND_MULT_VALUES,
            "grid_stop_mult": STOP_MULT_VALUES,
            "grid_require_reversal_bar": REQUIRE_REVERSAL_VALUES,
            "grid_regime_filter": REGIME_FILTER_VALUES,
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
            "note": "MES VWAP reversion; backtest sizing only",
        },
        "lineage": {
            "family": "vwap",
            "rank": 1,
            "predecessor": None,
            "rationale": "VWAP deviation reversion on MES 1h. Legacy WFE validator REJECTED (WFE=0.0196, 2/5 OOS windows profitable). This is the gate-v2 verdict for direct comparison with the M2K Donchian/ORB candidates run in the same funnel pass.",
            "legacy_wfe_status": "REJECTED (WFE=0.0196, 2026-04-02)",
            "mes_trend_status": "PASS via alt (rank11) - portfolio anchor",
            "mgc_trend_status": "PASS via alt (rank4) - portfolio anchor",
        },
    }

    # Provenance (2026-09-17 audit): record which cache produced this verdict.
    from backtest._gate_v2_helpers import inject_cache_provenance as _inject_prov  # noqa: E402
    verdict_doc = _inject_prov(verdict_doc, data_file)
    verdict_file.write_text(json.dumps(verdict_doc, indent=2, default=str))
    print(f"\n[MES-VWAP-R1] Verdict written -> {verdict_file}")
    return verdict_doc


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    import argparse

    parser = argparse.ArgumentParser(description="MES VWAP Reversion Rank1 gate-v2 validation")
    parser.add_argument(
        "--sota",
        action="store_true",
        help="Enable SOTA execution-realism hardening (gap stops, pessimistic "
        "tie-break, vol-scaled slippage, POV impact, margin cap). Default: off "
        "(baseline behavior, byte-identical to pre-hardening runs).",
    )
    args = parser.parse_args()

    verdict = run_wfo(sota_hardening=args.sota)
    if not verdict:
        print("[MES-VWAP-R1] No verdict produced.")
        sys.exit(1)

    final = verdict.get("verdict", "FAIL")
    passed_via = verdict.get("passed_via")
    gate = verdict.get("gate_v2_metrics", {})

    if final == "PASS" and passed_via == "core":
        print("\n[PASS-CORE] MES VWAP Rank 1 PASSES gate v2 (CORE path).")
        print("  SURPRISE: VWAP reversion alive under gate-v2 despite legacy WFE REJECT.")
        champ = verdict.get("champion_params", {})
        print(f"  CHAMPION: {champ}")
    elif final == "PASS" and passed_via == "alt":
        print("\n[PASS-ALT] MES VWAP Rank 1 PASSES gate v2 (ALT path - $50K+ accounts).")
        print("  SURPRISE: VWAP reversion alive under gate-v2 despite legacy WFE REJECT.")
        champ = verdict.get("champion_params", {})
        print(f"  CHAMPION: {champ}")
    else:
        print("\n[FAIL] MES VWAP Rank 1 FAILS gate v2.")
        dsr_val = gate.get("dsr", 0.0)
        p_edge = gate.get("p_edge", 0.0)
        pf_ci = gate.get("pf_ci_lower", 0.0)
        wfo = gate.get("wfo_consistency", "WEAK")
        fpmf = gate.get("fixed_params_min_pf", 0.0)

        if pf_ci < GATE_PF_CI_LOWER:
            print(f"  pf_ci_lower={pf_ci:.4f} below {GATE_PF_CI_LOWER} - OOS PF too variable")
        if p_edge < GATE_P_EDGE:
            print(f"  p_edge={p_edge:.4f} below {GATE_P_EDGE} - <95% of OOS windows profitable")
        if dsr_val < GATE_DSR_ALT:
            print(f"  dsr={dsr_val:.6f} below ALT floor {GATE_DSR_ALT}")
        if wfo not in GATE_WFO_CONSISTENCY_VALUES:
            print(f"  wfo_consistency={wfo} - VWAP reversion shows regime instability")
        if fpmf < GATE_FIXED_PARAMS_MIN_PF:
            print(f"  fixed_params_min_pf={fpmf:.4f} - no param set wins consistently")
        print("  VWAP reversion confirmed dead on MES under gate-v2 (corroborates legacy WFE).")


if __name__ == "__main__":
    main()
