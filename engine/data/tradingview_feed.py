"""
TradingView real-time price feed via tradingview-mcp CLI.

Optional data source — falls back gracefully when TradingView Desktop
is not running or Chrome CDP is not connected.

Usage:
    feed = TradingViewFeed()
    if feed.is_available():
        quote = feed.get_quote("MES")
        bars  = feed.get_bars("MES", "1h", limit=300)

CLI contract (tv CLI v2.0.0, verified 2026-04-21):
    tv status                       → connection + current symbol/resolution
    tv state                        → same as status plus studies
    tv symbol <TICKER>              → switch chart symbol
    tv timeframe <MIN>              → switch chart resolution
    tv ohlcv -n <N>                 → pull N bars for current chart
    tv quote                        → latest quote for current chart
"""

import subprocess
import json
import logging
import shutil
import threading
import time
from typing import Optional, Dict, Any
from datetime import datetime, timezone

import pandas as pd

logger = logging.getLogger(__name__)

# Resolve the tv CLI at import time. On Windows, `npm link` installs `tv.cmd`
# (a shell wrapper) and `tv` (bash wrapper) to %APPDATA%\npm. Python's
# subprocess.run does NOT auto-append .cmd when given the bare name "tv" —
# it only searches for .exe extensions without shell=True. shutil.which
# correctly locates tv.cmd. Fall back to "tv" so the module still imports
# cleanly when tv is not linked.
TV_CLI: str = shutil.which("tv") or "tv"

# Engine symbol → TradingView ticker mapping.
# Continuous-front-month contracts (!) maintain the same price as the active
# front-month future. Micro contracts price-equivalent to standard (MES≈ES etc).
TV_SYMBOL_MAP: dict[str, str] = {
    "MES": "CME_MINI:ES1!",
    "ES":  "CME_MINI:ES1!",
    "MNQ": "CME_MINI:NQ1!",
    "NQ":  "CME_MINI:NQ1!",
    "MCL": "NYMEX:CL1!",
    "CL":  "NYMEX:CL1!",
    "MGC": "COMEX:GC1!",
    "GC":  "COMEX:GC1!",
    "M2K": "CME_MINI:RTY1!",
    "RTY": "CME_MINI:RTY1!",
    "MYM": "CBOT_MINI:YM1!",
    "YM":  "CBOT_MINI:YM1!",
    "SPY": "AMEX:SPY",
    "QQQ": "NASDAQ:QQQ",
    "IWM": "AMEX:IWM",
    "DIA": "AMEX:DIA",
}

# Engine timeframe → TradingView resolution code
TV_TIMEFRAME_MAP: dict[str, str] = {
    "1m":  "1",
    "5m":  "5",
    "15m": "15",
    "30m": "30",
    "1h":  "60",
    "4h":  "240",
    "1d":  "1D",
    "1w":  "1W",
}

# Module-level lock: the TV chart is a single shared resource. Concurrent
# fetches would race on the `tv symbol` / `tv timeframe` / `tv ohlcv` sequence
# and get mixed-symbol bars. Serialize all chart-switching fetches.
_TV_CHART_LOCK = threading.Lock()


class TradingViewFeed:
    """Optional real-time price feed from TradingView Desktop via MCP CLI."""

    def __init__(self):
        self._available: Optional[bool] = None  # None = not yet checked

    def is_available(self) -> bool:
        """Check if TradingView Desktop + CDP is reachable."""
        if self._available is not None:
            return self._available

        if not shutil.which(TV_CLI):
            logger.debug("TradingView MCP CLI not found on PATH; feed unavailable")
            self._available = False
            return False

        try:
            result = subprocess.run(
                [TV_CLI, "status"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode != 0:
                logger.debug("tv status failed: %s", result.stderr)
                self._available = False
                return False
            payload = json.loads(result.stdout.strip() or "{}")
            self._available = bool(payload.get("success") and payload.get("cdp_connected"))
            if not self._available:
                logger.debug("tv status reports not connected: %s", payload)
        except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError) as e:
            logger.debug("tv status error: %s", e)
            self._available = False

        return self._available

    def _get_state(self) -> Optional[Dict[str, Any]]:
        """Return current chart state (symbol, resolution) or None."""
        try:
            r = subprocess.run(
                [TV_CLI, "state"], capture_output=True, text=True, timeout=5
            )
            if r.returncode != 0:
                return None
            return json.loads(r.stdout.strip() or "{}")
        except (subprocess.TimeoutExpired, json.JSONDecodeError):
            return None

    def _wait_for_chart_state(
        self,
        expected_symbol: Optional[str] = None,
        expected_resolution: Optional[str] = None,
        max_wait: float = 3.0,
    ) -> bool:
        """Poll `tv state` until reported symbol/resolution match what we set.

        Returns True once the state matches (chart finished repainting),
        False if the deadline expires. Each poll issues `tv state` which
        itself takes ~150-300ms, so we get 5-8 probes inside a 3s budget —
        on a fast chart this returns well under the old fixed 600ms sleep.
        """
        deadline = time.monotonic() + max_wait
        interval = 0.1
        while time.monotonic() < deadline:
            time.sleep(interval)
            state = self._get_state()
            if state is None:
                interval = min(interval * 1.5, 0.4)
                continue
            sym_ok = (expected_symbol is None) or (state.get("symbol") == expected_symbol)
            res_ok = (expected_resolution is None) or (state.get("resolution") == expected_resolution)
            if sym_ok and res_ok:
                return True
            interval = min(interval * 1.5, 0.4)
        return False

    def _set_symbol(self, ticker: str) -> bool:
        try:
            # Timeout is 20s because TV chart switches under heavy study load
            # (gamma overlay + Corey profile + TAPivots + JARVIS MCP manifest +
            # Volume, plus duplicates) take ~11s observed 2026-04-21 on this
            # machine. 8s was the original value and produced false "Failed to
            # set TV symbol" log noise on every multi-symbol scan, even though
            # `tv symbol` itself returned success:true when given enough time.
            r = subprocess.run(
                [TV_CLI, "symbol", ticker],
                capture_output=True, text=True, timeout=20
            )
            if r.returncode != 0:
                logger.debug(
                    "tv symbol %s exit=%s stderr=%s stdout=%s",
                    ticker, r.returncode, r.stderr.strip()[:200], r.stdout.strip()[:200]
                )
                return False
            # tv symbol can return success=true but chart_ready=false; accept it
            # since the subsequent timeframe switch + sleep gives the chart time
            # to load before we call tv ohlcv.
            return True
        except subprocess.TimeoutExpired:
            logger.debug("tv symbol %s timed out", ticker)
            return False

    def _set_timeframe(self, resolution: str) -> bool:
        try:
            # 20s matches _set_symbol — same TV chart redraw latency applies.
            r = subprocess.run(
                [TV_CLI, "timeframe", resolution],
                capture_output=True, text=True, timeout=20
            )
            if r.returncode != 0:
                logger.debug(
                    "tv timeframe %s exit=%s stderr=%s stdout=%s",
                    resolution, r.returncode, r.stderr.strip()[:200], r.stdout.strip()[:200]
                )
                return False
            return True
        except subprocess.TimeoutExpired:
            logger.debug("tv timeframe %s timed out", resolution)
            return False

    def get_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Get current price quote for a symbol from TradingView.

        Args:
            symbol: engine symbol ("MES", "ES1!", etc.) — auto-mapped to TV ticker

        Returns:
            Dict with {symbol, time, close, open, high, low, volume, source}
            or None if unavailable
        """
        if not self.is_available():
            return None

        ticker = TV_SYMBOL_MAP.get(symbol.upper(), symbol)

        with _TV_CHART_LOCK:
            prior = self._get_state()
            try:
                # Only switch if necessary
                if not prior or prior.get("symbol") != ticker:
                    if not self._set_symbol(ticker):
                        logger.debug("Failed to set symbol %s", ticker)
                        return None
                    self._wait_for_chart_state(expected_symbol=ticker)

                r = subprocess.run(
                    [TV_CLI, "quote"],
                    capture_output=True, text=True, timeout=8
                )
                if r.returncode != 0:
                    return None
                data = json.loads(r.stdout.strip() or "{}")
                return {
                    "symbol": symbol,
                    "time": datetime.now(timezone.utc).isoformat(),
                    "close": data.get("last") or data.get("close"),
                    "open": data.get("open"),
                    "high": data.get("high"),
                    "low": data.get("low"),
                    "volume": data.get("volume"),
                    "source": "tradingview",
                }
            except (subprocess.TimeoutExpired, json.JSONDecodeError, KeyError) as e:
                logger.debug("TradingView quote fetch error: %s", e)
                return None
            finally:
                # Restore prior symbol so we don't leave Matt's chart on the wrong ticker
                if prior and prior.get("symbol") and prior["symbol"] != ticker:
                    self._set_symbol(prior["symbol"])

    def get_bars(
        self,
        symbol: str,
        timeframe: str = "1h",
        limit: int = 300,
    ) -> pd.DataFrame:
        """
        Get OHLCV bars for a symbol via TradingView.

        Args:
            symbol: engine symbol ("MES", "MNQ", "MCL", "SPY", etc.) — auto-mapped
            timeframe: "1m", "5m", "15m", "30m", "1h", "4h", "1d" (default "1h")
            limit: number of bars to return, max 500 per `tv ohlcv --help`

        Returns:
            DataFrame with columns [timestamp, open, high, low, close, volume].
            Empty DataFrame if TV unavailable or fetch fails.
            df.attrs["source"] = "tradingview"
            df.attrs["symbol"] = <engine symbol>
            df.attrs["ticker"] = <TV ticker>

        Notes:
            - Serializes with other chart-switching calls via module lock.
            - Preserves the user's prior chart symbol/timeframe on return.
            - Respects staleness at the caller — this method does not filter.
        """
        empty = pd.DataFrame()
        empty.attrs["source"] = "tradingview"
        empty.attrs["symbol"] = symbol

        if not self.is_available():
            logger.debug("TV not available — skipping get_bars(%s, %s)", symbol, timeframe)
            return empty

        ticker = TV_SYMBOL_MAP.get(symbol.upper())
        if ticker is None:
            logger.debug("No TV ticker mapping for %s — skipping", symbol)
            return empty

        resolution = TV_TIMEFRAME_MAP.get(timeframe.lower())
        if resolution is None:
            logger.debug("No TV resolution mapping for %s — skipping", timeframe)
            return empty

        # Clamp per tv ohlcv --help (max 500)
        bar_count = max(1, min(int(limit), 500))

        with _TV_CHART_LOCK:
            prior = self._get_state()
            prior_symbol = prior.get("symbol") if prior else None
            prior_resolution = prior.get("resolution") if prior else None

            try:
                # Switch symbol if needed — poll state for chart repaint
                if prior_symbol != ticker:
                    if not self._set_symbol(ticker):
                        logger.warning("Failed to set TV symbol %s", ticker)
                        return empty
                    if not self._wait_for_chart_state(expected_symbol=ticker):
                        logger.warning("TV chart did not settle on %s within 3s", ticker)

                # Switch timeframe if needed — poll state for chart repaint
                if prior_resolution != resolution:
                    if not self._set_timeframe(resolution):
                        logger.warning("Failed to set TV resolution %s", resolution)
                        return empty
                    if not self._wait_for_chart_state(expected_resolution=resolution):
                        logger.warning("TV chart did not settle on %s within 3s", resolution)

                # Fetch bars
                r = subprocess.run(
                    [TV_CLI, "ohlcv", "-n", str(bar_count)],
                    capture_output=True, text=True, timeout=15
                )
                if r.returncode != 0:
                    logger.warning("tv ohlcv failed: %s", r.stderr.strip()[:200])
                    return empty

                payload = json.loads(r.stdout.strip() or "{}")
                bars = payload.get("bars", [])
                if not bars:
                    logger.debug("TV returned no bars for %s %s", ticker, resolution)
                    return empty

                df = pd.DataFrame(bars)
                if "time" in df.columns:
                    df["timestamp"] = pd.to_datetime(df["time"], unit="s", utc=True)
                    df = df.drop(columns=["time"])

                # Ensure canonical column order + types
                for col in ["open", "high", "low", "close", "volume"]:
                    if col not in df.columns:
                        df[col] = 0.0
                    df[col] = pd.to_numeric(df[col], errors="coerce")

                df = df[["timestamp", "open", "high", "low", "close", "volume"]]
                df.attrs["source"] = "tradingview"
                df.attrs["symbol"] = symbol
                df.attrs["ticker"] = ticker
                df.attrs["resolution"] = resolution
                logger.info(
                    "TV returned %d %s bars for %s (ticker=%s)",
                    len(df), timeframe, symbol, ticker
                )
                return df

            except (subprocess.TimeoutExpired, json.JSONDecodeError, KeyError) as e:
                logger.warning("TV get_bars error for %s %s: %s", symbol, timeframe, e)
                return empty
            finally:
                # Restore prior chart state so Matt's workspace is unchanged
                if prior_symbol and prior_symbol != ticker:
                    self._set_symbol(prior_symbol)
                if prior_resolution and prior_resolution != resolution:
                    self._set_timeframe(prior_resolution)

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
        When TradingView is unavailable or the snapshot is missing, returns
        {"tv_data_quality": "unavailable"} so downstream consumers can branch
        on the key without KeyError.
        """
        snap = self.get_snapshot(symbol)
        if snap is None:
            return {"tv_data_quality": "unavailable"}
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
            # Gamma levels — populated only when "MY FREE GAMMA LEVELS" overlay
            # is loaded on the chart. Consumers must treat None as "no signal".
            "tv_gex_flip": snap.gex_flip,
            "tv_call_wall": snap.call_wall,
            "tv_put_wall": snap.put_wall,
            "tv_hvl": snap.hvl,
            "tv_vol_trigger_up": snap.vol_trigger_up,
            "tv_vol_trigger_down": snap.vol_trigger_down,
            "tv_max_pain": snap.max_pain,
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
