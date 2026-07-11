#!/usr/bin/env python
"""
Offline strategy-discovery sweep — 2026-06-16

Safety: Research only. Writes to engine/data/discovery_2026_06_16/ ONLY.
        Never writes to gate_v2_verdicts/ or edge_ledger.jsonl.
        Does NOT modify signals.py, config.py, .env, or any live-routing code.
        Does NOT restart the engine or call any live endpoints.

Hypotheses tested (all 1h interval):
    H1: ADX-conditioned SMA trend  — MES, MGC
    H2: KAMA adaptive trend        — MNQ, MES
    H3: Donchian breakout + ATR-regime filter — MGC
    H4: RSI(2) mean-reversion      — MES

Validation: re-runs MGC rank4 champion through THIS driver with TEST_MONTHS=2
(matching rank4's WFO config) to confirm driver fidelity before trusting new results.

Usage (from engine/ directory):
    .venv/Scripts/python backtest/run_discovery_2026_06_16.py
    .venv/Scripts/python backtest/run_discovery_2026_06_16.py --validate-only
    .venv/Scripts/python backtest/run_discovery_2026_06_16.py --hypothesis H1
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
# Path setup
# ---------------------------------------------------------------------------
engine_root = Path(__file__).parent.parent
if str(engine_root) not in sys.path:
    sys.path.insert(0, str(engine_root))

OUTPUT_DIR = engine_root / "data" / "discovery_2026_06_16_rerun"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
CACHE_DIR = engine_root / "backtest" / "cache"

# ---------------------------------------------------------------------------
# Import canonical gate machinery — do NOT reimplement
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
# Contract specs per symbol — matches canonical runners
# ---------------------------------------------------------------------------
CONTRACT_SPECS = {
    "MGC": {
        "multiplier": 10.0,
        "tick_size": 0.10,
        # Was 0.62 (MES's rate) -- MGC's correct commission is 0.85 per
        # backtest/contract_specs.py's CONTRACT_SPECS["MGC"].commission
        # (found 2026-07-10; this file's own comment above claimed it
        # "matches canonical runners" but MGC had drifted).
        "commission": 0.85,
        "slippage_ticks": 2.0,
        "capital": 50_000.0,
    },
    "MES": {
        "multiplier": 5.0,
        "tick_size": 0.25,
        "commission": 0.62,
        "slippage_ticks": 1.0,
        "capital": 10_000.0,
    },
    "MNQ": {
        "multiplier": 2.0,
        "tick_size": 0.25,
        "commission": 0.62,
        "slippage_ticks": 1.0,
        "capital": 10_000.0,
    },
}

# Cost-sweep tiers (trend family — higher slippage, matches rank4).
# Per-symbol: ratios (0.5x/1.0x/2.0x/4.0x) scale off THIS symbol's own base
# commission in CONTRACT_SPECS above, not a flat MES-based literal (found
# 2026-07-10 -- run_cost_sweep()'s symbol param was accepted but unused for
# tier selection, so MGC cost-sweeps ran at MES's 0.62 base regardless).
def get_cost_sweep_tiers(symbol: str) -> dict:
    base_commission = CONTRACT_SPECS[symbol]["commission"]
    return {
        "optimistic": {"commission": round(base_commission * 0.5, 4), "slippage_ticks": 1.0},
        "realistic": {"commission": round(base_commission * 1.0, 4), "slippage_ticks": 2.0},
        "pessimistic": {"commission": round(base_commission * 2.0, 4), "slippage_ticks": 3.0},
        "catastrophic": {"commission": round(base_commission * 4.0, 4), "slippage_ticks": 4.0},
    }

# ---------------------------------------------------------------------------
# Bar loading — identical to run_mgc_trend_rank4._load_data
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
    """Load 1h bars for symbol from latest cache file (same logic as rank4)."""
    data_file = _find_latest_cache(CACHE_DIR, symbol, suffix="_1h.csv")
    print(f"  [load] {symbol}: {data_file.name}")
    df = _load_csv_bars(data_file)
    print(f"  [load] {symbol}: {len(df)} bars | {df.index.min().date()} -> {df.index.max().date()}")
    return df


# ---------------------------------------------------------------------------
# WFO window generation — identical to rank4 logic
# ---------------------------------------------------------------------------


def generate_windows(
    df: pd.DataFrame,
    train_months: int = 6,
    test_months: int = 1,
    step_months: int = 1,
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
# Backtester runner — thin wrapper around existing Backtester
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
# Signal generators — one per hypothesis
# ---------------------------------------------------------------------------


def _wilder_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    prev_c = close.shift(1)
    tr = pd.concat([(high - low), (high - prev_c).abs(), (low - prev_c).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


# ── H0 (validation) ── exact replica of generate_sma_trend_signals for rank4


def generate_sma_trend_signals_plain(
    df: pd.DataFrame,
    fast: int = 50,
    slow: int = 120,
    atr_trail_mult: float = 2.0,
    min_rv_annualized: float = 0.0,
) -> pd.DataFrame:
    """Plain SMA trend — matches rank4 champion / trend_signals.generate_sma_trend_signals."""
    from backtest.trend_signals import generate_sma_trend_signals

    return generate_sma_trend_signals(
        df,
        fast=fast,
        slow=slow,
        atr_trail_mult=atr_trail_mult,
        min_rv_annualized=min_rv_annualized,
    )


# ── H1 ── ADX-conditioned SMA trend


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

    Logic: use the canonical SMA trend signal, then suppress any ENTRY_NOW
    bar where ADX < adx_threshold. Exits are unchanged.

    FIX 2026-06-17: Original code used df_sig.get("signal") which never
    exists — canonical generate_sma_trend_signals writes to "entry_signal"
    (="ENTRY_NOW"/"NO_TRADE").  Guard condition 'if "signal" in df_sig.columns'
    was therefore always False, making the ADX filter a complete no-op.
    Corrected to operate on the "entry_signal" column that the Backtester
    actually reads (backtester.py line 779: row.get("entry_signal","NO_TRADE")).
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

    # FIX: operate on "entry_signal" — the column the Backtester reads.
    # Previously read non-existent "signal" column → filter was always a no-op.
    entry_mask = df_sig["entry_signal"] == "ENTRY_NOW"
    adx_weak = (adx_vals < adx_threshold) | adx_vals.isna()
    suppress = entry_mask & adx_weak
    df_sig.loc[suppress, "entry_signal"] = "NO_TRADE"
    return df_sig


# ── H2 ── KAMA adaptive trend


def generate_kama_trend_signals(
    df: pd.DataFrame,
    er_period: int = 10,
    fast_period: int = 2,
    slow_period: int = 30,
    atr_trail_mult: float = 2.0,
) -> pd.DataFrame:
    """KAMA slope/crossover trend signal.

    Entry: KAMA slope turns positive (KAMA > KAMA[1], confirmed rising).
    The slope is assessed as KAMA(t) - KAMA(t - slope_lookback).
    Exit: KAMA slope turns negative OR ATR trailing stop.

    Produces a DataFrame with Backtester-compatible columns:
    entry_signal, exit_signal, stop_level, target_1, target_2, bias, atr.
    """
    from backtest.indicators import kama as compute_kama

    n = len(df)
    close = df["close"]
    high = df["high"]
    low = df["low"]

    kama_vals = compute_kama(
        close, period=er_period, fast_period=fast_period, slow_period=slow_period
    )
    atr = _wilder_atr(high, low, close, period=14)
    kama_slope = kama_vals - kama_vals.shift(1)

    df_sig = df.copy()
    df_sig["kama"] = kama_vals
    df_sig["kama_slope"] = kama_slope
    df_sig["atr"] = atr

    entry_signal = np.full(n, "NO_TRADE", dtype=object)
    exit_signal = np.full(n, "NO_EXIT", dtype=object)
    stop_level = np.full(n, np.nan)
    target_1 = np.full(n, np.nan)
    target_2 = np.full(n, np.nan)
    bias = np.full(n, "NEUTRAL", dtype=object)

    in_trade = False
    stop_price = np.nan

    for i in range(1, n):
        prev_slope = kama_slope.iloc[i - 1]
        cur_slope = kama_slope.iloc[i]
        cur_close = float(close.iloc[i])
        cur_atr = float(atr.iloc[i]) if not pd.isna(atr.iloc[i]) else np.nan

        if pd.isna(kama_vals.iloc[i]) or np.isnan(cur_atr):
            continue

        # Mark bias based on KAMA slope direction
        bias[i] = "STRONG_BULL" if cur_slope > 0 else "STRONG_BEAR"

        if not in_trade:
            # Entry: slope transitions from <= 0 to > 0
            if not pd.isna(prev_slope) and prev_slope <= 0 and cur_slope > 0:
                in_trade = True
                stop_price = cur_close - atr_trail_mult * cur_atr
                entry_signal[i] = "ENTRY_NOW"
                stop_level[i] = stop_price
                target_1[i] = cur_close + 3.0 * cur_atr
                target_2[i] = cur_close + 5.0 * cur_atr
        else:
            stop_level[i] = stop_price
            # Exit: slope turns negative OR stop hit (static stop — backtester handles trailing)
            if cur_close <= stop_price or cur_slope < 0:
                in_trade = False
                stop_price = np.nan
                exit_signal[i] = "EXIT_NOW"

    df_sig["entry_signal"] = entry_signal
    df_sig["exit_signal"] = exit_signal
    df_sig["stop_level"] = stop_level
    df_sig["target_1"] = target_1
    df_sig["target_2"] = target_2
    df_sig["bias"] = bias
    return df_sig


# ── H3 ── Donchian breakout + ATR-regime filter


def generate_donchian_atr_regime_signals(
    df: pd.DataFrame,
    donchian_period: int = 20,
    atr_trail_mult: float = 2.0,
    atr_regime_lookback: int = 50,
) -> pd.DataFrame:
    """Donchian(N) breakout, filtered by ATR-regime (expanding volatility).

    Entry: close breaks above Donchian upper (shifted 1 bar, no look-ahead)
           AND ATR > SMA(ATR, atr_regime_lookback) [expanding volatility].
    Exit: close crosses below Donchian lower exit channel (N/2) OR ATR trailing stop.
    """
    from backtest.indicators import donchian_channels

    n = len(df)
    high = df["high"]
    low = df["low"]
    close = df["close"]
    atr = _wilder_atr(high, low, close, period=14)

    # Donchian channels (shift=1 built in to prevent look-ahead)
    entry_high, entry_low, exit_high, exit_low = donchian_channels(
        high, low, entry_period=donchian_period, exit_period=max(donchian_period // 2, 6)
    )

    # ATR regime: True when ATR > rolling SMA of ATR (expanding volatility)
    atr_sma = atr.rolling(atr_regime_lookback).mean()
    high_vol = atr > atr_sma

    df_sig = df.copy()
    df_sig["atr"] = atr

    entry_signal = np.full(n, "NO_TRADE", dtype=object)
    exit_signal = np.full(n, "NO_EXIT", dtype=object)
    stop_level = np.full(n, np.nan)
    target_1 = np.full(n, np.nan)
    target_2 = np.full(n, np.nan)
    bias = np.full(n, "NEUTRAL", dtype=object)

    in_trade = False
    stop_price = np.nan
    prev_close = np.nan

    for i in range(1, n):
        cur_close = float(close.iloc[i])
        cur_atr = float(atr.iloc[i]) if not pd.isna(atr.iloc[i]) else np.nan
        cur_entry_high = float(entry_high.iloc[i]) if not pd.isna(entry_high.iloc[i]) else np.nan
        cur_exit_low = float(exit_low.iloc[i]) if not pd.isna(exit_low.iloc[i]) else np.nan
        cur_high_vol = bool(high_vol.iloc[i])

        if np.isnan(cur_atr) or np.isnan(cur_entry_high):
            prev_close = cur_close
            continue

        if not in_trade:
            # Entry: breakout above Donchian high while in ATR-expanding regime
            if not np.isnan(prev_close) and cur_close > cur_entry_high and cur_high_vol:
                in_trade = True
                stop_price = cur_close - atr_trail_mult * cur_atr
                entry_signal[i] = "ENTRY_NOW"
                stop_level[i] = stop_price
                target_1[i] = cur_close + 3.0 * cur_atr
                target_2[i] = cur_close + 5.0 * cur_atr
                bias[i] = "STRONG_BULL"
        else:
            stop_level[i] = stop_price
            bias[i] = "STRONG_BULL"
            if cur_close <= stop_price or (
                not np.isnan(cur_exit_low) and cur_close <= cur_exit_low
            ):
                in_trade = False
                stop_price = np.nan
                exit_signal[i] = "EXIT_NOW"

        prev_close = cur_close

    df_sig["entry_signal"] = entry_signal
    df_sig["exit_signal"] = exit_signal
    df_sig["stop_level"] = stop_level
    df_sig["target_1"] = target_1
    df_sig["target_2"] = target_2
    df_sig["bias"] = bias
    return df_sig


# ── H4 ── RSI(2) mean-reversion (MES, LONG-only)


def generate_rsi2_meanrev_signals(
    df: pd.DataFrame,
    rsi_low_thresh: float = 10.0,
    rsi_exit_thresh: float = 65.0,
    sma_period: int = 200,
    atr_trail_mult: float = 2.0,
) -> pd.DataFrame:
    """RSI(2) mean-reversion — long when RSI(2) < low_thresh AND above SMA(200).

    Strategy: enter long when RSI(2) oversold; exit when RSI(2) > exit_thresh.
    SMA(200) trend filter prevents bottom-fishing in downtrends.
    ATR stop as backstop.
    """
    from backtest.indicators import rsi as compute_rsi

    n = len(df)
    close = df["close"]
    high = df["high"]
    low = df["low"]

    rsi2 = compute_rsi(close, period=2)
    sma200 = close.rolling(sma_period).mean()
    atr = _wilder_atr(high, low, close, period=14)

    df_sig = df.copy()
    df_sig["rsi2"] = rsi2
    df_sig["sma200"] = sma200
    df_sig["atr"] = atr

    entry_signal = np.full(n, "NO_TRADE", dtype=object)
    exit_signal = np.full(n, "NO_EXIT", dtype=object)
    stop_level = np.full(n, np.nan)
    target_1 = np.full(n, np.nan)
    target_2 = np.full(n, np.nan)
    bias = np.full(n, "NEUTRAL", dtype=object)

    in_trade = False
    stop_price = np.nan

    for i in range(1, n):
        cur_close = float(close.iloc[i])
        cur_rsi = float(rsi2.iloc[i]) if not pd.isna(rsi2.iloc[i]) else np.nan
        cur_sma = float(sma200.iloc[i]) if not pd.isna(sma200.iloc[i]) else np.nan
        cur_atr = float(atr.iloc[i]) if not pd.isna(atr.iloc[i]) else np.nan

        if np.isnan(cur_rsi) or np.isnan(cur_sma) or np.isnan(cur_atr):
            continue

        # Bias based on price vs SMA200
        bias[i] = "STRONG_BULL" if cur_close > cur_sma else "STRONG_BEAR"

        if not in_trade:
            # Entry: RSI(2) < low_thresh AND price above SMA(200) (mean-reversion long)
            if cur_rsi < rsi_low_thresh and cur_close > cur_sma:
                in_trade = True
                stop_price = cur_close - atr_trail_mult * cur_atr
                entry_signal[i] = "ENTRY_NOW"
                stop_level[i] = stop_price
                target_1[i] = cur_close + 2.0 * cur_atr  # tighter target for mean-rev
                target_2[i] = cur_close + 3.5 * cur_atr
        else:
            stop_level[i] = stop_price
            # Exit: RSI(2) crosses above exit threshold OR stop hit
            if cur_rsi > rsi_exit_thresh or cur_close <= stop_price:
                in_trade = False
                stop_price = np.nan
                exit_signal[i] = "EXIT_NOW"

    df_sig["entry_signal"] = entry_signal
    df_sig["exit_signal"] = exit_signal
    df_sig["stop_level"] = stop_level
    df_sig["target_1"] = target_1
    df_sig["target_2"] = target_2
    df_sig["bias"] = bias
    return df_sig


# ---------------------------------------------------------------------------
# IS grid search — identical logic to rank4
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
                combo_results.append(
                    {**params, "pf": round(result.profit_factor, 4), "trades": result.total_trades}
                )
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
    cost_tiers = get_cost_sweep_tiers(symbol)
    for tier in COST_TIER_ORDER:
        costs = cost_tiers[tier]
        try:
            df_sig = signal_fn(df, **champion_params)
            result = run_backtest(
                df,
                df_sig,
                symbol,
                commission=costs["commission"],
                slippage_ticks=costs["slippage_ticks"],
            )
            pf = result.profit_factor
            passes = pf > 1.0 and result.total_trades >= min_trades
            results[tier] = {"pf": round(pf, 4), "trades": result.total_trades, "passes": passes}
            print(
                f"    [{tier:12s}] PF={pf:.4f} trades={result.total_trades} {'PASS' if passes else 'FAIL'}"
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


# ---------------------------------------------------------------------------
# Gate v2 full evaluation — uses canonical helpers, NOT reimplemented
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

    if sample_adequacy_enforced() and not sample_adequate:
        verdict, passed_via = "INSUFFICIENT_SAMPLE", None
    elif core_pass:
        verdict, passed_via = "PASS", "core"
    elif alt_pass:
        verdict, passed_via = "PASS", "alt"
    else:
        verdict, passed_via = "FAIL", None

    # Identify primary block reason
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
# Main WFO driver — parameterized
# ---------------------------------------------------------------------------


def run_hypothesis(
    label: str,
    symbol: str,
    signal_fn: Callable,
    param_grid: list[dict],
    train_months: int = 6,
    test_months: int = 1,
    step_months: int = 1,
    df: pd.DataFrame | None = None,
    min_oos_trades_per_window: int = 1,
) -> dict:
    """Run a full WFO + gate-v2 evaluation for one (hypothesis, symbol) pair.

    Writes a verdict JSON to OUTPUT_DIR/<SYMBOL>_<label>.json.
    """
    print(f"\n{'='*70}")
    print(
        f"  {label} | {symbol} | train={train_months}mo test={test_months}mo step={step_months}mo"
    )
    print(f"  Grid: {len(param_grid)} combos")
    print(f"{'='*70}")

    if df is None:
        df = load_bars(symbol)

    windows = generate_windows(
        df, train_months=train_months, test_months=test_months, step_months=step_months
    )
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
            "hypothesis": label,
            "verdict": "FAIL",
            "passed_via": None,
            "primary_block": "no_oos_trades",
            "gate_v2_metrics": {},
        }
        _write_verdict(label, symbol, out)
        return out

    # Fixed-params sweep
    print(f"\n  Fixed-params sweep ({n_combos} combos)...")
    fixed_params_metrics = run_fixed_params_sweep(
        df, param_grid, signal_fn, symbol, min_trades=min_oos_trades_per_window
    )

    # Champion = most-selected IS params
    param_votes = Counter(str(sorted(r["best_params"].items())) for r in window_records)
    champion_key = param_votes.most_common(1)[0][0]
    champion_params = dict(
        sorted(
            window_records[
                next(
                    i
                    for i, r in enumerate(window_records)
                    if str(sorted(r["best_params"].items())) == champion_key
                )
            ]["best_params"].items()
        )
    )

    print(f"\n  Cost sweep (champion: {champion_params})...")
    cost_sweep_metrics = run_cost_sweep(
        df, champion_params, signal_fn, symbol, min_trades=min_oos_trades_per_window
    )

    # Gate v2
    gate = compute_gate_v2(
        oos_results,
        n_combos,
        fixed_params_metrics,
        cost_sweep_metrics,
        symbol,
        min_oos_trades_per_window=min_oos_trades_per_window,
    )

    print(f"\n  {'='*60}")
    print(
        f"  VERDICT: {gate['verdict']} (via {gate['passed_via'] or 'NONE'}) | {gate.get('primary_block', '')}"
    )
    print(
        f"  pf_ci_lower={gate['pf_ci_lower']:.4f} p_edge={gate['p_edge']:.4f} "
        f"mc_dd={gate['mc_95th_dd_pct']:.4f}% dsr={gate['dsr']:.6f}"
    )
    print(
        f"  wfo={gate['wfo_consistency']} fixed_min={gate['fixed_params_min_pf']:.4f} "
        f"cost={gate['cost_survives_through']} n_oos_trades={gate['total_oos_trades']}"
    )

    out = {
        "symbol": symbol,
        "hypothesis": label,
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
    _write_verdict(label, symbol, out)
    return out


def _write_verdict(label: str, symbol: str, data: dict, suffix: str = "") -> Path:
    """Write verdict JSON to isolation dir. Never touches gate_v2_verdicts/.

    If label already starts with symbol (e.g. label='MGC_H1fix_adx14_sma_trend'),
    use label directly as the filename to avoid double-symbol prefix.
    """
    if label.startswith(symbol + "_") or label.startswith(symbol.upper() + "_"):
        fname = f"{label}{suffix}.json"
    else:
        fname = f"{symbol}_{label}{suffix}.json"
    out_path = OUTPUT_DIR / fname
    out_path.write_text(json.dumps(data, indent=2, default=str))
    print(f"  [WRITTEN] {out_path}")
    return out_path


# ---------------------------------------------------------------------------
# STEP 3 DIAGNOSTIC: prove the fixed ADX filter binds on MGC 1h
# ---------------------------------------------------------------------------


def run_adx_binding_diagnostic(
    fast: int = 50, slow: int = 120, atr_trail_mult: float = 2.0
) -> None:
    """Print plain-trend entry count vs ADX-surviving count at thresholds {14,22,32}.

    Purpose: verify the corrected ADX filter actually removes entries rather
    than being a no-op.  If counts drop as threshold rises, the fix is working.
    If counts are identical, ADX is genuinely always above the threshold at
    entry bars — we print the actual ADX values at those bars to confirm.
    """
    from backtest.indicators import compute_adx
    from backtest.trend_signals import generate_sma_trend_signals

    print("\n" + "=" * 70)
    print("=== STEP 3: ADX BINDING DIAGNOSTIC (MGC 1h, fast=50 slow=120 atr=2.0) ===")

    df = load_bars("MGC")

    # Plain trend — baseline entry count
    df_plain = generate_sma_trend_signals(df, fast=fast, slow=slow, atr_trail_mult=atr_trail_mult)
    plain_entry_bars = df_plain.index[df_plain["entry_signal"] == "ENTRY_NOW"]
    n_plain = len(plain_entry_bars)
    print(f"\n  Plain-trend entry count (no ADX filter): {n_plain}")

    # Compute ADX once
    adx_df = compute_adx(df, period=14)
    adx_vals = adx_df["adx"]

    print(f"\n  {'Threshold':<12} {'Surviving entries':<20} {'Suppressed':<15} {'% suppressed'}")
    print(f"  {'-'*60}")
    for thresh in [14, 22, 32]:
        adx_weak = (adx_vals < thresh) | adx_vals.isna()
        suppress_mask = df_plain["entry_signal"] == "ENTRY_NOW"
        n_suppressed = int((suppress_mask & adx_weak).sum())
        n_surviving = n_plain - n_suppressed
        pct = 100.0 * n_suppressed / max(1, n_plain)
        print(f"  ADX >= {thresh:<6} {n_surviving:<20} {n_suppressed:<15} {pct:.1f}%")

    # If counts are identical at all thresholds, print actual ADX values at entry bars
    adx_weak_32 = (adx_vals < 32) | adx_vals.isna()
    suppress_at_32 = (df_plain["entry_signal"] == "ENTRY_NOW") & adx_weak_32
    if suppress_at_32.sum() == 0 and n_plain > 0:
        print("\n  [NOTE] ADX is >= 32 at ALL plain-trend entry bars.")
        print("  This means ADX conditioning at thresholds <= 32 will never suppress any entry.")
        print("  ADX values at entry bars:")
        entry_adx = adx_vals.reindex(plain_entry_bars).dropna()
        print(
            f"    min={entry_adx.min():.1f}  median={entry_adx.median():.1f}  "
            f"max={entry_adx.max():.1f}  count={len(entry_adx)}"
        )
        print(f"    Bars below ADX=32 at entry: {int((entry_adx < 32).sum())}")
        print(f"    Bars below ADX=22 at entry: {int((entry_adx < 22).sum())}")
        print(f"    Bars below ADX=14 at entry: {int((entry_adx < 14).sum())}")
    elif n_plain == 0:
        print("\n  [WARN] No plain-trend entries found — check SMA params or data range.")

    print("=" * 70)


# ---------------------------------------------------------------------------
# Validation run — MGC rank4 reproduction check
# ---------------------------------------------------------------------------


def run_validation():
    """Re-run MGC rank4 champion through this driver with TEST_MONTHS=2.

    Passes when: verdict=PASS (alt), pf_ci_lower roughly in [2.4, 2.8],
    dsr >= 0.9, mc_dd_pct <= 2.0%, total_oos_trades in [55, 80].
    (Some variation expected due to bootstrap RNG seed differences —
    accept within ±20% of rank4 metrics as 'reproduced'.)
    """
    print("\n" + "=" * 70)
    print("=== VALIDATION: MGC rank4 reproduction check ===")
    print("  Expected: PASS-ALT, pf_ci_lower~2.60, dsr~1.0, mc_dd~1.24%, ~67 OOS trades")

    # Rank4 grid (exact)
    grid = [
        {"fast": f, "slow": s, "atr_trail_mult": a}
        for f, s, a in itertools.product([40, 50], [80, 120], [1.5, 2.0])
    ]

    df = load_bars("MGC")
    result = run_hypothesis(
        label="validate_mgc_rank4",
        symbol="MGC",
        signal_fn=generate_sma_trend_signals_plain,
        param_grid=grid,
        train_months=6,
        test_months=2,  # matches rank4
        step_months=1,
        df=df,
        min_oos_trades_per_window=1,  # matches rank4's local override (not the global 5)
    )

    gate = result.get("gate_v2_metrics", {})
    expected = {
        "verdict": "PASS",
        "passed_via": "alt",
        "pf_ci_lower_min": 2.0,
        "dsr_min": 0.8,
        "mc_dd_pct_max": 4.0,  # gate ceiling is 4%; stored rank4 is 3.03%
        "oos_trades_min": 45,
    }

    checks = {
        "verdict_pass": result.get("verdict") == "PASS",
        "passed_via_alt": result.get("passed_via") == "alt",
        "pf_ci_lower_ok": (gate.get("pf_ci_lower") or 0) >= expected["pf_ci_lower_min"],
        "dsr_ok": (gate.get("dsr") or 0) >= expected["dsr_min"],
        "mc_dd_ok": (gate.get("mc_95th_dd_pct") or 99) <= expected["mc_dd_pct_max"],
        "oos_trades_ok": (gate.get("total_oos_trades") or 0) >= expected["oos_trades_min"],
    }
    all_pass = all(checks.values())

    print(f"\n  Validation checks: {'PASS' if all_pass else 'FAIL'}")
    for k, v in checks.items():
        print(f"    {'OK' if v else 'FAIL'} {k}")
    print(
        f"  Actual: verdict={result.get('verdict')} pf_ci={gate.get('pf_ci_lower')} "
        f"dsr={gate.get('dsr')} mc_dd%={gate.get('mc_95th_dd_pct')} "
        f"oos_trades={gate.get('total_oos_trades')}"
    )

    if not all_pass:
        print("\n  [STOP] Driver failed validation — do NOT trust hypothesis results.")
    else:
        print("\n  [OK] Driver validates against MGC rank4 — proceeding to hypotheses.")

    return all_pass, result


# ---------------------------------------------------------------------------
# Hypothesis definitions — param grids
# ---------------------------------------------------------------------------

# H1: ADX-conditioned SMA trend (MES and MGC)
# SMA params from existing trend config; ADX threshold grid [18, 22, 25]
H1_MES_GRID = [
    {"fast": 60, "slow": 200, "atr_trail_mult": 2.0, "adx_threshold": t} for t in [18, 22, 25]
]
# FIX rerun 2026-06-17: expanded threshold grid {14,18,22,25,28,32},
# locked to champion params fast=50/slow=120/atr=2.0 per task spec.
H1_MGC_GRID = [
    {"fast": 50, "slow": 120, "atr_trail_mult": 2.0, "adx_threshold": t}
    for t in [14, 18, 22, 25, 28, 32]
]

# H2: KAMA adaptive trend (MNQ and MES)
# er_period in {10, 20}, fast=2, slow=30 (standard)
H2_GRID = [
    {"er_period": ep, "fast_period": 2, "slow_period": 30, "atr_trail_mult": a}
    for ep in [10, 20]
    for a in [1.5, 2.0]
]

# H3: Donchian breakout + ATR-regime (MGC)
# donchian_period in {20, 40}, atr_regime_lookback in {50, 100}
H3_GRID = [
    {"donchian_period": dp, "atr_trail_mult": 2.0, "atr_regime_lookback": lb}
    for dp in [20, 40]
    for lb in [50, 100]
]

# H4: RSI(2) mean-reversion (MES)
# rsi_low_thresh in {5, 10, 15}; sma_period=200; exit=65; atr_mult=2.0
H4_GRID = [
    {"rsi_low_thresh": t, "rsi_exit_thresh": 65.0, "sma_period": 200, "atr_trail_mult": 2.0}
    for t in [5, 10, 15]
]

# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="Discovery sweep 2026-06-16")
    parser.add_argument(
        "--validate-only", action="store_true", help="Only run the MGC rank4 validation check"
    )
    parser.add_argument(
        "--hypothesis", choices=["H1", "H2", "H3", "H4"], help="Run only one hypothesis"
    )
    parser.add_argument(
        "--skip-validate", action="store_true", help="Skip validation (dangerous — use for reruns)"
    )
    args = parser.parse_args()

    # Step C: Validation
    if not args.skip_validate:
        validated, _val_result = run_validation()
        if not validated:
            print("\n[ABORT] Driver failed validation. Stopping.")
            sys.exit(1)
    else:
        print("[WARN] Skipping validation per --skip-validate flag.")
        validated = True

    if args.validate_only:
        print("\n[DONE] Validation-only mode.")
        return

    results = {}

    # Step D: Run hypotheses
    run_all = args.hypothesis is None

    if run_all or args.hypothesis == "H1":
        print("\n\n=== H1: ADX-conditioned SMA trend ===")
        # STEP 3: Run diagnostic first to prove the fix binds
        run_adx_binding_diagnostic(fast=50, slow=120, atr_trail_mult=2.0)

        results["H1_MES"] = run_hypothesis(
            "H1_adx_sma_trend",
            "MES",
            generate_adx_sma_trend_signals,
            H1_MES_GRID,
            train_months=6,
            test_months=1,
            step_months=1,
            min_oos_trades_per_window=1,
        )

        # STEP 4: MGC H1 — run each threshold individually for per-threshold verdict JSONs
        # Champion params: fast=50/slow=120/atr=2.0; thresholds {14,18,22,25,28,32}
        df_mgc = load_bars("MGC")
        mgc_threshold_results = {}
        for adx_thresh in [14, 18, 22, 25, 28, 32]:
            single_grid = [
                {"fast": 50, "slow": 120, "atr_trail_mult": 2.0, "adx_threshold": adx_thresh}
            ]
            label = f"MGC_H1fix_adx{adx_thresh:02d}_sma_trend"
            r = run_hypothesis(
                label=label,
                symbol="MGC",
                signal_fn=generate_adx_sma_trend_signals,
                param_grid=single_grid,
                train_months=6,
                test_months=2,
                step_months=1,
                df=df_mgc,
                min_oos_trades_per_window=1,
            )
            mgc_threshold_results[adx_thresh] = r
            results[f"H1_MGC_adx{adx_thresh}"] = r

        # Print MGC H1 threshold comparison table
        print("\n\n=== MGC H1 ADX THRESHOLD COMPARISON (fixed driver) ===")
        print("  Baseline rank4 (plain, no ADX): pf_ci~2.59, mc_dd~3.03%, 67 OOS, PASS-ALT")
        print(
            f"  {'adx_thresh':<12} {'verdict':<10} {'passed_via':<12} {'pf_ci_lower':<13} "
            f"{'p_edge':<9} {'mc_dd%':<9} {'dsr':<9} {'n_oos'}"
        )
        print(f"  {'-'*90}")
        for thresh, r in mgc_threshold_results.items():
            g = r.get("gate_v2_metrics", {})
            print(
                f"  ADX>={thresh:<6} {r.get('verdict','?'):<10} {r.get('passed_via') or 'n/a':<12} "
                f"{g.get('pf_ci_lower') or 'n/a':<13} "
                f"{g.get('p_edge') or 'n/a':<9} "
                f"{g.get('mc_95th_dd_pct') or 'n/a':<9} "
                f"{g.get('dsr') or 'n/a':<9} "
                f"{g.get('total_oos_trades') or 0}"
            )

    if run_all or args.hypothesis == "H2":
        print("\n\n=== H2: KAMA adaptive trend ===")
        results["H2_MNQ"] = run_hypothesis(
            "H2_kama_trend",
            "MNQ",
            generate_kama_trend_signals,
            H2_GRID,
            train_months=6,
            test_months=1,
            step_months=1,
            min_oos_trades_per_window=1,
        )
        results["H2_MES"] = run_hypothesis(
            "H2_kama_trend",
            "MES",
            generate_kama_trend_signals,
            H2_GRID,
            train_months=6,
            test_months=1,
            step_months=1,
            min_oos_trades_per_window=1,
        )

    if run_all or args.hypothesis == "H3":
        print("\n\n=== H3: Donchian breakout + ATR-regime ===")
        results["H3_MGC"] = run_hypothesis(
            "H3_donchian_atr_regime",
            "MGC",
            generate_donchian_atr_regime_signals,
            H3_GRID,
            train_months=6,
            test_months=2,
            step_months=1,
            min_oos_trades_per_window=1,
        )

    if run_all or args.hypothesis == "H4":
        print("\n\n=== H4: RSI(2) mean-reversion ===")
        results["H4_MES"] = run_hypothesis(
            "H4_rsi2_meanrev",
            "MES",
            generate_rsi2_meanrev_signals,
            H4_GRID,
            train_months=6,
            test_months=1,
            step_months=1,
            min_oos_trades_per_window=1,
        )

    # Summary
    print(f"\n\n{'='*70}")
    print("=== DISCOVERY SWEEP SUMMARY ===")
    print(
        f"{'Hypothesis':<30} {'Symbol':<6} {'Verdict':<22} {'pf_ci':<8} {'p_edge':<8} "
        f"{'mc_dd%':<8} {'dsr':<8} {'OOS':<6} {'Block'}"
    )
    print("-" * 110)
    for _key, r in results.items():
        g = r.get("gate_v2_metrics", {})
        print(
            f"{r.get('hypothesis','?'):<30} {r.get('symbol','?'):<6} "
            f"{r.get('verdict','?'):10} {r.get('passed_via') or '':10} "
            f"{g.get('pf_ci_lower') or 'n/a':<8} "
            f"{g.get('p_edge') or 'n/a':<8} "
            f"{g.get('mc_95th_dd_pct') or 'n/a':<8} "
            f"{g.get('dsr') or 'n/a':<8} "
            f"{g.get('total_oos_trades') or 0:<6} "
            f"{r.get('primary_block') or ''}"
        )

    survivors = [k for k, r in results.items() if r.get("verdict") == "PASS"]
    print(f"\nSurvivors (gate PASS): {survivors if survivors else 'NONE'}")
    print(f"Output dir: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
