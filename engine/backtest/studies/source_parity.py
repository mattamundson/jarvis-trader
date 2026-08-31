"""Research-only source-reference indicator implementations for parity testing.

These functions preserve formulas from legacy ThinkScript sources so JARVIS can
distinguish source parity from cleaner or standard indicator implementations.
They are not live-strategy APIs.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    return pd.concat(
        [high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs()], axis=1
    ).max(axis=1)


def _wilder_atr(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
) -> pd.Series:
    tr = _true_range(high, low, close)
    atr = pd.Series(np.nan, index=close.index, dtype=float)
    if len(tr) < period:
        return atr
    atr.iloc[period - 1] = tr.iloc[:period].mean()
    for i in range(period, len(tr)):
        atr.iloc[i] = (atr.iloc[i - 1] * (period - 1) + tr.iloc[i]) / period
    return atr


def kama_tos_legacy(
    close: pd.Series,
    period: int = 10,
    fast_sc: float = 0.4,
    slow_sc: float = 0.2222,
) -> pd.Series:
    """Core KAMA recurrence from NextSignalMomentumSTUDY.ts.

    The legacy source hard-codes smoothing bounds 0.4 and 0.2222 before
    squaring the interpolated smoothing coefficient. This is intentionally
    separate from Kaufman's conventional 2/(2+1) and 2/(30+1) constants.

    The first calculable value is seeded with close[period-1]; parity tests
    compare only after the warm-up region.
    """
    result = pd.Series(np.nan, index=close.index, dtype=float)
    if len(close) < period:
        return result

    direction = (close - close.shift(period)).abs()
    volatility = close.diff().abs().rolling(period).sum()
    er = direction.div(volatility.replace(0.0, np.nan)).fillna(0.0)
    scaled = er * (fast_sc - slow_sc) + slow_sc
    sc = scaled.pow(2)

    result.iloc[period - 1] = float(close.iloc[period - 1])
    for i in range(period, len(close)):
        prev = result.iloc[i - 1]
        result.iloc[i] = prev + sc.iloc[i] * (close.iloc[i] - prev)
    return result


def stc_tos_main_reference(
    close: pd.Series,
    fast: int = 23,
    slow: int = 50,
    k_period: int = 10,
    d_period: int = 3,
) -> pd.Series:
    """Reference form of the main ThinkScript STC.

    Models the documented price-series interpretation used by JARVIS:
    MACD -> stochastic -> EMA(D) -> stochastic -> EMA(D).
    """
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd = ema_fast - ema_slow

    def stochastic(series: pd.Series) -> pd.Series:
        lo = series.rolling(k_period).min()
        hi = series.rolling(k_period).max()
        width = hi - lo
        out = (series - lo).div(width.replace(0.0, np.nan)) * 100.0
        return out.where(width != 0.0, 50.0)

    fast_k1 = stochastic(macd)
    fast_d1 = fast_k1.ewm(span=d_period, adjust=False).mean()
    fast_k2 = stochastic(fast_d1)
    return fast_k2.ewm(span=d_period, adjust=False).mean().clip(0.0, 100.0)


def cohen_stc_recursive_reference(
    close: pd.Series,
    fast: int = 23,
    slow: int = 50,
    stc_length: int = 10,
    smooth_factor: float = 3.0,
) -> pd.Series:
    """Reference form of COHEN_MES_STC_SUB recursive alpha=1/smooth_factor STC."""
    macd = close.ewm(span=fast, adjust=False).mean() - close.ewm(span=slow, adjust=False).mean()

    def rolling_stoch(series: pd.Series) -> pd.Series:
        lo = series.rolling(stc_length).min()
        hi = series.rolling(stc_length).max()
        width = hi - lo
        out = (series - lo).div(width.replace(0.0, np.nan)) * 100.0
        return out.where(width != 0.0, 50.0)

    alpha = 1.0 / smooth_factor
    k1 = rolling_stoch(macd)
    smooth1 = pd.Series(np.nan, index=close.index, dtype=float)
    first1 = k1.first_valid_index()
    if first1 is None:
        return smooth1
    start1 = close.index.get_loc(first1)
    smooth1.iloc[start1] = k1.iloc[start1]
    for i in range(start1 + 1, len(close)):
        if np.isnan(k1.iloc[i]):
            continue
        prev = smooth1.iloc[i - 1]
        if np.isnan(prev):
            prev = k1.iloc[i]
        smooth1.iloc[i] = prev + alpha * (k1.iloc[i] - prev)

    k2 = rolling_stoch(smooth1)
    out = pd.Series(np.nan, index=close.index, dtype=float)
    first2 = k2.first_valid_index()
    if first2 is None:
        return out
    start2 = close.index.get_loc(first2)
    out.iloc[start2] = k2.iloc[start2]
    for i in range(start2 + 1, len(close)):
        if np.isnan(k2.iloc[i]):
            continue
        prev = out.iloc[i - 1]
        if np.isnan(prev):
            prev = k2.iloc[i]
        out.iloc[i] = prev + alpha * (k2.iloc[i] - prev)
    return out.clip(0.0, 100.0)


def phase_tos_source_reference(
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    ema_len: int = 21,
    atr_len: int = 14,
    phase_smooth_span: int = 3,
) -> tuple[pd.Series, pd.Series]:
    """Causal translation of the supplied Saty Phase Oscillator formulas.

    The uploaded source contains Pine-style ``ta.atr`` calls inside ThinkScript;
    this reference interprets those as Wilder ATR(14) while otherwise preserving
    the source equations. It intentionally does not clamp phase to [-100, 100].
    """
    pivot = close.ewm(span=ema_len, adjust=False).mean()
    atr = _wilder_atr(high, low, close, atr_len)
    raw_phase = ((close - pivot) / (3.0 * atr.replace(0.0, np.nan))) * 100.0
    phase = raw_phase.ewm(span=phase_smooth_span, adjust=False).mean()

    bb_offset = 2.0 * close.rolling(21).std()
    bb_up = pivot + bb_offset
    bb_down = pivot - bb_offset
    compression_threshold_up = pivot + 2.0 * atr
    compression_threshold_down = pivot - 2.0 * atr
    expansion_threshold_up = pivot + 1.854 * atr
    expansion_threshold_down = pivot - 1.854 * atr
    above_pivot = close >= pivot

    compression = pd.Series(
        np.where(
            above_pivot,
            bb_up - compression_threshold_up,
            compression_threshold_down - bb_down,
        ),
        index=close.index,
        dtype=float,
    )
    expansion_zone = pd.Series(
        np.where(
            above_pivot,
            bb_up - expansion_threshold_up,
            expansion_threshold_down - bb_down,
        ),
        index=close.index,
        dtype=float,
    )
    expansion = compression.shift(1) <= compression
    tracker = pd.Series(
        np.where(expansion & (expansion_zone > 0), 0, np.where(compression <= 0, 1, 0)),
        index=close.index,
        dtype=int,
    ).astype(bool)
    return phase, tracker
