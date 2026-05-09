"""pending_approval_notify fan-out (WebSocket + WhatsApp + optional Discord)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.mark.asyncio
async def test_notify_calls_emit_and_whatsapp():
    captured: dict = {}

    async def fake_emit(approval_id, symbol, final_action, *, quantity=None, entry_price=None):
        captured["approval_id"] = approval_id
        captured["symbol"] = symbol
        captured["final_action"] = final_action
        captured["quantity"] = quantity
        captured["entry_price"] = entry_price

    mock_tg_off = MagicMock()
    mock_tg_off.enabled = False

    with (
        patch("websocket.events.emit_pending_approval_created", new=fake_emit),
        patch(
            "notifications.whatsapp.send_whatsapp_message",
            new=AsyncMock(return_value=True),
        ) as mock_wa,
        patch("notifications.telegram.get_notifier", return_value=mock_tg_off),
    ):
        from notifications.pending_approval_notify import notify_pending_approval_queued

        await notify_pending_approval_queued(
            approval_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            symbol="mcl",
            action="buy",
            quantity=2.0,
            entry_price=71.25,
        )

    assert captured.get("approval_id") == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    assert captured.get("symbol") == "mcl"
    assert captured.get("final_action") == "buy"
    assert captured.get("quantity") == 2.0
    assert captured.get("entry_price") == 71.25

    mock_wa.assert_awaited_once()
    ca = mock_wa.call_args
    body = ca.args[0] if ca.args else ca.kwargs.get("message", "")
    assert ca.kwargs.get("alert_type") == "pending_approval"
    assert ca.kwargs.get("symbol") == "MCL"
    assert "MCL" in body
    assert "BUY" in body
    assert "Reply Y to approve" in body


@pytest.mark.asyncio
async def test_notify_telegram_when_enabled():
    mock_tg = MagicMock()
    mock_tg.enabled = True
    mock_tg.send = AsyncMock(return_value=True)

    with (
        patch("websocket.events.emit_pending_approval_created", new=AsyncMock()),
        patch(
            "notifications.whatsapp.send_whatsapp_message",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "notifications.telegram.get_notifier",
            return_value=mock_tg,
        ),
    ):
        from notifications.pending_approval_notify import notify_pending_approval_queued

        await notify_pending_approval_queued(
            approval_id="bbbbbbbb-cccc-dddd-eeee-ffffffffffff",
            symbol="ES",
            action="buy",
            quantity=1.0,
            entry_price=5000.0,
        )

    mock_tg.send.assert_awaited_once()
    text = mock_tg.send.call_args.args[0]
    assert "APPROVAL REQUIRED" in text
    assert "ES" in text
    assert "BUY" in text
    assert "pending-approvals" in text.lower() or "Pending Approvals" in text


@pytest.mark.asyncio
async def test_notify_discord_webhook_when_env_set(monkeypatch):
    monkeypatch.setenv(
        "JARVIS_DISCORD_APPROVAL_WEBHOOK",
        "https://discord.example/webhook",
    )

    mock_response = MagicMock()
    mock_response.status_code = 204

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(return_value=mock_response)

    mock_tg_off = MagicMock()
    mock_tg_off.enabled = False

    with (
        patch("websocket.events.emit_pending_approval_created", new=AsyncMock()),
        patch(
            "notifications.whatsapp.send_whatsapp_message",
            new=AsyncMock(return_value=False),
        ),
        patch("notifications.telegram.get_notifier", return_value=mock_tg_off),
        patch("httpx.AsyncClient", return_value=mock_client),
    ):
        from notifications.pending_approval_notify import notify_pending_approval_queued

        await notify_pending_approval_queued(
            approval_id="id-1",
            symbol="MNQ",
            action="sell",
            quantity=1.0,
            entry_price=None,
        )

    mock_client.post.assert_awaited_once()
    args, kwargs = mock_client.post.call_args
    assert args[0] == "https://discord.example/webhook"
    assert "MNQ" in kwargs["json"]["content"]
    assert "SELL" in kwargs["json"]["content"]
