#!/usr/bin/env python
"""
MNQ Breakout Gate v2 — Rank 5 $25K Capital Test (Position-Sizer Rounding Artifact)

# Rank5: $25K capital to test position-sizer rounding artifact from rank4

Context:
    Rank 4 ran with CAPITAL=25_000 and produced FAIL:
        pf_ci_lower  = 0.7317  (need >= 1.10)
        p_edge       = 0.3571  (need >= 0.95)
        mc_95th_dd   = 3.58%   (PASSES <= 7% ALT)
        dsr          = 0.0     (need >= 0.10)
        wfo_consistency = WEAK
        fixed_params_min_pf = 1.2621 (PASSES >= 1.20) ✅

    Task context suggested rank4 used $10K (where position sizer rounds to 0-2 contracts).
    Rank5 explicitly validates the $25K hypothesis using the SAME 6-combo tight grid:
        donchian=[18,20,22] x stop_atr_mult=[2.0,2.25]

    This is a clean re-run with:
        initial_capital = 25,000
        same tight grid as rank4
        output -> MNQ_breakout_rank5.json

    If WFO metrics remain WEAK at $25K, the capital-sizing artifact hypothesis is
    disproved and the issue is structural (MNQ 2H-2025 regime break, not sizing).

Rank 4 baseline (FAIL):
    pf_ci_lower         = 0.7317  (need >= 1.10)
    p_edge              = 0.3571  (need >= 0.95)
    mc_95th_dd          = 3.58%   (PASSES <= 7% ALT)
    dsr                 = 0.0     (need >= 0.10)
    wfo_consistency     = WEAK
    fixed_params_min_pf = 1.2621  (PASSES >= 1.20) ✅

ALT gate v2 thresholds (all must pass):
    pf_ci_lower         >= 1.10
    p_edge              >= 0.95
    mc_95th_dd          <= 0.07
    dsr                 >= 0.10
    fixed_params_min_pf >= 1.20
    wfo_consistency     in [MODERATE, STRONG]

Usage (from engine/ directory):
    .venv/Scripts/python backtest/run_mnq_breakout_rank5.py
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

SYMBOL = "MNQ"
MULTIPLIER = 2.0  # $2 per point (Micro Nasdaq)
# Rank5: $25K capital to test position-sizer rounding artifact from rank4.
# At $10K, stop_atr_mult=2.0 causes rounding to 0-2 contracts (stop risk > 1%).
# At $25K, sizing yields 3-5 contracts per trade -> better OOS representation.
CAPITAL = 25_000.0
TICK_SIZE = 0.25
COMMISSION = 0.62  # $/contract round-trip (IB micro futures)
SLIPPAGE_TICKS = 2.0

TRAIN_MONTHS = 6
TEST_MONTHS = 1
STEP_MONTHS = 1

# Same 6-combo tight grid as rank4 — donchian=[18,20,22] x stop_atr_mult=[2.0,2.25]
# Rank3 lesson: stop_atr_mult=1.75 produces PF~0.44, drags min_pf below 1.20.
# Rank4 lesson: this grid passes fixed_params_min_pf (1.2621 >= 1.20) but WFO is WEAK.
DONCHIAN_PERIOD_VALUES = [18, 20, 22]
STOP_ATR_MULT_VALUES = [2.0, 2.25]

# Fixed params
VOL_MULT = 0.0  # DISABLED — rank 2 proved vol_mult >= 1.5 kills all OOS signal
VOL_MA_PERIOD = 20

# Gate v2 thresholds

# ALT-specific thresholds

MIN_OOS_TRADES_PER_WINDOW = 5


# ---------------------------------------------------------------------------
# Helpers
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


def _run_signals_and_backtest(
    df: pd.DataFrame,
    donchian_period: int,
    stop_atr_mult: float,
) -> object:
    from backtest.backtester import Backtester
    from backtest.breakout_signals import generate_donchian_breakout_signals

    df_sig = generate_donchian_breakout_signals(
        df,
        donchian_period=donchian_period,
        vol_ma_period=VOL_MA_PERIOD,
        vol_mult=VOL_MULT,  # 0.0 = disabled
        stop_atr_mult=stop_atr_mult,
    )

    bt = Backtester(
        initial_capital=CAPITAL,
        risk_per_trade=0.01,
        max_daily_loss=0.02,
        max_drawdown=0.05,
        t1_exit_pct=0.50,
        t2_exit_pct=0.30,
        commission_per_contract=COMMISSION,
        slippage_ticks=SLIPPAGE_TICKS,
    )
    return bt.run(df_sig, symbol=SYMBOL, multiplier=MULTIPLIER)


def _best_is_params(df_train: pd.DataFrame, grid: list[tuple]) -> tuple[dict | None, object | None]:
    """Grid-search on IS data; return (best_params_dict, best_result)."""
    best_pf = -1.0
    best_params = None
    best_result = None

    for donchian_period, stop_atr_mult in grid:
        try:
            result = _run_signals_and_backtest(df_train, donchian_period, stop_atr_mult)
        except Exception as exc:
            print(f"    [WARN] IS error ({donchian_period},{stop_atr_mult}): {exc}")
            continue
        if result.total_trades < MIN_OOS_TRADES_PER_WINDOW:
            continue
        pf = result.profit_factor
        if pf > best_pf:
            best_pf = pf
            best_params = {
                "donchian_period": donchian_period,
                "stop_atr_mult": stop_atr_mult,
                "vol_mult": VOL_MULT,
            }
            best_result = result

    return best_params, best_result


# ---------------------------------------------------------------------------
# Gate v2 metrics — including fixed_params sweep for ALT metric
# ---------------------------------------------------------------------------

from backtest._constants import (  # noqa: E402
    GATE_FIXED_PARAMS_MIN_PF,
    GATE_WFO_CONSISTENCY_VALUES,
)
from backtest._gate_v2_helpers import _find_latest_cache  # noqa: E402
from backtest._gate_v2_helpers import bootstrap_pf_ci_lower as _bootstrap_pf_ci_lower  # noqa: E402
from backtest._gate_v2_helpers import (  # noqa: E402
    classify_wfo_consistency as _classify_wfo_consistency,  # noqa: E402
)


def _run_fixed_params_sweep(df: pd.DataFrame, grid: list[tuple]) -> dict:
    """
    Run all grid combos on the FULL dataset with fixed params (no IS/OOS split).
    Returns the minimum PF across all combos — this is fixed_params_min_pf for ALT gate.
    """
    pfs = []
    combo_results = []
    for donchian_period, stop_atr_mult in grid:
        try:
            result = _run_signals_and_backtest(df, donchian_period, stop_atr_mult)
            if result.total_trades >= MIN_OOS_TRADES_PER_WINDOW:
                pfs.append(result.profit_factor)
                combo_results.append(
                    {
                        "donchian_period": donchian_period,
                        "stop_atr_mult": stop_atr_mult,
                        "pf": round(result.profit_factor, 4),
                        "trades": result.total_trades,
                    }
                )
                print(
                    f"    combo ({donchian_period:2d}, {stop_atr_mult:.2f}): "
                    f"PF={result.profit_factor:.4f}  trades={result.total_trades}"
                )
            else:
                print(
                    f"    combo ({donchian_period:2d}, {stop_atr_mult:.2f}): "
                    f"SKIP (only {result.total_trades} trades)"
                )
        except Exception as exc:
            print(f"  [WARN] fixed-params error ({donchian_period},{stop_atr_mult}): {exc}")
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


def _compute_gate_v2(
    oos_results: list,
    n_grid_combos: int,
    fixed_params_metrics: dict,
) -> dict:
    """Compute all gate v2 metrics including ALT-specific fixed_params check."""
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

    # CORE: pf_ci_lower + p_edge + mc_dd_core + dsr
    core_pass = (
        pf_ci_lower >= GATE_PF_CI_LOWER
        and p_edge >= GATE_P_EDGE
        and mc_95th_dd <= GATE_MC_DD_CORE
        and dsr >= GATE_DSR
    )

    # ALT: mc_dd_alt ceiling + fixed_params_min_pf + wfo_consistency in [MODERATE, STRONG]
    alt_pass = (
        pf_ci_lower >= GATE_PF_CI_LOWER
        and p_edge >= GATE_P_EDGE
        and mc_95th_dd <= GATE_MC_DD_ALT
        and dsr >= GATE_DSR
        and fixed_params_min_pf >= GATE_FIXED_PARAMS_MIN_PF
        and wfo_consistency in GATE_WFO_CONSISTENCY_VALUES
    )

    if core_pass:
        verdict = "PASS"
    elif alt_pass:
        verdict = "PASS_ALT"
    else:
        verdict = "FAIL"

    return {
        "pf_ci_lower": round(pf_ci_lower, 4),
        "p_edge": round(p_edge, 4),
        "mc_95th_dd": round(mc_95th_dd, 6),
        "dsr": round(dsr, 4),
        "wfo_consistency": wfo_consistency,
        "fixed_params_min_pf": fixed_params_min_pf,
        "fixed_params_mean_pf": fixed_params_metrics.get("fixed_params_mean_pf", 0.0),
        "fixed_params_max_pf": fixed_params_metrics.get("fixed_params_max_pf", 0.0),
        "n_oos_windows": len(oos_results),
        "n_oos_windows_with_trades": len(oos_pfs),
        "total_oos_trades": all_trades,
        "core_verdict": "PASS" if core_pass else "FAIL",
        "alt_verdict": "PASS" if alt_pass else "FAIL",
        "verdict": verdict,
    }


# ---------------------------------------------------------------------------
# Main WFO loop
# ---------------------------------------------------------------------------


def run_wfo() -> dict:
    # Pick the MNQ 1h cache covering the latest end-date so a refreshed
    # IBKR pull (named MNQ_<start>_<end>_1h.csv) always wins over older files.
    data_dir = engine_root / "backtest" / "cache"
    data_file = _find_latest_cache(data_dir, "MNQ")
    print(f"[MNQ-R5] Selected {data_file.name}")

    print(f"[MNQ-R5] Loading {data_file.name} ...")
    df = _load_data(data_file)
    print(f"[MNQ-R5] {len(df)} bars | {df.index.min().date()} -> {df.index.max().date()}")

    windows = _generate_windows(df)
    if not windows:
        print("[MNQ-R5] ERROR: not enough data to form windows.")
        return {}

    # Same 6-combo tight grid as rank4
    grid = list(itertools.product(DONCHIAN_PERIOD_VALUES, STOP_ATR_MULT_VALUES))
    n_combos = len(grid)

    print(f"\n{'=' * 70}")
    print("=== MNQ BREAKOUT RANK 5 — $25K CAPITAL SIZING ARTIFACT TEST ===")
    print(f"Windows: {len(windows)} | Train: {TRAIN_MONTHS}mo | Test: {TEST_MONTHS}mo")
    print(f"Capital: ${CAPITAL:,.0f} (testing position-sizer rounding artifact hypothesis)")
    print(f"Grid: {n_combos} combos (same tight grid as rank4)")
    print(f"  donchian_period : {DONCHIAN_PERIOD_VALUES}  (consensus: 20)")
    print(f"  stop_atr_mult   : {STOP_ATR_MULT_VALUES}  (consensus: 2.0)")
    print(f"  vol_mult        : {VOL_MULT} (DISABLED — rank 2 lesson)")
    print(f"  vol_ma_period   : {VOL_MA_PERIOD} (fixed, irrelevant)")
    print("Rank 4 baseline  : pf_ci_lower=0.73 p_edge=0.36 wfo=WEAK fixed_min_pf=1.2621")
    print("Rank 5 hypothesis: $25K -> 3-5 contracts/trade -> better OOS representation")
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
            f"  Best IS: donchian={best_params['donchian_period']}  "
            f"stop_atr={best_params['stop_atr_mult']}  "
            f"PF={is_result.profit_factor:.2f}  trades={is_result.total_trades}"
        )

        try:
            oos_result = _run_signals_and_backtest(
                df_test,
                donchian_period=best_params["donchian_period"],
                stop_atr_mult=best_params["stop_atr_mult"],
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
        print("\n[MNQ-R5] No OOS results — WFO aborted.")
        return {}

    # Fixed-params sweep on full dataset (ALT metric)
    print(f"\n[MNQ-R5] Running fixed-params sweep on full dataset ({n_combos} tight combos)...")
    fixed_params_metrics = _run_fixed_params_sweep(df, grid)
    print(
        f"  fixed_params_min_pf  = {fixed_params_metrics['fixed_params_min_pf']:.4f}  "
        f"(need >= {GATE_FIXED_PARAMS_MIN_PF}, rank4 was 1.2621)"
    )
    print(f"  fixed_params_mean_pf = {fixed_params_metrics['fixed_params_mean_pf']:.4f}")
    print(f"  fixed_params_max_pf  = {fixed_params_metrics.get('fixed_params_max_pf', 0):.4f}")
    print(f"  combos with trades   = {fixed_params_metrics['n_combos_with_trades']} / {n_combos}")

    if fixed_params_metrics["fixed_params_min_pf"] >= GATE_FIXED_PARAMS_MIN_PF:
        print("  -> CLEAR: fixed_params_min_pf PASSES ALT threshold!")
    else:
        gap = GATE_FIXED_PARAMS_MIN_PF - fixed_params_metrics["fixed_params_min_pf"]
        print(f"  -> BLOCKED: still {gap:.4f} short of ALT threshold")

    # Gate v2 verdict
    gate = _compute_gate_v2(
        oos_results, n_grid_combos=n_combos, fixed_params_metrics=fixed_params_metrics
    )

    print(f"\n{'=' * 70}")
    print(f"=== GATE v2 VERDICT: {gate['verdict']} ===")
    print(f"  pf_ci_lower          = {gate['pf_ci_lower']:.4f}  (need >= {GATE_PF_CI_LOWER})")
    print(f"  p_edge               = {gate['p_edge']:.4f}  (need >= {GATE_P_EDGE})")
    print(
        f"  mc_95th_dd           = {gate['mc_95th_dd']:.4%}  "
        f"(need <= {GATE_MC_DD_CORE:.0%} core / {GATE_MC_DD_ALT:.0%} alt)"
    )
    print(f"  dsr                  = {gate['dsr']:.4f}  (need >= {GATE_DSR})")
    print(
        f"  wfo_consistency      = {gate['wfo_consistency']}  "
        f"(ALT accepts: {GATE_WFO_CONSISTENCY_VALUES})"
    )
    print(
        f"  fixed_params_min_pf  = {gate['fixed_params_min_pf']:.4f}  "
        f"(need >= {GATE_FIXED_PARAMS_MIN_PF} for ALT, rank4 was 1.2621)"
    )
    print(f"  core_verdict         = {gate['core_verdict']}")
    print(f"  alt_verdict          = {gate['alt_verdict']}")
    print(
        f"  OOS windows          = {gate['n_oos_windows_with_trades']} with trades "
        f"/ {gate['n_oos_windows']} total"
    )
    print(f"  Total OOS trades     = {gate['total_oos_trades']}")
    print(f"{'=' * 70}")

    # Write verdict JSON
    verdicts_dir = engine_root / "data" / "gate_v2_verdicts"
    verdicts_dir.mkdir(parents=True, exist_ok=True)
    verdict_file = verdicts_dir / "MNQ_breakout_rank5.json"

    verdict_doc = {
        "symbol": "MNQ",
        "family": "breakout",
        "rank": 5,
        "verdict": gate["verdict"],
        "core_verdict": gate["core_verdict"],
        "alt_verdict": gate["alt_verdict"],
        "passed_via": (
            "core"
            if gate["core_verdict"] == "PASS"
            else ("alt" if gate["alt_verdict"] == "PASS" else None)
        ),
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
        "params_fixed": {
            "vol_mult": VOL_MULT,
            "vol_ma_period": VOL_MA_PERIOD,
        },
        "wfo_config": {
            "train_months": TRAIN_MONTHS,
            "test_months": TEST_MONTHS,
            "step_months": STEP_MONTHS,
            "n_windows": len(windows),
            "n_oos_windows": gate["n_oos_windows"],
            "grid_combos": n_combos,
            "grid_donchian_period": DONCHIAN_PERIOD_VALUES,
            "grid_stop_atr_mult": STOP_ATR_MULT_VALUES,
            "capital": CAPITAL,
        },
        "gate_v2_metrics": {
            "pf_ci_lower": gate["pf_ci_lower"],
            "p_edge": gate["p_edge"],
            "mc_95th_dd": gate["mc_95th_dd"],
            "dsr": gate["dsr"],
            "wfo_consistency": gate["wfo_consistency"],
            "fixed_params_min_pf": gate["fixed_params_min_pf"],
            "fixed_params_mean_pf": gate["fixed_params_mean_pf"],
            "fixed_params_max_pf": gate["fixed_params_max_pf"],
            "n_combos_with_trades": fixed_params_metrics.get("n_combos_with_trades", 0),
            "combo_results": fixed_params_metrics.get("combo_results", []),
        },
        "thresholds": {
            "pf_ci_lower": GATE_PF_CI_LOWER,
            "p_edge": GATE_P_EDGE,
            "mc_95th_dd_core": GATE_MC_DD_CORE,
            "mc_95th_dd_alt": GATE_MC_DD_ALT,
            "dsr": GATE_DSR,
            "fixed_params_min_pf_alt": GATE_FIXED_PARAMS_MIN_PF,
            "wfo_consistency_alt": GATE_WFO_CONSISTENCY_VALUES,
        },
        "windows": window_records,
        "aux_freshness": {
            "data_file": data_file.name,
            "n_total_oos_trades": gate["total_oos_trades"],
        },
        "lineage": {
            "rank4_pf_ci_lower": 0.7317,
            "rank4_p_edge": 0.3571,
            "rank4_mc_95th_dd_pct": 3.5768,
            "rank4_wfo_consistency": "WEAK",
            "rank4_fixed_params_min_pf": 1.2621,
            "rank4_capital": 25000.0,
            "rank4_fail_reason": (
                "pf_ci_lower=0.73 p_edge=0.36 dsr=0.0 wfo=WEAK — "
                "fixed_params_min_pf passed (1.2621>=1.20); WFO failure structural"
            ),
            "rank5_hypothesis": (
                "$25K capital -> 3-5 contracts/trade -> better OOS representation -> "
                "WFO consistency improves from WEAK to MODERATE/STRONG"
            ),
            "rank5_note": (
                "If WFO metrics unchanged vs rank4, capital-sizing artifact hypothesis "
                "is disproved; issue is structural (MNQ 2H-2025 regime break)"
            ),
            "rank1_pf_ci_lower": 1.0696,
            "rank1_fixed_params_min_pf": 1.186,
            "rank2_lesson": "vol_mult >= 1.5 kills all OOS signal (0 trades); vol filters forbidden",
            "rank3_lesson": "wide grid (4x4=16) pulls down min_pf; tighter stops (0.75-1.0) hurt on MNQ volatility",
            "rank4_strategy": "tight 3x2=6 grid ±10% around consensus; fixed_params passed but WFO WEAK",
        },
    }

    # Provenance (2026-09-17 audit): record which cache produced this verdict.
    from backtest._gate_v2_helpers import inject_cache_provenance as _inject_prov  # noqa: E402
    verdict_doc = _inject_prov(verdict_doc, data_file)
    verdict_file.write_text(json.dumps(verdict_doc, indent=2, default=str))
    print(f"\n[MNQ-R5] Verdict written -> {verdict_file}")

    return verdict_doc


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    verdict = run_wfo()

    if not verdict:
        print("[MNQ-R5] No verdict produced — check data/logs above.")
        sys.exit(1)

    final = verdict.get("verdict", "FAIL")
    gate = verdict.get("gate_v2_metrics", {})

    if final == "PASS":
        print("\n[PASS] MNQ Breakout Rank 5 PASSES gate v2 (CORE).")
        print("  Capital-sizing artifact hypothesis CONFIRMED.")
        print("  Next: remove MNQ from DO_NOT_TRADE_SYMBOLS")
    elif final == "PASS_ALT":
        print("\n[PASS-ALT] MNQ Breakout Rank 5 PASSES gate v2 (ALT — $50K+ accounts).")
        print("  Capital-sizing artifact hypothesis CONFIRMED (partial).")
        print("  Next: decide whether to ungate MNQ under ALT constraints.")
    else:
        print("\n[FAIL] MNQ Breakout Rank 5 FAILS gate v2.")
        print("  Capital-sizing artifact hypothesis DISPROVED.")
        print("  Issue is structural: MNQ 2H-2025 regime break or persistent non-stationarity.")
        wfo = gate.get("wfo_consistency", "?")
        print(f"  WFO consistency: {wfo} (need MODERATE or STRONG for ALT)")
        p_edge = gate.get("p_edge", 0)
        print(f"  p_edge: {p_edge:.4f} (need >= 0.95)")

    # Detailed per-metric report with rank4 deltas
    rank4_metrics = {
        "pf_ci_lower": 0.7317,
        "p_edge": 0.3571,
        "mc_95th_dd": 0.035768,
        "dsr": 0.0,
        "fixed_params_min_pf": 1.2621,
    }

    print("\n  Per-metric vs rank4 delta:")
    checks = [
        ("pf_ci_lower", gate.get("pf_ci_lower", 0), GATE_PF_CI_LOWER, ">="),
        ("p_edge", gate.get("p_edge", 0), GATE_P_EDGE, ">="),
        ("mc_95th_dd (core)", gate.get("mc_95th_dd", 1.0), GATE_MC_DD_CORE, "<="),
        ("mc_95th_dd (alt)", gate.get("mc_95th_dd", 1.0), GATE_MC_DD_ALT, "<="),
        ("dsr", gate.get("dsr", 0), GATE_DSR, ">="),
        ("fixed_params_min_pf", gate.get("fixed_params_min_pf", 0), GATE_FIXED_PARAMS_MIN_PF, ">="),
    ]
    for name, val, threshold, op in checks:
        passes = (val >= threshold) if op == ">=" else (val <= threshold)
        status = "PASS" if passes else "FAIL"
        r4_key = name.replace(" (core)", "").replace(" (alt)", "")
        r4_val = rank4_metrics.get(r4_key)
        if r4_val is not None:
            delta = val - r4_val
            delta_str = f"  (rank4={r4_val:.4f}, delta={delta:+.4f})"
        else:
            delta_str = ""
        print(f"  {status:4s} {name}: {val:.4f} (need {op} {threshold}){delta_str}")

    print(
        f"  WFO consistency: {gate.get('wfo_consistency', '?')} "
        f"(ALT accepts: {GATE_WFO_CONSISTENCY_VALUES})"
    )


if __name__ == "__main__":
    main()
