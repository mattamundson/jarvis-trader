#!/usr/bin/env python
"""
MNQ Trend + RV-Filter -- THRESHOLD SWEEP (research, not production)

Derived from the original `run_mnq_trend_rv_filter_rank1.py` (generation-engine
Experiment 1, 2026-05-30; commit 71c6962 on unmerged branch
origin/worktree-generation-engine -- the verdict JSON was later deleted at
4963a39 without ever being merged to master). That run used
MIN_RV_ANNUALIZED=9.0, explicitly noted as "adopted from MES 36-trade
analysis; MNQ has NO prior RV sample -- threshold is a hypothesis, not
MNQ-calibrated." This script reruns the identical WFO/gate-v2 harness across
a grid of MIN_RV_ANNUALIZED values to see whether an MNQ-calibrated threshold
clears gate v2 where the inherited MES value (9.0) did not.

Everything else (grid scale, WFO window config, cost tiers, gate thresholds,
data source) is IDENTICAL to the original script -- only MIN_RV_ANNUALIZED
varies, controlled via the RV_THRESHOLD env var. Verdicts are written to a
SCRATCH directory (JARVIS_VERDICTS_DIR), never to engine/data/gate_v2_verdicts/
-- this is read-only research, not a production gate-v2 update.

Usage (from engine/ directory):
    RV_THRESHOLD=7.0 JARVIS_VERDICTS_DIR=<scratch> .venv/Scripts/python backtest/run_mnq_rv_threshold_sweep.py
"""
from __future__ import annotations

import itertools
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

engine_root = Path(os.environ.get("JARVIS_ENGINE_ROOT", str(Path(__file__).parent.parent)))
if str(engine_root) not in sys.path:
    sys.path.insert(0, str(engine_root))

# ---------------------------------------------------------------------------
# Constants (identical to original run_mnq_trend_rv_filter_rank1.py)
# ---------------------------------------------------------------------------

SYMBOL = "MNQ"
MULTIPLIER = 2.0
CAPITAL = 50_000.0  # ALT-routing convention; $10K floors MNQ to 0 contracts
TICK_SIZE = 0.25
COMMISSION = 0.62
SLIPPAGE_TICKS = 2.0

TRAIN_MONTHS = 6
TEST_MONTHS = 3
STEP_MONTHS = 3

FAST_PERIOD_VALUES = [20, 25, 30]
SLOW_PERIOD_VALUES = [80, 100, 120]
ATR_TRAIL_MULT_VALUES = [2.0]

# THE SWEPT PARAMETER (only change from the original script)
MIN_RV_ANNUALIZED = float(os.environ.get("RV_THRESHOLD", "9.0"))

COST_SWEEP_TIERS = {
    "optimistic": {"commission": 0.31, "slippage_ticks": 1.0},
    "realistic": {"commission": 0.62, "slippage_ticks": 2.0},
    "pessimistic": {"commission": 1.24, "slippage_ticks": 3.0},
    "catastrophic": {"commission": 2.48, "slippage_ticks": 4.0},
}

MIN_OOS_TRADES_PER_WINDOW = 1

CACHE_DIR = Path(os.environ.get("JARVIS_CACHE_DIR", str(engine_root / "backtest" / "cache")))
VERDICTS_DIR = Path(
    os.environ.get("JARVIS_VERDICTS_DIR", str(engine_root / "data" / "gate_v2_verdicts_SCRATCH"))
)


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
            best_params = {"fast": fast, "slow": slow, "atr_trail_mult": atr_trail_mult}
            best_result = result
    return best_params, best_result


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
)
from backtest._gate_v2_helpers import bootstrap_pf_ci_lower as _bootstrap_pf_ci_lower  # noqa: E402
from backtest._gate_v2_helpers import (  # noqa: E402
    classify_wfo_consistency as _classify_wfo_consistency,
)


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
            results[tier] = {"pf": round(pf, 4), "trades": result.total_trades, "passes": passes}
            if passes:
                last_surviving = tier
        except Exception as exc:
            print(f"  [WARN] cost-sweep error at {tier}: {exc}")
            results[tier] = {"pf": 0.0, "trades": 0, "passes": False}
    return {"cost_survives_through": last_surviving or "none", "tier_results": results}


def _compute_gate_v2(
    oos_results: list,
    n_grid_combos: int,
    fixed_params_metrics: dict,
    cost_sweep_metrics: dict,
) -> dict:
    from backtest.deflated_sharpe import deflated_sharpe_ratio

    oos_pfs = [r.profit_factor for r in oos_results if r.total_trades >= MIN_OOS_TRADES_PER_WINDOW]
    oos_dds = [r.max_drawdown_pct for r in oos_results]
    oos_sharpes = [
        r.sharpe_ratio for r in oos_results if r.total_trades >= MIN_OOS_TRADES_PER_WINDOW
    ]
    all_trades = sum(r.total_trades for r in oos_results)

    pf_ci_lower = _bootstrap_pf_ci_lower(oos_pfs)
    p_edge = float(sum(1 for pf in oos_pfs if pf > 1.0) / max(1, len(oos_pfs)))
    mc_95th_dd = float(np.percentile(oos_dds, 95.0)) if oos_dds else 1.0

    mean_sharpe = float(np.mean(oos_sharpes)) if oos_sharpes else 0.0
    n_obs = max(all_trades, 30)
    dsr_result = deflated_sharpe_ratio(sharpe=mean_sharpe, n_trials=n_grid_combos, n_obs=n_obs)
    dsr = dsr_result.get("dsr", 0.0) if isinstance(dsr_result, dict) else float(dsr_result)

    wfo_consistency = _classify_wfo_consistency(oos_pfs)
    fixed_params_min_pf = fixed_params_metrics.get("fixed_params_min_pf", 0.0)
    cost_survives_through = cost_sweep_metrics.get("cost_survives_through", "none")

    cost_tier_idx = (
        COST_TIER_ORDER.index(cost_survives_through)
        if cost_survives_through in COST_TIER_ORDER
        else -1
    )
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
        and fixed_params_min_pf >= GATE_FIXED_PARAMS_MIN_PF
        and cost_passes
        and mc_95th_dd <= GATE_MC_DD_ALT
    )

    n_core_passed = sum(
        [
            pf_ci_lower >= GATE_PF_CI_LOWER,
            p_edge >= GATE_P_EDGE,
            mc_95th_dd <= GATE_MC_DD_CORE,
            dsr >= GATE_DSR,
        ]
    )
    n_alt_passed = sum(
        [
            dsr >= GATE_DSR_ALT,
            wfo_consistency in GATE_WFO_CONSISTENCY_VALUES,
            fixed_params_min_pf >= GATE_FIXED_PARAMS_MIN_PF,
            cost_passes,
            mc_95th_dd <= GATE_MC_DD_ALT,
        ]
    )

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
    }


def run_wfo() -> dict:
    from backtest._gate_v2_helpers import _find_latest_cache

    data_file_override = os.environ.get("JARVIS_DATA_FILE")
    if data_file_override:
        data_file = Path(data_file_override)
        if not data_file.is_absolute():
            data_file = CACHE_DIR / data_file
    else:
        data_file = _find_latest_cache(CACHE_DIR, "MNQ")
    print(f"[MNQ-RV-SWEEP th={MIN_RV_ANNUALIZED}] Selected {data_file.name}")
    df = _load_data(data_file)
    print(f"[MNQ-RV-SWEEP th={MIN_RV_ANNUALIZED}] {len(df)} bars | {df.index.min().date()} -> {df.index.max().date()}")

    windows = _generate_windows(df)
    if not windows:
        print("[MNQ-RV-SWEEP] ERROR: not enough data to form windows.")
        return {}

    grid = list(itertools.product(FAST_PERIOD_VALUES, SLOW_PERIOD_VALUES, ATR_TRAIL_MULT_VALUES))
    n_combos = len(grid)

    oos_results = []
    window_records = []

    for win in windows:
        wnum = win["window_num"]
        ts, te = win["train_start"], win["train_end"]
        os_, oe = win["test_start"], win["test_end"]
        df_train = df[(df.index >= ts) & (df.index < te)].copy()
        df_test = df[(df.index >= os_) & (df.index <= oe)].copy()

        best_params, is_result = _best_is_params(df_train, grid)
        if best_params is None:
            print(f"  Window {wnum}: [SKIP] No valid IS params")
            continue
        try:
            oos_result = _run_signals_and_backtest(
                df_test,
                fast=best_params["fast"],
                slow=best_params["slow"],
                atr_trail_mult=best_params["atr_trail_mult"],
            )
        except Exception as exc:
            print(f"  Window {wnum}: [SKIP] OOS error: {exc}")
            continue

        print(
            f"  Window {wnum}: IS best={best_params}  OOS PF={oos_result.profit_factor:.2f} "
            f"DD={oos_result.max_drawdown_pct:.1%} trades={oos_result.total_trades}"
        )
        oos_results.append(oos_result)
        window_records.append(
            {
                "window": wnum,
                "best_params": best_params,
                "oos_pf": round(oos_result.profit_factor, 3),
                "oos_dd": round(oos_result.max_drawdown_pct, 4),
                "oos_trades": oos_result.total_trades,
            }
        )

    if not oos_results:
        print(f"\n[MNQ-RV-SWEEP th={MIN_RV_ANNUALIZED}] No OOS results — degenerate (RV filter too aggressive).")
        return {
            "symbol": SYMBOL,
            "family": "trend_rv_filter",
            "min_rv_annualized": MIN_RV_ANNUALIZED,
            "verdict": "FAIL",
            "passed_via": None,
            "degenerate": True,
            "created_at": datetime.now(tz=timezone.utc).isoformat(),
            "note": "no OOS trades at this threshold",
        }

    fixed_params_metrics = _run_fixed_params_sweep(df, grid)

    param_votes = Counter(
        (r["best_params"]["fast"], r["best_params"]["slow"], r["best_params"]["atr_trail_mult"])
        for r in window_records
    )
    most_selected = param_votes.most_common(1)[0][0] if param_votes else (25, 100, 2.0)
    champion_params = {
        "fast": most_selected[0],
        "slow": most_selected[1],
        "atr_trail_mult": most_selected[2],
    }
    cost_sweep_metrics = _run_cost_sweep(df, champion_params)

    gate = _compute_gate_v2(
        oos_results,
        n_grid_combos=n_combos,
        fixed_params_metrics=fixed_params_metrics,
        cost_sweep_metrics=cost_sweep_metrics,
    )

    print(f"\n{'=' * 70}")
    print(f"=== MNQ RV-FILTER th={MIN_RV_ANNUALIZED}%  VERDICT: {gate['verdict']} (via {gate['passed_via'] or 'NONE'}) ===")
    print(f"  pf_ci_lower          = {gate['pf_ci_lower']:.4f}  (need >= {GATE_PF_CI_LOWER})")
    print(f"  p_edge               = {gate['p_edge']:.4f}  (need >= {GATE_P_EDGE})")
    print(f"  mc_95th_dd           = {gate['mc_95th_dd_pct']:.4f}%  (need <= {GATE_MC_DD_CORE*100:.0f}% core / {GATE_MC_DD_ALT*100:.0f}% alt)")
    print(f"  dsr                  = {gate['dsr']:.6f}  (need >= {GATE_DSR} core / {GATE_DSR_ALT} alt)")
    print(f"  wfo_consistency      = {gate['wfo_consistency']}")
    print(f"  fixed_params_min_pf  = {gate['fixed_params_min_pf']:.4f}  (need >= {GATE_FIXED_PARAMS_MIN_PF})")
    print(f"  cost_survives_through= {gate['cost_survives_through']}")
    print(f"  n_core_passed        = {gate['n_core_passed']}/4   n_alt_passed = {gate['n_alt_passed']}/5")
    print(f"  Total OOS trades     = {gate['total_oos_trades']}  ({gate['n_oos_windows_with_trades']}/{gate['n_oos_windows']} windows with trades)")
    print(f"{'=' * 70}")

    VERDICTS_DIR.mkdir(parents=True, exist_ok=True)
    th_tag = str(MIN_RV_ANNUALIZED).replace(".", "p")
    verdict_file = VERDICTS_DIR / f"MNQ_trend_rv_filter_th{th_tag}.json"
    verdict_doc = {
        "symbol": SYMBOL,
        "family": "trend_rv_filter",
        "min_rv_annualized": MIN_RV_ANNUALIZED,
        "verdict": gate["verdict"],
        "passed_via": gate["passed_via"],
        "core_verdict": gate["core_verdict"],
        "alt_verdict": gate["alt_verdict"],
        "n_core_passed": gate["n_core_passed"],
        "n_alt_passed": gate["n_alt_passed"],
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
        "gate_v2_metrics": {
            "pf_ci_lower": gate["pf_ci_lower"],
            "p_edge": gate["p_edge"],
            "mc_95th_dd_pct": gate["mc_95th_dd_pct"],
            "dsr": gate["dsr"],
            "wfo_consistency": gate["wfo_consistency"],
            "fixed_params_min_pf": gate["fixed_params_min_pf"],
            "fixed_params_mean_pf": gate["fixed_params_mean_pf"],
            "fixed_params_max_pf": gate["fixed_params_max_pf"],
            "cost_survives_through": gate["cost_survives_through"],
            "combo_results": fixed_params_metrics.get("combo_results", []),
        },
        "champion_params": champion_params,
        "windows": window_records,
        "data_file": data_file.name,
    }
    # Provenance (2026-09-17 audit): record which cache produced this verdict.
    from backtest._gate_v2_helpers import inject_cache_provenance as _inject_prov  # noqa: E402
    verdict_doc = _inject_prov(verdict_doc, data_file)
    verdict_file.write_text(json.dumps(verdict_doc, indent=2, default=str))
    print(f"[MNQ-RV-SWEEP th={MIN_RV_ANNUALIZED}] Verdict written -> {verdict_file}")
    return verdict_doc


def main():
    verdict = run_wfo()
    if not verdict:
        sys.exit(1)


if __name__ == "__main__":
    main()
