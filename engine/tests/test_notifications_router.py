"""
Tests for engine/routers/notifications_router.py

Covered:
  - POST /notifications/whatsapp/test
      * notifier not configured -> status "not_configured", sent False
      * notifier configured + send succeeds -> status "sent", sent True
      * notifier configured + send fails -> status "failed", sent False
  - POST /notifications/vix-alert-check
      * VIX below all thresholds -> sent False, no WhatsApp call made
      * VIX above EXTREME threshold -> alert sent, WhatsApp called with message
      * VIXOverlay raising -> 500 with the exception detail

Design:
  - Minimal FastAPI app wrapping only notifications_router (no auth middleware —
    this router has none of its own, matching production wiring in main.py).
  - The router does lazy `from notifications.whatsapp import ...` /
    `from analytics.vix_overlay import VIXOverlay` imports *inside* each
    endpoint function, so patching the source modules
    (notifications.whatsapp.*, analytics.vix_overlay.VIXOverlay) is
    effective per-call — no need to patch the router module's namespace.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

import routers.notifications_router as notifications_router  # noqa: E402

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def app_with_router():
    """FastAPI app mounting only the notifications router (no auth middleware)."""
    app = FastAPI()
    app.include_router(notifications_router.router)
    return app


@pytest.fixture
def client(app_with_router):
    return TestClient(app_with_router)


# ---------------------------------------------------------------------------
# POST /notifications/whatsapp/test
# ---------------------------------------------------------------------------


def test_whatsapp_test_not_configured(client):
    """notifier.enabled=False -> not_configured, no send attempted."""
    fake_notifier = MagicMock()
    fake_notifier.enabled = False
    fake_notifier.test = AsyncMock()

    with patch("notifications.whatsapp.get_notifier", return_value=fake_notifier):
        resp = client.post("/notifications/whatsapp/test")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "not_configured"
    assert data["sent"] is False
    assert "timestamp" in data
    fake_notifier.test.assert_not_called()


def test_whatsapp_test_configured_send_succeeds(client):
    """notifier.enabled=True and test() succeeds -> status sent, sent True."""
    fake_notifier = MagicMock()
    fake_notifier.enabled = True
    fake_notifier.test = AsyncMock(return_value=True)

    with patch("notifications.whatsapp.get_notifier", return_value=fake_notifier):
        resp = client.post("/notifications/whatsapp/test")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "sent"
    assert data["sent"] is True
    fake_notifier.test.assert_awaited_once()


def test_whatsapp_test_configured_send_fails(client):
    """notifier.enabled=True but test() returns False -> status failed, sent False."""
    fake_notifier = MagicMock()
    fake_notifier.enabled = True
    fake_notifier.test = AsyncMock(return_value=False)

    with patch("notifications.whatsapp.get_notifier", return_value=fake_notifier):
        resp = client.post("/notifications/whatsapp/test")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "failed"
    assert data["sent"] is False


# ---------------------------------------------------------------------------
# POST /notifications/vix-alert-check
# ---------------------------------------------------------------------------


def _fake_vix_state(value, regime="NORMAL", classification="NORMAL", source="stub"):
    state = MagicMock()
    state.vix_value = value
    state.regime = regime
    state.classification = classification
    state.source = source
    return state


def test_vix_alert_check_normal_no_alert(client):
    """VIX below all thresholds -> no alert, WhatsApp never called."""
    fake_overlay = MagicMock()
    fake_overlay.get_state.return_value = _fake_vix_state(15.0)

    with (
        patch("analytics.vix_overlay.VIXOverlay", return_value=fake_overlay),
        patch("notifications.whatsapp.send_whatsapp_message", new=AsyncMock()) as mock_send,
    ):
        resp = client.post("/notifications/vix-alert-check")

    assert resp.status_code == 200
    data = resp.json()
    assert data["sent"] is False
    assert data["vix"] == 15.0
    assert data["regime"] == "NORMAL"
    assert "no alert needed" in data["reason"].lower()
    mock_send.assert_not_called()


def test_vix_alert_check_extreme_sends_alert(client):
    """VIX >= 40 -> EXTREME alert, WhatsApp send invoked with a formatted message."""
    fake_overlay = MagicMock()
    fake_overlay.get_state.return_value = _fake_vix_state(
        45.2, regime="EXTREME", classification="EXTREME", source="live"
    )

    with (
        patch("analytics.vix_overlay.VIXOverlay", return_value=fake_overlay),
        patch("notifications.whatsapp.send_whatsapp_message", new=AsyncMock(return_value=True)) as mock_send,
    ):
        resp = client.post("/notifications/vix-alert-check")

    assert resp.status_code == 200
    data = resp.json()
    assert data["sent"] is True
    assert data["vix"] == 45.2
    assert data["alert_level"] == "EXTREME VIX"
    assert "halting" in data["guidance"].lower()
    mock_send.assert_awaited_once()
    sent_message = mock_send.await_args.args[0]
    assert "EXTREME VIX" in sent_message
    assert "45.2" in sent_message


def test_vix_alert_check_overlay_error_returns_500(client):
    """VIXOverlay() raising is surfaced as a 500, not swallowed."""
    with patch("analytics.vix_overlay.VIXOverlay", side_effect=RuntimeError("data feed down")):
        resp = client.post("/notifications/vix-alert-check")

    assert resp.status_code == 500
    assert "data feed down" in resp.json()["detail"]
