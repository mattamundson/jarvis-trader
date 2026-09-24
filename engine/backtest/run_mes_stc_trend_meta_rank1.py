#!/usr/bin/env python
"""
MES STC + Trend-Agreement Meta-Label — Rank 1

New candidate family (2026-09-02), NOT a rehash of the ~30 prior MES
candidates on file. Motivation: the raw STC 5-layer signal (generate_signals,
signals.py) fires often (1580 raw ENTRY_NOW bars over 2024-06..2026-03) but
is unprofitable on its own (PF 0.35 full-sample). The SMA(50/55/60,200) trend
family (rank7-11) has a real edge in places but fires too rarely (17-38 OOS
trades total) to ever clear the 30-trade sample floor. Meta-labeling
(Lopez de Prado, Advances in Financial ML ch.3) separates "which direction"
from "should I take it": here the STC signal supplies direction/entries at
its native frequency, and an SMA(trend_fast, trend_slow) trend-agreement
filter is the meta-label that vetoes STC entries whose direction disagrees
with the prevailing trend. This can only remove entries (never add), so it
raises precision without inventing sample size the base signal doesn't have
-- if the base signal's raw frequency isn't enough to survive the filter and
still clear MIN_OOS_TRADES_TOTAL, that is itself the honest result.

Primary model : generate_signals() STC 15/83 + 5-layer regime (signals.py;
                already-shipped, not re-tuned here -- locked per
                ml-pitfalls-defense.md "lock the strategy spec before running").
Meta-label    : keep ENTRY_NOW only when bias direction (BULL/BEAR) agrees
                with SMA(trend_fast, trend_slow) trend state at that bar.
                Disagreeing entries are downgraded to NO_TRADE. Additive-only
                filter -- cannot create an entry the primary model didn't.

Grid (1 free dimension -- trend_slow; trend_fast fixed at 50, mirroring the
SMA-trend family's own champion fast period so this isn't a fresh multiple-
testing surface):
    trend_fast: 50 (fixed)
    trend_slow: [100, 150, 200]
    3 combos total.

WFO config: same as rank7-11 (TRAIN=6mo, TEST=1mo, STEP=1mo) for methodology
parity/comparability.

Data: MES 1h, widest available cache (same _find_latest_cache convention as
the trend family).
Writes: engine/data/gate_v2_verdicts/MES_stc_trend_meta_rank1.json

Usage (from engine/ directory):
    .venv/Scripts/python backtest/run_mes_stc_trend_meta_rank1.py
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

from backtest.contract_specs import CONTRACT_SPECS  # noqa: E402

SYMBOL = "MES"
MULTIPLIER = 5.0
CAPITAL = 50_000.0
TICK_SIZE = 0.25
COMMISSION = CONTRACT_SPECS["MES"].commission
SLIPPAGE_TICKS = 2.0

TRAIN_MONTHS = 6
TEST_MONTHS = 1
STEP_MONTHS = 1

TREND_FAST_FIXED = 50
TREND_SLOW_VALUES = [100, 150, 200]

COST_SWEEP_TIERS = {
    "optimistic": {"commission": 0.31, "slippage_ticks": 1.0},
    "realistic": {"commission": 0.62, "slippage_ticks": 2.0},
    "pessimistic": {"commission": 1.24, "slippage_ticks": 3.0},
    "catastrophic": {"commission": 2.48, "slippage_ticks": 4.0},
}

MIN_OOS_TRADES_PER_WINDOW = 1


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


_STC_BASE_CACHE: dict[int, pd.DataFrame] = {}


def _stc_base_signals(df_full: pd.DataFrame) -> pd.DataFrame:
    """Compute the STC 5-layer primary signal ONCE on the full dataset.

    generate_signals() does expensive per-bar work (indicator stack + Discord
    IB level DB lookups), so it must not be re-run per window x combo (~100+
    calls). STC/regime indicators are causal (backward-looking only), so
    computing on the full series then slicing by date per window/combo below
    introduces no look-ahead -- each bar's entry_signal only reflects bars
    <= that bar either way.
    """
    key = id(df_full)
    cached = _STC_BASE_CACHE.get(key)
    if cached is not None:
        return cached
    from backtest.signals import generate_signals

    _STC_BASE_CACHE.clear()  # single full-dataset df per run; avoid unbounded growth
    df_sig = generate_signals(df_full, symbol=SYMBOL, regime_filter=True)
    _STC_BASE_CACHE[key] = df_sig
    return df_sig


def _generate_stc_trend_meta_signals(
    df: pd.DataFrame, trend_fast: int, trend_slow: int, df_sig_base: pd.DataFrame | None = None
) -> pd.DataFrame:
    """STC 5-layer primary entries, gated by an SMA trend-agreement meta-label.

    Additive-only: only ever downgrades ENTRY_NOW -> NO_TRADE, never the reverse.
    """
    df_sig = (df_sig_base if df_sig_base is not None else _stc_base_signals(df)).copy()

    sma_f = df_sig["close"].rolling(trend_fast).mean()
    sma_s = df_sig["close"].rolling(trend_slow).mean()
    trend_bull = (sma_f > sma_s).fillna(False).to_numpy()
    trend_bear = (sma_f < sma_s).fillna(False).to_numpy()

    entry = df_sig["entry_signal"].to_numpy(copy=True)
    bias_str = df_sig["bias"].astype(str)
    is_entry = entry == "ENTRY_NOW"
    is_bull_bias = bias_str.str.contains("BULL", na=False).to_numpy()
    is_bear_bias = bias_str.str.contains("BEAR", na=False).to_numpy()

    keep = is_entry & (
        (is_bull_bias & trend_bull) | (is_bear_bias & trend_bear)
    )
    df_sig["entry_signal"] = np.where(is_entry & ~keep, "NO_TRADE", entry)
    return df_sig


def _run_signals_and_backtest(
    df_sig_base: pd.DataFrame,
    trend_fast: int,
    trend_slow: int,
    _unused: float,
    commission: float = COMMISSION,
    slippage_ticks: float = SLIPPAGE_TICKS,
) -> object:
    """df_sig_base must already carry entry_signal/bias/stop_level/target_1-3
    from a prior _stc_base_signals() call, sliced to the desired date range."""
    from backtest.backtester import Backtester

    df_sig = _generate_stc_trend_meta_signals(
        df_sig_base, trend_fast=trend_fast, trend_slow=trend_slow, df_sig_base=df_sig_base
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
    for trend_fast, trend_slow, _unused in grid:
        try:
            result = _run_signals_and_backtest(df_train, trend_fast, trend_slow, _unused)
        except Exception as exc:
            print(f"    [WARN] IS error ({trend_fast},{trend_slow}): {exc}")
            continue
        if result.total_trades < MIN_OOS_TRADES_PER_WINDOW:
            continue
        pf = result.profit_factor
        if pf > best_pf:
            best_pf = pf
            best_params = {"trend_fast": trend_fast, "trend_slow": trend_slow}
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
    MIN_OOS_TRADES_TOTAL,
    _find_latest_cache,
    sample_adequacy_enforced,
)
from backtest._gate_v2_helpers import (  # noqa: E402
    classify_wfo_consistency as _classify_wfo_consistency,
)


def _run_fixed_params_sweep(df: pd.DataFrame, grid: list[tuple]) -> dict:
    pfs = []
    combo_results = []
    for trend_fast, trend_slow, _unused in grid:
        try:
            result = _run_signals_and_backtest(df, trend_fast, trend_slow, _unused)
            if result.total_trades >= MIN_OOS_TRADES_PER_WINDOW:
                pfs.append(result.profit_factor)
                combo_results.append(
                    {
                        "trend_fast": trend_fast,
                        "trend_slow": trend_slow,
                        "pf": round(result.profit_factor, 4),
                        "trades": result.total_trades,
                    }
                )
                print(
                    f"    combo (fast={trend_fast:3d}, slow={trend_slow:3d}): "
                    f"PF={result.profit_factor:.4f}  trades={result.total_trades}"
                )
            else:
                print(
                    f"    combo (fast={trend_fast:3d}, slow={trend_slow:3d}): "
                    f"SKIP (only {result.total_trades} trades)"
                )
        except Exception as exc:
            print(f"  [WARN] fixed-params error ({trend_fast},{trend_slow}): {exc}")
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


def _run_cost_sweep(df: pd.DataFrame, champion_params: dict) -> dict:
    results = {}
    cost_survives_through = "none"
    survival_intact = True
    for tier in COST_TIER_ORDER:
        costs = COST_SWEEP_TIERS[tier]
        try:
            result = _run_signals_and_backtest(
                df,
                trend_fast=champion_params["trend_fast"],
                trend_slow=champion_params["trend_slow"],
                _unused=0.0,
                commission=costs["commission"],
                slippage_ticks=costs["slippage_ticks"],
            )
            pf = result.profit_factor
            passes = pf > 1.0 and result.total_trades >= MIN_OOS_TRADES_PER_WINDOW
            results[tier] = {"pf": round(pf, 4), "trades": result.total_trades, "passes": passes}
            print(
                f"    [{tier:12s}] commission={costs['commission']:.2f}  "
                f"slip={costs['slippage_ticks']:.1f}t  PF={pf:.4f}  "
                f"trades={result.total_trades}  {'PASS' if passes else 'FAIL'}"
            )
            if survival_intact and passes:
                cost_survives_through = tier
            elif not passes:
                survival_intact = False
        except Exception as exc:
            print(f"  [WARN] cost-sweep error at {tier}: {exc}")
            results[tier] = {"pf": 0.0, "trades": 0, "passes": False}
            survival_intact = False
    return {"cost_survives_through": cost_survives_through, "tier_results": results}


def _compute_gate_v2(
    oos_results: list,
    n_grid_combos: int,
    fixed_params_metrics: dict,
    cost_sweep_metrics: dict,
) -> dict:
    from backtest._gate_v2_trade_metrics import (
        trade_level_dsr,
        trade_level_mc_95th_dd,
        trade_level_p_edge,
        trade_level_pf_ci_lower,
        trade_level_win_rate_ci_lower,
    )

    oos_pfs = [r.profit_factor for r in oos_results if r.total_trades >= MIN_OOS_TRADES_PER_WINDOW]
    oos_dds = [r.max_drawdown_pct for r in oos_results]
    all_trades = sum(r.total_trades for r in oos_results)
    sample_adequate = all_trades >= MIN_OOS_TRADES_TOTAL

    pf_ci_lower = trade_level_pf_ci_lower(oos_results)
    p_edge = trade_level_p_edge(oos_results)
    mc_95th_dd = trade_level_mc_95th_dd(oos_results, initial_capital=CAPITAL)
    dsr = trade_level_dsr(oos_results, n_grid_combos=n_grid_combos, initial_capital=CAPITAL)
    win_rate_ci_lower = trade_level_win_rate_ci_lower(oos_results)
    mc_95th_dd_window_legacy = float(np.percentile(oos_dds, 95.0)) if oos_dds else 1.0

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

    core_reasons = []
    core_reasons.append(
        f"mbb_pf_ci_lower={pf_ci_lower:.4f} {'>=' if pf_ci_lower >= GATE_PF_CI_LOWER else '<'} {GATE_PF_CI_LOWER}"
    )
    core_reasons.append(
        f"p_positive_edge={p_edge:.4f} {'>=' if p_edge >= GATE_P_EDGE else '<'} {GATE_P_EDGE}"
    )
    core_reasons.append(
        f"mc_95th_dd_pct={mc_95th_dd * 100:.4f} {'<=' if mc_95th_dd <= GATE_MC_DD_CORE else '>'} {GATE_MC_DD_CORE * 100:.1f}"
    )
    core_reasons.append(f"dsr={dsr:.6f} {'>=' if dsr >= GATE_DSR else '<'} {GATE_DSR} (not selection-bias)")

    alt_reasons = []
    alt_reasons.append(
        f"dsr={dsr:.6f} >= {GATE_DSR_ALT} (alt floor)"
        if dsr >= GATE_DSR_ALT
        else f"FAIL dsr={dsr:.6f} < {GATE_DSR_ALT} (alt floor)"
    )
    alt_reasons.append(
        f"rolling_wfo={wfo_consistency} in {GATE_WFO_CONSISTENCY_VALUES}"
        if wfo_consistency in GATE_WFO_CONSISTENCY_VALUES
        else f"FAIL rolling_wfo={wfo_consistency} not in {GATE_WFO_CONSISTENCY_VALUES}"
    )
    alt_reasons.append(
        f"fixed_params_min_pf={fixed_params_min_pf:.3f} >= {GATE_FIXED_PARAMS_MIN_PF}"
        if fixed_params_min_pf >= GATE_FIXED_PARAMS_MIN_PF
        else f"FAIL fixed_params_min_pf={fixed_params_min_pf:.3f} < {GATE_FIXED_PARAMS_MIN_PF}"
    )
    alt_reasons.append(
        f"cost_survives_through={cost_survives_through} >= realistic"
        if cost_passes
        else f"FAIL cost_survives_through={cost_survives_through} < realistic"
    )
    alt_reasons.append(
        f"mc_95th_dd_pct={mc_95th_dd * 100:.4f} <= {GATE_MC_DD_ALT * 100:.1f} (alt ceiling)"
        if mc_95th_dd <= GATE_MC_DD_ALT
        else f"FAIL mc_95th_dd_pct={mc_95th_dd * 100:.4f} > {GATE_MC_DD_ALT * 100:.1f} (alt ceiling)"
    )

    n_core_passed = sum(1 for r in core_reasons if not r.startswith("FAIL"))
    n_alt_passed = sum(1 for r in alt_reasons if not r.startswith("FAIL"))

    if sample_adequacy_enforced() and not sample_adequate:
        verdict = "INSUFFICIENT_SAMPLE"
        passed_via = None
    elif core_pass:
        verdict = "PASS"
        passed_via = "core"
    elif alt_pass:
        verdict = "PASS"
        passed_via = "alt"
    else:
        verdict = "FAIL"
        passed_via = None

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
        "min_oos_trades_total": MIN_OOS_TRADES_TOTAL,
        "sample_adequate": sample_adequate,
        "win_rate_ci_lower": round(win_rate_ci_lower, 4),
        "core_reasons": core_reasons,
        "alt_reasons": alt_reasons,
        "reasons": core_reasons + alt_reasons,
    }


def run_wfo() -> dict:
    data_dir = engine_root / "backtest" / "cache"
    data_file = _find_latest_cache(data_dir, "MES")
    print(f"[MES-STC-META-R1] Selected {data_file.name}")
    df = _load_data(data_file)
    print(f"[MES-STC-META-R1] {len(df)} bars | {df.index.min().date()} -> {df.index.max().date()}")

    windows = _generate_windows(df)
    if not windows:
        print("[MES-STC-META-R1] ERROR: not enough data to form windows.")
        return {}

    print("[MES-STC-META-R1] Computing STC 5-layer base signal once on full dataset...")
    df_sig_full = _stc_base_signals(df)
    n_raw_entries = int((df_sig_full["entry_signal"] == "ENTRY_NOW").sum())
    print(f"[MES-STC-META-R1] {n_raw_entries} raw STC ENTRY_NOW bars before trend-meta filter.")

    grid = [(TREND_FAST_FIXED, slow, 0.0) for slow in TREND_SLOW_VALUES]
    n_combos = len(grid)

    print(f"\n{'=' * 70}")
    print("=== MES STC + TREND-AGREEMENT META-LABEL — RANK 1 ===")
    print(f"Windows target | Train: {TRAIN_MONTHS}mo | Test: {TEST_MONTHS}mo | Step: {STEP_MONTHS}mo")
    print(f"Grid: {n_combos} combos | trend_fast={TREND_FAST_FIXED} (fixed) | trend_slow={TREND_SLOW_VALUES}")
    print("Primary: generate_signals() STC 15/83 + 5-layer regime (locked, not re-tuned)")
    print(f"{'=' * 70}")

    oos_results = []
    window_records = []

    for win in windows:
        wnum = win["window_num"]
        ts, te, os_, oe = win["train_start"], win["train_end"], win["test_start"], win["test_end"]
        print(
            f"\nWindow {wnum}: IS {ts.strftime('%Y-%m')}->{te.strftime('%Y-%m')}  "
            f"OOS {os_.strftime('%Y-%m')}->{oe.strftime('%Y-%m')}  ({win['n_train']} / {win['n_test']} bars)"
        )
        df_train = df_sig_full[(df_sig_full.index >= ts) & (df_sig_full.index < te)].copy()
        df_test = df_sig_full[(df_sig_full.index >= os_) & (df_sig_full.index <= oe)].copy()

        best_params, is_result = _best_is_params(df_train, grid)
        if best_params is None:
            print(f"  [SKIP] No valid IS params (all combos < {MIN_OOS_TRADES_PER_WINDOW} trades or errored)")
            continue

        print(
            f"  Best IS: trend_fast={best_params['trend_fast']}  trend_slow={best_params['trend_slow']}  "
            f"PF={is_result.profit_factor:.2f}  trades={is_result.total_trades}"
        )

        try:
            oos_result = _run_signals_and_backtest(
                df_test, best_params["trend_fast"], best_params["trend_slow"], 0.0
            )
        except Exception as exc:
            print(f"  [SKIP] OOS error: {exc}")
            continue

        print(
            f"  OOS:     PF={oos_result.profit_factor:.2f}  DD={oos_result.max_drawdown_pct:.1%}  "
            f"Sharpe={oos_result.sharpe_ratio:.2f}  trades={oos_result.total_trades}"
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
        print("\n[MES-STC-META-R1] No OOS results — WFO aborted.")
        return {}

    print(f"\n[MES-STC-META-R1] Running fixed-params sweep on full dataset ({n_combos} combos)...")
    fixed_params_metrics = _run_fixed_params_sweep(df_sig_full, grid)
    print(f"  fixed_params_min_pf  = {fixed_params_metrics['fixed_params_min_pf']:.4f}  (need >= {GATE_FIXED_PARAMS_MIN_PF})")
    print(f"  fixed_params_mean_pf = {fixed_params_metrics['fixed_params_mean_pf']:.4f}")

    from collections import Counter

    param_votes = Counter(
        (r["best_params"]["trend_fast"], r["best_params"]["trend_slow"]) for r in window_records
    )
    most_selected = param_votes.most_common(1)[0][0] if param_votes else (TREND_FAST_FIXED, 200)
    champion_params = {"trend_fast": most_selected[0], "trend_slow": most_selected[1]}
    print(
        f"\n[MES-STC-META-R1] Running cost sweep (champion: trend_fast={champion_params['trend_fast']}, "
        f"trend_slow={champion_params['trend_slow']})..."
    )
    cost_sweep_metrics = _run_cost_sweep(df_sig_full, champion_params)
    print(f"  cost_survives_through = {cost_sweep_metrics['cost_survives_through']}  (need >= 'realistic')")

    gate = _compute_gate_v2(oos_results, n_combos, fixed_params_metrics, cost_sweep_metrics)

    print(f"\n{'=' * 70}")
    print(f"=== GATE v2 VERDICT: {gate['verdict']} (via {gate['passed_via'] or 'NONE'}) ===")
    print(f"  pf_ci_lower          = {gate['pf_ci_lower']:.4f}  (need >= {GATE_PF_CI_LOWER})")
    print(f"  p_edge               = {gate['p_edge']:.4f}  (need >= {GATE_P_EDGE})")
    print(f"  mc_95th_dd           = {gate['mc_95th_dd_pct']:.4f}%  (need <= {GATE_MC_DD_CORE * 100:.0f}% core / {GATE_MC_DD_ALT * 100:.0f}% alt)")
    print(f"  dsr                  = {gate['dsr']:.6f}  (need >= {GATE_DSR} core / {GATE_DSR_ALT} alt)")
    print(f"  wfo_consistency      = {gate['wfo_consistency']}  (ALT accepts: {GATE_WFO_CONSISTENCY_VALUES})")
    print(f"  fixed_params_min_pf  = {gate['fixed_params_min_pf']:.4f}  (need >= {GATE_FIXED_PARAMS_MIN_PF})")
    print(f"  cost_survives_through= {gate['cost_survives_through']}  (need >= 'realistic')")
    print(f"  core_verdict         = {gate['core_verdict']}")
    print(f"  alt_verdict          = {gate['alt_verdict']}")
    print(f"  OOS windows          = {gate['n_oos_windows_with_trades']} with trades / {gate['n_oos_windows']} total")
    print(f"  Total OOS trades     = {gate['total_oos_trades']}  (need >= {MIN_OOS_TRADES_TOTAL})")
    print(f"{'=' * 70}")

    verdicts_dir = engine_root / "data" / "gate_v2_verdicts"
    verdicts_dir.mkdir(parents=True, exist_ok=True)
    verdict_file = verdicts_dir / "MES_stc_trend_meta_rank1.json"

    verdict_doc = {
        "symbol": SYMBOL,
        "family": "stc_trend_meta",
        "rank": 1,
        "verdict": gate["verdict"],
        "passed_via": gate["passed_via"],
        "core_verdict": gate["core_verdict"],
        "alt_verdict": gate["alt_verdict"],
        "n_core_passed": gate["n_core_passed"],
        "n_alt_passed": gate["n_alt_passed"],
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
        "gate_v2": {
            "verdict": gate["verdict"],
            "passed_via": gate["passed_via"],
            "core_verdict": gate["core_verdict"],
            "alt_verdict": gate["alt_verdict"],
            "core_reasons": gate["core_reasons"],
            "alt_reasons": gate["alt_reasons"],
            "reasons": gate["reasons"],
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
            "grid_trend_fast": TREND_FAST_FIXED,
            "grid_trend_slow": TREND_SLOW_VALUES,
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
            "combo_results": fixed_params_metrics.get("combo_results", []),
            "cost_survives_through": gate["cost_survives_through"],
            "cost_tier_results": cost_sweep_metrics.get("tier_results", {}),
            "total_oos_trades": gate["total_oos_trades"],
            "min_oos_trades_total": gate["min_oos_trades_total"],
            "sample_adequate": gate["sample_adequate"],
            "win_rate_ci_lower": gate["win_rate_ci_lower"],
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
    }

    verdict_file.write_text(json.dumps(verdict_doc, indent=2, default=str))
    print(f"\n[MES-STC-META-R1] Verdict written -> {verdict_file}")
    return verdict_doc


def main():
    verdict = run_wfo()
    if not verdict:
        print("[MES-STC-META-R1] No verdict produced — check data/logs above.")
        sys.exit(1)
    final = verdict.get("verdict", "FAIL")
    print(f"\n[{final}] MES STC+Trend-Meta Rank 1: {final} (via {verdict.get('passed_via') or 'none'}).")


if __name__ == "__main__":
    main()
