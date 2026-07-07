"""
Pipeline WebSocket Manager
==========================
Dedicated connection registry for /ws/pipeline — real-time verdict push.

Broadcasts read-only events: verdict, analyst_signals, regime.
Order-related events NEVER appear here.
Failures in broadcast never propagate to the pipeline path.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Set

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class PipelineWebSocketManager:
    """
    Manages WebSocket connections subscribed to pipeline verdict events.

    Separate from the general WebSocketManager so broadcast failures
    in this read-only channel cannot affect order or safety paths.
    """

    def __init__(self) -> None:
        self.active_connections: Set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        """Accept a new pipeline WebSocket connection."""
        await ws.accept()
        async with self._lock:
            self.active_connections.add(ws)
        logger.info(
            "Pipeline WS client connected — total: %d",
            len(self.active_connections),
        )

    async def disconnect(self, ws: WebSocket) -> None:
        """Remove a client from the registry (on close or error)."""
        async with self._lock:
            self.active_connections.discard(ws)
        logger.info(
            "Pipeline WS client disconnected — total: %d",
            len(self.active_connections),
        )

    async def broadcast(self, event: dict) -> None:
        """
        Send event to all connected clients.

        Dead clients are removed silently; failures never raise.
        """
        if not self.active_connections:
            return

        async with self._lock:
            connections = list(self.active_connections)

        dead: Set[WebSocket] = set()
        for ws in connections:
            try:
                await ws.send_json(event)
            except Exception as exc:  # noqa: BLE001
                logger.debug("Pipeline WS send failed (client removed): %s", exc)
                dead.add(ws)

        if dead:
            async with self._lock:
                self.active_connections.difference_update(dead)

    def connection_count(self) -> int:
        """Return number of active pipeline subscribers."""
        return len(self.active_connections)


# Module-level singleton — imported by pipeline.py emit hooks and the router
manager = PipelineWebSocketManager()


# ── Convenience emit helpers (fire-and-forget safe) ──────────────────────────


def _ts() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


async def emit_verdict(symbol: str, verdict_dict: dict) -> None:
    """Broadcast a pipeline verdict (read-only — never order data)."""
    try:
        await manager.broadcast(
            {
                "type": "verdict",
                "symbol": symbol,
                "verdict": verdict_dict,
                "ts": _ts(),
            }
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("emit_verdict suppressed: %s", exc)


async def emit_analyst_signals(symbol: str, reports: dict) -> None:
    """Broadcast analyst-stage reports after gather completes."""
    try:
        await manager.broadcast(
            {
                "type": "analyst_signals",
                "symbol": symbol,
                "reports": reports,
                "ts": _ts(),
            }
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("emit_analyst_signals suppressed: %s", exc)
