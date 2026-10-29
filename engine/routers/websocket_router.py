"""
WebSocket endpoints
"""

import asyncio
import logging
from datetime import datetime

from fastapi import APIRouter, WebSocket

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["websocket"])

# Global references (injected from main.py)
ws_manager = None


def inject_dependencies(wsm):
    """Inject dependencies from main.py"""
    global ws_manager
    ws_manager = wsm


# ── WebSocket Real-Time Events ────────────────────────────────────────────


@router.websocket("/ws/events")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for real-time trading events.

    Accepts connections at /ws/events.
    Sends JSON events for:
      - order_fill: Order execution
      - kill_switch: Kill switch state changes
      - circuit_breaker: Circuit breaker triggers
      - pipeline_complete: Pipeline analysis completion
      - safety_event: Safety/risk events
      - price_update: Price updates
      - ping: Keep-alive ping

    Connection is kept alive with ping frames every 30 seconds.
    Client is automatically removed on disconnect or send failure.
    """
    if not ws_manager:
        await websocket.close(code=1011, reason="WebSocket manager not initialized")
        return

    await ws_manager.connect(websocket)

    try:
        # Keep the connection alive and listen for client frames
        ping_interval = 30  # seconds
        last_ping = datetime.now()

        while True:
            try:
                # Receive with timeout to allow periodic ping
                data = await asyncio.wait_for(websocket.receive_json(), timeout=ping_interval)
                logger.debug(f"WebSocket received: {data.get('type', 'unknown')}")

            except asyncio.TimeoutError:
                # Send ping to keep connection alive
                now = datetime.now()
                if (now - last_ping).total_seconds() >= ping_interval:
                    try:
                        await websocket.send_json({"type": "ping", "timestamp": now.isoformat()})
                        last_ping = now
                    except Exception as e:
                        logger.debug(f"Ping failed: {e}")
                        break

            except Exception as e:
                logger.debug(f"WebSocket receive error: {e}")
                break

    except Exception as e:
        logger.error(f"WebSocket connection error: {e}")
    finally:
        await ws_manager.disconnect(websocket)
        logger.info("WebSocket connection closed")


# ── WebSocket Status Endpoint ─────────────────────────────────────────────


@router.get("/ws/status")
async def websocket_status():
    """Get WebSocket manager status — connected client count."""
    if not ws_manager:
        return {"status": "not_initialized", "connections": 0}
    return {"status": "ok", "connections": ws_manager.get_connection_count()}


@router.get("/ws/events/recent")
async def get_recent_ws_events(limit: int = 20):
    """Get recent WebSocket events from buffer (for polling fallback).
    
    Returns the same event structure as the WebSocket stream, newest first.
    Used by dashboard when WebSocket connection unavailable (e.g., Vercel).
    
    Args:
        limit: Maximum events to return (default 20, max 50)
        
    Returns:
        events: List of event dicts with type, data, timestamp
        count: Number of events returned
    """
    if not ws_manager:
        return {"events": [], "count": 0}
    
    limit = min(max(1, limit), 50)
    events = await ws_manager.get_recent_events(limit)
    return {"events": events, "count": len(events)}


# ── Performance Report Endpoint ───────────────────────────────────────────────
