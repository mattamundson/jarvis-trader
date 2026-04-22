"""
STATUS: ARCHIVED — FAILED gate v2 (2026-04-22). Test PF 3.66 but only n=3.
Insufficient evidence floor per gate_v2_policy.py.
Retained for reference; see backtest/archive/failed/README.md.

RSI-oversold breakout signal generator for JARVIS TRADER.

Entry  : RSI was deep-oversold within the last `rsi_lookback` bars (long),
         AND close breaks above the prior-bar Donchian-entry high. Symmetric
         short: RSI deep-overbought recently AND close breaks Donchian-entry low.
Exit   : RSI reverts to the opposite extreme (overbought for long, oversold for
         short) OR price breaches the Donchian-exit band (tighter Donchian N=6).
Stop   : entry -/+ atr_stop_mult * ATR(14) at entry bar.
Targets: entry +/- {3, 5, 7} * ATR  (matches repo convention).

Rationale: deep RSI extremes flag exhaustion; a subsequent Donchian breakout is
the confirmation that the market has absorbed the extreme and is reversing.
Combining oscillator (RSI) + structural breakout (Donchian) filters out
false-extreme bars where RSI pins <25 but price keeps falling.

Symmetric long/short by design.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.indicators import donchian_channels, rsi, wilder_atr

RSI_BREAKOUT_PARAMS: dict[str, dict] = {
    # Placeholder — grid search in scripts/mes_rsi_breakout_search.py will tune.
    "MES": {
        "rsi_period": 14,
        "rsi_oversold": 25.0,
        "rsi_overbought": 75.0,
        "rsi_exit_oversold": 30.0,
        "rsi_exit_overbought": 70.0,
        "rsi_lookback": 5,
        "entry_period": 20,
        "exit_period": 10,
        "atr_stop_mult": 2.0,
    },
}

_T1_MULT = 3.0
_T2_MULT = 5.0
_T3_MULT = 7.0


def generate_rsi_breakout_signals(
    df: pd.DataFrame,
    rsi_period: int = 14,
    rsi_oversold: float = 25.0,
    rsi_overbought: float = 75.0,
    rsi_exit_oversold: float = 30.0,
    rsi_exit_overbought: float = 70.0,
    rsi_lookback: int = 5,
    entry_period: int = 20,
    exit_period: int = 10,
    atr_stop_mult: float = 2.0,
) -> pd.DataFrame:
    """
    Generate RSI-breakout signals compatible with the JARVIS Backtester.

    Args:
        rsi_period: Wilder RSI smoothing period.
        rsi_oversold / rsi_overbought: entry extremes (deep-oversold/overbought).
        rsi_exit_oversold / rsi_exit_overbought: exit thresholds (mean revert back).
        rsi_lookback: bars to look back for a recent oversold/overbought print.
        entry_period: Donchian period for breakout confirmation.
        exit_period: Donchian period for trailing-exit (tighter than entry).
        atr_stop_mult: initial stop distance in ATR multiples.

    Returns df with standard signal columns:
        entry_signal, exit_signal, stop_level, target_1/2/3, bias, regime,
        atr, rsi.
    """
    df = df.copy()

    rsi_series = rsi(df["close"], period=rsi_period)
    atr = wilder_atr(df["high"], df["low"], df["close"], period=14)
    entry_high, entry_low, exit_high, exit_low = donchian_channels(
        df["high"], df["low"], entry_period=entry_period, exit_period=exit_period,
    )

    # Recent-extreme detector: was RSI deep-oversold (overbought) within the
    # last `rsi_lookback` bars? Use prior-bar window so current bar is the
    # confirmation, not part of the trigger.
    rsi_prev = rsi_series.shift(1)
    rsi_min_recent = rsi_prev.rolling(rsi_lookback, min_periods=1).min()
    rsi_max_recent = rsi_prev.rolling(rsi_lookback, min_periods=1).max()

    recently_oversold = rsi_min_recent < rsi_oversold
    recently_overbought = rsi_max_recent > rsi_overbought

    breakout_up = df["close"] > entry_high
    breakout_dn = df["close"] < entry_low

    long_entry_cond = (recently_oversold & breakout_up).fillna(False)
    short_entry_cond = (recently_overbought & breakout_dn).fillna(False)

    # Fire on the first bar the condition becomes true (edge-detect), so a
    # multi-bar breakout doesn't re-trigger every bar.
    enter_long = long_entry_cond & ~long_entry_cond.shift(1, fill_value=False)
    enter_short = short_entry_cond & ~short_entry_cond.shift(1, fill_value=False)

    # Exit: RSI reverts to opposite extreme OR breaks the tighter Donchian band.
    long_exit_cond = (
        (rsi_series > rsi_exit_overbought) | (df["close"] < exit_low)
    ).fillna(False)
    short_exit_cond = (
        (rsi_series < rsi_exit_oversold) | (df["close"] > exit_high)
    ).fillna(False)
    exit_trigger = long_exit_cond | short_exit_cond

    n = len(df)
    entry_signal = np.full(n, "NO_TRADE", dtype=object)
    exit_signal = np.full(n, "NO_EXIT", dtype=object)
    stop_level = np.full(n, np.nan)
    target_1 = np.full(n, np.nan)
    target_2 = np.full(n, np.nan)
    target_3 = np.full(n, np.nan)

    for i in range(n):
        if pd.isna(rsi_series.iloc[i]) or pd.isna(atr.iloc[i]):
            continue
        price = float(df["close"].iloc[i])
        atr_i = float(atr.iloc[i])

        if enter_long.iloc[i]:
            entry_signal[i] = "ENTRY_NOW"
            stop_level[i] = price - atr_stop_mult * atr_i
            target_1[i] = price + _T1_MULT * atr_i
            target_2[i] = price + _T2_MULT * atr_i
            target_3[i] = price + _T3_MULT * atr_i
        elif enter_short.iloc[i]:
            entry_signal[i] = "ENTRY_NOW"
            stop_level[i] = price + atr_stop_mult * atr_i
            target_1[i] = price - _T1_MULT * atr_i
            target_2[i] = price - _T2_MULT * atr_i
            target_3[i] = price - _T3_MULT * atr_i
        elif exit_trigger.iloc[i]:
            exit_signal[i] = "EXIT_NOW"

    df["entry_signal"] = entry_signal
    df["exit_signal"] = exit_signal
    df["stop_level"] = stop_level
    df["target_1"] = target_1
    df["target_2"] = target_2
    df["target_3"] = target_3
    df["atr"] = atr
    df["rsi"] = rsi_series

    # Bias/regime columns — label the underlying setup, not the open position.
    df["bias"] = "NEUTRAL"
    df.loc[recently_oversold & (df["close"] > df["close"].shift(1)), "bias"] = "OVERSOLD_REVERSAL"
    df.loc[recently_overbought & (df["close"] < df["close"].shift(1)), "bias"] = "OVERBOUGHT_REVERSAL"

    df["regime"] = "RANGE_BOUND"
    df.loc[enter_long, "regime"] = "BREAKOUT_UP"
    df.loc[enter_short, "regime"] = "BREAKOUT_DN"

    return df


def get_rsi_breakout_params(symbol: str) -> dict | None:
    """Return validated RSI-breakout params for symbol, or None if not configured."""
    return RSI_BREAKOUT_PARAMS.get(symbol.upper())
