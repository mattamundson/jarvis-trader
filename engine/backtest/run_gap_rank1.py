#!/usr/bin/env python
"""
RTH-Gap Gate v2 Validation -- GENERATION-ENGINE EXPERIMENT 4.

First `gap` family ever run through gate v2 (the 56-verdict ledger has only
trend/breakout/orb/donchian/mean_reversion/tpo). Sourced from the Corey Gapfinder
study (gapfinder.py / corey_gapfinder_v1) -- a study that ships as VISUAL-ONLY in the
engine (no gap edge has ever been tested mechanically). Tests whether the RTH
overnight-gap structure is a real, gate-v2-grade edge on MES / MGC.

THE GAP IS RTH-DEFINED (see gap_signals.py): today's RTH open vs YESTERDAY's RTH
close, overnight excluded. Two near-inverse mechanical readings, selected by GAP_MODE:
  fade (default) -- gap up -> SHORT toward fill; gap down -> LONG toward fill.
  go             -- continuation: gap up -> LONG; gap down -> SHORT.

Swept gate-v2 parameter: min_gap_pct in {0.0015, 0.0025, 0.0040} (IS selection,
fixed-params sweep, DSR n_trials). Signals from gap_signals.generate_gap_signals,
which RTH-filters and uses the PRIOR session's RTH close (no look-ahead).
$50K ALT capital (the $10K sizer floors to 0 contracts -- MNQ artifact 2026-05-30).

Usage (from engine/, live deps + data via env):
    JARVIS_ENGINE_ROOT=<live engine>  JARVIS_CACHE_DIR=...  JARVIS_VERDICTS_DIR=...
    JARVIS_DATA_FILE=MES_..._5m_cont.csv  JARVIS_SYMBOL=MES  JARVIS_MULTIPLIER=5.0
    GAP_MODE=fade  .venv/Scripts/python <worktree>/engine/backtest/run_gap_rank1.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

engine_root = Path(os.environ.get("JARVIS_ENGINE_ROOT", str(Path(__file__).resolve().parents[1])))
if str(engine_root) not in sys.path:
    sys.path.insert(0, str(engine_root))

# Path-load the worktree adapter (new file; its `from backtest.*` imports resolve
# against the live engine on sys.path above).
_gap_path = Path(__file__).resolve().parent / "gap_signals.py"
_spec = importlib.util.spec_from_file_location("gap_signals_wt", _gap_path)
_gap_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_gap_mod)
generate_gap_signals = _gap_mod.generate_gap_signals

MODE = os.environ.get("GAP_MODE", "fade").strip().lower()
FAMILY = f"gap_{MODE}"

SYMBOL = os.environ.get("JARVIS_SYMBOL", "MES")
MULTIPLIER = float(os.environ.get("JARVIS_MULTIPLIER", "5.0"))
CAPITAL = 50_000.0  # ALT convention (see MNQ $10K false-degenerate artifact 2026-05-30)
TICK_SIZE = 0.25  # cosmetic; backtester derives real tick per symbol via _get_tick_size
COMMISSION = 0.62
SLIPPAGE_TICKS = 2.0

TRAIN_MONTHS = int(os.environ.get("JARVIS_TRAIN_MONTHS", "6"))
TEST_MONTHS = int(os.environ.get("JARVIS_TEST_MONTHS", "3"))
STEP_MONTHS = int(os.environ.get("JARVIS_STEP_MONTHS", "3"))
DATA_START = os.environ.get("JARVIS_DATA_START")  # ISO floor, e.g. 2025-10-01 (skip thin data)

# The swept gate-v2 parameter: minimum gap size (fraction of prior close) to qualify.
MIN_GAP_PCT_VALUES = [0.0015, 0.0025, 0.0040]

COST_SWEEP_TIERS = {
    "optimistic": {"commission": 0.31, "slippage_ticks": 1.0},
    "realistic": {"commission": 0.62, "slippage_ticks": 2.0},
    "pessimistic": {"commission": 1.24, "slippage_ticks": 3.0},
    "catastrophic": {"commission": 2.48, "slippage_ticks": 4.0},
}
MIN_OOS_TRADES_PER_WINDOW = 1

CACHE_DIR = Path(os.environ.get("JARVIS_CACHE_DIR", str(engine_root / "backtest" / "cache")))
VERDICTS_DIR = Path(
    os.environ.get("JARVIS_VERDICTS_DIR", str(engine_root / "data" / "gate_v2_verdicts"))
)

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
from backtest.backtester import Backtester  # noqa: E402


def _load_data(data_file: Path) -> pd.DataFrame:
    df = pd.read_csv(data_file)
    df.columns = [c.lower() for c in df.columns]
    ts_col = "timestamp" if "timestamp" in df.columns else "datetime"
    df[ts_col] = pd.to_datetime(df[ts_col], utc=True)
    df = df.set_index(ts_col).sort_index()
    required = {"open", "high", "low", "close"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns in {data_file.name}: {missing}")
    if DATA_START:
        floor = pd.Timestamp(DATA_START)
        if df.index.tz is not None and floor.tz is None:
            floor = floor.tz_localize("UTC")
        df = df[df.index >= floor]
    return df


def _generate_windows(df: pd.DataFrame) -> list[dict]:
    data_start, data_end = df.index.min(), df.index.max()
    windows, cursor, wnum = [], data_start, 1
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


def _bt(df, min_gap_pct, commission=COMMISSION, slippage_ticks=SLIPPAGE_TICKS):
    sig = generate_gap_signals(df, mode=MODE, min_gap_pct=min_gap_pct)
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
    return bt.run(sig, symbol=SYMBOL, multiplier=MULTIPLIER)


def _best_is(df_train, grid):
    best_pf, best_g, best_res = -1.0, None, None
    for g in grid:
        try:
            r = _bt(df_train, g)
        except Exception as exc:
            print(f"    [WARN] IS error min_gap={g}: {exc}")
            continue
        if r.total_trades < MIN_OOS_TRADES_PER_WINDOW:
            continue
        if r.profit_factor > best_pf:
            best_pf, best_g, best_res = r.profit_factor, g, r
    return best_g, best_res


def _fixed_sweep(df, grid):
    pfs, combos = [], []
    for g in grid:
        try:
            r = _bt(df, g)
            if r.total_trades >= MIN_OOS_TRADES_PER_WINDOW:
                pfs.append(r.profit_factor)
                combos.append(
                    {
                        "min_gap_pct": g,
                        "pf": round(r.profit_factor, 4),
                        "trades": r.total_trades,
                    }
                )
                print(f"    combo min_gap={g}: PF={r.profit_factor:.4f} trades={r.total_trades}")
            else:
                print(f"    combo min_gap={g}: SKIP ({r.total_trades} trades)")
        except Exception as exc:
            print(f"  [WARN] fixed-sweep min_gap={g}: {exc}")
    if not pfs:
        return {
            "fixed_params_min_pf": 0.0,
            "fixed_params_mean_pf": 0.0,
            "fixed_params_max_pf": 0.0,
            "n_combos_with_trades": 0,
            "combo_results": combos,
        }
    return {
        "fixed_params_min_pf": round(float(min(pfs)), 4),
        "fixed_params_mean_pf": round(float(np.mean(pfs)), 4),
        "fixed_params_max_pf": round(float(max(pfs)), 4),
        "n_combos_with_trades": len(pfs),
        "combo_results": combos,
    }


def _cost_sweep(df, g):
    results, last = {}, None
    for tier in COST_TIER_ORDER:
        ct = COST_SWEEP_TIERS[tier]
        try:
            r = _bt(df, g, commission=ct["commission"], slippage_ticks=ct["slippage_ticks"])
            passes = r.profit_factor > 1.0 and r.total_trades >= MIN_OOS_TRADES_PER_WINDOW
            results[tier] = {
                "pf": round(r.profit_factor, 4),
                "trades": r.total_trades,
                "passes": passes,
            }
            print(
                f"    [{tier:12s}] PF={r.profit_factor:.4f} trades={r.total_trades} {'PASS' if passes else 'FAIL'}"
            )
            if passes:
                last = tier
        except Exception as exc:
            print(f"  [WARN] cost {tier}: {exc}")
            results[tier] = {"pf": 0.0, "trades": 0, "passes": False}
    return {"cost_survives_through": last or "none", "tier_results": results}


def _gate(oos_results, n_combos, fixed_m, cost_m):
    from backtest.deflated_sharpe import deflated_sharpe_ratio

    oos_pfs = [r.profit_factor for r in oos_results if r.total_trades >= MIN_OOS_TRADES_PER_WINDOW]
    oos_dds = [r.max_drawdown_pct for r in oos_results]
    oos_sharpes = [
        r.sharpe_ratio for r in oos_results if r.total_trades >= MIN_OOS_TRADES_PER_WINDOW
    ]
    all_trades = sum(r.total_trades for r in oos_results)
    pf_ci = _bootstrap_pf_ci_lower(oos_pfs)
    p_edge = float(sum(1 for pf in oos_pfs if pf > 1.0) / max(1, len(oos_pfs)))
    mc_dd = float(np.percentile(oos_dds, 95.0)) if oos_dds else 1.0
    mean_sharpe = float(np.mean(oos_sharpes)) if oos_sharpes else 0.0
    dsr_r = deflated_sharpe_ratio(sharpe=mean_sharpe, n_trials=n_combos, n_obs=max(all_trades, 30))
    dsr = dsr_r.get("dsr", 0.0) if isinstance(dsr_r, dict) else float(dsr_r)
    wfo = _classify_wfo_consistency(oos_pfs)
    fpf = fixed_m.get("fixed_params_min_pf", 0.0)
    cost = cost_m.get("cost_survives_through", "none")
    cost_idx = COST_TIER_ORDER.index(cost) if cost in COST_TIER_ORDER else -1
    cost_pass = cost_idx >= COST_TIER_ORDER.index("realistic")
    core = (
        pf_ci >= GATE_PF_CI_LOWER
        and p_edge >= GATE_P_EDGE
        and mc_dd <= GATE_MC_DD_CORE
        and dsr >= GATE_DSR
    )
    alt = (
        dsr >= GATE_DSR_ALT
        and wfo in GATE_WFO_CONSISTENCY_VALUES
        and fpf >= GATE_FIXED_PARAMS_MIN_PF
        and cost_pass
        and mc_dd <= GATE_MC_DD_ALT
    )
    verdict = "PASS" if (core or alt) else "FAIL"
    passed_via = "core" if core else ("alt" if alt else None)
    return {
        "verdict": verdict,
        "passed_via": passed_via,
        "core_verdict": "PASS" if core else "FAIL",
        "alt_verdict": "PASS" if alt else "FAIL",
        "pf_ci_lower": round(pf_ci, 4),
        "p_edge": round(p_edge, 4),
        "mc_95th_dd": round(mc_dd, 6),
        "mc_95th_dd_pct": round(mc_dd * 100, 4),
        "dsr": round(dsr, 6),
        "wfo_consistency": wfo,
        "fixed_params_min_pf": fpf,
        "fixed_params_mean_pf": fixed_m.get("fixed_params_mean_pf", 0.0),
        "fixed_params_max_pf": fixed_m.get("fixed_params_max_pf", 0.0),
        "cost_survives_through": cost,
        "n_oos_windows": len(oos_results),
        "n_oos_windows_with_trades": len(oos_pfs),
        "total_oos_trades": all_trades,
    }


def run_wfo() -> dict:
    from backtest._gate_v2_helpers import _find_latest_cache

    override = os.environ.get("JARVIS_DATA_FILE")
    if override:
        data_file = Path(override)
        if not data_file.is_absolute():
            data_file = CACHE_DIR / data_file
    else:
        data_file = _find_latest_cache(CACHE_DIR, SYMBOL)
    print(f"[{SYMBOL}-GAP-{MODE}] {data_file.name}")
    df = _load_data(data_file)
    print(
        f"[{SYMBOL}-GAP-{MODE}] {len(df)} bars | {df.index.min().date()} -> {df.index.max().date()}"
    )

    windows = _generate_windows(df)
    if not windows:
        print("ERROR: no windows")
        return {}
    grid = list(MIN_GAP_PCT_VALUES)
    n_combos = len(grid)
    tf = "5m" if "_5m" in data_file.name else ("1h" if "_1h" in data_file.name else "?")
    print(f"=== {SYMBOL} GAP {MODE} | windows={len(windows)} | min_gap grid={grid} | {tf} bars ===")

    oos_results, window_records = [], []
    for win in windows:
        ts, te, os_, oe = win["train_start"], win["train_end"], win["test_start"], win["test_end"]
        df_train = df[(df.index >= ts) & (df.index < te)].copy()
        df_test = df[(df.index >= os_) & (df.index <= oe)].copy()
        best_g, is_res = _best_is(df_train, grid)
        if best_g is None:
            print(f"Window {win['window_num']}: [SKIP] no valid IS min_gap")
            continue
        try:
            oos = _bt(df_test, best_g)
        except Exception as exc:
            print(f"Window {win['window_num']}: [SKIP] OOS err {exc}")
            continue
        print(
            f"Window {win['window_num']}: IS min_gap={best_g} PF={is_res.profit_factor:.2f} "
            f"t={is_res.total_trades} | OOS PF={oos.profit_factor:.2f} t={oos.total_trades}"
        )
        oos_results.append(oos)
        window_records.append(
            {
                "window": win["window_num"],
                "is_period": f"{ts.strftime('%Y-%m')} -> {te.strftime('%Y-%m')}",
                "oos_period": f"{os_.strftime('%Y-%m')} -> {oe.strftime('%Y-%m')}",
                "best_min_gap_pct": best_g,
                "is_pf": round(is_res.profit_factor, 3),
                "is_trades": is_res.total_trades,
                "oos_pf": round(oos.profit_factor, 3),
                "oos_dd": round(oos.max_drawdown_pct, 4),
                "oos_sharpe": round(oos.sharpe_ratio, 3),
                "oos_trades": oos.total_trades,
            }
        )

    if not oos_results:
        print(f"[{SYMBOL}-GAP-{MODE}] No OOS results.")
        return {
            "symbol": SYMBOL,
            "family": FAMILY,
            "rank": 1,
            "verdict": "FAIL",
            "degenerate": True,
        }

    print(f"[{SYMBOL}-GAP-{MODE}] fixed sweep...")
    fixed_m = _fixed_sweep(df, grid)
    votes = Counter(r["best_min_gap_pct"] for r in window_records)
    champ_g = votes.most_common(1)[0][0] if votes else 0.0025
    print(f"[{SYMBOL}-GAP-{MODE}] cost sweep (champ min_gap={champ_g})...")
    cost_m = _cost_sweep(df, champ_g)
    gate = _gate(oos_results, n_combos, fixed_m, cost_m)

    print(f"\n=== GATE v2: {gate['verdict']} (via {gate['passed_via'] or 'NONE'}) ===")
    for k in (
        "pf_ci_lower",
        "p_edge",
        "mc_95th_dd_pct",
        "dsr",
        "wfo_consistency",
        "fixed_params_min_pf",
        "cost_survives_through",
        "total_oos_trades",
    ):
        print(f"  {k:22}= {gate[k]}")

    VERDICTS_DIR.mkdir(parents=True, exist_ok=True)
    verdict_file = VERDICTS_DIR / f"{SYMBOL}_{FAMILY}_rank1.json"
    doc = {
        "symbol": SYMBOL,
        "family": FAMILY,
        "rank": 1,
        "verdict": gate["verdict"],
        "passed_via": gate["passed_via"],
        "core_verdict": gate["core_verdict"],
        "alt_verdict": gate["alt_verdict"],
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
        "wfo_config": {
            "train_months": TRAIN_MONTHS,
            "test_months": TEST_MONTHS,
            "step_months": STEP_MONTHS,
            "n_windows": len(windows),
            "n_oos_windows": gate["n_oos_windows"],
            "total_oos_trades": gate["total_oos_trades"],
            "grid_combos": n_combos,
            "min_gap_pct_grid": MIN_GAP_PCT_VALUES,
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
            "n_combos_with_trades": fixed_m.get("n_combos_with_trades", 0),
            "combo_results": fixed_m.get("combo_results", []),
            "cost_survives_through": gate["cost_survives_through"],
            "cost_tier_results": cost_m.get("tier_results", {}),
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
        "champion_params": {"min_gap_pct": champ_g, "mode": MODE},
        "windows": window_records,
        "lineage": {
            "experiment": "generation-engine experiment 4: Corey RTH-gap family",
            "mechanical_rule": MODE,
            "conditioning": "none",
            "data_file": data_file.name,
            "bar_timeframe": tf,
            "data_span": f"{df.index.min().date()} -> {df.index.max().date()}",
            "gap_definition_note": (
                "RTH-session gap: today's RTH open vs YESTERDAY's RTH close (ET 09:30-16:00), "
                "overnight excluded. Backtester runs on RTH-only bars (gap plays are intraday-RTH; "
                "EOD exit fits). NOT a 24h close-to-open gap."
            ),
            "kill_switch_note": "fixed_params_min_pf is measured on the single full-series "
            "backtest and is depressed by the -5% max-DD kill switch halting early; the "
            "per-window OOS p_edge/pf_ci_lower are the reliable edge signal.",
            "source_study": "thinkorswim-scripts (Corey Gapfinder) / engine/backtest/gapfinder.py",
            "no_lookahead": "prior-session RTH close (shift 1) for the gap; entry on first RTH bar",
        },
    }
    verdict_file.write_text(json.dumps(doc, indent=2, default=str))
    print(f"[{SYMBOL}-GAP-{MODE}] verdict -> {verdict_file}")
    return doc


if __name__ == "__main__":
    if MODE not in ("fade", "go"):
        sys.exit(f"GAP_MODE must be fade|go, got {MODE!r}")
    v = run_wfo()
    if not v:
        sys.exit(1)
    print(f"\n[{v['verdict']}] {SYMBOL} GAP {MODE} -- first gap-family gate-v2 verdict.")
