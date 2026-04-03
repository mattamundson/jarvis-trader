"""
WebSocket Price Feed Manager
=============================
Real-time price updates for trading symbols (MCL, MNQ, etc.).
Handles client connections, broadcasts price updates, and manages heartbeats.
"""

import asyncio
import logging
from datetime import datetime
from typing import Set

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

# Price feed connection manager (singleton)
_price_feed_manager = None


def get_price_feed_manager():
    """Get or create the global price feed manager."""
    global _price_feed_manager
    if _price_feed_manager is None:
        _price_feed_manager = PriceFeedManager()
    return _price_feed_manager


class PriceFeedManager:
    """
    Manages WebSocket connections for real-time price feeds.

    Tracks active connections, broadcasts price updates, and maintains heartbeat.
    """

    def __init__(self):
        self.active_connections: Set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket):
        """Accept a new WebSocket connection and add to active connections."""
        await websocket.accept()
        async with self._lock:
            self.active_connections.add(websocket)
        logger.info(f"Price feed client connected. Total: {len(self.active_connections)}")

    async def disconnect(self, websocket: WebSocket):
        """Remove a disconnected client from active connections."""
        async with self._lock:
            self.active_connections.discard(websocket)
        logger.info(f"Price feed client disconnected. Total: {len(self.active_connections)}")

    async def broadcast_price(self, symbol: str, price: float, change_pct: float = 0.0):
        """
        Broadcast a price update to all connected clients.

        Args:
            symbol: Trading symbol (e.g., "MCL", "MNQ")
            price: Current price
            change_pct: Percentage change from previous price
        """
        message = {
            "type": "price",
            "symbol": symbol,
            "price": price,
            "timestamp": datetime.now().isoformat(),
            "change_pct": change_pct,
        }

        if not self.active_connections:
            return

        async with self._lock:
            connections_copy = list(self.active_connections)

        disconnected = set()

        for websocket in connections_copy:
            try:
                await websocket.send_json(message)
            except Exception as e:
                logger.debug(f"Failed to send price update: {e}")
                disconnected.add(websocket)

        if disconnected:
            async with self._lock:
                self.active_connections.difference_update(disconnected)

    async def broadcast_heartbeat(self):
        """Send heartbeat to all connected clients."""
        message = {
            "type": "heartbeat",
            "timestamp": datetime.now().isoformat(),
        }

        if not self.active_connections:
            return

        async with self._lock:
            connections_copy = list(self.active_connections)

        disconnected = set()

        for websocket in connections_copy:
            try:
                await websocket.send_json(message)
            except Exception as e:
                logger.debug(f"Heartbeat send failed: {e}")
                disconnected.add(websocket)

        if disconnected:
            async with self._lock:
                self.active_connections.difference_update(disconnected)

    def get_connection_count(self) -> int:
        """Get the current number of active connections."""
        return len(self.active_connections)


async def price_feed_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for real-time price updates.

    Accepts connections at /ws/prices.
    Broadcasts price updates with heartbeat every 30 seconds.
    Handles client messages (subscribe/unsubscribe).
    """
    manager = get_price_feed_manager()

    if not manager:
        await websocket.close(code=1011, reason="Price feed manager not initialized")
        return

    await manager.connect(websocket)

    try:
        heartbeat_interval = 30  # seconds
        last_heartbeat = datetime.now()
        subscribed_symbols = {"MCL", "MNQ"}  # Default subscriptions

        while True:
            try:
                # Receive with timeout to allow periodic heartbeat
                data = await asyncio.wait_for(websocket.receive_json(), timeout=heartbeat_interval)

                # Handle subscribe/unsubscribe messages
                if data.get("type") == "subscribe":
                    symbol = data.get("symbol")
                    if symbol:
                        subscribed_symbols.add(symbol)
                        logger.debug(f"Client subscribed to {symbol}")

                elif data.get("type") == "unsubscribe":
                    symbol = data.get("symbol")
                    if symbol:
                        subscribed_symbols.discard(symbol)
                        logger.debug(f"Client unsubscribed from {symbol}")

            except asyncio.TimeoutError:
                # Send heartbeat
                now = datetime.now()
                if (now - last_heartbeat).total_seconds() >= heartbeat_interval:
                    try:
                        await manager.broadcast_heartbeat()
                        last_heartbeat = now
                    except Exception as e:
                        logger.debug(f"Heartbeat error: {e}")
                        break

            except WebSocketDisconnect:
                break

            except Exception as e:
                logger.debug(f"Price feed receive error: {e}")
                break

    except Exception as e:
        logger.error(f"Price feed connection error: {e}")
    finally:
        await manager.disconnect(websocket)
        logger.info("Price feed connection closed")
