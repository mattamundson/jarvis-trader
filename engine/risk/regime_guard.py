"""
RegimeGuard Agent
=================
Uses technical indicators (ADX, Volatility) to determine the current market regime.
Ensures that strategies (like Market Making) only run in suitable environments.
"""

import logging
from datetime import datetime

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

        Production note (2026-05-20): `data_manager.get_bars()` returns a
        `pd.DataFrame` (see engine/data/market_data.py:773). Earlier revisions
        of this method assumed a list-of-bar-objects interface and used naked
        DataFrame truthiness (`if not bars`), which raises ValueError; the
        bare except below then silently returned "unknown" for every call,
        permanently blocking mean-reversion strategy admission. Regression
        test: tests/test_regime_guard.py::TestProductionDataFrameInterface.
        """
        try:
            # Fetch 100 bars of 1h data for stable indicator calculation
            bars = await self.data_manager.get_bars(symbol, timeframe="1h", count=100)

            # Normalize: accept either a pd.DataFrame (production path —
            # MarketDataManager.get_bars()) or a list-of-bar-objects (legacy
            # test/connector path). Both flow into a DataFrame with OHLCV cols.
            if isinstance(bars, pd.DataFrame):
                if bars.empty or len(bars) < 20:
                    return "unknown"
                df = bars
            else:
                if not bars or len(bars) < 20:
                    return "unknown"
                df = pd.DataFrame([b.__dict__ if hasattr(b, "__dict__") else b for b in bars])

            # Guard against missing OHLC columns (e.g. CSV-cache schema drift)
            required_cols = {"high", "low", "close"}
            if not required_cols.issubset(df.columns):
                logger.warning(
                    f"RegimeGuard: {symbol} bars missing OHLC columns "
                    f"(have {list(df.columns)}) — returning 'unknown'"
                )
                return "unknown"

            # Calculate ADX
            adx_df = self.indicators.adx(df["high"].values, df["low"].values, df["close"].values)

            if adx_df is None or adx_df.empty:
                return "unknown"

            # ADX column is usually named 'ADX_14' by pandas_ta
            adx_cols = [c for c in adx_df.columns if "ADX" in c]
            if not adx_cols:
                return "unknown"
            current_adx = adx_df[adx_cols[0]].iloc[-1]

            # NaN guard — early ADX samples are NaN until the smoothing window fills
            if pd.isna(current_adx):
                return "unknown"

            if current_adx > self.adx_threshold:
                regime = "trending"
            else:
                regime = "ranging"

            self.last_regime = regime
            self.last_check = datetime.now()

            logger.info(f"RegimeGuard: {symbol} ADX={current_adx:.2f} -> {regime}")
            return regime

        except Exception as e:
            # Bare except retained intentionally: this method gates strategy
            # admission and must NEVER propagate. But we now log the exception
            # type so future drift (like the 2026-05-20 DataFrame-truthiness
            # silent failure) is visible at WARN, not buried.
            logger.error(
                f"RegimeGuard failed to detect regime for {symbol}: " f"{type(e).__name__}: {e}"
            )
            return "unknown"

    def is_suitable_for_mm(self, symbol: str = "SPY") -> bool:
        """
        Market Making thrives in mean-reverting (ranging) markets.
        Returns True if the regime is "ranging".
        """
        return self.last_regime == "ranging"
