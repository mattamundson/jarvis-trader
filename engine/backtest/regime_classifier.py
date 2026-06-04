"""
JARVIS TRADER — Regime Classifier v2
Advanced market regime detection including TREND, MEANREV, RANGE, VOLATILE, and CRISIS.
Implements the requirements from Phase 2 of the JARVIS Master Battle Plan.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Dict, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger("jarvis_trader.regime_v2")

class MarketRegime(str, Enum):
    TREND = "TREND"
    MEANREV = "MEANREV"
    RANGE = "RANGE"
    VOLATILE = "VOLATILE"
    CRISIS = "CRISIS"

class RegimeClassifierV2:
    """
    Classifies market state into 5 distinct regimes for strategy routing.

    Logic:
    1. CRISIS: VIX > 35 or extreme volatility with negative trend.
    2. VOLATILE: High ATR relative to median.
    3. TREND: Strong EMA alignment and ADX-like directional strength.
    4. MEANREV: Bollinger compression followed by reversal signals.
    5. RANGE: Default state when no strong signals exist.
    """

    def __init__(
        self,
        vix_crisis_threshold: float = 35.0,
        atr_volatile_threshold: float = 1.8,
        persistence_bars: int = 3,  # Minimum bars to hold a regime
    ):
        self._vix_crisis_threshold = vix_crisis_threshold
        self._atr_volatile_threshold = atr_volatile_threshold
        self._persistence_bars = persistence_bars
        self._last_regime: Optional[MarketRegime] = None
        self._regime_counter: int = 0

    def classify(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Add 'regime_v2' column to DataFrame.
        Expected columns: open, high, low, close, volume, vix (optional), atr, ema_8, ema_21, ema_34.
        """
        df = df.copy()
        regimes = []

        # Ensure required indicators exist
        if "atr" not in df.columns:
            from backtest.indicators import wilder_atr
            df["atr"] = wilder_atr(df["high"], df["low"], df["close"], period=14)

        atr_median = df["atr"].rolling(50).median()
        atr_norm = (df["atr"] / atr_median.replace(0, np.nan)).fillna(1.0)

        # EMA alignment for trend
        # We assume these exist or we compute them
        for p in [8, 21, 34]:
            col = f"ema_{p}"
            if col not in df.columns:
                df[col] = df["close"].ewm(span=p, adjust=False).mean()

        # Bollinger Bands for MeanRev/Range
        std = df["close"].rolling(20).std()
        mid = df["close"].rolling(20).mean()
        bbw = (4 * std / mid).fillna(0)
        bbw_median = bbw.rolling(50).median()
        bbw_norm = (bbw / bbw_median.replace(0, np.nan)).fillna(1.0)

        for i in range(len(df)):
            row = df.iloc[i]
            vix = row.get("vix", 0)

            # 1. CRISIS Check
            if vix > self._vix_crisis_threshold:
                current = MarketRegime.CRISIS
            elif row["close"] < row["ema_34"] and atr_norm.iloc[i] > 2.5:
                current = MarketRegime.CRISIS

            # 2. VOLATILE Check
            elif atr_norm.iloc[i] > self._atr_volatile_threshold:
                current = MarketRegime.VOLATILE

            # 3. TREND Check
            elif (row["ema_8"] > row["ema_21"] > row["ema_34"]) or \
                 (row["ema_8"] < row["ema_21"] < row["ema_34"]):
                current = MarketRegime.TREND

            # 4. MEANREV Check (Compression)
            elif bbw_norm.iloc[i] < 0.8:
                current = MarketRegime.MEANREV

            # 5. RANGE (Default)
            else:
                current = MarketRegime.RANGE

            # Apply Persistence Logic
            if current == self._last_regime:
                self._regime_counter += 1
            else:
                if self._regime_counter < self._persistence_bars and self._last_regime:
                    current = self._last_regime
                    self._regime_counter += 1
                else:
                    self._last_regime = current
                    self._regime_counter = 1

            regimes.append(current)

        df["regime_v2"] = [r.value for r in regimes]
        return df

    def get_summary(self, df: pd.DataFrame) -> Dict[str, float]:
        if "regime_v2" not in df.columns:
            df = self.classify(df)
        counts = df["regime_v2"].value_counts(normalize=True) * 100
        return counts.to_dict()

    def classify_latest(self, df: pd.DataFrame) -> dict:
        """
        Classify only the latest bar and return a descriptive dict.
        """
        if df.empty or len(df) < 50:
            return {
                "regime": MarketRegime.RANGE.value,
                "description": "Insufficient data for V2 classification",
                "atr_norm": 1.0,
            }

        classified = self.classify(df)
        last_row = classified.iloc[-1]

        # Calculate some extra context for the prompt
        atr_median = classified["atr"].tail(50).median()
        atr_norm = last_row["atr"] / atr_median if atr_median > 0 else 1.0

        return {
            "regime": last_row["regime_v2"],
            "description": f"Market state: {last_row['regime_v2']} | ATR Norm: {atr_norm:.2f}",
            "atr_norm": round(atr_norm, 3),
            "ema_alignment": {
                "8": round(last_row.get("ema_8", 0), 2),
                "21": round(last_row.get("ema_21", 0), 2),
                "34": round(last_row.get("ema_34", 0), 2),
            }
        }
