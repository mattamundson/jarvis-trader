"""
WebSocket Events Endpoint
==========================
Real-time trading events: kill_switch, circuit_breaker, order_fill,
pipeline_complete, safety_event.
Uses the global WebSocketManager for broadcasting.
"""

import asyncio
import logging
from datetime import datetime

from fastapi import WebSocket, WebSocketDisconnect

from .manager import WebSocketManager

logger = logging.getLogger(__name__)


async def events_endpoint(websocket: WebSocket, ws_manager: WebSocketManager):
    """
    WebSocket endpoint for real-time trading events.

    Accepts connections at /ws/events.
    Broadcasts: kill_switch, circuit_breaker, order_fill, pipeline_complete,
    safety_event.
    Heartbeat ping every 30 seconds.

    Args:
        websocket: FastAPI WebSocket connection
        ws_manager: Global WebSocketManager instance
    """
    if not ws_manager:
        await websocket.close(code=1011, reason="WebSocket manager not initialized")
        return

    await ws_manager.connect(websocket)

    try:
        heartbeat_interval = 30  # seconds
        last_heartbeat = datetime.now()

        while True:
            try:
                # Receive with timeout to allow periodic heartbeat
                # Client sends keep-alive or subscribes to specific events
                await asyncio.wait_for(websocket.receive_json(), timeout=heartbeat_interval)
                # Events are already broadcast via manager.broadcast()
                # Client messages here are optional (for future filtering)

            except asyncio.TimeoutError:
                # Send heartbeat ping
                now = datetime.now()
                if (now - last_heartbeat).total_seconds() >= heartbeat_interval:
                    try:
                        await ws_manager.ping()
                        last_heartbeat = now
                    except Exception as e:
                        logger.debug(f"Heartbeat error: {e}")
                        break

            except WebSocketDisconnect:
                break

            except Exception as e:
                logger.debug(f"Events endpoint receive error: {e}")
                break

    except Exception as e:
        logger.error(f"Events endpoint connection error: {e}")
    finally:
        await ws_manager.disconnect(websocket)
        logger.info("Events endpoint connection closed")
