"""
WebSocket Manager
=================
Tracks connected clients and broadcasts real-time events.
"""

import asyncio
import logging
from collections import deque
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
    - Recent event buffer for REST polling fallback
    """

    def __init__(self):
        self.active_connections: Set[WebSocket] = set()
        self._lock = asyncio.Lock()
        self._event_buffer: deque = deque(maxlen=50)
        self._buffer_lock = asyncio.Lock()

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
        Broadcast an event to all connected clients and store in buffer.

        Event structure:
        {
            "type": "order_fill" | "kill_switch" | "circuit_breaker" | "pipeline_complete" | "safety_event" | "price_update" | "pending_approval_created",
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

        async with self._buffer_lock:
            self._event_buffer.append(event)

        if not self.active_connections:
            return

        async with self._lock:
            connections_copy = list(self.active_connections)

        disconnected = set()

        for websocket in connections_copy:
            try:
                await websocket.send_json(event)
            except Exception as e:
                logger.warning(f"Failed to send WebSocket event: {e}")
                disconnected.add(websocket)

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

    async def get_recent_events(self, limit: int = 20) -> list[dict]:
        """Get recent WS events from buffer, newest first.
        
        Args:
            limit: Maximum number of events to return
            
        Returns:
            List of event dicts in reverse chronological order
        """
        async with self._buffer_lock:
            events = list(self._event_buffer)
        return list(reversed(events))[:limit]
