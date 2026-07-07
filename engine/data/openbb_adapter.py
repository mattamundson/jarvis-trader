"""
OpenBB Data Adapter
===================
Unified interface to access global market data via the OpenBB Platform SDK.
Replaces multiple independent data providers with a single standardized hub.
"""

import logging

import pandas as pd
from openbb import obb

logger = logging.getLogger("jarvis_trader.data.openbb")

class OpenBBAdapter:
    def __init__(self):
        """
        Initialize OpenBB Platform.
        Requires personal access tokens for specific providers to be set in .env
        or OpenBB Hub config (e.g., OPENBB_TOKEN_POLYGON, OPENBB_TOKEN_FRED).
        """
        self.obb = obb
        logger.info("✅ OpenBB: Adapter initialized")

    def get_price_history(
        self,
        symbol: str,
        interval: str = "1d",
        provider: str = "yfinance",
        **kwargs
    ) -> pd.DataFrame:
        """
        Fetch historical price data.
        Returns a standardized DataFrame with OHLCV data.
        """
        try:
            res = self.obb.equity.price.historical(
                symbol=symbol,
                interval=interval,
                provider=provider,
                **kwargs
            )
            df = res.to_df()
            logger.info(f"OpenBB: Fetched {len(df)} bars for {symbol} via {provider}")
            return df
        except Exception as e:
            logger.error(f"OpenBB: Failed to fetch price history for {symbol}: {e}")
            return pd.DataFrame()

    def get_economic_calendar(self, provider: str = "fred", **kwargs) -> pd.DataFrame:
        """Fetch global economic indicators."""
        try:
            # Note: Specific OpenBB namespace for economics
            res = self.obb.economy.calendar(provider=provider, **kwargs)
            return res.to_df()
        except Exception as e:
            logger.error(f"OpenBB: Failed to fetch economic calendar: {e}")
            return pd.DataFrame()

    def get_financials(self, symbol: str, type: str = "income_statement", provider: str = "fmp") -> pd.DataFrame:
        """Fetch fundamental data (Income, Balance Sheet, Cash Flow)."""
        try:
            if type == "income_statement":
                res = self.obb.equity.fundamental.income(symbol=symbol, provider=provider)
            elif type == "balance_sheet":
                res = self.obb.equity.fundamental.balance(symbol=symbol, provider=provider)
            elif type == "cash_flow":
                res = self.obb.equity.fundamental.cash(symbol=symbol, provider=provider)
            else:
                raise ValueError(f"Unknown financial statement type: {type}")
            return res.to_df()
        except Exception as e:
            logger.error(f"OpenBB: Failed to fetch financials for {symbol}: {e}")
            return pd.DataFrame()

    def get_options_chains(self, symbol: str, provider: str = "intrinio") -> pd.DataFrame:
        """Fetch options chains."""
        try:
            res = self.obb.derivatives.options.chains(symbol=symbol, provider=provider)
            return res.to_df()
        except Exception as e:
            logger.error(f"OpenBB: Failed to fetch options for {symbol}: {e}")
            return pd.DataFrame()
