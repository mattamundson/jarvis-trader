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

    def get_snapshot(self, symbol: str) -> Optional[Any]:
        """
        Get full indicator snapshot via TVIndicatorBridge.
        Returns TVIndicatorSnapshot (data_quality != 'unavailable') or None.
        Delegates all logic to TVIndicatorBridge — this method is the public API.
        """
        if not self.is_available():
            return None
        try:
            from data.tv_indicator_bridge import get_tv_bridge  # lazy import
            bridge = get_tv_bridge()
            snap = bridge.get_snapshot(symbol)
            return snap if snap.data_quality != "unavailable" else None
        except Exception as e:
            logger.debug("TV bridge snapshot error: %s", e)
            return None

    def get_all_indicators(self, symbol: str) -> dict:
        """
        Return all indicator values as a flat dict for injection into pipeline.
        Returns {} if TradingView unavailable or snapshot missing.
        """
        snap = self.get_snapshot(symbol)
        if snap is None:
            return {}
        return {
            "tv_stc": snap.stc_value,
            "tv_stc_state": snap.stc_state,
            "tv_composite": snap.composite_score,
            "tv_regime": snap.regime,
            "tv_orb_high": snap.orb_high,
            "tv_orb_low": snap.orb_low,
            "tv_vwap": snap.vwap,
            "tv_atr": snap.atr_value,
            "tv_atr_neg1": snap.atr_neg1,
            "tv_atr_pos1": snap.atr_pos1,
            "tv_atr_neg2": snap.atr_neg2,
            "tv_atr_pos2": snap.atr_pos2,
            "tv_ib_high": snap.ib_high,
            "tv_ib_low": snap.ib_low,
            "tv_ib_range": snap.ib_range,
            "tv_ibu50": snap.ibu50,
            "tv_ibu100": snap.ibu100,
            "tv_ibd50": snap.ibd50,
            "tv_ibd100": snap.ibd100,
            "tv_phase": snap.phase_oscillator,
            "tv_compressed": snap.is_compressed,
            "tv_corey_score": snap.corey_score,
            "tv_poc": snap.vp_poc,
            "tv_vah": snap.vp_vah,
            "tv_val": snap.vp_val,
            "tv_pp": snap.pivot_pp,
            "tv_r1": snap.pivot_r1,
            "tv_s1": snap.pivot_s1,
            "tv_kc_upper": snap.kc_upper,
            "tv_kc_mid": snap.kc_mid,
            "tv_kc_lower": snap.kc_lower,
            "tv_kc_alignment": snap.kc_alignment,
            "tv_gap_exists": snap.gap_exists,
            "tv_gap_direction": snap.gap_direction,
            "tv_cycle_phase": snap.cycle_phase,
            "tv_ote_bull_high": snap.ote_bull_high,
            "tv_ote_bull_low": snap.ote_bull_low,
            "tv_in_bull_ote": snap.in_bull_ote,
            "tv_in_bear_ote": snap.in_bear_ote,
            "tv_vpoc_today": snap.vpoc_today,
            "tv_data_quality": snap.data_quality,
        }

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
        # Try the bridge first for richer structured data
        snap = self.get_snapshot("")
        if snap is not None and snap.data_quality != "unavailable":
            return {
                "regime": snap.regime or "RANGING",
                "composite_score": snap.composite_score,
                "stc_value": snap.stc_value,
                "stc_state": snap.stc_state,
                "is_compressed": snap.is_compressed,
                "data_quality": snap.data_quality,
                "source": "tradingview_bridge",
            }

        # Fall back to original pine tables method
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
