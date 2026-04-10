"""
TradingView real-time price feed via tradingview-mcp CLI.

Optional data source — falls back gracefully when TradingView Desktop
is not running or Chrome CDP is not connected.

Usage:
    feed = TradingViewFeed()
    if feed.is_available():
        quote = feed.get_quote("ES1!")
        # Returns: {symbol, time, close, open, high, low, volume, bid, ask}
"""

import subprocess
import json
import logging
import shutil
from typing import Optional, Dict, Any
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

TV_CLI = "tv"  # tradingview-mcp CLI command


class TradingViewFeed:
    """Optional real-time price feed from TradingView Desktop via MCP CLI."""

    def __init__(self):
        self._available: Optional[bool] = None  # None = not yet checked

    def is_available(self) -> bool:
        """Check if TradingView Desktop + CDP is reachable."""
        if self._available is not None:
            return self._available

        # Check if 'tv' CLI is on PATH
        if not shutil.which(TV_CLI):
            # Try node-based invocation from project path
            logger.debug("TradingView MCP CLI not found on PATH; feed unavailable")
            self._available = False
            return False

        try:
            result = subprocess.run(
                [TV_CLI, "health-check"],
                capture_output=True, text=True, timeout=5
            )
            self._available = result.returncode == 0
            if not self._available:
                logger.debug("TradingView health check failed: %s", result.stderr)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            self._available = False

        return self._available

    def get_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Get current price quote for a symbol from TradingView.

        Args:
            symbol: TradingView symbol (e.g., "ES1!", "NQ1!", "MCL1!")

        Returns:
            Dict with {symbol, time, close, open, high, low, volume, bid, ask}
            or None if unavailable
        """
        if not self.is_available():
            return None

        try:
            # Switch chart to symbol and get quote
            # First set the symbol, then get the quote
            set_result = subprocess.run(
                [TV_CLI, "chart", "set-symbol", symbol],
                capture_output=True, text=True, timeout=10
            )
            if set_result.returncode != 0:
                logger.debug("Failed to set symbol %s: %s", symbol, set_result.stderr)
                return None

            quote_result = subprocess.run(
                [TV_CLI, "data", "get-quote"],
                capture_output=True, text=True, timeout=10
            )
            if quote_result.returncode != 0:
                return None

            data = json.loads(quote_result.stdout.strip())
            return {
                "symbol": symbol,
                "time": datetime.now(timezone.utc).isoformat(),
                "close": data.get("last") or data.get("close"),
                "open": data.get("open"),
                "high": data.get("high"),
                "low": data.get("low"),
                "volume": data.get("volume"),
                "bid": data.get("bid"),
                "ask": data.get("ask"),
                "source": "tradingview",
            }
        except (subprocess.TimeoutExpired, json.JSONDecodeError, KeyError) as e:
            logger.debug("TradingView quote fetch error: %s", e)
            self._available = False  # Mark unavailable on error
            return None

    def get_regime_context(self, study_filter: str = "Regime") -> Optional[Dict[str, Any]]:
        """
        Extract regime filter outputs from a custom Pine indicator via MCP.

        Reads table output from a Pine indicator named 'Regime' (or similar).
        Returns structured regime data if available.

        Args:
            study_filter: Name of the Pine indicator to read from

        Returns:
            Dict with {regime, layer_votes, stc_value} or None
        """
        if not self.is_available():
            return None

        try:
            result = subprocess.run(
                [TV_CLI, "data", "get-pine-tables", "--filter", study_filter],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode != 0:
                return None

            tables = json.loads(result.stdout.strip())
            if not tables:
                return None

            # Parse first table entry for regime string
            first_table = tables[0] if isinstance(tables, list) else tables
            return {
                "regime": first_table.get("regime") or first_table.get("text"),
                "raw": first_table,
                "source": "tradingview_pine",
            }
        except (subprocess.TimeoutExpired, json.JSONDecodeError):
            return None

    def reset_availability(self):
        """Force re-check of availability on next call."""
        self._available = None
