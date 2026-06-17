#!/usr/bin/env python
"""
WFO Live-Config Match — 2026-06-17

Safety: Research only. Writes to engine/data/wfo_live_match/ ONLY.
        Never writes to gate_v2_verdicts/ or edge_ledger.jsonl.
        Does NOT modify signals.py, config.py, .env, or any live-routing code.
        Does NOT restart the engine or call any live endpoints.

Purpose:
    Pin the offline discovery harness to EXACTLY the live MGC rank4 WFO config
    so future promotion decisions are apples-to-apples.

    Live rank4 config (from engine/data/gate_v2_verdicts/MGC_trend_rank4.json):
        train_months=6, test_months=2, step_months=1
        grid: fast in [40,50], slow in [80,120], atr_trail_mult in [1.5,2.0]
        → 8 combos, 19 windows, 67 OOS trades, pf_ci=2.60, mc_dd=3.03%

    Steps:
        1. VALIDATION — plain SMA trend (no ADX) under live config.
           Reproduced when: ~67 OOS trades, pf_ci in [2.3, 2.9], mc_dd ~3%.
        2. ADX sweep — adx_threshold in {14, 18, 22, 25} under the SAME live
           config. Definitive ADX answer under live methodology.

Usage (from engine/ directory, using the main checkout venv):
    C:\\Users\\mattm\\ThinkorSwim\\jarvis-trader\\engine\\.venv\\Scripts\\python.exe ^
        C:\\Users\\mattm\\ThinkorSwim\\_wfo_match\\engine\\backtest\\run_wfo_live_match.py

    With options:
    ... run_wfo_live_match.py --validate-only
    ... run_wfo_live_match.py --adx-only
    ... run_wfo_live_match.py --skip-validate   (dangerous: bypasses fidelity check)
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Path setup — use the MAIN checkout's engine/, not the worktree's copy,
# so we import the same code the live engine runs.
# ---------------------------------------------------------------------------
MAIN_ENGINE_ROOT = Path("C:/Users/mattm/ThinkorSwim/jarvis-trader/engine")
if str(MAIN_ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(MAIN_ENGINE_ROOT))

# Output dir is isolated — never touches gate_v2_verdicts/ or edge_ledger.jsonl
OUTPUT_DIR = MAIN_ENGINE_ROOT / "data" / "wfo_live_match"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# DB + cache also from the main checkout
CACHE_DIR = MAIN_ENGINE_ROOT / "backtest" / "cache"
DB_PATH = Path("C:/Users/mattm/ThinkorSwim/jarvis-trader/engine/data/jarvis_trader.db")

# ---------------------------------------------------------------------------
# Live rank4 WFO config (single source of truth for this file)
# ---------------------------------------------------------------------------
LIVE_TRAIN_MONTHS = 6
LIVE_TEST_MONTHS = 2
LIVE_STEP_MONTHS = 1
LIVE_GRID_FAST = [40, 50]
LIVE_GRID_SLOW = [80, 120]
LIVE_GRID_ATR = [1.5, 2.0]

LIVE_GRID = [
    {"fast": f, "slow": s, "atr_trail_mult": a}
    for f, s, a in itertools.product(LIVE_GRID_FAST, LIVE_GRID_SLOW, LIVE_GRID_ATR)
]

# ADX thresholds to sweep (task spec)
ADX_THRESHOLDS = [14, 18, 22, 25]

# Reference metrics from live rank4 verdict JSON (for validation comparison)
LIVE_RANK4_REFERENCE = {
    "total_oos_trades": 67,
    "pf_ci_lower": 2.5968,
    "mc_95th_dd_pct": 3.0347,
    "dsr": 1.0,
    "verdict": "PASS",
    "passed_via": "alt",
}

# ---------------------------------------------------------------------------
# Import canonical gate machinery — same as the live runner
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
    MIN_OOS_TRADES_TOTAL,
    N_BOOTSTRAP,
    _find_latest_cache,
    bootstrap_pf_ci_lower,
    classify_wfo_consistency,
    sample_adequacy_enforced,
)
from backtest._gate_v2_trade_metrics import (  # noqa: E402
    trade_level_dsr,
    trade_level_mc_95th_dd,
    trade_level_win_rate_ci_lower,
)

# ---------------------------------------------------------------------------
# Contract spec for MGC (matches live rank4 verdict)
# ---------------------------------------------------------------------------
CONTRACT_SPECS = {
    "MGC": {
        "multiplier": 10.0,
        "tick_size": 0.10,
        "commission": 0.62,
        "slippage_ticks": 2.0,
        "capital": 50_000.0,
    },
}

COST_SWEEP_TIERS = {
    "optimistic": {"commission": 0.31, "slippage_ticks": 1.0},
    "realistic": {"commission": 0.62, "slippage_ticks": 2.0},
    "pessimistic": {"commission": 1.24, "slippage_ticks": 3.0},
    "catastrophic": {"commission": 2.48, "slippage_ticks": 4.0},
}

# ---------------------------------------------------------------------------
# Bar loading
# ---------------------------------------------------------------------------


def _load_csv_bars(data_file: Path) -> pd.DataFrame:
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


def load_bars(symbol: str) -> pd.DataFrame:
    data_file = _find_latest_cache(CACHE_DIR, symbol, suffix="_1h.csv")
    print(f"  [load] {symbol}: {data_file.name}")
    df = _load_csv_bars(data_file)
    print(f"  [load] {symbol}: {len(df)} bars | {df.index.min().date()} -> {df.index.max().date()}")
    return df


# ---------------------------------------------------------------------------
# WFO window generation
# ---------------------------------------------------------------------------


def generate_windows(
    df: pd.DataFrame,
    train_months: int = LIVE_TRAIN_MONTHS,
    test_months: int = LIVE_TEST_MONTHS,
    step_months: int = LIVE_STEP_MONTHS,
    min_bars_per_split: int = 30,
) -> list[dict]:
    data_start = df.index.min()
    data_end = df.index.max()
    windows = []
    cursor = data_start
    wnum = 1
    while True:
        train_start = cursor
        train_end = train_start + pd.DateOffset(months=train_months)
        test_start = train_end
        test_end = test_start + pd.DateOffset(months=test_months)
        if test_start >= data_end:
            break
        if test_end > data_end:
            test_end = data_end
        df_train = df[(df.index >= train_start) & (df.index < train_end)]
        df_test = df[(df.index >= test_start) & (df.index <= test_end)]
        if len(df_train) >= min_bars_per_split and len(df_test) >= min_bars_per_split:
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
        cursor += pd.DateOffset(months=step_months)
        if cursor >= data_end:
            break
    return windows


# ---------------------------------------------------------------------------
# Backtester runner
# ---------------------------------------------------------------------------


def run_backtest(
    df: pd.DataFrame,
    df_signals: pd.DataFrame,
    symbol: str,
    commission: float | None = None,
    slippage_ticks: float | None = None,
):
    from backtest.backtester import Backtester

    spec = CONTRACT_SPECS[symbol]
    bt = Backtester(
        initial_capital=spec["capital"],
        risk_per_trade=0.01,
        max_daily_loss=0.02,
        max_drawdown=0.05,
        t1_exit_pct=0.50,
        t2_exit_pct=0.30,
        commission_per_contract=commission if commission is not None else spec["commission"],
        slippage_ticks=slippage_ticks if slippage_ticks is not None else spec["slippage_ticks"],
    )
    return bt.run(df_signals, symbol=symbol, multiplier=spec["multiplier"])


# ---------------------------------------------------------------------------
# Signal generators
# ---------------------------------------------------------------------------


def _wilder_atr(
    high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14
) -> pd.Series:
    prev_c = close.shift(1)
    tr = pd.concat([(high - low), (high - prev_c).abs(), (low - prev_c).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


def generate_sma_trend_signals_plain(
    df: pd.DataFrame,
    fast: int = 50,
    slow: int = 120,
    atr_trail_mult: float = 2.0,
    min_rv_annualized: float = 0.0,
) -> pd.DataFrame:
    """Plain SMA trend — identical to live generate_sma_trend_signals."""
    from backtest.trend_signals import generate_sma_trend_signals
    return generate_sma_trend_signals(
        df,
        fast=fast,
        slow=slow,
        atr_trail_mult=atr_trail_mult,
        min_rv_annualized=min_rv_annualized,
    )


def generate_adx_sma_trend_signals(
    df: pd.DataFrame,
    fast: int = 50,
    slow: int = 120,
    atr_trail_mult: float = 2.0,
    adx_threshold: float = 22.0,
    adx_period: int = 14,
    min_rv_annualized: float = 0.0,
) -> pd.DataFrame:
    """SMA trend with ADX(14) >= threshold filter on entries.

    Operates on 'entry_signal' column (backtester.py reads this column).
    Suppresses ENTRY_NOW bars where ADX < adx_threshold.
    Exits are unchanged.
    """
    from backtest.indicators import compute_adx
    from backtest.trend_signals import generate_sma_trend_signals

    df_sig = generate_sma_trend_signals(
        df,
        fast=fast,
        slow=slow,
        atr_trail_mult=atr_trail_mult,
        min_rv_annualized=min_rv_annualized,
    )
    adx_df = compute_adx(df, period=adx_period)
    adx_vals = adx_df["adx"]

    entry_mask = df_sig["entry_signal"] == "ENTRY_NOW"
    adx_weak = (adx_vals < adx_threshold) | adx_vals.isna()
    suppress = entry_mask & adx_weak
    df_sig.loc[suppress, "entry_signal"] = "NO_TRADE"
    return df_sig


# ---------------------------------------------------------------------------
# IS grid search
# ---------------------------------------------------------------------------


def best_is_params(
    df_train: pd.DataFrame,
    grid: list[dict],
    signal_fn: Callable,
    symbol: str,
    min_trades: int = 1,
) -> tuple[dict | None, object | None]:
    best_pf = -1.0
    best_params = None
    best_result = None
    for params in grid:
        try:
            df_sig = signal_fn(df_train, **params)
            result = run_backtest(df_train, df_sig, symbol)
        except Exception as exc:
            print(f"    [WARN] IS error {params}: {exc}")
            continue
        if result.total_trades < min_trades:
            continue
        pf = result.profit_factor
        if pf > best_pf:
            best_pf = pf
            best_params = params
            best_result = result
    return best_params, best_result


# ---------------------------------------------------------------------------
# Fixed-params sweep (full dataset)
# ---------------------------------------------------------------------------


def run_fixed_params_sweep(
    df: pd.DataFrame,
    grid: list[dict],
    signal_fn: Callable,
    symbol: str,
    min_trades: int = 1,
) -> dict:
    pfs = []
    combo_results = []
    for params in grid:
        try:
            df_sig = signal_fn(df, **params)
            result = run_backtest(df, df_sig, symbol)
            if result.total_trades >= min_trades:
                pfs.append(result.profit_factor)
                combo_results.append({
                    **params,
                    "pf": round(result.profit_factor, 4),
                    "trades": result.total_trades,
                })
                print(f"    {params} => PF={result.profit_factor:.4f} trades={result.total_trades}")
            else:
                print(f"    {params} => SKIP ({result.total_trades} trades)")
        except Exception as exc:
            print(f"  [WARN] fixed-params error {params}: {exc}")
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
    signal_fn: Callable,
    symbol: str,
    min_trades: int = 1,
) -> dict:
    results = {}
    cost_survives_through = "none"
    survival_intact = True
    for tier in COST_TIER_ORDER:
        costs = COST_SWEEP_TIERS[tier]
        try:
            df_sig = signal_fn(df, **champion_params)
            result = run_backtest(
                df, df_sig, symbol,
                commission=costs["commission"],
                slippage_ticks=costs["slippage_ticks"],
            )
            pf = result.profit_factor
            passes = pf > 1.0 and result.total_trades >= min_trades
            results[tier] = {"pf": round(pf, 4), "trades": result.total_trades, "passes": passes}
            print(f"    [{tier:12s}] PF={pf:.4f} trades={result.total_trades} {'PASS' if passes else 'FAIL'}")
            if survival_intact and passes:
                cost_survives_through = tier
            elif not passes:
                survival_intact = False
        except Exception as exc:
            print(f"  [WARN] cost-sweep error at {tier}: {exc}")
            results[tier] = {"pf": 0.0, "trades": 0, "passes": False}
            survival_intact = False
    return {"cost_survives_through": cost_survives_through, "tier_results": results}


# ---------------------------------------------------------------------------
# Gate v2 full evaluation — uses canonical helpers
# ---------------------------------------------------------------------------


def compute_gate_v2(
    oos_results: list,
    n_grid_combos: int,
    fixed_params_metrics: dict,
    cost_sweep_metrics: dict,
    symbol: str,
    min_oos_trades_per_window: int = 1,
) -> dict:
    spec = CONTRACT_SPECS[symbol]
    capital = spec["capital"]

    oos_pfs = [r.profit_factor for r in oos_results if r.total_trades >= min_oos_trades_per_window]
    oos_dds = [r.max_drawdown_pct for r in oos_results]
    all_trades = sum(r.total_trades for r in oos_results)
    sample_adequate = all_trades >= MIN_OOS_TRADES_TOTAL

    pf_ci_lower = bootstrap_pf_ci_lower(oos_pfs, n=N_BOOTSTRAP)
    p_edge = float(sum(1 for pf in oos_pfs if pf > 1.0) / max(1, len(oos_pfs)))

    mc_95th_dd = trade_level_mc_95th_dd(oos_results, initial_capital=capital)
    dsr = trade_level_dsr(oos_results, n_grid_combos=n_grid_combos, initial_capital=capital)
    win_rate_ci_lower = trade_level_win_rate_ci_lower(oos_results)
    mc_95th_dd_window_legacy = float(np.percentile(oos_dds, 95.0)) if oos_dds else 1.0

    wfo_consistency = classify_wfo_consistency(oos_pfs)
    fixed_params_min_pf = fixed_params_metrics.get("fixed_params_min_pf", 0.0)
    cost_survives_through = cost_sweep_metrics.get("cost_survives_through", "none")
    cost_tier_idx = (
        COST_TIER_ORDER.index(cost_survives_through) if cost_survives_through in COST_TIER_ORDER else -1
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

    if sample_adequacy_enforced() and not sample_adequate:
        verdict, passed_via = "INSUFFICIENT_SAMPLE", None
    elif core_pass:
        verdict, passed_via = "PASS", "core"
    elif alt_pass:
        verdict, passed_via = "PASS", "alt"
    else:
        verdict, passed_via = "FAIL", None

    if verdict != "PASS":
        primary_block = None
        if pf_ci_lower < GATE_PF_CI_LOWER:
            primary_block = f"pf_ci_lower={pf_ci_lower:.4f}<{GATE_PF_CI_LOWER}"
        elif dsr < GATE_DSR_ALT:
            primary_block = f"dsr={dsr:.4f}<{GATE_DSR_ALT}"
        elif wfo_consistency not in GATE_WFO_CONSISTENCY_VALUES:
            primary_block = f"wfo={wfo_consistency}"
        elif fixed_params_min_pf < GATE_FIXED_PARAMS_MIN_PF:
            primary_block = f"fixed_pf={fixed_params_min_pf:.4f}<{GATE_FIXED_PARAMS_MIN_PF}"
        elif not cost_passes:
            primary_block = f"cost_survives={cost_survives_through}"
        elif mc_95th_dd > GATE_MC_DD_ALT:
            primary_block = f"mc_dd={mc_95th_dd*100:.2f}%>{GATE_MC_DD_ALT*100:.0f}%"
        elif p_edge < GATE_P_EDGE:
            primary_block = f"p_edge={p_edge:.4f}<{GATE_P_EDGE}"
        else:
            primary_block = "unknown"
    else:
        primary_block = None

    return {
        "verdict": verdict,
        "passed_via": passed_via,
        "primary_block": primary_block,
        "core_verdict": "PASS" if core_pass else "FAIL",
        "alt_verdict": "PASS" if alt_pass else "FAIL",
        "pf_ci_lower": round(pf_ci_lower, 4),
        "p_edge": round(p_edge, 4),
        "mc_95th_dd": round(mc_95th_dd, 6),
        "mc_95th_dd_pct": round(mc_95th_dd * 100, 4),
        "mc_95th_dd_window_legacy": round(mc_95th_dd_window_legacy, 6),
        "dsr": round(dsr, 6),
        "wfo_consistency": wfo_consistency,
        "fixed_params_min_pf": fixed_params_min_pf,
        "fixed_params_mean_pf": fixed_params_metrics.get("fixed_params_mean_pf", 0.0),
        "fixed_params_max_pf": fixed_params_metrics.get("fixed_params_max_pf", 0.0),
        "cost_survives_through": cost_survives_through,
        "n_oos_windows": len(oos_results),
        "n_oos_windows_with_trades": len(oos_pfs),
        "total_oos_trades": all_trades,
        "sample_adequate": sample_adequate,
        "win_rate_ci_lower": round(win_rate_ci_lower, 4),
    }


# ---------------------------------------------------------------------------
# Main WFO driver — always uses live config
# ---------------------------------------------------------------------------


def run_hypothesis(
    label: str,
    symbol: str,
    signal_fn: Callable,
    param_grid: list[dict],
    df: pd.DataFrame | None = None,
    min_oos_trades_per_window: int = 1,
) -> dict:
    """Run a full WFO + gate-v2 evaluation pinned to the live rank4 WFO config.

    Config is fixed: train_months=6, test_months=2, step_months=1.
    Writes a verdict JSON to OUTPUT_DIR/<label>.json.
    """
    train_months = LIVE_TRAIN_MONTHS
    test_months = LIVE_TEST_MONTHS
    step_months = LIVE_STEP_MONTHS

    print(f"\n{'='*70}")
    print(f"  {label} | {symbol} | train={train_months}mo test={test_months}mo step={step_months}mo")
    print(f"  Grid: {len(param_grid)} combos")
    print(f"  [LIVE CONFIG MATCH] Exact rank4 WFO windowing")
    print(f"{'='*70}")

    if df is None:
        df = load_bars(symbol)

    windows = generate_windows(df, train_months=train_months, test_months=test_months, step_months=step_months)
    if not windows:
        print("  [ABORT] Not enough data for WFO windows.")
        return {"verdict": "INSUFFICIENT_SAMPLE", "error": "no_windows"}

    print(f"  Windows: {len(windows)}")
    n_combos = len(param_grid)

    oos_results = []
    window_records = []

    for win in windows:
        wnum = win["window_num"]
        ts, te = win["train_start"], win["train_end"]
        os_, oe = win["test_start"], win["test_end"]

        df_train = df[(df.index >= ts) & (df.index < te)].copy()
        df_test = df[(df.index >= os_) & (df.index <= oe)].copy()

        print(
            f"\n  Window {wnum}: IS {ts.strftime('%Y-%m')}->{te.strftime('%Y-%m')} "
            f"OOS {os_.strftime('%Y-%m')}->{oe.strftime('%Y-%m')} "
            f"({win['n_train']}/{win['n_test']} bars)"
        )

        best_params, is_result = best_is_params(
            df_train, param_grid, signal_fn, symbol, min_trades=min_oos_trades_per_window
        )
        if best_params is None:
            print("    [SKIP] No valid IS params")
            continue

        print(
            f"    Best IS: {best_params} PF={is_result.profit_factor:.2f} trades={is_result.total_trades}"
        )

        try:
            df_sig_test = signal_fn(df_test, **best_params)
            oos_result = run_backtest(df_test, df_sig_test, symbol)
        except Exception as exc:
            print(f"    [SKIP] OOS error: {exc}")
            continue

        print(
            f"    OOS: PF={oos_result.profit_factor:.2f} DD={oos_result.max_drawdown_pct:.1%} "
            f"trades={oos_result.total_trades}"
        )

        oos_results.append(oos_result)
        window_records.append(
            {
                "window": wnum,
                "best_params": best_params,
                "is_pf": round(is_result.profit_factor, 3),
                "is_trades": is_result.total_trades,
                "oos_pf": round(oos_result.profit_factor, 3),
                "oos_dd": round(oos_result.max_drawdown_pct, 4),
                "oos_trades": oos_result.total_trades,
            }
        )

    if not oos_results:
        print("  [ABORT] No OOS results.")
        out = {
            "symbol": symbol,
            "label": label,
            "verdict": "FAIL",
            "passed_via": None,
            "primary_block": "no_oos_trades",
            "gate_v2_metrics": {},
        }
        _write_verdict(label, out)
        return out

    # Fixed-params sweep
    print(f"\n  Fixed-params sweep ({n_combos} combos)...")
    fixed_params_metrics = run_fixed_params_sweep(
        df, param_grid, signal_fn, symbol, min_trades=min_oos_trades_per_window
    )

    # Champion = most-selected IS params
    param_votes = Counter(
        str(sorted(r["best_params"].items())) for r in window_records
    )
    champion_key = param_votes.most_common(1)[0][0]
    champion_params = dict(sorted(window_records[
        next(i for i, r in enumerate(window_records) if str(sorted(r["best_params"].items())) == champion_key)
    ]["best_params"].items()))

    print(f"\n  Cost sweep (champion: {champion_params})...")
    cost_sweep_metrics = run_cost_sweep(
        df, champion_params, signal_fn, symbol, min_trades=min_oos_trades_per_window
    )

    gate = compute_gate_v2(
        oos_results, n_combos, fixed_params_metrics, cost_sweep_metrics, symbol,
        min_oos_trades_per_window=min_oos_trades_per_window,
    )

    print(f"\n  {'='*60}")
    print(f"  VERDICT: {gate['verdict']} (via {gate['passed_via'] or 'NONE'}) | {gate.get('primary_block', '')}")
    print(f"  pf_ci_lower={gate['pf_ci_lower']:.4f} p_edge={gate['p_edge']:.4f} "
          f"mc_dd={gate['mc_95th_dd_pct']:.4f}% dsr={gate['dsr']:.6f}")
    print(f"  wfo={gate['wfo_consistency']} fixed_min={gate['fixed_params_min_pf']:.4f} "
          f"cost={gate['cost_survives_through']} n_oos_trades={gate['total_oos_trades']}")

    out = {
        "symbol": symbol,
        "label": label,
        "verdict": gate["verdict"],
        "passed_via": gate["passed_via"],
        "primary_block": gate.get("primary_block"),
        "core_verdict": gate["core_verdict"],
        "alt_verdict": gate["alt_verdict"],
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
        "champion_params": champion_params,
        "wfo_config": {
            "train_months": train_months,
            "test_months": test_months,
            "step_months": step_months,
            "n_windows": len(windows),
            "n_oos_windows": gate["n_oos_windows"],
            "n_oos_windows_with_trades": gate["n_oos_windows_with_trades"],
            "total_oos_trades": gate["total_oos_trades"],
            "grid_combos": n_combos,
        },
        "gate_v2_metrics": {
            "pf_ci_lower": gate["pf_ci_lower"],
            "p_edge": gate["p_edge"],
            "mc_95th_dd": gate["mc_95th_dd"],
            "mc_95th_dd_pct": gate["mc_95th_dd_pct"],
            "dsr": gate["dsr"],
            "wfo_consistency": gate["wfo_consistency"],
            "fixed_params_min_pf": gate["fixed_params_min_pf"],
            "cost_survives_through": gate["cost_survives_through"],
            "cost_tier_results": cost_sweep_metrics.get("tier_results", {}),
            "total_oos_trades": gate["total_oos_trades"],
            "sample_adequate": gate["sample_adequate"],
            "win_rate_ci_lower": gate["win_rate_ci_lower"],
            "combo_results": fixed_params_metrics.get("combo_results", []),
        },
        "windows": window_records,
    }
    _write_verdict(label, out)
    return out


def _write_verdict(label: str, data: dict) -> Path:
    """Write verdict JSON to isolated wfo_live_match/ dir only."""
    out_path = OUTPUT_DIR / f"{label}.json"
    out_path.write_text(json.dumps(data, indent=2, default=str))
    print(f"  [WRITTEN] {out_path}")
    return out_path


# ---------------------------------------------------------------------------
# Validation: reproduce live rank4 with plain trend under live config
# ---------------------------------------------------------------------------


def run_validation(df_mgc: pd.DataFrame) -> tuple[bool, dict]:
    """Re-run plain MGC trend under the exact live rank4 WFO config.

    Reproduced when total_oos_trades within 10 of 67, pf_ci_lower within
    15% of 2.5968, mc_dd_pct within 1.5% of 3.03%.
    Bootstrap has RNG variance so tight exact-match is unreliable.
    """
    print(f"\n{'='*70}")
    print("=== VALIDATION: plain MGC trend under live rank4 config ===")
    print(f"  Live reference: {LIVE_RANK4_REFERENCE}")
    print(f"  Grid: fast{LIVE_GRID_FAST} x slow{LIVE_GRID_SLOW} x atr{LIVE_GRID_ATR} = {len(LIVE_GRID)} combos")
    print(f"  WFO:  train={LIVE_TRAIN_MONTHS}mo test={LIVE_TEST_MONTHS}mo step={LIVE_STEP_MONTHS}mo")

    result = run_hypothesis(
        label="MGC_plain_trend_live_config",
        symbol="MGC",
        signal_fn=generate_sma_trend_signals_plain,
        param_grid=LIVE_GRID,
        df=df_mgc,
        min_oos_trades_per_window=1,
    )

    gate = result.get("gate_v2_metrics", {})
    actual_trades = gate.get("total_oos_trades", 0)
    actual_pf_ci = gate.get("pf_ci_lower", 0.0)
    actual_mc_dd = gate.get("mc_95th_dd_pct", 99.0)
    actual_verdict = result.get("verdict")
    actual_via = result.get("passed_via")

    ref = LIVE_RANK4_REFERENCE
    trade_diff = abs(actual_trades - ref["total_oos_trades"])
    pf_ci_pct_diff = abs(actual_pf_ci - ref["pf_ci_lower"]) / ref["pf_ci_lower"] * 100
    mc_dd_diff = abs(actual_mc_dd - ref["mc_95th_dd_pct"])

    checks = {
        "verdict_pass": actual_verdict == "PASS",
        "passed_via_alt": actual_via == "alt",
        "oos_trades_within_10": trade_diff <= 10,
        "pf_ci_within_15pct": pf_ci_pct_diff <= 15.0,
        "mc_dd_within_1_5pct": mc_dd_diff <= 1.5,
    }
    all_pass = all(checks.values())

    print(f"\n  Validation checks: {'REPRODUCED' if all_pass else 'DISCREPANCY'}")
    print(f"  Metric            | Actual          | Live ref        | Delta    | OK?")
    print(f"  {'-'*70}")
    print(f"  OOS trades        | {actual_trades:<15} | {ref['total_oos_trades']:<15} | {trade_diff:<8} | {'OK' if checks['oos_trades_within_10'] else 'FAIL'}")
    print(f"  pf_ci_lower       | {actual_pf_ci:<15.4f} | {ref['pf_ci_lower']:<15.4f} | {pf_ci_pct_diff:<7.1f}% | {'OK' if checks['pf_ci_within_15pct'] else 'FAIL'}")
    print(f"  mc_dd_pct         | {actual_mc_dd:<15.4f} | {ref['mc_95th_dd_pct']:<15.4f} | {mc_dd_diff:<8.4f} | {'OK' if checks['mc_dd_within_1_5pct'] else 'FAIL'}")
    print(f"  verdict           | {actual_verdict or '?':<15} | {'PASS':<15} | -        | {'OK' if checks['verdict_pass'] else 'FAIL'}")
    print(f"  passed_via        | {actual_via or '?':<15} | {'alt':<15} | -        | {'OK' if checks['passed_via_alt'] else 'FAIL'}")

    if not all_pass:
        failing = [k for k, v in checks.items() if not v]
        print(f"\n  [DISCREPANCY] Failing checks: {failing}")
        print("  The harness does NOT fully reproduce live. There may be a remaining")
        print("  config/data difference beyond test_months.")
    else:
        print("\n  [REPRODUCED] Harness confirmed live-comparable. ADX results are apples-to-apples.")

    return all_pass, result


# ---------------------------------------------------------------------------
# ADX sweep: one verdict per threshold under the live config
# ---------------------------------------------------------------------------


def run_adx_sweep(df_mgc: pd.DataFrame) -> dict[int, dict]:
    """Run ADX-conditioned trend at each threshold under the live WFO config.

    Grid per threshold is the full 8-combo live grid (not champion-only)
    so WFO IS-selection can pick the best combo per window including ADX
    threshold variation. This is intentionally the same as plain: same IS
    grid but entries additionally gated by ADX >= threshold.

    Each threshold gets its own verdict JSON.
    """
    print(f"\n{'='*70}")
    print("=== ADX SWEEP: adx_threshold in {14, 18, 22, 25} under live config ===")
    print(f"  Grid per threshold: {len(LIVE_GRID)} combos x {{fast,slow,atr_trail_mult}}")
    print(f"  WFO: train={LIVE_TRAIN_MONTHS}mo test={LIVE_TEST_MONTHS}mo step={LIVE_STEP_MONTHS}mo")

    adx_results: dict[int, dict] = {}

    for thresh in ADX_THRESHOLDS:
        # Build grid with the fixed adx_threshold injected into each combo
        adx_grid = [
            {**combo, "adx_threshold": float(thresh)}
            for combo in LIVE_GRID
        ]
        label = f"MGC_adx{thresh:02d}_live_config"
        r = run_hypothesis(
            label=label,
            symbol="MGC",
            signal_fn=generate_adx_sma_trend_signals,
            param_grid=adx_grid,
            df=df_mgc,
            min_oos_trades_per_window=1,
        )
        adx_results[thresh] = r

    return adx_results


# ---------------------------------------------------------------------------
# Comparison table
# ---------------------------------------------------------------------------


def print_comparison_table(plain_result: dict, adx_results: dict[int, dict]) -> None:
    print(f"\n\n{'='*70}")
    print("=== LIVE-CONFIG COMPARISON: plain vs ADX-conditioned ===")
    print(f"  {'label':<28} {'verdict':<10} {'via':<8} {'pf_ci':<8} {'p_edge':<8} "
          f"{'mc_dd%':<8} {'dsr':<8} {'OOS':<6} {'block'}")
    print(f"  {'-'*100}")

    def _row(label: str, r: dict) -> None:
        g = r.get("gate_v2_metrics", {})
        print(
            f"  {label:<28} "
            f"{r.get('verdict','?'):<10} "
            f"{r.get('passed_via') or 'n/a':<8} "
            f"{g.get('pf_ci_lower') or 'n/a':<8} "
            f"{g.get('p_edge') or 'n/a':<8} "
            f"{g.get('mc_95th_dd_pct') or 'n/a':<8} "
            f"{g.get('dsr') or 'n/a':<8} "
            f"{g.get('total_oos_trades') or 0:<6} "
            f"{r.get('primary_block') or ''}"
        )

    _row("plain_trend (live config)", plain_result)
    for thresh, r in sorted(adx_results.items()):
        _row(f"ADX>={thresh} (live config)", r)

    # Interpretation
    plain_gate = plain_result.get("gate_v2_metrics", {})
    plain_pf = plain_gate.get("pf_ci_lower", 0.0) or 0.0
    plain_oos = plain_gate.get("total_oos_trades", 0) or 0

    improvements = []
    degradations = []
    neutrals = []
    for thresh, r in sorted(adx_results.items()):
        g = r.get("gate_v2_metrics", {})
        adx_pf = g.get("pf_ci_lower", 0.0) or 0.0
        adx_oos = g.get("total_oos_trades", 0) or 0
        adx_verdict = r.get("verdict", "FAIL")
        if adx_verdict == "PASS" and adx_pf > plain_pf:
            improvements.append(thresh)
        elif adx_oos < plain_oos * 0.7:
            degradations.append(thresh)  # >30% OOS trade loss
        elif adx_verdict == "FAIL":
            degradations.append(thresh)
        else:
            neutrals.append(thresh)

    print(f"\n  INTERPRETATION:")
    if improvements:
        print(f"    ADX improves vs plain under live config: thresholds {improvements}")
        print(f"    -> ADX activation JUSTIFIED for these thresholds.")
    if neutrals:
        print(f"    ADX neutral vs plain: thresholds {neutrals}")
    if degradations:
        print(f"    ADX degrades vs plain: thresholds {degradations}")
        print(f"    -> These thresholds reduce sample size without metric improvement.")

    if not improvements:
        print(f"    -> CONCLUSION: ADX does NOT improve on plain trend under the live methodology.")
        print(f"       Activating ADX conditioning on MGC is NOT justified.")
    else:
        best_thresh = max(improvements, key=lambda t: adx_results[t].get("gate_v2_metrics", {}).get("pf_ci_lower", 0) or 0)
        print(f"    -> CONCLUSION: ADX with threshold={best_thresh} outperforms plain under live methodology.")
        print(f"       ADX activation JUSTIFIED. Recommend threshold={best_thresh}.")

    print(f"\n  Output dir: {OUTPUT_DIR}")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="WFO live-config match — MGC plain vs ADX")
    parser.add_argument("--validate-only", action="store_true",
                        help="Run validation only (plain trend reproduction check)")
    parser.add_argument("--adx-only", action="store_true",
                        help="Skip validation, run ADX sweep only (skips plain validation)")
    parser.add_argument("--skip-validate", action="store_true",
                        help="Skip validation gate (dangerous: do not trust ADX results if plain fails)")
    args = parser.parse_args()

    df_mgc = load_bars("MGC")

    if args.adx_only:
        adx_results = run_adx_sweep(df_mgc)
        print("\n[DONE] ADX sweep complete. No plain-trend comparison available (--adx-only).")
        return

    # Step 1: Validation — reproduce live rank4
    reproduced, plain_result = run_validation(df_mgc)

    if args.validate_only:
        print("\n[DONE] Validation-only mode.")
        return

    if not reproduced and not args.skip_validate:
        print("\n[ABORT] Validation failed — harness does not reproduce live metrics.")
        print("  Use --skip-validate to proceed anyway (results will NOT be live-comparable).")
        sys.exit(1)
    elif not reproduced:
        print("\n[WARN] Proceeding despite validation failure (--skip-validate). Results may not be live-comparable.")

    # Step 2: ADX sweep under live config
    adx_results = run_adx_sweep(df_mgc)

    # Step 3: Comparison table + interpretation
    print_comparison_table(plain_result, adx_results)


if __name__ == "__main__":
    main()
