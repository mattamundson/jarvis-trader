"""
TradingViewFeed — Tier 0 bar data source via TradingView Desktop CDP (port 9222).

Uses the local `tradingview-mcp` CLI to drive TradingView Desktop directly.
Confirmed working symbol format for CME Micro E-mini S&P: ``MES1!``.
"""

from __future__ import annotations

import json
import logging
import subprocess
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

_BASE_DIR = Path(__file__).parent.parent.parent
_CLI = _BASE_DIR / "tradingview-mcp" / "src" / "cli" / "index.js"
_LAUNCHER = Path(r"C:\Users\mattm\master-jarvis\launch-tv-cdp.ps1")
_SYMBOL = "MES1!"
_TIMEFRAME = "5"
_BARS_LIMIT = 300
_CHART_STABILIZE_TIMEOUT_SECONDS = 30
_CHART_STABILIZE_POLL_INTERVAL_SECONDS = 3
_OHLCV_RETRIES = 3
_OHLCV_RETRY_DELAY_SECONDS = 2

_TIMEFRAME_MAP = {
    "1m": "1",
    "5m": "5",
    "15m": "15",
    "30m": "30",
    "60m": "60",
    "1h": "60",
    "4h": "240",
    "1d": "D",
    "1w": "W",
    "1M": "M",
}

_DISCORD_WEBHOOK = (
    __import__("os").getenv("DISCORD_WEBHOOK_URL") or ""
).strip()


class TradingViewFeed:
    """Bar data from TradingView Desktop via CDP."""

    def __init__(
        self,
        cli: Optional[Path] = None,
        launcher: Optional[Path] = None,
        symbol: str = _SYMBOL,
        timeframe: str = _TIMEFRAME,
        limit: int = _BARS_LIMIT,
    ) -> None:
        self.cli = cli or _CLI
        self.launcher = launcher or _LAUNCHER
        self.symbol = symbol
        self.timeframe = timeframe
        self.limit = limit

    def is_available(self) -> bool:
        if not self.cli.exists():
            logger.warning("[TradingViewFeed] CLI not found at %s", self.cli)
            return False
        try:
            result = subprocess.run(
                ["node", str(self.cli), "status"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            payload = json.loads(result.stdout)
            return bool(payload.get("success") and payload.get("cdp_connected"))
        except Exception as exc:
            logger.warning("[TradingViewFeed] availability check failed: %s", exc)
            return False

    def _run(self, *args: str) -> dict:
        cmd = ["node", str(self.cli), *args]
        logger.debug("[TradingViewFeed] running: %s", " ".join(cmd))
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            logger.debug("[TradingViewFeed] stderr: %s", result.stderr.strip())
        payload = json.loads(result.stdout) if result.stdout.strip() else {}
        return payload

    def _normalize_timeframe(self, timeframe: str) -> str:
        normalized = _TIMEFRAME_MAP.get(timeframe)
        if normalized:
            return normalized
        if timeframe.endswith("m"):
            return timeframe[:-1]
        return timeframe

    def _send_alert(self, message: str) -> None:
        if not _DISCORD_WEBHOOK:
            return
        try:
            payload = json.dumps({"content": message}).encode("utf-8")
            req = urllib.request.Request(
                _DISCORD_WEBHOOK,
                data=payload,
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                if response.status != 204:
                    logger.warning("[TradingViewFeed] webhook returned %s", response.status)
        except Exception as exc:
            logger.warning("[TradingViewFeed] webhook send failed: %s", exc)

    def _self_heal(self) -> bool:
        launcher = self.launcher
        if not launcher.exists():
            logger.warning("[TradingViewFeed] launcher not found at %s", launcher)
            return False
        try:
            subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(launcher),
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except Exception as exc:
            logger.warning("[TradingViewFeed] self-heal launch failed: %s", exc)
            return False

        deadline = time.time() + _CHART_STABILIZE_TIMEOUT_SECONDS
        while time.time() < deadline:
            if self.is_available():
                return True
            time.sleep(_CHART_STABILIZE_POLL_INTERVAL_SECONDS)
        return False

    def _stabilize_chart(self) -> bool:
        deadline = time.time() + _CHART_STABILIZE_TIMEOUT_SECONDS
        last_payload = {}
        while time.time() < deadline:
            quote_payload = self._run("quote")
            if isinstance(quote_payload, dict) and quote_payload.get("success") and quote_payload.get("symbol"):
                return True
            last_payload = quote_payload
            time.sleep(_CHART_STABILIZE_POLL_INTERVAL_SECONDS)
        logger.debug("[TradingViewFeed] chart did not stabilize within timeout: %s", last_payload)
        return False

    def _fetch_ohlcv(self, limit: int) -> Optional[pd.DataFrame]:
        for attempt in range(1, _OHLCV_RETRIES + 1):
            payload = self._run("ohlcv", "-n", str(limit))
            if isinstance(payload, dict) and payload.get("success") and payload.get("bars"):
                bars = payload["bars"]
                return pd.DataFrame(
                    {
                        "timestamp": [datetime.fromtimestamp(bar["time"], tz=timezone.utc) for bar in bars],
                        "open": [float(bar["open"]) for bar in bars],
                        "high": [float(bar["high"]) for bar in bars],
                        "low": [float(bar["low"]) for bar in bars],
                        "close": [float(bar["close"]) for bar in bars],
                        "volume": [float(bar["volume"]) for bar in bars],
                    }
                )
            logger.debug("[TradingViewFeed] ohlcv attempt %s failed: %s", attempt, payload)
            time.sleep(_OHLCV_RETRY_DELAY_SECONDS)
        return None

    def get_bars(
        self,
        symbol: str,
        timeframe: str = "5m",
        limit: int = 300,
    ) -> pd.DataFrame:
        symbol = symbol or self.symbol
        timeframe = self._normalize_timeframe(timeframe)
        limit = limit or self.limit

        if not self.is_available():
            logger.info("[TradingViewFeed] CDP unavailable, attempting self-heal...")
            self._send_alert("[JARVIS] TradingView CDP unavailable; attempting self-heal.")
            if not self._self_heal() or not self.is_available():
                logger.warning("[TradingViewFeed] self-heal failed; returning empty bars")
                self._send_alert("[JARVIS] TradingView CDP self-heal failed.")
                return pd.DataFrame()

        try:
            set_symbol = self._run("symbol", symbol)
            if not isinstance(set_symbol, dict) or not set_symbol.get("success"):
                logger.warning("[TradingViewFeed] symbol switch failed: %s", set_symbol)
                self._send_alert("[JARVIS] TradingView symbol switch failed.")
                return pd.DataFrame()

            set_tf = self._run("timeframe", timeframe)
            if not isinstance(set_tf, dict) or not set_tf.get("success"):
                logger.warning("[TradingViewFeed] timeframe switch failed: %s", set_tf)
                self._send_alert("[JARVIS] TradingView timeframe switch failed.")
                return pd.DataFrame()

            if not self._stabilize_chart():
                logger.warning("[TradingViewFeed] chart did not stabilize after symbol/tf change")
                self._send_alert("[JARVIS] TradingView chart did not stabilize after symbol/timeframe change.")
                return pd.DataFrame()

            frame = self._fetch_ohlcv(limit)
            if frame is None or frame.empty:
                self._send_alert("[JARVIS] TradingView returned empty bars after successful connection.")
                return pd.DataFrame()

            frame.attrs["source"] = "tradingview"
            frame.attrs["symbol"] = symbol
            return frame
        except Exception as exc:
            logger.warning("[TradingViewFeed] get_bars failed: %s", exc)
            self._send_alert(f"[JARVIS] TradingView feed error: {exc}")
            return pd.DataFrame()
