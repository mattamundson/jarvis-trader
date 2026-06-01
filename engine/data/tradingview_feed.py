"""
TradingViewFeed — Tier 0 bar data source via TradingView Desktop CDP (port 9222).

is_available() returns False until a real CDP bar-extraction implementation is
added. The market_data.py waterfall falls through to Tier 1 (IBKR) cleanly.

Implementing Tier 0 requires CDP automation to read historical OHLCV bars from
the active TV chart widget — non-trivial and blocked until TV Desktop is
consistently running with a loaded chart.
"""

import logging

import pandas as pd

logger = logging.getLogger(__name__)


class TradingViewFeed:
    """Bar data from TradingView Desktop via CDP.

    Stub implementation. is_available() always returns False so the market_data
    waterfall routes to Tier 1 (IBKR). get_bars() returns an empty DataFrame
    matching the expected schema (timestamp column, OHLCV).
    """

    def is_available(self) -> bool:
        return False

    def get_bars(
        self,
        symbol: str,
        timeframe: str = "5m",
        limit: int = 300,
    ) -> pd.DataFrame:
        """Return empty DataFrame; caller checks .empty before using."""
        return pd.DataFrame()
