"""
Pipeline WebSocket Router
=========================
Endpoint: GET /ws/pipeline?api_key=<key>

Delivers real-time pipeline events to read-only subscribers:
  - verdict       — final pipeline verdict per symbol
  - analyst_signals — all analyst reports after the gather stage
  - regime        — regime changes (future)
  - hello         — sent on connect
  - ping          — 30-second heartbeat

Auth: api_key query parameter (browsers cannot send custom headers on WS upgrade).
[ASSUMPTION] settings.API_KEY is always set in engine/.env — startup check enforces this.
"""

import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from config import settings
from websocket.pipeline_ws import manager as pipeline_manager

router = APIRouter(tags=["pipeline-ws"])
logger = logging.getLogger(__name__)

_HEARTBEAT_SECONDS = 30
_SUBSCRIBED_TOPICS = ["verdict", "analyst_signals", "regime"]


@router.websocket("/ws/pipeline")
async def pipeline_ws_endpoint(websocket: WebSocket, api_key: str = "") -> None:
    """
    Real-time pipeline verdict push endpoint.

    Clients connect with:  ws://host:8010/ws/pipeline?api_key=<value>

    Auth failure → close 1008 (policy violation).
    On connect → hello frame with subscribed_topics.
    Heartbeat → ping frame every 30 s.
    """
    engine_key: str = settings.API_KEY or ""

    if not engine_key or api_key != engine_key:
        logger.warning(
            "Pipeline WS rejected — bad api_key (client=%s...)",
            api_key[:8] if api_key else "<empty>",
        )
        await websocket.close(code=1008)
        return

    await pipeline_manager.connect(websocket)

    try:
        # Hello frame
        await websocket.send_json(
            {
                "type": "hello",
                "ts": datetime.now(tz=timezone.utc).isoformat(),
                "subscribed_topics": _SUBSCRIBED_TOPICS,
            }
        )

        # Keep-alive loop: receive ignores client messages; heartbeat fires on timeout
        while True:
            try:
                await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=_HEARTBEAT_SECONDS,
                )
                # Client messages are silently ignored — this is a server-push channel
            except asyncio.TimeoutError:
                # Send heartbeat ping
                try:
                    await websocket.send_json(
                        {
                            "type": "ping",
                            "ts": datetime.now(tz=timezone.utc).isoformat(),
                        }
                    )
                except Exception:  # noqa: BLE001
                    break
            except WebSocketDisconnect:
                break
            except Exception:  # noqa: BLE001
                break
    except Exception as exc:  # noqa: BLE001
        logger.debug("Pipeline WS connection error: %s", exc)
    finally:
        await pipeline_manager.disconnect(websocket)
