"""
STATUS: ARCHIVED — FAILED gate v2 (2026-04-22). Test PF 0.648 on MES 1h (n=90).
No edge after ADX strength gate. Retained for reference; see
backtest/archive/failed/README.md before resurrecting.

ADX-EMA trend signal generator for JARVIS TRADER.

Entry  : ADX >= adx_threshold (strong trend) AND ema_slope direction aligns
         with DI bias (long when plus_di > minus_di, short when minus_di > plus_di).
Exit   : ADX < adx_exit_threshold (trend weakening) OR opposite DI crossover.
Stop   : entry +/- atr_trail_mult * ATR(14) at entry bar.
Targets: entry +/- {3, 5, 7} * ATR  (matches trend_signals.py convention).

Rationale: SMA(fast,slow) crossover captures trend direction but not trend
strength. ADX adds a strength gate (>= 25 = strong trend), reducing false
signals in choppy regimes. EMA slope over N bars filters flat/directionless
DI crossovers.

Symmetric long/short by design — unlike trend_signals.py which is long-only.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.indicators import compute_adx, ema_slope, wilder_atr

# Default parameters — tune via grid search in scripts/mes_adx_ema_search.py
ADX_EMA_PARAMS: dict[str, dict] = {
    # Placeholder; validated params fill in after grid search.
    "MES": {
        "adx_threshold": 25.0,
        "adx_exit_threshold": 20.0,
        "adx_period": 14,
        "ema_period": 21,
        "ema_lookback": 3,
        "atr_trail_mult": 2.5,
    },
}

_T1_MULT = 3.0
_T2_MULT = 5.0
_T3_MULT = 7.0


def generate_adx_ema_signals(
    df: pd.DataFrame,
    adx_threshold: float = 25.0,
    adx_exit_threshold: float = 20.0,
    adx_period: int = 14,
    ema_period: int = 21,
    ema_lookback: int = 3,
    atr_trail_mult: float = 2.5,
) -> pd.DataFrame:
    """
    Generate ADX-EMA trend signals compatible with the JARVIS Backtester.

    Args:
        adx_threshold: Minimum ADX required to enter (strong trend gate).
        adx_exit_threshold: ADX drop that triggers exit (trend weakening).
        adx_period: Wilder ADX smoothing period.
        ema_period: EMA period for slope direction filter.
        ema_lookback: Bars over which ema_slope is measured.
        atr_trail_mult: Initial stop distance in ATR multiples.

    Returns df with columns:
        entry_signal  : "ENTRY_NOW" | "NO_TRADE"
        exit_signal   : "EXIT_NOW"  | "NO_EXIT"
        stop_level    : price +/- trail_mult * ATR  (long: below, short: above)
        target_1/2/3  : ATR-spaced targets in trade direction
        bias          : "STRONG_BULL" | "STRONG_BEAR" | "NEUTRAL"
        regime        : "TRENDING_BULL" | "TRENDING_BEAR" | "RANGE_BOUND"
        atr           : ATR(14) series
        adx           : ADX(14) series
    """
    df = df.copy()

    adx_df = compute_adx(df, period=adx_period)
    adx = adx_df["adx"]
    plus_di = adx_df["plus_di"]
    minus_di = adx_df["minus_di"]

    slope = ema_slope(df["close"], period=ema_period, lookback=ema_lookback)
    atr = wilder_atr(df["high"], df["low"], df["close"], period=14)

    # Trend-strength gate + direction checks
    strong = (adx >= adx_threshold).fillna(False)
    weak = (adx < adx_exit_threshold).fillna(False)
    bull_bias = (plus_di > minus_di).fillna(False) & (slope > 0).fillna(False)
    bear_bias = (minus_di > plus_di).fillna(False) & (slope < 0).fillna(False)

    # Entry fires on the first bar where (strong ADX) AND (aligned direction)
    # both hold — covers fresh trend starts (ADX crossed threshold) AND
    # reversals (direction flipped while ADX stayed strong).
    strong_bull = strong & bull_bias
    strong_bear = strong & bear_bias

    enter_long = strong_bull & ~strong_bull.shift(1, fill_value=False)
    enter_short = strong_bear & ~strong_bear.shift(1, fill_value=False)

    # Exit when ADX weakens; direction flips are handled as entry-on-opposite-side
    # (backtester flattens the prior position when the new entry fires).
    exit_trigger = weak

    n = len(df)
    entry_signal = np.full(n, "NO_TRADE", dtype=object)
    exit_signal = np.full(n, "NO_EXIT", dtype=object)
    stop_level = np.full(n, np.nan)
    target_1 = np.full(n, np.nan)
    target_2 = np.full(n, np.nan)
    target_3 = np.full(n, np.nan)

    for i in range(n):
        if pd.isna(adx.iloc[i]) or pd.isna(atr.iloc[i]):
            continue
        price = float(df["close"].iloc[i])
        atr_i = float(atr.iloc[i])

        if enter_long.iloc[i]:
            entry_signal[i] = "ENTRY_NOW"
            stop_level[i] = price - atr_trail_mult * atr_i
            target_1[i] = price + _T1_MULT * atr_i
            target_2[i] = price + _T2_MULT * atr_i
            target_3[i] = price + _T3_MULT * atr_i
        elif enter_short.iloc[i]:
            entry_signal[i] = "ENTRY_NOW"
            stop_level[i] = price + atr_trail_mult * atr_i
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
    df["adx"] = adx

    df["bias"] = "NEUTRAL"
    df.loc[strong & bull_bias, "bias"] = "STRONG_BULL"
    df.loc[strong & bear_bias, "bias"] = "STRONG_BEAR"

    df["regime"] = "RANGE_BOUND"
    df.loc[strong & bull_bias, "regime"] = "TRENDING_BULL"
    df.loc[strong & bear_bias, "regime"] = "TRENDING_BEAR"

    return df


def get_adx_ema_params(symbol: str) -> dict | None:
    """Return validated ADX-EMA params for symbol, or None if not configured."""
    return ADX_EMA_PARAMS.get(symbol.upper())
