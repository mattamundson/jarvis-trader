"""
Jesse-style Indicator Library
=============================
High-performance, clean-API technical indicators.
Focuses on event-driven calculation safety and performance.
"""

from typing import Union

import numpy as np
import pandas as pd
import pandas_ta as ta


class JesseIndicators:
    @staticmethod
    def sma(data: Union[pd.Series, np.ndarray], period: int = 20) -> np.ndarray:
        """Simple Moving Average."""
        if isinstance(data, pd.Series):
            return data.rolling(window=period).mean().values
        return ta.sma(pd.Series(data), length=period).values

    @staticmethod
    def ema(data: Union[pd.Series, np.ndarray], period: int = 50) -> np.ndarray:
        """Exponential Moving Average."""
        if isinstance(data, pd.Series):
            return data.ewm(span=period, adjust=False).mean().values
        return ta.ema(pd.Series(data), length=period).values

    @staticmethod
    def rsi(data: Union[pd.Series, np.ndarray], period: int = 14) -> np.ndarray:
        """Relative Strength Index."""
        return ta.rsi(pd.Series(data), length=period).values

    @staticmethod
    def supertrend(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 7, multiplier: float = 3.0) -> pd.DataFrame:
        """
        SuperTrend indicator (Optimized logic).
        Returns a DataFrame with [SUPERT_7_3.0, SUPERTd_7_3.0, SUPERTl_7_3.0, SUPERTs_7_3.0]
        """
        st = ta.supertrend(
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
        return ta.hma(pd.Series(data), length=period).values

    @staticmethod
    def bollinger_bands(data: Union[pd.Series, np.ndarray], period: int = 20, std_dev: float = 2.0) -> pd.DataFrame:
        """Bollinger Bands."""
        return ta.bbands(pd.Series(data), length=period, std=std_dev)

    @staticmethod
    def atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> np.ndarray:
        """Average True Range (Volatility measure)."""
        return ta.atr(pd.Series(high), pd.Series(low), pd.Series(close), length=period).values

    @staticmethod
    def stoch_rsi(data: Union[pd.Series, np.ndarray], period: int = 14, k: int = 3, d: int = 3) -> pd.DataFrame:
        """Stochastic RSI."""
        return ta.stochrsi(pd.Series(data), length=period, k=k, d=d)

    @staticmethod
    def adx(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> pd.DataFrame:
        """Average Directional Index (Trend Strength)."""
        return ta.adx(pd.Series(high), pd.Series(low), pd.Series(close), length=period)
