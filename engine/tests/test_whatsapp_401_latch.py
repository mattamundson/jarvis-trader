"""US-010: a Twilio 401 must disable the WhatsApp channel for the process
lifetime (one loud error, no per-alert retry flood) and leave valid-cred
behavior unchanged."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from notifications.whatsapp import WhatsAppNotifier


def _notifier() -> WhatsAppNotifier:
    n = WhatsAppNotifier.__new__(WhatsAppNotifier)
    n.account_sid = "ACtest"
    n.auth_token = "tok"
    n.from_number = "whatsapp:+10000000000"
    n.to_number = "whatsapp:+10000000001"
    n.enabled = True
    return n


def _client_returning(status_code: int, payload: dict | None = None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = "auth error"
    resp.json.return_value = payload or {}
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.post = AsyncMock(return_value=resp)
    return client


class TestTwilio401Latch:
    def test_401_latches_channel_off(self):
        n = _notifier()
        with patch("notifications.whatsapp.httpx.AsyncClient", return_value=_client_returning(401)):
            assert asyncio.run(n.send("x")) is False
        assert n.enabled is False
        # Second send short-circuits — no HTTP call at all.
        with patch("notifications.whatsapp.httpx.AsyncClient") as cl:
            assert asyncio.run(n.send("y")) is False
            cl.assert_not_called()

    def test_success_path_unchanged(self):
        n = _notifier()
        with patch(
            "notifications.whatsapp.httpx.AsyncClient",
            return_value=_client_returning(201, {"sid": "SM123"}),
        ):
            assert asyncio.run(n.send("x")) is True
        assert n.enabled is True

    def test_non_auth_error_does_not_latch(self):
        n = _notifier()
        with patch("notifications.whatsapp.httpx.AsyncClient", return_value=_client_returning(500)):
            assert asyncio.run(n.send("x")) is False
        assert n.enabled is True  # transient server error — keep trying later
