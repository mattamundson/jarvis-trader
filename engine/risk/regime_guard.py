"""
RegimeGuard Agent
=================
Uses technical indicators (ADX, Volatility) to determine the current market regime.
Ensures that strategies (like Market Making) only run in suitable environments.
"""

import logging
from datetime import datetime

import numpy as np
import pandas as pd

from analysis.jesse_indicators import JesseIndicators

logger = logging.getLogger("jarvis_trader.risk.regime_guard")

class RegimeGuard:
    def __init__(self, data_manager, adx_threshold: float = 25.0):
        self.data_manager = data_manager
        self.adx_threshold = adx_threshold
        self.last_regime = "unknown"
        self.last_check = None
        self.indicators = JesseIndicators()

    async def get_market_regime(self, symbol: str = "SPY") -> str:
        """
        Calculates the current market regime for a symbol.
        Returns "trending" (ADX > threshold) or "ranging" (ADX < threshold).
        """
        try:
            # Fetch 100 bars of 1h data for stable indicator calculation
            bars = await self.data_manager.get_bars(symbol, timeframe="1h", count=100)
            if not bars or len(bars) < 20:
                return "unknown"

            df = pd.DataFrame([b.__dict__ if hasattr(b, "__dict__") else b for b in bars])

            # Calculate ADX
            adx_df = self.indicators.adx(
                df['high'].values, 
                df['low'].values, 
                df['close'].values
            )

            if adx_df is None or adx_df.empty:
                return "unknown"

            # ADX column is usually named 'ADX_14' by pandas_ta
            adx_col = [c for c in adx_df.columns if 'ADX' in c][0]
            current_adx = adx_df[adx_col].iloc[-1]

            if current_adx > self.adx_threshold:
                regime = "trending"
            else:
                regime = "ranging"

            self.last_regime = regime
            self.last_check = datetime.now()

            logger.info(f"RegimeGuard: {symbol} ADX={current_adx:.2f} -> {regime}")
            return regime

        except Exception as e:
            logger.error(f"RegimeGuard failed to detect regime for {symbol}: {e}")
            return "unknown"

    def is_suitable_for_mm(self, symbol: str = "SPY") -> bool:
        """
        Market Making thrives in mean-reverting (ranging) markets.
        Returns True if the regime is "ranging".
        """
        return self.last_regime == "ranging"
