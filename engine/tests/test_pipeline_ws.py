"""
Pipeline WebSocket Tests
========================
Tests for /ws/pipeline real-time verdict push endpoint.

Covers:
- Auth rejection (no api_key)
- Auth success + hello frame
- Broadcast reaches all connected clients
- Dead client does not break broadcast to live clients
- Pipeline verdict triggers broadcast (via emit_verdict)
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_settings():
    """Patch settings.API_KEY with a known test value."""
    with patch("routers.pipeline_ws_router.settings") as m:
        m.API_KEY = "test-secret-key"
        yield m


@pytest.fixture
def app(mock_settings):
    """Minimal FastAPI app with only the pipeline WS router."""
    from routers.pipeline_ws_router import router

    _app = FastAPI()
    _app.include_router(router)
    return _app


@pytest.fixture
def client(app):
    return TestClient(app)


# ── Tests ──────────────────────────────────────────────────────────────────────


def test_connection_requires_api_key(client):
    """Connecting without api_key must be rejected (close 1008)."""
    with pytest.raises(Exception):  # noqa: B017 (any error = connection correctly rejected)
        # TestClient raises when the server closes the connection immediately
        with client.websocket_connect("/ws/pipeline") as ws:
            ws.receive_json()


def test_connection_with_wrong_api_key_rejected(client):
    """Wrong api_key must be rejected."""
    with pytest.raises(Exception):  # noqa: B017 (any error = connection correctly rejected)
        with client.websocket_connect("/ws/pipeline?api_key=wrong-key") as ws:
            ws.receive_json()


def test_connection_with_valid_api_key_succeeds(client):
    """Valid api_key → connection accepted → hello frame received."""
    with client.websocket_connect("/ws/pipeline?api_key=test-secret-key") as ws:
        msg = ws.receive_json()
    assert msg["type"] == "hello"
    assert "ts" in msg
    assert "verdict" in msg["subscribed_topics"]
    assert "analyst_signals" in msg["subscribed_topics"]


def test_broadcast_reaches_all_clients():
    """Two clients connected to PipelineWebSocketManager both receive broadcast."""

    async def _run():
        from websocket.pipeline_ws import PipelineWebSocketManager

        mgr = PipelineWebSocketManager()

        # Create two mock WebSocket objects
        ws1 = AsyncMock()
        ws2 = AsyncMock()

        # Simulate accept without actually accepting
        await mgr.connect(ws1)
        await mgr.connect(ws2)

        assert mgr.connection_count() == 2

        payload = {"type": "verdict", "symbol": "MES", "verdict": {}, "ts": "2026-01-01T00:00:00Z"}
        await mgr.broadcast(payload)

        ws1.send_json.assert_awaited_once_with(payload)
        ws2.send_json.assert_awaited_once_with(payload)

    asyncio.run(_run())


def test_dead_client_cleanup():
    """A failed send removes the dead client; live clients still receive."""

    async def _run():
        from websocket.pipeline_ws import PipelineWebSocketManager

        mgr = PipelineWebSocketManager()

        ws_live = AsyncMock()
        ws_dead = AsyncMock()
        ws_dead.send_json.side_effect = RuntimeError("connection closed")

        await mgr.connect(ws_live)
        await mgr.connect(ws_dead)
        assert mgr.connection_count() == 2

        payload = {"type": "ping", "ts": "now"}
        await mgr.broadcast(payload)

        # Dead client removed, live client got the message
        assert mgr.connection_count() == 1
        ws_live.send_json.assert_awaited_once_with(payload)

    asyncio.run(_run())


def test_pipeline_verdict_triggers_broadcast():
    """emit_verdict calls manager.broadcast with the right shape."""

    async def _run():
        from websocket import pipeline_ws

        broadcast_calls = []

        original_broadcast = pipeline_ws.manager.broadcast

        async def mock_broadcast(event):
            broadcast_calls.append(event)

        pipeline_ws.manager.broadcast = mock_broadcast

        try:
            await pipeline_ws.emit_verdict(
                symbol="MCL",
                verdict_dict={
                    "final_action": "buy",
                    "confidence": 0.82,
                    "regime": "TRENDING_BULL",
                },
            )
        finally:
            pipeline_ws.manager.broadcast = original_broadcast

        assert len(broadcast_calls) == 1
        evt = broadcast_calls[0]
        assert evt["type"] == "verdict"
        assert evt["symbol"] == "MCL"
        assert evt["verdict"]["final_action"] == "buy"
        assert "ts" in evt

    asyncio.run(_run())


def test_emit_analyst_signals_shape():
    """emit_analyst_signals broadcasts the correct structure."""

    async def _run():
        from websocket import pipeline_ws

        captured = []

        async def mock_broadcast(event):
            captured.append(event)

        pipeline_ws.manager.broadcast = mock_broadcast

        try:
            await pipeline_ws.emit_analyst_signals(
                symbol="MNQ",
                reports={"technical": {"signal": 0.7}, "news": {"signal": 0.5}},
            )
        finally:
            # Re-import to get a fresh singleton reference
            import importlib

            importlib.reload(pipeline_ws)

        assert len(captured) == 1
        evt = captured[0]
        assert evt["type"] == "analyst_signals"
        assert evt["symbol"] == "MNQ"
        assert "reports" in evt
        assert "ts" in evt

    asyncio.run(_run())
