"""
JARVIS ANALYSIS — Regime Classification Engine
==============================================
Determines current market regime (Trending, Ranging, Volatile)
using ADX, ATR, and price action density.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np
import pandas as pd


class MarketRegime(Enum):
    TRENDING = "trending"
    RANGING = "ranging"
    VOLATILE = "volatile"
    NEUTRAL = "neutral"
    MEANREV = "meanrev"
    CRISIS = "crisis"

@dataclass
class RegimeStatus:
    regime: MarketRegime
    adx: float
    atr_ratio: float
    volatility: float
    description: str

class RegimeEngine:
    """
    Classifies market state for strategy routing.
    """

    def __init__(self, adx_threshold: float = 25.0, volatility_threshold: float = 1.5):
        self.adx_threshold = adx_threshold
        self.vol_threshold = volatility_threshold

    def classify(self, df: pd.DataFrame) -> RegimeStatus:
        """
        Identify the regime from OHLCV data.
        """
        if df.empty or len(df) < 30:
            return RegimeStatus(MarketRegime.NEUTRAL, 0, 1.0, 0, "Insufficient data")

        # 1. ADX Calculation (Simplified)
        adx = self._calculate_adx(df)

        # 2. Volatility (ATR Ratio)
        atr = self._calculate_atr(df)
        avg_atr = df["high"].sub(df["low"]).rolling(100).mean().iloc[-1]
        atr_ratio = atr / avg_atr if avg_atr > 0 else 1.0

        # 3. StdDev Volatility
        vol = df["close"].pct_change().std() * np.sqrt(252) # Annualized

        # Classification Logic
        if atr_ratio > self.vol_threshold:
            regime = MarketRegime.VOLATILE
            desc = f"Extreme volatility detected (ATR Ratio: {atr_ratio:.2f}). Priority: Risk mitigation & wide stops."
        elif adx > self.adx_threshold:
            regime = MarketRegime.TRENDING
            desc = f"Strong trend identified (ADX: {adx:.1f}). Priority: Breakout & Momentum strategies."
        elif adx < 20:
            regime = MarketRegime.RANGING
            desc = f"Market in consolidation (ADX: {adx:.1f}). Priority: Mean-reversion & Range oscillators."
        else:
            regime = MarketRegime.NEUTRAL
            desc = "No dominant regime detected. Priority: Standard signal confluence."

        return RegimeStatus(regime, adx, atr_ratio, vol, desc)

    def _calculate_adx(self, df: pd.DataFrame, period: int = 14) -> float:
        """Simplified ADX logic."""
        high = df["high"]
        low = df["low"]
        close = df["close"]

        plus_dm = high.diff()
        minus_dm = low.diff()

        plus_dm[plus_dm < 0] = 0
        plus_dm[plus_dm <= minus_dm] = 0

        minus_dm[minus_dm > 0] = 0
        minus_dm[minus_dm >= plus_dm] = 0
        minus_dm = minus_dm.abs()

        tr = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low - close.shift()).abs()
        ], axis=1).max(axis=1)

        atr = tr.rolling(period).mean()
        plus_di = 100 * (plus_dm.rolling(period).mean() / atr)
        minus_di = 100 * (minus_dm.rolling(period).mean() / atr)

        dx = 100 * (abs(plus_di - minus_di) / (plus_di + minus_di))
        adx = dx.rolling(period).mean().iloc[-1]

        return adx if not np.isnan(adx) else 0.0

    def _calculate_atr(self, df: pd.DataFrame, period: int = 14) -> float:
        high = df["high"]
        low = df["low"]
        close = df["close"]
        tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
        atr = tr.rolling(period).mean().iloc[-1]
        return atr if not np.isnan(atr) else 0.0
