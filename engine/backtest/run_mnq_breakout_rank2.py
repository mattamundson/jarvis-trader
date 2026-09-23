#!/usr/bin/env python
"""
MNQ Breakout Gate v2 — Rank 2 Targeted Sweep

Tightened grid around the Donchian-channel breakout strategy for MNQ
(Micro Nasdaq, $2/pt, 1h bars). Rank 1 verdict missed core by:
    pf_ci_lower   : 1.0696  (need >= 1.10)
    fixed_params_min_pf : 1.186 (need >= 1.20)
    mc_95th_dd    : 5.29%   (passes ALT at <= 7%; misses CORE at <= 5%)

Rank 2 hypothesis: higher volume-confirmation threshold (vol_mult >= 1.5)
filters lower-conviction breakouts, raising PF.  Sweep donchian_period and
stop_atr_mult simultaneously to keep grid under 30 combos.

Usage (from engine/ directory):
    .venv/Scripts/python backtest/run_mnq_breakout_rank2.py
    .venv/Scripts/python backtest/run_mnq_breakout_rank2.py --fast
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

engine_root = Path(__file__).parent.parent
if str(engine_root) not in sys.path:
    sys.path.insert(0, str(engine_root))

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SYMBOL = "MNQ"
MULTIPLIER = 2.0  # $2 per point (Micro Nasdaq)
CAPITAL = 10_000.0
TICK_SIZE = 0.25
COMMISSION = 0.62  # $/contract round-trip (IB micro futures)
SLIPPAGE_TICKS = 2.0

TRAIN_MONTHS = 6
TEST_MONTHS = 1
STEP_MONTHS = 1

# Rank 2 targeted grid — three params, 3×3×3 = 27 combos full / 12 fast
# donchian_period: tighter (15) and wider (25) around baseline 20
DONCHIAN_PERIOD_VALUES = [15, 20, 25]
# vol_mult: baseline was 1.0; push toward quality with 1.5 / 2.0
VOL_MULT_VALUES = [1.0, 1.5, 2.0]
# stop_atr_mult: tighter stop (1.5) and same (2.0) and slightly wider (2.5)
STOP_ATR_MULT_VALUES = [1.5, 2.0, 2.5]

# Fixed param
VOL_MA_PERIOD = 20

# Fast grid: 2×2×3 = 12 combos — most-promising quadrant
FAST_DONCHIAN = [15, 20]
FAST_VOL_MULT = [1.5, 2.0]
FAST_STOP_ATR = [1.5, 2.0, 2.5]

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
    donchian_period: int,
    vol_mult: float,
    stop_atr_mult: float,
) -> BacktestResult:  # noqa: F821 - lazy: imported inside fn body
    from backtest.backtester import Backtester
    from backtest.breakout_signals import generate_donchian_breakout_signals

    df_sig = generate_donchian_breakout_signals(
        df,
        donchian_period=donchian_period,
        vol_ma_period=VOL_MA_PERIOD,
        vol_mult=vol_mult,
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

    for donchian_period, vol_mult, stop_atr_mult in grid:
        try:
            result = _run_signals_and_backtest(df_train, donchian_period, vol_mult, stop_atr_mult)
        except Exception as exc:
            print(f"    [WARN] IS error ({donchian_period},{vol_mult},{stop_atr_mult}): {exc}")
            continue
        if result.total_trades < MIN_OOS_TRADES_PER_WINDOW:
            continue
        pf = result.profit_factor
        if pf > best_pf:
            best_pf = pf
            best_params = {
                "donchian_period": donchian_period,
                "vol_mult": vol_mult,
                "stop_atr_mult": stop_atr_mult,
            }
            best_result = result

    return best_params, best_result


# ---------------------------------------------------------------------------
# Gate v2 metrics
# ---------------------------------------------------------------------------

from backtest._gate_v2_helpers import _find_latest_cache  # noqa: E402
from backtest._gate_v2_helpers import bootstrap_pf_ci_lower as _bootstrap_pf_ci_lower  # noqa: E402


def _compute_gate_v2(oos_results: list, n_grid_combos: int) -> dict:
    """Compute all four gate v2 metrics from OOS BacktestResult objects."""
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
    # Pick the MNQ 1h cache covering the latest end-date so a refreshed
    # IBKR pull (named MNQ_<start>_<end>_1h.csv) always wins over older files.
    data_dir = engine_root / "backtest" / "cache"
    data_file = _find_latest_cache(data_dir, "MNQ")
    print(f"[MNQ-WFO] Selected {data_file.name}")

    print(f"[MNQ-WFO] Loading {data_file.name} ...")
    df = _load_data(data_file)
    print(f"[MNQ-WFO] {len(df)} bars | {df.index.min().date()} -> {df.index.max().date()}")

    windows = _generate_windows(df)
    if not windows:
        print("[MNQ-WFO] ERROR: not enough data to form windows.")
        return {}

    # Build parameter grid
    if fast:
        donchian_vals = FAST_DONCHIAN
        vol_mult_vals = FAST_VOL_MULT
        stop_atr_vals = FAST_STOP_ATR
    else:
        donchian_vals = DONCHIAN_PERIOD_VALUES
        vol_mult_vals = VOL_MULT_VALUES
        stop_atr_vals = STOP_ATR_MULT_VALUES

    grid = list(itertools.product(donchian_vals, vol_mult_vals, stop_atr_vals))
    n_combos = len(grid)

    print(f"\n{'=' * 70}")
    print(f"=== MNQ BREAKOUT RANK 2 WFO ({'fast' if fast else 'full'} grid) ===")
    print(f"Windows: {len(windows)} | Train: {TRAIN_MONTHS}mo | Test: {TEST_MONTHS}mo")
    print(f"Grid: {n_combos} combos")
    print(f"  donchian_period : {donchian_vals}")
    print(f"  vol_mult        : {vol_mult_vals}")
    print(f"  stop_atr_mult   : {stop_atr_vals}")
    print(f"  vol_ma_period   : {VOL_MA_PERIOD} (fixed)")
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
            f"vol_mult={best_params['vol_mult']}  "
            f"stop_atr={best_params['stop_atr_mult']}  "
            f"PF={is_result.profit_factor:.2f}  trades={is_result.total_trades}"
        )

        try:
            oos_result = _run_signals_and_backtest(
                df_test,
                donchian_period=best_params["donchian_period"],
                vol_mult=best_params["vol_mult"],
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
        print("\n[MNQ-WFO] No OOS results — WFO aborted.")
        return {}

    # Gate v2 verdict
    gate = _compute_gate_v2(oos_results, n_grid_combos=n_combos)

    print(f"\n{'=' * 70}")
    print(f"=== GATE v2 VERDICT: {gate['verdict']} ===")
    print(f"  pf_ci_lower = {gate['pf_ci_lower']:.4f}  (need >= {GATE_PF_CI_LOWER})")
    print(f"  p_edge      = {gate['p_edge']:.4f}  (need >= {GATE_P_EDGE})")
    print(
        f"  mc_95th_dd  = {gate['mc_95th_dd']:.4%}  (need <= {GATE_MC_DD_CORE:.0%} core / {GATE_MC_DD_ALT:.0%} alt)"
    )
    print(f"  dsr         = {gate['dsr']:.4f}  (need >= {GATE_DSR})")
    print(
        f"  OOS windows = {gate['n_oos_windows_with_trades']} with trades / {gate['n_oos_windows']} total"
    )
    print(f"  Total OOS trades = {gate['total_oos_trades']}")
    print(f"{'=' * 70}")

    # Write verdict JSON
    verdicts_dir = engine_root / "data" / "gate_v2_verdicts"
    verdicts_dir.mkdir(parents=True, exist_ok=True)
    verdict_file = verdicts_dir / "MNQ_breakout_rank2.json"

    verdict_doc = {
        "symbol": "MNQ",
        "family": "breakout",
        "rank": 2,
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
            "vol_ma_period": VOL_MA_PERIOD,
        },
        "wfo_config": {
            "train_months": TRAIN_MONTHS,
            "test_months": TEST_MONTHS,
            "step_months": STEP_MONTHS,
            "n_windows": len(windows),
            "n_oos_windows": gate["n_oos_windows"],
            "grid_combos": n_combos,
            "fast_grid": fast,
            "grid_donchian_period": donchian_vals,
            "grid_vol_mult": vol_mult_vals,
            "grid_stop_atr_mult": stop_atr_vals,
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
        "rank1_comparison": {
            "rank1_pf_ci_lower": 1.0696,
            "rank1_fixed_params_min_pf": 1.186,
            "rank1_mc_95th_dd_pct": 5.2917,
            "rank2_gap_to_close": "pf_ci_lower (+0.0304) and fixed_params_min_pf (+0.014)",
        },
    }

<<<<<<< HEAD
=======
    # Provenance (2026-09-17 audit): record which cache produced this verdict.
    from backtest._gate_v2_helpers import inject_cache_provenance as _inject_prov  # noqa: E402
    verdict_doc = _inject_prov(verdict_doc, data_file)
>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2
    verdict_file.write_text(json.dumps(verdict_doc, indent=2, default=str))
    print(f"\n[MNQ-WFO] Verdict written -> {verdict_file}")

    return verdict_doc


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


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


def main():
    parser = argparse.ArgumentParser(description="MNQ Breakout Rank 2 Gate v2 WFO")
    parser.add_argument(
        "--fast",
        action="store_true",
        help="Use reduced grid (12 combos vs 27) for faster iteration",
    )
    args = parser.parse_args()

    verdict = run_wfo(fast=args.fast)

    if not verdict:
        print("[MNQ-WFO] No verdict produced — check data/logs above.")
        sys.exit(1)

    final = verdict.get("verdict", "FAIL")
    if final == "PASS":
        print("\n[PASS] MNQ Breakout Rank 2 PASSES gate v2 (CORE).")
        print("  Next: remove MNQ from DO_NOT_TRADE_SYMBOLS in signals.py")
    elif final == "PASS_ALT":
        print("\n[PASS-ALT] MNQ Breakout Rank 2 PASSES gate v2 (ALT — $50K+ accounts).")
        print("  Next: decide whether to ungate under ALT constraints.")
    else:
        print("\n[FAIL] MNQ Breakout Rank 2 FAILS gate v2.")
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


if __name__ == "__main__":
    main()
