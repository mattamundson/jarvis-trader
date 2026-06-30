#!/usr/bin/env python
"""
MCL Gate v2 Re-validation — Hypothesis C: Vol-Regime Gate

Walk-forward validation of the Bollinger+RSI mean-reversion strategy on MCL
(micro crude oil 1h) with an RV-band regime filter.

Background: MCL's first-pass mean-rev attempt (commit c4a1ef1) produced
PF 0.855 / 254 trades. Post-mortem: trend-day chop killed edge. Hypothesis C
adds a realized-volatility band gate to the existing module, suppressing entries
during trending (high-RV) and ultra-thin (low-RV) regimes.

Gate v2 thresholds to beat:
    pf_ci_lower  >= 1.10   (bootstrap 95% CI lower bound on OOS PF)
    p_edge       >= 0.95   (fraction of OOS windows with PF > 1.0)
    mc_95th_dd   <= 0.05   (95th-pct OOS max drawdown as fraction)
    dsr          >= 0.10   (deflated Sharpe ratio)

Usage (from engine/ directory):
    .venv/Scripts/python backtest/run_mcl_hypothesis_c.py
    .venv/Scripts/python backtest/run_mcl_hypothesis_c.py --fast
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

# Ensure engine root is on sys.path when called as a script
engine_root = Path(__file__).parent.parent
if str(engine_root) not in sys.path:
    sys.path.insert(0, str(engine_root))

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SYMBOL = "MCL"
MULTIPLIER = 100.0  # MCL = 100 barrels × $0.01/tick = $1/tick
CAPITAL = 10_000.0
TICK_SIZE = 0.01
COMMISSION = 0.85  # $/contract round-trip (IB micro futures typical)
SLIPPAGE_TICKS = 1.0

TRAIN_MONTHS = 6
TEST_MONTHS = 1
STEP_MONTHS = 1

# Hypothesis C parameter grid
# Full grid: 3×3×3 = 27 combos; --fast reduces to a representative 9
RV_MIN_VALUES = [20.0, 25.0, 30.0]
RV_MAX_VALUES = [40.0, 45.0, 50.0]
RV_LOOKBACK_VALUES = [15, 20, 30]

# Fast grid: a representative 9-point subset
FAST_RV_MIN = [20.0, 25.0, 30.0]
FAST_RV_MAX = [40.0, 50.0]
FAST_RV_LOOKBACK = [15, 20]

# BB + RSI params fixed to MEANREV_PARAMS["MCL"] defaults
BB_PERIOD = 20
BB_STD = 2.0
RSI_PERIOD = 14
RSI_LONG = 30.0
RSI_SHORT = 70.0
STOP_ATR_MULT = 1.5

# Gate v2 thresholds

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
    rv_min: float,
    rv_max: float,
    rv_lookback: int,
) -> BacktestResult:  # noqa: F821 - lazy: imported inside fn body
    from backtest.backtester import Backtester
    from backtest.meanrev_signals import generate_bollinger_rsi_signals

    df_sig = generate_bollinger_rsi_signals(
        df,
        bb_period=BB_PERIOD,
        bb_std=BB_STD,
        rsi_period=RSI_PERIOD,
        rsi_long=RSI_LONG,
        rsi_short=RSI_SHORT,
        stop_atr_mult=STOP_ATR_MULT,
        regime_filter_mode="rv_band",
        regime_filter_min_rv=rv_min,
        regime_filter_max_rv=rv_max,
        regime_filter_rv_lookback=rv_lookback,
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


def _best_is_params(
    df_train: pd.DataFrame, grid: list[tuple]
) -> tuple[dict, BacktestResult] | tuple[None, None]:  # noqa: F821
    """Grid-search on IS data; return (best_params_dict, best_result)."""
    best_pf = -1.0
    best_params = None
    best_result = None

    for rv_min, rv_max, rv_lb in grid:
        if rv_min >= rv_max:
            continue
        try:
            result = _run_signals_and_backtest(df_train, rv_min, rv_max, rv_lb)
        except Exception as exc:
            print(f"    [WARN] IS error ({rv_min},{rv_max},{rv_lb}): {exc}")
            continue
        if result.total_trades < MIN_OOS_TRADES_PER_WINDOW:
            continue
        pf = result.profit_factor
        if pf > best_pf:
            best_pf = pf
            best_params = {"rv_min": rv_min, "rv_max": rv_max, "rv_lookback": rv_lb}
            best_result = result

    return best_params, best_result


# ---------------------------------------------------------------------------
# Gate v2 metrics
# ---------------------------------------------------------------------------

from backtest._gate_v2_helpers import (  # noqa: E402
    GATE_DSR,
    GATE_MC_DD_ALT,
    GATE_MC_DD_CORE,
    GATE_P_EDGE,
    GATE_PF_CI_LOWER,
    _find_latest_cache,  # noqa: E402
)  # noqa: E402
from backtest._gate_v2_helpers import bootstrap_pf_ci_lower as _bootstrap_pf_ci_lower  # noqa: E402


def _compute_gate_v2(oos_results: list[BacktestResult], n_grid_combos: int) -> dict:  # noqa: F821
    """Compute all four gate v2 metrics from OOS BacktestResult objects."""
    from backtest._gate_v2_trade_metrics import trade_level_dsr

    oos_pfs = [r.profit_factor for r in oos_results if r.total_trades >= MIN_OOS_TRADES_PER_WINDOW]
    oos_dds = [r.max_drawdown_pct for r in oos_results]
    all_trades = sum(r.total_trades for r in oos_results)

    pf_ci_lower = _bootstrap_pf_ci_lower(oos_pfs)
    p_edge = float(sum(1 for pf in oos_pfs if pf > 1.0) / max(1, len(oos_pfs)))
    mc_95th_dd = float(np.percentile(oos_dds, 95.0)) if oos_dds else 1.0

    # DSR: use mean OOS Sharpe, all OOS bars combined as T, N = grid size
    # DSR from the ACTUAL per-trade OOS return series, not the mean of per-window
    # Sharpes (a 1-2 trade window's giant Sharpe deflated to a fake ~1.0 and
    # auto-passed both gate floors). See _gate_v2_trade_metrics for the why.
    dsr = trade_level_dsr(oos_results, n_grid_combos=n_grid_combos, initial_capital=CAPITAL)

    core_pass = (
        pf_ci_lower >= GATE_PF_CI_LOWER
        and p_edge >= GATE_P_EDGE
        and mc_95th_dd <= GATE_MC_DD_CORE
        and dsr >= GATE_DSR
    )
    alt_pass = (
        pf_ci_lower >= GATE_PF_CI_LOWER
        and p_edge >= GATE_P_EDGE
        and mc_95th_dd <= GATE_MC_DD_ALT
        and dsr >= GATE_DSR
    )

    verdict = "PASS" if core_pass else ("PASS_ALT" if alt_pass else "FAIL")

    return {
        "pf_ci_lower": round(pf_ci_lower, 4),
        "p_edge": round(p_edge, 4),
        "mc_95th_dd": round(mc_95th_dd, 6),
        "dsr": round(dsr, 4),
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


def run_wfo(fast: bool = False) -> dict:
    data_dir = engine_root / "backtest" / "cache"
    data_file = _find_latest_cache(data_dir, "MCL")
    print(f"[MCL-WFO] Selected {data_file.name}")

    print(f"[MCL-WFO] Loading {data_file.name} ...")
    df = _load_data(data_file)
    print(f"[MCL-WFO] {len(df)} bars | {df.index.min().date()} -> {df.index.max().date()}")

    windows = _generate_windows(df)
    if not windows:
        print("[MCL-WFO] ERROR: not enough data to form windows.")
        return {}

    # Build parameter grid
    if fast:
        rv_min_vals = FAST_RV_MIN
        rv_max_vals = FAST_RV_MAX
        rv_lb_vals = FAST_RV_LOOKBACK
    else:
        rv_min_vals = RV_MIN_VALUES
        rv_max_vals = RV_MAX_VALUES
        rv_lb_vals = RV_LOOKBACK_VALUES

    grid = list(itertools.product(rv_min_vals, rv_max_vals, rv_lb_vals))
    n_combos = len(grid)

    print(f"\n{'=' * 65}")
    print(f"=== MCL HYPOTHESIS C WFO ({'fast' if fast else 'full'} grid) ===")
    print(f"Windows: {len(windows)} | Train: {TRAIN_MONTHS}mo | Test: {TEST_MONTHS}mo")
    print(f"Grid: {n_combos} combos  RV_MIN={rv_min_vals}  RV_MAX={rv_max_vals}  LB={rv_lb_vals}")
    print(f"{'=' * 65}")

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
            f"  Best IS: rv_min={best_params['rv_min']}  rv_max={best_params['rv_max']}  "
            f"lookback={best_params['rv_lookback']}  "
            f"PF={is_result.profit_factor:.2f}  trades={is_result.total_trades}"
        )

        try:
            oos_result = _run_signals_and_backtest(
                df_test,
                rv_min=best_params["rv_min"],
                rv_max=best_params["rv_max"],
                rv_lookback=best_params["rv_lookback"],
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
        print("\n[MCL-WFO] No OOS results — WFO aborted.")
        return {}

    # Gate v2 verdict
    gate = _compute_gate_v2(oos_results, n_grid_combos=n_combos)

    print(f"\n{'=' * 65}")
    print(f"=== GATE v2 VERDICT: {gate['verdict']} ===")
    print(f"  pf_ci_lower = {gate['pf_ci_lower']:.3f}  (need >= {GATE_PF_CI_LOWER})")
    print(f"  p_edge      = {gate['p_edge']:.3f}  (need >= {GATE_P_EDGE})")
    print(
        f"  mc_95th_dd  = {gate['mc_95th_dd']:.3%}  (need <= {GATE_MC_DD_CORE:.0%} core / {GATE_MC_DD_ALT:.0%} alt)"
    )
    print(f"  dsr         = {gate['dsr']:.4f}  (need >= {GATE_DSR})")
    print(
        f"  OOS windows = {gate['n_oos_windows_with_trades']} with trades / {gate['n_oos_windows']} total"
    )
    print(f"  Total OOS trades = {gate['total_oos_trades']}")
    print(f"{'=' * 65}")

    # Write verdict JSON
    verdicts_dir = engine_root / "data" / "gate_v2_verdicts"
    verdicts_dir.mkdir(parents=True, exist_ok=True)
    ts_str = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    verdict_file = verdicts_dir / f"MCL_hyp_c_{ts_str}.json"

    verdict_doc = {
        "symbol": "MCL",
        "family": "mean_reversion",
        "rank": "hypothesis_c_rv_band",
        "verdict": gate["verdict"],
        "core_verdict": gate["core_verdict"],
        "alt_verdict": gate["alt_verdict"],
        "passed_via": (
            "core"
            if gate["core_verdict"] == "PASS"
            else ("alt" if gate["alt_verdict"] == "PASS" else None)
        ),
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
        "params": {
            "bb_period": BB_PERIOD,
            "bb_std": BB_STD,
            "rsi_period": RSI_PERIOD,
            "rsi_long": RSI_LONG,
            "rsi_short": RSI_SHORT,
            "stop_atr_mult": STOP_ATR_MULT,
            "regime_filter_mode": "rv_band",
        },
        "wfo_config": {
            "train_months": TRAIN_MONTHS,
            "test_months": TEST_MONTHS,
            "step_months": STEP_MONTHS,
            "n_windows": len(windows),
            "n_oos_windows": gate["n_oos_windows"],
            "grid_combos": n_combos,
            "fast_grid": fast,
        },
        "gate_v2_metrics": {
            "pf_ci_lower": gate["pf_ci_lower"],
            "p_edge": gate["p_edge"],
            "mc_95th_dd": gate["mc_95th_dd"],
            "dsr": gate["dsr"],
        },
        "thresholds": {
            "pf_ci_lower": GATE_PF_CI_LOWER,
            "p_edge": GATE_P_EDGE,
            "mc_95th_dd_core": GATE_MC_DD_CORE,
            "mc_95th_dd_alt": GATE_MC_DD_ALT,
            "dsr": GATE_DSR,
        },
        "windows": window_records,
        "aux_freshness": {
            "data_file": data_file.name,
            "n_total_oos_trades": gate["total_oos_trades"],
        },
        "n_core_passed": 1 if gate["core_verdict"] == "PASS" else 0,
        "n_alt_passed": 1 if gate["alt_verdict"] == "PASS" else 0,
    }

    verdict_file.write_text(json.dumps(verdict_doc, indent=2, default=str))
    print(f"\n[MCL-WFO] Verdict written -> {verdict_file}")

    return verdict_doc


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="MCL Hypothesis C Gate v2 WFO")
    parser.add_argument(
        "--fast",
        action="store_true",
        help="Use reduced grid (9 combos vs 27) for faster iteration",
    )
    args = parser.parse_args()

    verdict = run_wfo(fast=args.fast)

    if not verdict:
        print("[MCL-WFO] No verdict produced — check data/logs above.")
        sys.exit(1)

    final = verdict.get("verdict", "FAIL")
    if final == "PASS":
        print("\n[PASS] Hypothesis C PASSES gate v2 (CORE).")
        print("  Next: remove MCL from DO_NOT_TRADE_SYMBOLS in signals.py:108")
    elif final == "PASS_ALT":
        print("\n[PASS-ALT] Hypothesis C PASSES gate v2 (ALT routing only -- $50K+ accounts).")
        print("  Next: decide whether to ungate under ALT constraints.")
    else:
        print("\n[FAIL] Hypothesis C FAILS gate v2.")
        gate = verdict.get("gate_v2_metrics", {})
        thresholds = verdict.get("thresholds", {})
        for metric, needed_key in [
            ("pf_ci_lower", "pf_ci_lower"),
            ("p_edge", "p_edge"),
            ("mc_95th_dd", "mc_95th_dd_core"),
            ("dsr", "dsr"),
        ]:
            val = gate.get(metric, 0)
            threshold = thresholds.get(needed_key, "?")
            status = "PASS" if _check_metric(metric, val, thresholds) else "FAIL"
            print(f"  {status} {metric}: {val:.4f} (need {threshold})")
        print("  Next: document failure metrics in project_mcl_revalidation_options memo.")


def _check_metric(metric: str, val: float, thresholds: dict) -> bool:
    if metric == "pf_ci_lower":
        return val >= thresholds.get("pf_ci_lower", 1.10)
    if metric == "p_edge":
        return val >= thresholds.get("p_edge", 0.95)
    if metric == "mc_95th_dd":
        return val <= thresholds.get("mc_95th_dd_core", 0.05)
    if metric == "dsr":
        return val >= thresholds.get("dsr", 0.10)
    return False


if __name__ == "__main__":
    main()
