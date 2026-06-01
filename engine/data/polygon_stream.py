"""
Polygon.io WebSocket Streamer
Maintains a persistent connection to Polygon.io's WebSocket API,
subscribing to 1-minute aggregations ('AM' messages) to provide high-frequency
data without the overhead of HTTP polling or visual scraping.
"""

import asyncio
import inspect
import json
import logging
import time
from collections.abc import Coroutine
from typing import Callable, Dict, List, Optional, Union

try:
    import websockets
except ImportError:
    # Fallback to standard logging if websockets is not installed
    pass

try:
    from engine.config import settings  # noqa: F401  (presence-check only)
except ImportError:
    pass

logger = logging.getLogger(__name__)

_SubscriberT = Union[Callable[[Dict], None], Callable[[Dict], Coroutine]]


class PolygonStreamer:
    # Using the standard stocks cluster for equities & ETFs
    WS_URL = "wss://socket.polygon.io/stocks"

    _RECONNECT_DELAY_INITIAL = 5  # seconds
    _RECONNECT_DELAY_MAX = 300  # cap at 5 minutes
    _RECONNECT_MULTIPLIER = 2

    def __init__(self, api_key: str, symbols: List[str]):
        self.api_key = api_key
        # 'AM' equals 1-minute aggregate bars
        self.symbols = [f"AM.{s}" for s in symbols]
        self.connection = None
        self.running = False
        self.subscribers: List[Callable[[Dict], None]] = []
        # Cache for latest 1m bars: {ticker: {timestamp, open, high, low, close, volume}}
        self.latest_bars: Dict[str, Dict] = {}
        # Exponential backoff state for reconnects
        self._reconnect_delay = self._RECONNECT_DELAY_INITIAL
        self.last_message_ts: float = 0.0

    def subscribe(self, callback: Callable[[Dict], None]) -> None:
        """Register a callback for incoming AM (aggregate per minute) messages."""
        if callback not in self.subscribers:
            self.subscribers.append(callback)

    def seconds_since_last_bar(self) -> float:
        """Returns seconds elapsed since the last AM bar was received, or inf if never."""
        if self.last_message_ts == 0.0:
            return float("inf")
        return time.monotonic() - self.last_message_ts

    async def connect(self) -> None:
        """Connect to Polygon WebSocket and authenticate."""
        if "websockets" not in globals():
            logger.error("[POLYGON-WS] Install 'websockets' package to stream live data.")
            return

        self.running = True
        while self.running:
            try:
                logger.info(f"[POLYGON-WS] Connecting to {self.WS_URL}...")
                async with websockets.connect(self.WS_URL) as ws:
                    self.connection = ws

                    # Polygon sends an initial "connected" greeting on connect; consume
                    # it before authenticating so the next recv() is the auth result.
                    await ws.recv()

                    # Authenticate
                    auth_message = {"action": "auth", "params": self.api_key}
                    await ws.send(json.dumps(auth_message))
                    auth_response = await ws.recv()
                    logger.info(f"[POLYGON-WS] Auth Response: {auth_response}")
                    auth_data = json.loads(auth_response)
                    if isinstance(auth_data, list):
                        auth_data = auth_data[0]
                    if auth_data.get("status") in ("auth_failed", "auth_timeout"):
                        logger.warning(
                            "[POLYGON-WS] Auth rejected (plan does not include WebSocket). "
                            "Disabling streamer -- REST fallback still active."
                        )
                        self.running = False
                        return

                    # Successful auth — reset backoff
                    self._reconnect_delay = self._RECONNECT_DELAY_INITIAL

                    # Subscribe to 1m aggregations
                    sub_message = {"action": "subscribe", "params": ",".join(self.symbols)}
                    logger.info(f"[POLYGON-WS] Subscribing to: {self.symbols}")
                    await ws.send(json.dumps(sub_message))
                    sub_response = await ws.recv()
                    logger.info(f"[POLYGON-WS] Sub Response: {sub_response}")

                    # Listen indefinitely
                    while self.running:
                        message = await ws.recv()
                        data = json.loads(message)
                        for item in data:
                            # Deliver 1-min Aggregate Messages ('AM') to listeners
                            if item.get("ev") == "AM":
                                ticker = item.get("sym", "UNKNOWN")
                                # Update internal cache for get_current_price waterfall
                                self.latest_bars[ticker] = {
                                    "timestamp": item.get("e"),  # end time of the bar
                                    "open": item.get("o"),
                                    "high": item.get("h"),
                                    "low": item.get("l"),
                                    "close": item.get("c"),
                                    "volume": item.get("v"),
                                }
                                self.last_message_ts = time.monotonic()

                                for cb in self.subscribers:
                                    cb_name = getattr(cb, "__name__", repr(cb))
                                    try:
                                        if inspect.iscoroutinefunction(cb):
                                            await cb(item)
                                        else:
                                            cb(item)
                                    except Exception as e:
                                        logger.error(
                                            f"[POLYGON-WS] Subscriber '{cb_name}' raised: {e}",
                                            exc_info=True,
                                        )

            except websockets.ConnectionClosed as e:
                logger.warning(
                    f"[POLYGON-WS] Closed natively: {e}. "
                    f"Reconnecting in {self._reconnect_delay}s..."
                )
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(
                    self._reconnect_delay * self._RECONNECT_MULTIPLIER,
                    self._RECONNECT_DELAY_MAX,
                )
            except Exception as e:
                logger.error(f"[POLYGON-WS] Unexpected error: {e}", exc_info=True)
                logger.warning(f"[POLYGON-WS] Retrying in {self._reconnect_delay}s...")
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(
                    self._reconnect_delay * self._RECONNECT_MULTIPLIER,
                    self._RECONNECT_DELAY_MAX,
                )

    async def disconnect(self) -> None:
        self.running = False
        if self.connection:
            await self.connection.close()
            logger.info("[POLYGON-WS] Disconnected cleanly.")

    def get_latest_bar(self, symbol: str) -> Optional[Dict]:
        """Returns the most recent 1m bar cached from the stream."""
        return self.latest_bars.get(symbol)
