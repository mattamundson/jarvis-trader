"""
Donchian Channel Breakout signal generator for JARVIS TRADER.

Entry : close > highest_high over lookback_entry prior bars (breakout up) — LONG only.
Exit  : close < lowest_low over lookback_exit prior bars  OR  ATR trailing stop hit.
Stop  : entry - atr_trail_mult × ATR(14) at entry bar.
Targets: entry + N × ATR matching trend_signals.py conventions (_T1_MULT=3, _T2=5, _T3=7).

Rationale: Donchian captures actual N-bar price highs (no lag like SMA(200)).
Compared to SMA(50,200), Donchian enters faster when price breaks a new high,
and exits faster on channel breach — both strategies are trend-following but
disagree at turning points, making them complementary candidates.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

_ATR_PERIOD = 14
_T1_MULT = 3.0
_T2_MULT = 5.0
_T3_MULT = 7.0


def _wilder_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    prev_c = close.shift(1)
    tr = pd.concat([(high - low), (high - prev_c).abs(), (low - prev_c).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


def generate_donchian_signals(
    df: pd.DataFrame,
    lookback_entry: int = 20,
    lookback_exit: int = 10,
    atr_trail_mult: float = 2.0,
) -> pd.DataFrame:
    """
    Generate Donchian Channel breakout signals compatible with the JARVIS Backtester.

    Args:
        lookback_entry : bars to look back for the channel high (entry condition)
        lookback_exit  : bars to look back for the channel low (exit condition)
        atr_trail_mult : ATR multiplier for stop and target sizing

    Returns df with columns matching trend_signals.py output:
        entry_signal  : "ENTRY_NOW" | "NO_TRADE"
        exit_signal   : "EXIT_NOW" | "NO_EXIT"
        stop_level    : entry − trail_mult × ATR
        target_1/2/3  : entry + N × ATR
        bias          : "STRONG_BULL" | "NEUTRAL"
        regime        : "TRENDING_BULL" | "RANGE_BOUND"
        atr           : ATR(14) series
    """
    df = df.copy()

    # Donchian channels (use shift(1) to avoid look-ahead: signal uses yesterday's channel)
    channel_high = df["high"].rolling(lookback_entry).max().shift(1)
    channel_low = df["low"].rolling(lookback_exit).min().shift(1)
    atr = _wilder_atr(df["high"], df["low"], df["close"], _ATR_PERIOD)

    # Entry: close breaks above prior N-bar high. Exit: close breaks below prior M-bar low.
    in_channel = df["close"] > channel_high  # True when price is above entry channel
    breakout_up = in_channel & ~in_channel.shift(1, fill_value=False) & channel_high.notna()
    breakdown = df["close"] < channel_low

    n = len(df)
    entry_signal = np.full(n, "NO_TRADE", dtype=object)
    exit_signal  = np.full(n, "NO_EXIT",  dtype=object)
    stop_level   = np.full(n, np.nan)
    target_1     = np.full(n, np.nan)
    target_2     = np.full(n, np.nan)
    target_3     = np.full(n, np.nan)

    for i in range(n):
        if pd.isna(channel_high.iloc[i]) or pd.isna(atr.iloc[i]):
            continue
        price = float(df["close"].iloc[i])
        atr_i = float(atr.iloc[i])

        if breakout_up.iloc[i]:
            entry_signal[i] = "ENTRY_NOW"
            stop_level[i]   = price - atr_trail_mult * atr_i
            target_1[i]     = price + _T1_MULT * atr_i
            target_2[i]     = price + _T2_MULT * atr_i
            target_3[i]     = price + _T3_MULT * atr_i
        elif breakdown.iloc[i] and not pd.isna(channel_low.iloc[i]):
            exit_signal[i] = "EXIT_NOW"

    df["entry_signal"] = entry_signal
    df["exit_signal"]  = exit_signal
    df["stop_level"]   = stop_level
    df["target_1"]     = target_1
    df["target_2"]     = target_2
    df["target_3"]     = target_3
    df["atr"]          = atr

    df["bias"] = "NEUTRAL"
    df.loc[in_channel & channel_high.notna(), "bias"] = "STRONG_BULL"

    df["regime"] = "RANGE_BOUND"
    df.loc[in_channel & channel_high.notna(), "regime"] = "TRENDING_BULL"

    return df
