"""
WebSocket Manager
=================
Tracks connected clients and broadcasts real-time events.
"""

import asyncio
import logging
from datetime import datetime
from typing import Set

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class WebSocketManager:
    """
    Manages WebSocket connections and broadcasts events to all connected clients.

    Handles:
    - Connection tracking (add/remove clients)
    - Graceful disconnection handling (remove on send failure)
    - JSON event broadcasting with timestamp
    - Ping/pong keep-alive
    """

    def __init__(self):
        self.active_connections: Set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket):
        """Accept a new WebSocket connection and add to active connections."""
        await websocket.accept()
        async with self._lock:
            self.active_connections.add(websocket)
        logger.info(
            f"WebSocket client connected. Total connections: {len(self.active_connections)}"
        )

    async def disconnect(self, websocket: WebSocket):
        """Remove a disconnected client from active connections."""
        async with self._lock:
            self.active_connections.discard(websocket)
        logger.info(
            f"WebSocket client disconnected. Total connections: {len(self.active_connections)}"
        )

    async def broadcast(self, event_type: str, data: dict):
        """
        Broadcast an event to all connected clients.

        Event structure:
        {
            "type": "order_fill" | "kill_switch" | "circuit_breaker" | "pipeline_complete" | "safety_event" | "price_update",
            "data": {...},
            "timestamp": "ISO8601"
        }

        Removes clients that fail to receive (disconnected).
        """
        event = {
            "type": event_type,
            "data": data,
            "timestamp": datetime.now().isoformat(),
        }

        if not self.active_connections:
            return  # No clients connected

        # Make a copy of connections in case set changes during iteration
        async with self._lock:
            connections_copy = list(self.active_connections)

        disconnected = set()

        for websocket in connections_copy:
            try:
                await websocket.send_json(event)
            except Exception as e:
                logger.warning(f"Failed to send WebSocket event: {e}")
                # Mark for removal (client likely disconnected)
                disconnected.add(websocket)

        # Remove failed connections
        if disconnected:
            async with self._lock:
                self.active_connections.difference_update(disconnected)

    async def ping(self):
        """Send a ping frame to all connected clients (keep-alive)."""
        async with self._lock:
            connections_copy = list(self.active_connections)

        disconnected = set()

        for websocket in connections_copy:
            try:
                await websocket.send_json({"type": "ping"})
            except Exception as e:
                logger.debug(f"Ping failed: {e}")
                disconnected.add(websocket)

        # Remove failed connections
        if disconnected:
            async with self._lock:
                self.active_connections.difference_update(disconnected)

    def get_connection_count(self) -> int:
        """Get the current number of active connections."""
        return len(self.active_connections)
