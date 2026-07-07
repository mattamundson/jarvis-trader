"""
Supertrend signal generator for JARVIS TRADER.

Origin: X-bookmark edge scan 2026-07-02 (Tier-B survivor `supertrend_weekly_spx`,
@QuantifiedStrat). Long the index on a Supertrend (ATR period 10, multiplier 3) buy
signal; flat to cash on a sell. Long-only. Same trend-premium family as sma12 but a
volatility-scaled trailing-stop exit instead of an SMA cross.

Economic rationale: multi-week trend-following momentum persistence in equity indices;
a vol-scaled trailing stop cuts time-at-risk and drawdown vs buy-and-hold.

Contract: operates on the passed bars (resample to weekly before calling for the
canonical variant). Returns the input frame plus:
    supertrend  : the trailing band level
    trend       : 1 (up) | -1 (down)
    position    : 1 (long) | 0 (cash)  -- long-only
    entry_signal: "ENTRY_NOW" | "NO_TRADE"
    exit_signal : "EXIT_NOW"  | "NO_EXIT"
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _wilder_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
    prev_c = close.shift(1)
    tr = pd.concat([(high - low), (high - prev_c).abs(), (low - prev_c).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


def generate_supertrend_signals(df: pd.DataFrame, atr_period: int = 10, multiplier: float = 3.0) -> pd.DataFrame:
    """Generate long-only Supertrend regime signals.

    Standard Supertrend: final upper/lower bands carried forward, trend flips when close
    crosses the opposing final band. No look-ahead (each bar uses its own close vs the
    prior bar's band); the runner shifts position to trade the next bar.
    """
    df = df.copy()
    hl2 = (df["high"] + df["low"]) / 2.0
    atr = _wilder_atr(df["high"], df["low"], df["close"], atr_period)
    upper = hl2 + multiplier * atr
    lower = hl2 - multiplier * atr

    n = len(df)
    close = df["close"].to_numpy()
    fu = upper.to_numpy().copy()
    fl = lower.to_numpy().copy()
    trend = np.ones(n, dtype=int)

    for i in range(1, n):
        # while ATR is still warming up (NaN band), carry trend, keep raw bands
        if np.isnan(fu[i - 1]) or np.isnan(fl[i - 1]):
            trend[i] = trend[i - 1]
            continue
        # final upper band: tighten unless prior close broke above it
        fu[i] = fu[i] if (fu[i] < fu[i - 1] or close[i - 1] > fu[i - 1]) else fu[i - 1]
        fl[i] = fl[i] if (fl[i] > fl[i - 1] or close[i - 1] < fl[i - 1]) else fl[i - 1]
        if close[i] > fu[i - 1]:
            trend[i] = 1
        elif close[i] < fl[i - 1]:
            trend[i] = -1
        else:
            trend[i] = trend[i - 1]

    st = np.where(trend == 1, fl, fu)
    df["supertrend"] = st
    df["trend"] = trend
    df["position"] = (trend == 1).astype(float)
    flip_up = (trend == 1) & (pd.Series(trend, index=df.index).shift(1) == -1)
    flip_dn = (trend == -1) & (pd.Series(trend, index=df.index).shift(1) == 1)
    df["entry_signal"] = np.where(flip_up.to_numpy(), "ENTRY_NOW", "NO_TRADE")
    df["exit_signal"] = np.where(flip_dn.to_numpy(), "EXIT_NOW", "NO_EXIT")
    return df
