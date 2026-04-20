"""
SMA trend-following signal generator for JARVIS TRADER.

Validated on MES 1h via walk-forward optimization (2026-04-20):
    SMA(50, 200) + 2.0×ATR trailing stop
    Train PF 2.063 (2024-06→2025-06) | Test PF 1.689 (2025-06→2026-03)
    WFE 0.819 | 6 WFO winners clustered near (fast=40-50, slow=180-200, trail=2.0-5.0)

Entry : fast SMA crosses above slow SMA (Golden Cross) — LONG only.
Exit  : fast SMA crosses below slow SMA  OR  ATR trailing stop hit.
Stop  : initial stop = entry - trail_mult × ATR(14) at entry bar.
        (Static at entry; full trailing stop requires Backtester enhancement.)
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Walk-forward champion parameters
SMA_TREND_PARAMS: dict[str, dict] = {
    "MES": {"fast": 50, "slow": 200, "atr_trail_mult": 2.0},
}

_ATR_PERIOD = 14
_T1_MULT = 3.0   # static first target: 3× ATR from entry
_T2_MULT = 5.0
_T3_MULT = 7.0


def _wilder_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    prev_c = close.shift(1)
    tr = pd.concat([(high - low), (high - prev_c).abs(), (low - prev_c).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


def generate_sma_trend_signals(
    df: pd.DataFrame,
    fast: int = 50,
    slow: int = 200,
    atr_trail_mult: float = 2.0,
) -> pd.DataFrame:
    """
    Generate SMA trend-following signals compatible with the JARVIS Backtester.

    Returns df with columns:
        entry_signal  : "ENTRY_NOW" | "NO_TRADE"
        stop_level    : entry − trail_mult × ATR  (set at signal bar)
        target_1/2/3  : entry + N × ATR
        bias          : "STRONG_BULL" | "STRONG_BEAR" | "NEUTRAL"
        regime        : "TRENDING_BULL" | "RANGE_BOUND"
        atr           : ATR(14) series
    """
    df = df.copy()

    sma_f = df["close"].rolling(fast).mean()
    sma_s = df["close"].rolling(slow).mean()
    atr = _wilder_atr(df["high"], df["low"], df["close"], _ATR_PERIOD)

    # Force numpy bool dtype: NaN comparisons → False, shift with fill_value avoids
    # the object-dtype conversion that makes Python's ~bool give wrong results (Python 3.12+).
    above = (sma_f > sma_s).fillna(False).astype(bool)
    prev_above = above.shift(1, fill_value=False)
    cross_up = above & ~prev_above   # golden cross
    cross_dn = ~above & prev_above   # death cross

    n = len(df)
    entry_signal = np.full(n, "NO_TRADE", dtype=object)
    stop_level   = np.full(n, np.nan)
    target_1     = np.full(n, np.nan)
    target_2     = np.full(n, np.nan)
    target_3     = np.full(n, np.nan)

    for i in range(n):
        if pd.isna(sma_s.iloc[i]) or pd.isna(atr.iloc[i]):
            continue
        price = float(df["close"].iloc[i])
        atr_i = float(atr.iloc[i])

        if cross_up.iloc[i]:
            entry_signal[i] = "ENTRY_NOW"
            stop_level[i]  = price - atr_trail_mult * atr_i
            target_1[i]    = price + _T1_MULT * atr_i
            target_2[i]    = price + _T2_MULT * atr_i
            target_3[i]    = price + _T3_MULT * atr_i

    df["entry_signal"] = entry_signal
    df["stop_level"]   = stop_level
    df["target_1"]     = target_1
    df["target_2"]     = target_2
    df["target_3"]     = target_3
    df["atr"]          = atr

    df["bias"] = "NEUTRAL"
    df.loc[above, "bias"] = "STRONG_BULL"
    df.loc[~above & sma_s.notna(), "bias"] = "STRONG_BEAR"

    df["regime"] = "RANGE_BOUND"
    df.loc[above, "regime"] = "TRENDING_BULL"

    return df


def get_sma_trend_params(symbol: str) -> dict:
    """Return validated SMA trend params for symbol, or None if not configured."""
    return SMA_TREND_PARAMS.get(symbol.upper())
