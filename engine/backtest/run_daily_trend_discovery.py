#!/usr/bin/env python
"""
Daily-Timeframe Trend Discovery — Gate v2 Validation (discovery batch 1)

WHY THIS BATCH (honest rationale):
The full gate-v2 verdict ledger (38 verdicts) shows the ONLY validated edge is
trend-following on MGC (gold) and MES (S&P), all at the 1-HOUR timeframe. Every
other family — meanrev, donchian, ORB, gap, initial-balance, TPO, confluence,
VIX-filter — FAILS, most with pf_ci_lower < 1.0. The one lower-TF attempt
(MES_trend_15m) failed badly (mc_dd 23.6%).

The TEXTBOOK home of trend-following is the *higher* timeframe (daily), where
slower bars suppress intrabar noise and capture the persistent drift that makes
trend systems work. That regime is COMPLETELY UNTESTED in this repo, yet daily
data goes back to 2022 (4+ years — more history than any 1h set). This batch
asks one clean question: does the proven SMA-trend recipe replicate / improve at
the daily timeframe on the two instruments where it already passes at 1h?

DESIGN: reuses the EXACT validated gate-v2 machinery from
run_mgc_trend_rv_filter_rank1.py (signal gen, IS grid search, OOS WFO,
fixed-params sweep, cost sweep, gate computation) — only the config (timeframe,
SMA periods, WFO window lengths) and I/O are new. RV filter DISABLED
(min_rv_annualized=0.0) for a pure trend read.

Runs fully offline against cached daily CSVs. No IB, no engine, no live state.
Verdicts written to this worktree's data/gate_v2_verdicts/ (isolated from live).

Usage (from engine/ directory, with the MAIN checkout's venv):
    <main>/engine/.venv/Scripts/python.exe backtest/run_daily_trend_discovery.py
"""
from __future__ import annotations

import itertools
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np  # noqa: F401  (used indirectly via reused helpers)

engine_root = Path(__file__).parent.parent
if str(engine_root) not in sys.path:
    sys.path.insert(0, str(engine_root))

# Reuse the proven, already-validated gate-v2 runner as a function library.
import backtest.run_mgc_trend_rv_filter_rank1 as M  # noqa: E402
from backtest._constants import GATE_FIXED_PARAMS_MIN_PF  # noqa: E402
from backtest._gate_v2_helpers import (  # noqa: E402
    GATE_DSR,
    GATE_DSR_ALT,
    GATE_MC_DD_ALT,
    GATE_MC_DD_CORE,
    GATE_P_EDGE,
    GATE_PF_CI_LOWER,
)

# ---------------------------------------------------------------------------
# MAIN-checkout cache (this worktree has no cached CSVs — they are gitignored).
# ---------------------------------------------------------------------------
MAIN_CACHE = Path(r"C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\backtest\cache")

# Verdicts land in THIS worktree (experimental — must not touch live authorization).
VERDICTS_DIR = engine_root / "data" / "gate_v2_verdicts"

# ---------------------------------------------------------------------------
# Daily-trend configuration (theory-motivated; classic daily SMA trend).
# ---------------------------------------------------------------------------
SHARED = dict(
    capital=50_000.0,
    # Probe (full-sample) showed SMA(50,200) daily fires only 2 entries in 4yr.
    # Faster daily periods (fast 5-20 / slow 20-40) are the only ones that trade
    # at all; even these yield just 8-14 trades over the FULL 4yr. Shorter WFO
    # windows maximize the number of OOS windows to give the sample its best shot.
    train_months=12,
    test_months=3,
    step_months=3,
    fast_values=[5, 10],
    slow_values=[20, 40],
    atr_trail_values=[2.0],
    min_oos_trades_per_window=1,
)

# Daily 4yr CSVs (longest history available), explicit to force daily TF.
INSTRUMENTS = [
    dict(symbol="MES", multiplier=5.0, tick_size=0.25, commission=0.62,
         slippage_ticks=2.0, data_file="MES_2022-01-01_2026-03-28_1d.csv",
         desc="Micro E-mini S&P 500 (daily)"),
    dict(symbol="MGC", multiplier=10.0, tick_size=0.10, commission=0.62,
         slippage_ticks=2.0, data_file="MGC_2022-01-01_2026-03-28_1d.csv",
         desc="Micro Gold (daily)"),
]

# Minimum total OOS trades for the verdict to be sample-trustworthy.
MIN_TOTAL_OOS_TRADES = 30


def _apply_config(inst: dict) -> None:
    """Override the reused module's globals for this instrument/timeframe."""
    M.SYMBOL = inst["symbol"]
    M.MULTIPLIER = inst["multiplier"]
    M.TICK_SIZE = inst["tick_size"]
    M.CAPITAL = SHARED["capital"]
    M.COMMISSION = inst["commission"]
    M.SLIPPAGE_TICKS = inst["slippage_ticks"]
    M.TRAIN_MONTHS = SHARED["train_months"]
    M.TEST_MONTHS = SHARED["test_months"]
    M.STEP_MONTHS = SHARED["step_months"]
    M.FAST_PERIOD_VALUES = SHARED["fast_values"]
    M.SLOW_PERIOD_VALUES = SHARED["slow_values"]
    M.ATR_TRAIL_MULT_VALUES = SHARED["atr_trail_values"]
    M.MIN_RV_ANNUALIZED = 0.0  # disable RV filter — pure trend read
    M.MIN_OOS_TRADES_PER_WINDOW = SHARED["min_oos_trades_per_window"]


def run_one(inst: dict) -> dict:
    _apply_config(inst)
    sym = inst["symbol"]
    tag = f"{sym}-DAILY"
    data_file = MAIN_CACHE / inst["data_file"]
    if not data_file.exists():
        print(f"[{tag}] ERROR: cache file missing: {data_file}")
        return {}

    print(f"\n{'#' * 72}")
    print(f"# {sym} DAILY TREND DISCOVERY — {inst['desc']}")
    print(f"# data: {data_file.name}")
    print(f"{'#' * 72}")

    df = M._load_data(data_file)
    print(f"[{tag}] {len(df)} bars | {df.index.min().date()} -> {df.index.max().date()}")

    windows = M._generate_windows(df)
    if not windows:
        print(f"[{tag}] ERROR: not enough data to form windows.")
        return {}

    grid = list(itertools.product(
        SHARED["fast_values"], SHARED["slow_values"], SHARED["atr_trail_values"]))
    n_combos = len(grid)
    print(f"[{tag}] {len(windows)} windows | {n_combos} grid combos | "
          f"train={SHARED['train_months']}mo test={SHARED['test_months']}mo")

    oos_results, window_records = [], []
    for win in windows:
        wnum = win["window_num"]
        ts, te = win["train_start"], win["train_end"]
        os_, oe = win["test_start"], win["test_end"]
        df_train = df[(df.index >= ts) & (df.index < te)].copy()
        df_test = df[(df.index >= os_) & (df.index <= oe)].copy()

        best_params, is_result = M._best_is_params(df_train, grid)
        if best_params is None:
            print(f"  W{wnum} OOS {os_:%Y-%m}->{oe:%Y-%m}: [SKIP] no valid IS params")
            continue
        try:
            oos_result = M._run_signals_and_backtest(
                df_test, fast=best_params["fast"], slow=best_params["slow"],
                atr_trail_mult=best_params["atr_trail_mult"],
                commission=inst["commission"], slippage_ticks=inst["slippage_ticks"])
        except Exception as exc:
            print(f"  W{wnum}: [SKIP] OOS error: {exc}")
            continue
        print(f"  W{wnum} IS {ts:%Y-%m}->{te:%Y-%m} (f{best_params['fast']}/s{best_params['slow']} "
              f"PF={is_result.profit_factor:.2f} n={is_result.total_trades})  "
              f"OOS {os_:%Y-%m}->{oe:%Y-%m} PF={oos_result.profit_factor:.2f} "
              f"DD={oos_result.max_drawdown_pct:.1%} n={oos_result.total_trades}")
        oos_results.append(oos_result)
        window_records.append({
            "window": wnum,
            "is_period": f"{ts:%Y-%m}->{te:%Y-%m}",
            "oos_period": f"{os_:%Y-%m}->{oe:%Y-%m}",
            "best_params": best_params,
            "is_pf": round(is_result.profit_factor, 3),
            "is_trades": is_result.total_trades,
            "oos_pf": round(oos_result.profit_factor, 3),
            "oos_dd": round(oos_result.max_drawdown_pct, 4),
            "oos_sharpe": round(oos_result.sharpe_ratio, 3),
            "oos_trades": oos_result.total_trades,
        })

    if not oos_results:
        print(f"[{tag}] No OOS results — WFO aborted (daily too slow / sample-starved).")
        return {}

    print(f"[{tag}] fixed-params sweep ...")
    fixed_params_metrics = M._run_fixed_params_sweep(df, grid)
    param_votes = Counter(
        (r["best_params"]["fast"], r["best_params"]["slow"], r["best_params"]["atr_trail_mult"])
        for r in window_records)
    most_selected = param_votes.most_common(1)[0][0] if param_votes else (50, 200, 3.0)
    champion_params = {"fast": most_selected[0], "slow": most_selected[1],
                       "atr_trail_mult": most_selected[2]}
    print(f"[{tag}] cost sweep (champion {champion_params}) ...")
    cost_sweep_metrics = M._run_cost_sweep(df, champion_params)

    gate = M._compute_gate_v2(
        oos_results, n_grid_combos=n_combos,
        fixed_params_metrics=fixed_params_metrics,
        cost_sweep_metrics=cost_sweep_metrics)

    total_oos = gate["total_oos_trades"]
    sample_ok = total_oos >= MIN_TOTAL_OOS_TRADES
    final_verdict = gate["verdict"]
    if not sample_ok and final_verdict == "PASS":
        final_verdict = "INSUFFICIENT_SAMPLE"

    print(f"\n{'=' * 72}")
    print(f"=== {sym} DAILY TREND — GATE v2: {final_verdict} "
          f"(raw {gate['verdict']} via {gate['passed_via'] or 'NONE'}) ===")
    print(f"  pf_ci_lower = {gate['pf_ci_lower']:.4f} (>= {GATE_PF_CI_LOWER})")
    print(f"  p_edge      = {gate['p_edge']:.4f} (>= {GATE_P_EDGE})")
    print(f"  mc_95th_dd  = {gate['mc_95th_dd_pct']:.4f}% (<= {GATE_MC_DD_CORE*100:.0f}% core / {GATE_MC_DD_ALT*100:.0f}% alt)")
    print(f"  dsr         = {gate['dsr']:.4f} (>= {GATE_DSR} core / {GATE_DSR_ALT} alt)")
    print(f"  wfo         = {gate['wfo_consistency']}")
    print(f"  fixed_min_pf= {gate['fixed_params_min_pf']:.4f} (>= {GATE_FIXED_PARAMS_MIN_PF})")
    print(f"  cost_through= {gate['cost_survives_through']}")
    print(f"  OOS trades  = {total_oos} across {gate['n_oos_windows_with_trades']}/{gate['n_oos_windows']} windows  "
          f"(sample {'OK' if sample_ok else 'INSUFFICIENT, need >= ' + str(MIN_TOTAL_OOS_TRADES)})")
    print(f"{'=' * 72}")

    verdict_doc = {
        "symbol": sym,
        "family": "trend_daily",
        "rank": 1,
        "timeframe": "1d",
        "verdict": final_verdict,
        "raw_gate_verdict": gate["verdict"],
        "passed_via": gate["passed_via"],
        "core_verdict": gate["core_verdict"],
        "alt_verdict": gate["alt_verdict"],
        "sample_sufficient": sample_ok,
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
        "discovery_batch": "daily-trend-discovery-2026-06-12",
        "rationale": "untested higher-TF home of trend-following; daily 4yr history",
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
        },
        "gate_v2": {
            "core_reasons": gate["core_reasons"],
            "alt_reasons": gate["alt_reasons"],
        },
        "wfo_config": {
            "train_months": SHARED["train_months"],
            "test_months": SHARED["test_months"],
            "step_months": SHARED["step_months"],
            "n_windows": len(windows),
            "n_oos_windows": gate["n_oos_windows"],
            "n_oos_windows_with_trades": gate["n_oos_windows_with_trades"],
            "total_oos_trades": total_oos,
            "grid_combos": n_combos,
            "grid_fast_period": SHARED["fast_values"],
            "grid_slow_period": SHARED["slow_values"],
            "grid_atr_trail_mult": SHARED["atr_trail_values"],
            "rv_filter": "disabled (min_rv_annualized=0)",
        },
        "champion_params": champion_params,
        "windows": window_records,
        "data_file": inst["data_file"],
        "multiplier": inst["multiplier"],
    }

    VERDICTS_DIR.mkdir(parents=True, exist_ok=True)
    out = VERDICTS_DIR / f"{sym}_trend_daily_rank1.json"
    out.write_text(json.dumps(verdict_doc, indent=2, default=str))
    print(f"[{tag}] verdict -> {out}")
    return verdict_doc


def main() -> None:
    results = []
    for inst in INSTRUMENTS:
        try:
            v = run_one(inst)
            if v:
                results.append(v)
        except Exception as exc:  # noqa: BLE001
            import traceback
            print(f"[{inst['symbol']}-DAILY] FATAL: {exc}")
            traceback.print_exc()

    print(f"\n{'#' * 72}")
    print("# DAILY TREND DISCOVERY — SUMMARY")
    print(f"{'#' * 72}")
    for v in results:
        m = v["gate_v2_metrics"]
        print(f"  {v['symbol']:4s} {v['verdict']:20s} "
              f"pf_ci={m['pf_ci_lower']:.3f} p_edge={m['p_edge']:.3f} "
              f"dd={m['mc_95th_dd_pct']:.2f}% dsr={m['dsr']:.3f} "
              f"wfo={m['wfo_consistency']:8s} oos_trades={v['wfo_config']['total_oos_trades']}")
    if not results:
        print("  (no verdicts produced)")


if __name__ == "__main__":
    main()
