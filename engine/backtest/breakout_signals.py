"""
Donchian-channel breakout signal generator for JARVIS TRADER.

Designed for MNQ (Micro Nasdaq 1h) — per the per-symbol decision memo
(commit `c4a1ef1`) MNQ is currently blocklisted via DO_NOT_TRADE_SYMBOLS
pending a validated edge. NQ is momentum-heavy, tech-led, and prone to
clean range expansions off consolidation. Donchian breakout with optional
volume confirmation captures that character far better than an MA cross.

Thesis
------
    * Price closes ABOVE the highest-high of the prior N bars → LONG breakout.
    * Price closes BELOW the lowest-low  of the prior N bars → SHORT breakout.
    * Volume confirmation (optional) ensures real participation, not a wick.
    * Stop : ATR-based buffer from the entry price.
    * Exit : price re-enters the channel (symmetric reversion-complete flag).

Symmetric (LONG + SHORT) — unlike `trend_signals.py` which is LONG-only.

Entry (LONG)
------------
    * close > rolling_max(high, N, shift=1)   AND
      volume > vol_mult × rolling_mean(volume, vol_ma_period)

Entry (SHORT)
-------------
    * close < rolling_min(low, N, shift=1)    AND
      volume > vol_mult × rolling_mean(volume, vol_ma_period)

Exit
----
    * close falls BACK inside the prior-bar Donchian channel → EXIT_NOW
      (symmetric — the backtester applies per-trade direction semantics).
    * Stop hit                                                → handled by backtester.

Output format
-------------
Matches the column contract consumed by `mcl_meanrev_smoke.py` /
`scripts/*_smoke.py` so downstream tooling is reusable:
    entry_signal  : "ENTRY_NOW" | "NO_TRADE"
    exit_signal   : "EXIT_NOW"  | "NO_EXIT"
    bias          : "STRONG_BULL" | "STRONG_BEAR" | "NEUTRAL"
    regime        : "BREAKOUT" | "NEUTRAL"
    stop_level    : entry ∓ stop_atr_mult × ATR(14)
    target_1      : entry ± 3 × ATR(14)
    target_2      : entry ± 5 × ATR(14)
    target_3      : entry ± 7 × ATR(14)
    donchian_high / donchian_low : shifted channel bounds
    vol_ma        : rolling-mean volume used in the confirm gate
    atr_14        : volatility context
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Default MNQ-targeted params — to be refined via backtest / gate v2 battery.
BREAKOUT_PARAMS: dict[str, dict] = {
    "MNQ": {
        "donchian_period": 20,
        "vol_ma_period": 20,
        # v1 baseline: vol_mult=1.0 means "any breakout bar whose volume is
        # above average." Raise to 1.5 / 2.0 in a second iteration if the
        # baseline shows edge and volume filter adds Sharpe.
        "vol_mult": 1.0,
        "stop_atr_mult": 2.0,
    },
}

_ATR_PERIOD = 14
_T1_MULT = 3.0
_T2_MULT = 5.0
_T3_MULT = 7.0


def _wilder_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    prev_c = close.shift(1)
    tr = pd.concat([(high - low), (high - prev_c).abs(), (low - prev_c).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


def generate_donchian_breakout_signals(
    df: pd.DataFrame,
    donchian_period: int = 20,
    vol_ma_period: int = 20,
    vol_mult: float = 1.0,
    stop_atr_mult: float = 2.0,
    ema_trend_period: int = 0,
    atr_regime_mult: float = 0.0,
) -> pd.DataFrame:
    """Generate Donchian-channel breakout signals.

    Args:
        df: OHLCV DataFrame with columns open, high, low, close, volume.
        donchian_period: Channel lookback (default 20 bars).
        vol_ma_period: Volume-average lookback for the confirmation filter
            (default 20).
        vol_mult: Volume threshold as multiple of the moving average.
            1.0 means "volume at least average" — a soft gate. 0.0 disables
            the filter entirely. 1.5-2.0 would require visible participation.
        stop_atr_mult: Stop distance in ATR(14) multiples (default 2.0).

    Returns:
        Copy of df with the column set documented in the module docstring.
    """
    df = df.copy()

    high = df["high"]
    low = df["low"]
    close = df["close"]
    volume = df["volume"] if "volume" in df.columns else pd.Series(0.0, index=df.index)

    # Shift(1) so the current bar's high/low does NOT count as "above
    # channel" — otherwise every bar that sets a new high would fire.
    donchian_high = high.rolling(donchian_period).max().shift(1)
    donchian_low = low.rolling(donchian_period).min().shift(1)

    vol_ma = volume.rolling(vol_ma_period).mean()
    atr = _wilder_atr(high, low, close, _ATR_PERIOD)

    # Regime filter: EMA trend direction gate (ema_trend_period=0 disables, backward compatible).
    if ema_trend_period > 0:
        ema_trend = close.ewm(span=ema_trend_period, adjust=False).mean()
        ema_warm = ema_trend.notna()
        long_ema_ok = (close > ema_trend) & ema_warm
        short_ema_ok = (close < ema_trend) & ema_warm
    else:
        ema_trend = pd.Series(np.nan, index=df.index)
        long_ema_ok = pd.Series(True, index=df.index)
        short_ema_ok = pd.Series(True, index=df.index)

    # Regime filter: ATR expansion gate (atr_regime_mult=0.0 disables, backward compatible).
    if atr_regime_mult > 0.0:
        atr_sma50 = atr.rolling(50).mean()
        atr_regime_active = (atr > atr_sma50 * atr_regime_mult) & atr_sma50.notna()
    else:
        atr_regime_active = pd.Series(True, index=df.index)

    # vol_mult=0 disables the filter (always passes). Otherwise require
    # volume > mult × MA. NaN MA (warmup) → gate fails.
    if vol_mult <= 0:
        vol_ok = pd.Series(True, index=df.index)
    else:
        vol_ok = volume > (vol_mult * vol_ma)

    # Warm-up guard: all indicators must be populated. Without this, the
    # first few bars of the dataset can fire bogus "breakouts" against NaN
    # channel bounds.
    warm = (
        donchian_high.notna()
        & donchian_low.notna()
        & atr.notna()
        & vol_ma.notna()
    )

    long_cond = (close > donchian_high) & vol_ok & warm & long_ema_ok & atr_regime_active
    short_cond = (close < donchian_low) & vol_ok & warm & short_ema_ok & atr_regime_active

    # Conflict guard — channel_high < channel_low is impossible in a
    # valid dataset, but close can straddle a single-bar channel when
    # donchian_period=1. Belt-and-suspenders.
    conflict = long_cond & short_cond
    long_cond = long_cond & ~conflict
    short_cond = short_cond & ~conflict

    # Exit: price has returned BACK inside the (prior-bar) channel. This
    # is symmetric — a long trade exits when close falls below channel_high,
    # and a short trade exits when close rises above channel_low. The
    # `exit_signal` is set when BOTH conditions hold (price strictly inside
    # the channel), which guarantees at most one exit flag per side per bar.
    exit_cond = (close <= donchian_high) & (close >= donchian_low) & warm

    n = len(df)
    entry_signal = np.full(n, "NO_TRADE", dtype=object)
    exit_signal = np.full(n, "NO_EXIT", dtype=object)
    bias = np.full(n, "NEUTRAL", dtype=object)
    stop_level = np.full(n, np.nan)
    target_1 = np.full(n, np.nan)
    target_2 = np.full(n, np.nan)
    target_3 = np.full(n, np.nan)

    long_idx = np.flatnonzero(long_cond.values)
    for i in long_idx:
        price = float(close.iloc[i])
        atr_i = float(atr.iloc[i])
        entry_signal[i] = "ENTRY_NOW"
        bias[i] = "STRONG_BULL"
        stop_level[i] = price - stop_atr_mult * atr_i
        target_1[i] = price + _T1_MULT * atr_i
        target_2[i] = price + _T2_MULT * atr_i
        target_3[i] = price + _T3_MULT * atr_i

    short_idx = np.flatnonzero(short_cond.values)
    for i in short_idx:
        price = float(close.iloc[i])
        atr_i = float(atr.iloc[i])
        entry_signal[i] = "ENTRY_NOW"
        bias[i] = "STRONG_BEAR"
        stop_level[i] = price + stop_atr_mult * atr_i
        target_1[i] = price - _T1_MULT * atr_i
        target_2[i] = price - _T2_MULT * atr_i
        target_3[i] = price - _T3_MULT * atr_i

    exit_idx = np.flatnonzero(exit_cond.values)
    for i in exit_idx:
        exit_signal[i] = "EXIT_NOW"

    regime = np.where(warm, "BREAKOUT", "NEUTRAL")

    df["entry_signal"] = entry_signal
    df["exit_signal"] = exit_signal
    df["bias"] = bias
    df["regime"] = regime
    df["stop_level"] = stop_level
    df["target_1"] = target_1
    df["target_2"] = target_2
    df["target_3"] = target_3
    df["donchian_high"] = donchian_high
    df["donchian_low"] = donchian_low
    df["vol_ma"] = vol_ma
    df["atr_14"] = atr
    df["ema_trend"] = ema_trend
    df["atr_regime_active"] = atr_regime_active

    return df


def get_breakout_params(symbol: str) -> dict | None:
    """Return validated breakout params for symbol, or None."""
    return BREAKOUT_PARAMS.get(symbol.upper())
