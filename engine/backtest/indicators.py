"""
JARVIS TRADER — Backtest Indicators
Pure-Python implementations of all ThinkorSwim-derived indicators.
No TA-Lib dependency. Uses numpy and pandas only.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from typing import Tuple, Dict, List, Optional


def wilder_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's Average True Range (used by Saty ATR Levels script)."""
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs()
    ], axis=1).max(axis=1)

    atr = pd.Series(index=close.index, dtype=float)
    atr.iloc[:period] = np.nan
    if len(tr) >= period:
        atr.iloc[period - 1] = tr.iloc[:period].mean()
        for i in range(period, len(tr)):
            atr.iloc[i] = (atr.iloc[i - 1] * (period - 1) + tr.iloc[i]) / period
    return atr


def sma_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """SMA of True Range (used by Keltner channels)."""
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def kama(close: pd.Series, period: int = 10, fast_period: int = 2, slow_period: int = 30) -> pd.Series:
    """
    Kaufman Adaptive Moving Average (KAMA).
    Used by NextSignalMomentum script. Period=10, slow=30.
    """
    fast_sc = 2.0 / (fast_period + 1)
    slow_sc = 2.0 / (slow_period + 1)

    result = pd.Series(index=close.index, dtype=float)
    result.iloc[:period] = np.nan

    if len(close) < period:
        return result

    result.iloc[period - 1] = close.iloc[period - 1]

    for i in range(period, len(close)):
        change = abs(close.iloc[i] - close.iloc[i - period])
        volatility = close.diff().abs().iloc[i - period + 1:i + 1].sum()

        if volatility == 0:
            er = 0.0
        else:
            er = change / volatility

        sc = (er * (fast_sc - slow_sc) + slow_sc) ** 2
        result.iloc[i] = result.iloc[i - 1] + sc * (close.iloc[i] - result.iloc[i - 1])

    return result


def stc(close: pd.Series, fast: int = 23, slow: int = 50,
        k_period: int = 10, d_period: int = 3) -> pd.Series:
    """
    Schaff Trend Cycle (STC).
    Used by shared_OB_STYLE_CYCLE script.
    Parameters: fast=23, slow=50, K=10, D=3.
    Oversold=19, Overbought=88.
    Returns Series 0-100.
    """
    # MACD line
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow

    def _stoch(series: pd.Series, period: int) -> pd.Series:
        lowest = series.rolling(period).min()
        highest = series.rolling(period).max()
        denom = highest - lowest
        result = pd.Series(index=series.index, dtype=float)
        mask = denom != 0
        result[mask] = (series[mask] - lowest[mask]) / denom[mask] * 100
        result[~mask] = 50.0
        return result

    # First stochastic of MACD
    k1 = _stoch(macd_line, k_period)
    d1 = k1.ewm(span=d_period, adjust=False).mean()

    # Second stochastic of smoothed
    k2 = _stoch(d1, k_period)
    stc_val = k2.ewm(span=d_period, adjust=False).mean()

    return stc_val.clip(0, 100)


def phase_oscillator(
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    ema_len: int = 21,
    atr_len: int = 14,
    bb_len: int = 21,
    bb_std: float = 2.0
) -> Tuple[pd.Series, pd.Series]:
    """
    Saty Phase Oscillator.
    Returns (phase_value, is_compression).
    Phase = (close - EMA) / (3 * ATR) * 100, clamped [-100, 100].
    Compression = Bollinger Bands narrower than ATR bands.
    """
    ema = close.ewm(span=ema_len, adjust=False).mean()
    atr = wilder_atr(high, low, close, atr_len)

    phase = ((close - ema) / (3 * atr * (atr > 0).astype(float) + 1e-10)) * 100
    phase = phase.clip(-100, 100)

    # Bollinger Bands on close
    bb_mid = close.rolling(bb_len).mean()
    bb_std_val = close.rolling(bb_len).std()
    bb_upper = bb_mid + bb_std * bb_std_val
    bb_lower = bb_mid - bb_std * bb_std_val
    bb_width = bb_upper - bb_lower

    # ATR bands width
    atr_band_width = 2 * atr

    # Compression when BB width < ATR band width
    is_compression = (bb_width < atr_band_width).fillna(False)

    return phase, is_compression


def volume_stack(
    open_: pd.Series,
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    volume: pd.Series
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    Saty Volume Stack.
    Returns (buy_vol, sell_vol, buy_pct).
    buy_vol = volume * (close - low) / (high - low)
    sell_vol = volume * (high - close) / (high - low)
    """
    hl_range = (high - low).replace(0, np.nan)
    buy_vol = volume * (close - low) / hl_range
    sell_vol = volume * (high - close) / hl_range
    buy_vol = buy_vol.fillna(volume * 0.5)
    sell_vol = sell_vol.fillna(volume * 0.5)
    total = buy_vol + sell_vol
    buy_pct = (buy_vol / total.replace(0, np.nan) * 100).fillna(50.0)
    return buy_vol, sell_vol, buy_pct


def keltner_channels(
    close: pd.Series,
    high: pd.Series,
    low: pd.Series,
    sma_len: int = 20,
    atr_factor: float = 1.5
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    Keltner Channel (used by OB_OMEGA and KMaster scripts).
    Returns (upper, basis, lower).
    Basis = SMA(20), ATR = SMA of True Range.
    """
    basis = close.rolling(sma_len).mean()
    atr = sma_atr(high, low, close, sma_len)
    upper = basis + atr_factor * atr
    lower = basis - atr_factor * atr
    return upper, basis, lower


def ib_levels(
    high: pd.Series,
    low: pd.Series,
    timestamps: pd.DatetimeIndex,
    market_open_hour: int = 9,
    market_open_minute: int = 30,
    ib_minutes: int = 60
) -> pd.DataFrame:
    """
    Initial Balance levels for each trading day.
    Returns DataFrame indexed by date with IB levels.
    """
    if not isinstance(timestamps, pd.DatetimeIndex):
        timestamps = pd.DatetimeIndex(timestamps)

    df = pd.DataFrame({
        'high': high.values,
        'low': low.values,
        'ts': timestamps
    })
    df['date'] = df['ts'].dt.date
    df['time_min'] = df['ts'].dt.hour * 60 + df['ts'].dt.minute

    open_min = market_open_hour * 60 + market_open_minute
    close_min = open_min + ib_minutes

    ib_data = {}
    for date, group in df.groupby('date'):
        ib_bars = group[(group['time_min'] >= open_min) & (group['time_min'] < close_min)]
        if len(ib_bars) == 0:
            continue
        ib_high = ib_bars['high'].max()
        ib_low = ib_bars['low'].min()
        ib_range = ib_high - ib_low
        ib_data[date] = {
            'ib_high': ib_high,
            'ib_low': ib_low,
            'ib_range': ib_range,
            'quad_25': ib_low + 0.25 * ib_range,
            'quad_50': ib_low + 0.50 * ib_range,
            'quad_75': ib_low + 0.75 * ib_range,
            'ext_50_up': ib_high + 0.50 * ib_range,
            'ext_100_up': ib_high + 1.00 * ib_range,
            'ext_300_up': ib_high + 3.00 * ib_range,
            'ext_50_down': ib_low - 0.50 * ib_range,
            'ext_100_down': ib_low - 1.00 * ib_range,
            'ext_300_down': ib_low - 3.00 * ib_range,
        }

    return pd.DataFrame.from_dict(ib_data, orient='index')


def cci(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 50
) -> pd.Series:
    """
    Commodity Channel Index (CCI).
    Used by shared_mtftrendbar script with period=50.
    Zero-cross = trend direction change.
    """
    typical = (high + low + close) / 3
    ma = typical.rolling(period).mean()
    mean_dev = typical.rolling(period).apply(
        lambda x: np.mean(np.abs(x - x.mean())), raw=True
    )
    result = (typical - ma) / (0.015 * mean_dev.replace(0, np.nan))
    return result.fillna(0)


def atr_fib_levels(
    prior_close: float,
    atr: float,
    ratios: Optional[List[float]] = None
) -> Dict[str, float]:
    """
    ATR Fibonacci levels from prior close (Saty ATR Levels script).
    Returns flat dict with both up and down levels.
    """
    if ratios is None:
        ratios = [0.236, 0.382, 0.5, 0.618, 0.786, 1.0, 1.236, 1.5, 2.0, 3.0]

    result = {}
    for r in ratios:
        key = str(r)
        result[f"up_{key}"] = prior_close + r * atr
        result[f"down_{key}"] = prior_close - r * atr
    return result


def range_consumed_pct(
    current_price: float,
    prior_close: float,
    atr: float
) -> float:
    """
    How much of the daily ATR range has been consumed.
    < 70% = room to run, > 90% = exhausted.
    """
    if atr <= 0:
        return 0.0
    return min(200.0, abs(current_price - prior_close) / atr * 100)


def volume_ratio(volume: pd.Series, period: int = 20) -> pd.Series:
    """
    Volume Ratio: current volume / rolling mean volume.
    Values > 1.0 indicate above-average volume (high conviction).
    Values < 1.0 indicate below-average volume (low conviction).
    """
    vol_ma = volume.rolling(period).mean()
    return (volume / vol_ma.replace(0, np.nan)).fillna(0.0)


def ema_ribbon(close: pd.Series) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    EMA Ribbon (8/21/34) from Saty ATR Levels script.
    Returns (ema_8, ema_21, ema_34).
    All up = bullish, all down = bearish, mixed = neutral.
    """
    ema_8 = close.ewm(span=8, adjust=False).mean()
    ema_21 = close.ewm(span=21, adjust=False).mean()
    ema_34 = close.ewm(span=34, adjust=False).mean()
    return ema_8, ema_21, ema_34
