#!/usr/bin/env python
"""
M2K Donchian Channel Breakout Gate v2 — Rank 1

Hypothesis: Donchian channel breakout (close > N-bar high) captures trend
entries on Russell 2000 micro without the SMA(fast,slow) lag.  M2K SMA trend
family is exhausted (ranks 1-3 all FAIL, 2026-05-24); Donchian is the next
candidate for the momentum/breakout hypothesis.

Method:
  - Grid: ENTRY_LOOKBACKS × EXIT_LOOKBACKS × ATR_TRAIL_MULTS (18 combos: 3×3×2)
  - Walk-forward: 6mo train, 3mo test, 3mo step (3-month OOS to avoid 1-trade coin-flip)
  - Gate v2 CORE path: pf_ci_lower>=1.10, p_edge>=0.95, mc_95th_dd<=5%, dsr>=0.10
  - Gate v2 ALT path:  dsr>=0.30, wfo in [MODERATE, STRONG], fixed_params_min_pf>=1.2,
                       cost_survives>=realistic, mc_95th_dd<=7%

Grid:
  ENTRY_LOOKBACKS  = [15, 20, 25]   (bars to look back for channel high)
  EXIT_LOOKBACKS   = [5, 10, 15]    (bars to look back for channel low exit)
  ATR_TRAIL_MULTS  = [1.5, 2.0]     (stop / target sizing)
  18 combos total

Contract specs:
  M2K (Russell 2000 micro): multiplier=$5.0/point, tick_size=0.10, commission=$0.62

Benchmark: M2K SMA trend exhausted — p_edge=0.50 (rank3), family FAIL.
Writes: engine/data/gate_v2_verdicts/M2K_donchian_rank1.json

Usage (from engine/ directory):
    .venv/Scripts/python backtest/run_m2k_donchian_rank1.py
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
MULTIPLIER = 5.0
CAPITAL = 50_000.0
TICK_SIZE = 0.10
COMMISSION = 0.62
SLIPPAGE_TICKS = 1.0

TRAIN_MONTHS = 6
TEST_MONTHS = 3
STEP_MONTHS = 3

ENTRY_LOOKBACKS = [15, 20, 25]
EXIT_LOOKBACKS = [5, 10, 15]
ATR_TRAIL_MULTS = [1.5, 2.0]

MIN_OOS_TRADES_PER_WINDOW = 1

COST_SWEEP_TIERS = {
    "optimistic": {"commission": 0.31, "slippage_ticks": 0.5},
    "realistic": {"commission": 0.62, "slippage_ticks": 1.0},
    "pessimistic": {"commission": 1.24, "slippage_ticks": 2.0},
    "catastrophic": {"commission": 2.48, "slippage_ticks": 3.0},
}


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def _load_m2k_data(data_dir: Path) -> pd.DataFrame:
    from backtest._gate_v2_helpers import _find_latest_cache

    data_file = _find_latest_cache(data_dir, "M2K")
    print(f"[M2K] Selected {data_file.name}")
    df = pd.read_csv(data_file)
    df.columns = [c.lower() for c in df.columns]
    ts_col = "timestamp" if "timestamp" in df.columns else "datetime"
    df[ts_col] = pd.to_datetime(df[ts_col])
    df = df.set_index(ts_col).sort_index()
    required = {"open", "high", "low", "close"}
    if missing := required - set(df.columns):
        raise ValueError(f"Missing columns: {missing}")
    print(f"[M2K] {len(df)} bars | {df.index.min().date()} -> {df.index.max().date()}")
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
# Signal + backtest
# ---------------------------------------------------------------------------


def _run_signals_and_backtest(
    df: pd.DataFrame,
    lookback_entry: int,
    lookback_exit: int,
    atr_trail_mult: float,
    commission: float = COMMISSION,
    slippage_ticks: float = SLIPPAGE_TICKS,
) -> object:
    from backtest.backtester import Backtester
    from backtest.donchian_signals import generate_donchian_signals

    df_sig = generate_donchian_signals(
        df,
        lookback_entry=lookback_entry,
        lookback_exit=lookback_exit,
        atr_trail_mult=atr_trail_mult,
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


def _best_is_params(
    df_train: pd.DataFrame,
    grid: list[tuple],
) -> tuple[dict | None, object | None]:
    best_pf = -1.0
    best_params = None
    best_result = None

    for entry_lb, exit_lb, atr_mult in grid:
        try:
            result = _run_signals_and_backtest(df_train, entry_lb, exit_lb, atr_mult)
        except Exception as exc:
            print(f"    [WARN] IS error entry={entry_lb} exit={exit_lb} atr={atr_mult}: {exc}")
            continue
        if result.total_trades < MIN_OOS_TRADES_PER_WINDOW:
            continue
        pf = result.profit_factor
        if pf > best_pf:
            best_pf = pf
            best_params = {
                "lookback_entry": entry_lb,
                "lookback_exit": exit_lb,
                "atr_trail_mult": atr_mult,
            }
            best_result = result

    return best_params, best_result


# ---------------------------------------------------------------------------
# Gate v2 helpers
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
)
from backtest._gate_v2_helpers import bootstrap_pf_ci_lower as _bootstrap_pf_ci_lower  # noqa: E402
from backtest._gate_v2_helpers import (  # noqa: E402
    classify_wfo_consistency as _classify_wfo_consistency,
)


def _run_fixed_params_sweep(df: pd.DataFrame, grid: list[tuple]) -> dict:
    pfs = []
    combo_results = []
    for entry_lb, exit_lb, atr_mult in grid:
        try:
            result = _run_signals_and_backtest(df, entry_lb, exit_lb, atr_mult)
            if result.total_trades >= MIN_OOS_TRADES_PER_WINDOW:
                pfs.append(result.profit_factor)
                combo_results.append(
                    {
                        "lookback_entry": entry_lb,
                        "lookback_exit": exit_lb,
                        "atr_trail_mult": atr_mult,
                        "pf": round(result.profit_factor, 4),
                        "trades": result.total_trades,
                    }
                )
                print(
                    f"    entry={entry_lb:2d} exit={exit_lb:2d} atr={atr_mult:.1f}: "
                    f"PF={result.profit_factor:.4f}  trades={result.total_trades}"
                )
            else:
                print(
                    f"    entry={entry_lb:2d} exit={exit_lb:2d} atr={atr_mult:.1f}: "
                    f"SKIP ({result.total_trades} trades)"
                )
        except Exception as exc:
            print(f"  [WARN] fixed-params error entry={entry_lb} exit={exit_lb}: {exc}")

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


def _run_cost_sweep(df: pd.DataFrame, champion: dict) -> dict:
    results = {}
    last_surviving = None
    for tier in COST_TIER_ORDER:
        costs = COST_SWEEP_TIERS[tier]
        try:
            result = _run_signals_and_backtest(
                df,
                lookback_entry=champion["lookback_entry"],
                lookback_exit=champion["lookback_exit"],
                atr_trail_mult=champion["atr_trail_mult"],
                commission=costs["commission"],
                slippage_ticks=costs["slippage_ticks"],
            )
            pf = result.profit_factor
            passes = pf > 1.0 and result.total_trades >= MIN_OOS_TRADES_PER_WINDOW
            results[tier] = {"pf": round(pf, 4), "trades": result.total_trades, "passes": passes}
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
    return {"cost_survives_through": last_surviving or "none", "tier_results": results}


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


# ---------------------------------------------------------------------------
# Main WFO loop
# ---------------------------------------------------------------------------


def run_wfo() -> dict:
    data_dir = engine_root / "backtest" / "cache"
    df = _load_m2k_data(data_dir)

    windows = _generate_windows(df)
    if not windows:
        print("[M2K-DCH-R1] ERROR: not enough data to form windows.")
        return {}

    grid = list(itertools.product(ENTRY_LOOKBACKS, EXIT_LOOKBACKS, ATR_TRAIL_MULTS))
    n_combos = len(grid)

    print(f"\n{'=' * 70}")
    print("=== M2K DONCHIAN RANK 1 — BREAKOUT TREND (LONG ONLY) ===")
    print(
        f"Windows: {len(windows)} | Train: {TRAIN_MONTHS}mo | Test: {TEST_MONTHS}mo "
        f"| Step: {STEP_MONTHS}mo"
    )
    print(f"Grid: {n_combos} combos")
    print(f"  entry_lookback: {ENTRY_LOOKBACKS}")
    print(f"  exit_lookback:  {EXIT_LOOKBACKS}")
    print(f"  atr_trail_mult: {ATR_TRAIL_MULTS}")
    print("Benchmark: M2K SMA trend family exhausted (rank3 p_edge=0.50, FAIL 2026-05-24)")
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

        print(
            f"  Best IS: entry={best_params['lookback_entry']} exit={best_params['lookback_exit']} "
            f"atr={best_params['atr_trail_mult']}  "
            f"PF={is_result.profit_factor:.2f}  trades={is_result.total_trades}"
        )

        try:
            oos_result = _run_signals_and_backtest(
                df_test,
                lookback_entry=best_params["lookback_entry"],
                lookback_exit=best_params["lookback_exit"],
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
        print("\n[M2K-DCH-R1] No OOS results — WFO aborted.")
        return {}

    print(f"\n[M2K-DCH-R1] Fixed-params sweep on full dataset ({n_combos} combos)...")
    fixed_params_metrics = _run_fixed_params_sweep(df, grid)
    print(
        f"  fixed_params_min_pf = {fixed_params_metrics['fixed_params_min_pf']:.4f}  "
        f"(need >= {GATE_FIXED_PARAMS_MIN_PF})"
    )

    param_votes = Counter(
        (
            r["best_params"]["lookback_entry"],
            r["best_params"]["lookback_exit"],
            r["best_params"]["atr_trail_mult"],
        )
        for r in window_records
    )
    most_selected = param_votes.most_common(1)[0][0] if param_votes else (20, 10, 2.0)
    champion = {
        "lookback_entry": most_selected[0],
        "lookback_exit": most_selected[1],
        "atr_trail_mult": most_selected[2],
    }
    print(
        f"\n[M2K-DCH-R1] Cost sweep (champion: entry={champion['lookback_entry']} "
        f"exit={champion['lookback_exit']} atr={champion['atr_trail_mult']})..."
    )
    cost_sweep_metrics = _run_cost_sweep(df, champion)
    print(f"  cost_survives_through = {cost_sweep_metrics['cost_survives_through']}")

    gate = _compute_gate_v2(
        oos_results,
        n_grid_combos=n_combos,
        fixed_params_metrics=fixed_params_metrics,
        cost_sweep_metrics=cost_sweep_metrics,
    )

    print(f"\n{'=' * 70}")
    print(f"=== GATE v2 VERDICT: {gate['verdict']} (via {gate['passed_via'] or 'NONE'}) ===")
    print(f"  p_edge               = {gate['p_edge']:.4f}")
    print(f"  mc_95th_dd           = {gate['mc_95th_dd_pct']:.4f}%")
    print(f"  dsr                  = {gate['dsr']:.6f}")
    print(f"  wfo_consistency      = {gate['wfo_consistency']}")
    print(f"  fixed_params_min_pf  = {gate['fixed_params_min_pf']:.4f}")
    print(f"  cost_survives_through= {gate['cost_survives_through']}")
    print(f"  core_verdict         = {gate['core_verdict']}")
    print(f"  alt_verdict          = {gate['alt_verdict']}")
    print(
        f"  OOS windows          = {gate['n_oos_windows_with_trades']} with trades "
        f"/ {gate['n_oos_windows']} total"
    )
    print(f"  Total OOS trades     = {gate['total_oos_trades']}")
    print(f"{'=' * 70}")

    verdicts_dir = engine_root / "data" / "gate_v2_verdicts"
    verdicts_dir.mkdir(parents=True, exist_ok=True)
    verdict_file = verdicts_dir / "M2K_donchian_rank1.json"

    verdict_doc = {
        "symbol": SYMBOL,
        "family": "donchian",
        "rank": 1,
        "verdict": gate["verdict"],
        "passed_via": gate["passed_via"],
        "core_verdict": gate["core_verdict"],
        "alt_verdict": gate["alt_verdict"],
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
        "champion_params": champion,
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
            "cost_survives_through": gate["cost_survives_through"],
            "cost_tier_results": cost_sweep_metrics.get("tier_results", {}),
            "combo_results": fixed_params_metrics.get("combo_results", []),
        },
        "wfo_config": {
            "train_months": TRAIN_MONTHS,
            "test_months": TEST_MONTHS,
            "step_months": STEP_MONTHS,
            "n_windows": len(windows),
            "n_oos_windows": gate["n_oos_windows"],
            "n_oos_windows_with_trades": gate["n_oos_windows_with_trades"],
            "total_oos_trades": gate["total_oos_trades"],
            "entry_lookbacks": ENTRY_LOOKBACKS,
            "exit_lookbacks": EXIT_LOOKBACKS,
            "atr_trail_mults": ATR_TRAIL_MULTS,
            "n_combos": n_combos,
        },
        "lineage": {
            "benchmark": "M2K_trend_rank3",
            "benchmark_p_edge": 0.50,
            "benchmark_verdict": "FAIL",
            "hypothesis": "Donchian N-bar breakout — M2K SMA trend family exhausted (ranks 1-3 FAIL); "
            "testing if price-level breakout captures momentum without SMA lag penalty",
        },
        "windows": window_records,
    }

    verdict_file.write_text(json.dumps(verdict_doc, indent=2, default=str))
    print(f"\n[M2K-DCH-R1] Verdict written -> {verdict_file}")

    return verdict_doc


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    verdict = run_wfo()
    if not verdict:
        print("[M2K-DCH-R1] No verdict produced.")
        sys.exit(1)

    final = verdict.get("verdict", "FAIL")
    passed_via = verdict.get("passed_via")
    gate = verdict.get("gate_v2_metrics", {})
    p = gate.get("p_edge", "?")

    if final == "PASS" and passed_via == "core":
        print(f"\n[PASS-CORE] M2K Donchian Rank 1 PASSES gate v2 (CORE). p_edge={p}")
    elif final == "PASS" and passed_via == "alt":
        print(f"\n[PASS-ALT] M2K Donchian Rank 1 PASSES gate v2 (ALT). p_edge={p}")
    else:
        print(f"\n[FAIL] M2K Donchian Rank 1 FAILS gate v2. p_edge={p}")
        wfo = gate.get("wfo_consistency", "?")
        fmin = gate.get("fixed_params_min_pf", "?")
        print(f"  wfo_consistency={wfo}  fixed_params_min_pf={fmin}")

    print(f"  Champion params: {verdict.get('champion_params')}")


if __name__ == "__main__":
    main()
