"""
Polygon.io WebSocket Streamer
Maintains a persistent connection to Polygon.io's WebSocket API,
subscribing to 1-minute aggregations ('AM' messages) to provide high-frequency
data without the overhead of HTTP polling or visual scraping.
"""
import asyncio
import json
import logging
from typing import Optional, List, Callable, Dict

try:
    import websockets
except ImportError:
    # Fallback to standard logging if websockets is not installed
    pass

try:
    from engine.config import settings
except ImportError:
    from config import settings

logger = logging.getLogger(__name__)

class PolygonStreamer:
    # Using the standard stocks cluster for equities & ETFs
    WS_URL = "wss://socket.polygon.io/stocks"
    
    def __init__(self, api_key: str, symbols: List[str]):
        self.api_key = api_key
        # 'AM' equals 1-minute aggregate bars
        self.symbols = [f"AM.{s}" for s in symbols]
        self.connection = None
        self.running = False
        self.subscribers: List[Callable[[Dict], None]] = []
        # Cache for latest 1m bars: {ticker: {timestamp, open, high, low, close, volume}}
        self.latest_bars: Dict[str, Dict] = {}

    def subscribe(self, callback: Callable[[Dict], None]) -> None:
        """Register a callback for incoming AM (aggregate per minute) messages."""
        if callback not in self.subscribers:
            self.subscribers.append(callback)

    async def connect(self) -> None:
        """Connect to Polygon WebSocket and authenticate."""
        if 'websockets' not in globals():
            logger.error("[POLYGON-WS] Install 'websockets' package to stream live data.")
            return

        self.running = True
        while self.running:
            try:
                logger.info(f"[POLYGON-WS] Connecting to {self.WS_URL}...")
                async with websockets.connect(self.WS_URL) as ws:
                    self.connection = ws
                    
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
                                
                                for cb in self.subscribers:
                                    try:
                                        # Schedule lightly parsing or handling it within the callback
                                        cb(item)
                                    except Exception as e:
                                        logger.error(f"[POLYGON-WS] Subscriber err: {e}")

            except websockets.ConnectionClosed as e:
                logger.warning(f"[POLYGON-WS] Closed natively: {e}. Reconnecting in 5s...")
                await asyncio.sleep(5)
            except Exception as e:
                logger.error(f"[POLYGON-WS] Unexpected error: {e}", exc_info=True)
                await asyncio.sleep(5)

    async def disconnect(self) -> None:
        self.running = False
        if self.connection:
            await self.connection.close()
            logger.info("[POLYGON-WS] Disconnected cleanly.")

    def get_latest_bar(self, symbol: str) -> Optional[Dict]:
        """Returns the most recent 1m bar cached from the stream."""
        return self.latest_bars.get(symbol)
