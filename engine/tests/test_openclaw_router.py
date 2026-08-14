"""Unit tests for routers/openclaw_router.py.

This router is the WhatsApp<->GMS trade-approval relay: inbound OpenClaw
webhook messages ("yes"/"no"/"hold") drive real paper-trade approve/reject
decisions. Tests mock the router's declared external dependencies —
the approval-service functions (get_latest_pending_approval_row,
approve_pending_trade, reject_pending_trade) and the outbound WhatsApp
reply sender — while exercising the router's own logic: command parsing,
sender authorization, and ApprovalFlowError -> HTTP response translation.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routers.openclaw_router as openclaw_router
from approval.service import ApprovalFlowError
from routers.openclaw_router import inject_dependencies
from routers.openclaw_router import router as openclaw_api_router


@pytest.fixture
def app_with_router():
    app = FastAPI()
    app.include_router(openclaw_api_router)
    return app


@pytest.fixture
def client(app_with_router):
    return TestClient(app_with_router)


@pytest.fixture(autouse=True)
def _wired():
    """Inject MagicMock dependencies and restore module globals after each test."""
    prior_db = openclaw_router._db_manager
    prior_pt = openclaw_router._paper_tracker
    prior_sl = openclaw_router._safety_layer
    inject_dependencies(MagicMock(), MagicMock(), MagicMock())
    yield
    openclaw_router._db_manager = prior_db
    openclaw_router._paper_tracker = prior_pt
    openclaw_router._safety_layer = prior_sl


@pytest.fixture(autouse=True)
def _clear_openclaw_whatsapp_to(monkeypatch):
    """Ensure sender-restriction is off by default; individual tests opt in."""
    monkeypatch.delenv("OPENCLAW_WHATSAPP_TO", raising=False)


def _post_webhook(client, message: str, from_number: str = "+15551234567"):
    return client.post(
        "/openclaw/webhook",
        json={"message": message, "from_number": from_number},
    )


# ─────────────────────────────────────────────────────────────────────────────
# Approve ("yes"/"approve"/"y")
# ─────────────────────────────────────────────────────────────────────────────
def test_webhook_approve_success(client):
    row = {"approval_id": "abc-123"}
    approve_result = {
        "status": "approved",
        "approval_id": "abc-123",
        "paper_trade_id": "pt-1",
        "symbol": "MES",
        "action": "buy",
        "quantity": 1,
        "entry_price": 5800.0,
        "execution": {"approved": True},
    }
    with (
        patch.object(openclaw_router, "get_latest_pending_approval_row", return_value=row),
        patch.object(
            openclaw_router, "approve_pending_trade", new=AsyncMock(return_value=approve_result)
        ),
        patch.object(openclaw_router, "_send_reply") as mock_reply,
    ):
        resp = _post_webhook(client, "yes")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "approved"
    assert data["paper_trade_id"] == "pt-1"
    assert data["message"] == "JARVIS: Approved — MES BUY @ $5800.00 opened"
    mock_reply.assert_called_once_with("JARVIS: Approved — MES BUY @ $5800.00 opened")


def test_webhook_approve_no_pending_trades(client):
    """No pending approvals — informational, non-error response (idempotent)."""
    with (
        patch.object(
            openclaw_router,
            "get_latest_pending_approval_row",
            side_effect=ApprovalFlowError(404, "No pending approvals"),
        ),
        patch.object(openclaw_router, "_send_reply") as mock_reply,
    ):
        resp = _post_webhook(client, "approve")

    assert resp.status_code == 200
    data = resp.json()
    assert data == {"status": "no_pending", "message": "JARVIS: No pending trades to approve"}
    mock_reply.assert_called_once()


def test_webhook_approve_service_failure_maps_to_http_error(client):
    """Kill-switch-blocked (or any other) ApprovalFlowError surfaces as the matching HTTP status."""
    row = {"approval_id": "abc-123"}
    with (
        patch.object(openclaw_router, "get_latest_pending_approval_row", return_value=row),
        patch.object(
            openclaw_router,
            "approve_pending_trade",
            new=AsyncMock(
                side_effect=ApprovalFlowError(409, "Kill switch active — cannot approve")
            ),
        ),
        patch.object(openclaw_router, "_send_reply") as mock_reply,
    ):
        resp = _post_webhook(client, "y")

    assert resp.status_code == 409
    assert "Kill switch active" in resp.json()["detail"]
    mock_reply.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────────
# Reject ("no"/"reject"/"n")
# ─────────────────────────────────────────────────────────────────────────────
def test_webhook_reject_success(client):
    row = {"approval_id": "abc-123", "symbol": "mcl"}
    reject_result = {
        "status": "rejected",
        "approval_id": "abc-123",
        "symbol": "mcl",
        "reason": "rejected_via_whatsapp",
    }
    with (
        patch.object(openclaw_router, "get_latest_pending_approval_row", return_value=row),
        patch.object(openclaw_router, "reject_pending_trade", return_value=reject_result),
        patch.object(openclaw_router, "_send_reply") as mock_reply,
    ):
        resp = _post_webhook(client, "no")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "rejected"
    assert data["message"] == "JARVIS: MCL trade rejected"
    mock_reply.assert_called_once_with("JARVIS: MCL trade rejected")


def test_webhook_reject_no_pending_trades(client):
    with (
        patch.object(
            openclaw_router,
            "get_latest_pending_approval_row",
            side_effect=ApprovalFlowError(404, "No pending approvals"),
        ),
        patch.object(openclaw_router, "_send_reply") as mock_reply,
    ):
        resp = _post_webhook(client, "reject")

    assert resp.status_code == 200
    assert resp.json() == {"status": "no_pending", "message": "JARVIS: No pending trades to reject"}
    mock_reply.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────────
# Hold / unknown commands — no service calls
# ─────────────────────────────────────────────────────────────────────────────
def test_webhook_hold_command_takes_no_action(client):
    with (
        patch.object(openclaw_router, "get_latest_pending_approval_row") as mock_get,
        patch.object(openclaw_router, "approve_pending_trade") as mock_approve,
        patch.object(openclaw_router, "reject_pending_trade") as mock_reject,
    ):
        resp = _post_webhook(client, "hold")

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "message": "JARVIS: Trade held — no action taken"}
    mock_get.assert_not_called()
    mock_approve.assert_not_called()
    mock_reject.assert_not_called()


def test_webhook_unknown_command(client):
    resp = _post_webhook(client, "banana")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "unknown_command"
    assert "banana" in data["message"]


def test_webhook_malformed_body_falls_through_to_unknown_command(client):
    """Non-JSON body must not 500 — request.json() failure degrades to empty dict."""
    resp = client.post(
        "/openclaw/webhook",
        content=b"not-json{{{",
        headers={"content-type": "text/plain"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "unknown_command"


# ─────────────────────────────────────────────────────────────────────────────
# Sender authorization — the security-critical gate for this relay
# ─────────────────────────────────────────────────────────────────────────────
def test_webhook_unauthorized_sender_rejected_before_touching_approvals(client, monkeypatch):
    monkeypatch.setenv("OPENCLAW_WHATSAPP_TO", "+15551234567")
    with (
        patch.object(openclaw_router, "get_latest_pending_approval_row") as mock_get,
        patch.object(openclaw_router, "approve_pending_trade") as mock_approve,
    ):
        resp = _post_webhook(client, "yes", from_number="+19998887777")

    assert resp.status_code == 200
    assert resp.json() == {"status": "unauthorized", "message": "Sender not authorized"}
    mock_get.assert_not_called()
    mock_approve.assert_not_called()


def test_webhook_authorized_sender_allowed_through(client, monkeypatch):
    monkeypatch.setenv("OPENCLAW_WHATSAPP_TO", "+15551234567")
    with (
        patch.object(
            openclaw_router,
            "get_latest_pending_approval_row",
            side_effect=ApprovalFlowError(404, "No pending approvals"),
        ),
        patch.object(openclaw_router, "_send_reply"),
    ):
        resp = _post_webhook(client, "yes", from_number="+15551234567")

    assert resp.status_code == 200
    assert resp.json()["status"] == "no_pending"
