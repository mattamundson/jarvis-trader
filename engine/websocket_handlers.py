"""
JARVIS TRADER WebSocket Handlers
=================================
Real-time WebSocket endpoints for price feeds and trading events.
"""

from fastapi import WebSocket

from websocket.manager import WebSocketManager


async def setup_websocket_endpoints(app, ws_manager: WebSocketManager) -> None:
    """Register WebSocket endpoints on the FastAPI app."""

    from websocket.events_endpoint import events_endpoint
    from websocket.price_feed import price_feed_endpoint

    # Price feed endpoint
    app.websocket("/ws/prices")(price_feed_endpoint)

    # Events endpoint (trading events)
    async def events_handler(websocket: WebSocket):
        """Route WebSocket /ws/events to events_endpoint with ws_manager."""
        await events_endpoint(websocket, ws_manager)

    app.websocket("/ws/events")(events_handler)
