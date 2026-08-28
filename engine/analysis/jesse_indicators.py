"""
Jesse-style Indicator Library
=============================
High-performance, clean-API technical indicators.
Focuses on event-driven calculation safety and performance.
"""

from typing import Any, Union

import numpy as np
import pandas as pd

try:
    import pandas_ta as ta
except ModuleNotFoundError:
    ta = None


def _pandas_ta() -> Any:
    if ta is None:
        raise RuntimeError("pandas_ta is unavailable in this Python environment")
    return ta


def _atr_fallback(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int) -> np.ndarray:
    high_s = pd.Series(high, dtype="float64")
    low_s = pd.Series(low, dtype="float64")
    close_s = pd.Series(close, dtype="float64")
    true_range = pd.concat(
        [
            high_s - low_s,
            (high_s - close_s.shift(1)).abs(),
            (low_s - close_s.shift(1)).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return true_range.rolling(window=period, min_periods=1).mean().values


class JesseIndicators:
    @staticmethod
    def sma(data: Union[pd.Series, np.ndarray], period: int = 20) -> np.ndarray:
        """Simple Moving Average."""
        if isinstance(data, pd.Series):
            return data.rolling(window=period).mean().values
        return _pandas_ta().sma(pd.Series(data), length=period).values

    @staticmethod
    def ema(data: Union[pd.Series, np.ndarray], period: int = 50) -> np.ndarray:
        """Exponential Moving Average."""
        if isinstance(data, pd.Series):
            return data.ewm(span=period, adjust=False).mean().values
        return _pandas_ta().ema(pd.Series(data), length=period).values

    @staticmethod
    def rsi(data: Union[pd.Series, np.ndarray], period: int = 14) -> np.ndarray:
        """Relative Strength Index."""
        return _pandas_ta().rsi(pd.Series(data), length=period).values

    @staticmethod
    def supertrend(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 7, multiplier: float = 3.0) -> pd.DataFrame:
        """
        SuperTrend indicator (Optimized logic).
        Returns a DataFrame with [SUPERT_7_3.0, SUPERTd_7_3.0, SUPERTl_7_3.0, SUPERTs_7_3.0]
        """
        st = _pandas_ta().supertrend(
            pd.Series(high),
            pd.Series(low),
            pd.Series(close),
            length=period,
            multiplier=multiplier
        )
        return st

    @staticmethod
    def hma(data: Union[pd.Series, np.ndarray], period: int = 20) -> np.ndarray:
        """Hull Moving Average (Very fast, low lag)."""
        return _pandas_ta().hma(pd.Series(data), length=period).values

    @staticmethod
    def bollinger_bands(data: Union[pd.Series, np.ndarray], period: int = 20, std_dev: float = 2.0) -> pd.DataFrame:
        """Bollinger Bands."""
        return _pandas_ta().bbands(pd.Series(data), length=period, std=std_dev)

    @staticmethod
    def atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> np.ndarray:
        """Average True Range (Volatility measure)."""
        if ta is None:
            return _atr_fallback(high, low, close, period)
        return _pandas_ta().atr(pd.Series(high), pd.Series(low), pd.Series(close), length=period).values

    @staticmethod
    def stoch_rsi(data: Union[pd.Series, np.ndarray], period: int = 14, k: int = 3, d: int = 3) -> pd.DataFrame:
        """Stochastic RSI."""
        return _pandas_ta().stochrsi(pd.Series(data), length=period, k=k, d=d)

    @staticmethod
    def adx(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> pd.DataFrame:
        """Average Directional Index (Trend Strength)."""
        return _pandas_ta().adx(pd.Series(high), pd.Series(low), pd.Series(close), length=period)
