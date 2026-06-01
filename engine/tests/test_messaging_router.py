"""
WhatsApp inbound command coverage for messaging_router.

Covers the four read-only / state-mutating commands shipped in commit 269c8d1:
  - STATUS
  - PNL
  - POSITIONS
  - CONFIRM CLEAR  (remote kill-switch deactivation — Matt-only)

Origin gate, malformed payload, and the safety-layer-unavailable branch are
also exercised. CONFIRM CLEAR is treated as the most-load-bearing path because
it is the only WhatsApp command that mutates safety-layer state (calls
SafetyLayer.deactivate_kill_switch).
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

import routers.messaging_router as messaging_router  # noqa: E402

# ─────────────────────────────────────────────────────────────────────────────
# Sender constants (conftest sets WHATSAPP_TO=+0987654321)
# ─────────────────────────────────────────────────────────────────────────────
ADMIN_SENDER = "+0987654321"
NON_ADMIN_SENDER = "+9999999999"


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def app_with_router():
    """FastAPI app mounting only the messaging router (no auth middleware)."""
    app = FastAPI()
    app.include_router(messaging_router.router)
    return app


@pytest.fixture
def client(app_with_router):
    return TestClient(app_with_router)


@pytest.fixture
def mock_safety_layer():
    """SafetyLayer mock with get_status() and a settable is_killed property."""
    sl = MagicMock()
    sl.get_status.return_value = {
        "is_killed": False,
        "kill_switch_reason": None,
        "daily_realized_pnl": 0.0,
        "equity_peak": 10_000.0,
        "current_equity": 10_000.0,
        "recent_order_count": 0,
    }
    # is_killed is a @property on the real class — emulate with PropertyMock.
    type(sl).is_killed = PropertyMock(return_value=False)
    sl.deactivate_kill_switch = MagicMock(return_value=None)
    sl.activate_kill_switch = MagicMock(return_value=None)
    return sl


@pytest.fixture
def mock_paper_tracker():
    pt = MagicMock()
    pt.get_open_positions.return_value = []
    return pt


@pytest.fixture
def wired(mock_safety_layer, mock_paper_tracker):
    """Inject mocks into the module globals; restore after each test."""
    prior_safety = messaging_router._safety_layer
    prior_paper = messaging_router._paper_tracker
    prior_db = messaging_router._db_manager
    messaging_router._safety_layer = mock_safety_layer
    messaging_router._paper_tracker = mock_paper_tracker
    messaging_router._db_manager = MagicMock()  # truthy stand-in (not exercised here)
    yield {"safety_layer": mock_safety_layer, "paper_tracker": mock_paper_tracker}
    messaging_router._safety_layer = prior_safety
    messaging_router._paper_tracker = prior_paper
    messaging_router._db_manager = prior_db


def _post_whatsapp(client, body: str, sender: str = ADMIN_SENDER):
    """Helper: POST the webhook with the JSON shape the route accepts."""
    return client.post(
        "/messaging/inbound/whatsapp",
        json={"Body": body, "From": sender},
    )


# ─────────────────────────────────────────────────────────────────────────────
# STATUS command
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_status_no_open_positions(client, wired):
    wired["paper_tracker"].get_open_positions.return_value = []
    sent: list[str] = []

    async def fake_reply(recipient, message):
        sent.append(message)
        return True

    with patch.object(messaging_router, "_send_whatsapp_reply", side_effect=fake_reply):
        resp = _post_whatsapp(client, "STATUS")

    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "action": "status"}
    assert len(sent) == 1
    body = sent[0]
    assert "JARVIS STATUS" in body
    assert "Open positions: 0" in body
    assert "Kill: armed" in body
    assert "Today realized: $+0.00" in body


@pytest.mark.asyncio
async def test_status_with_open_positions(client, wired):
    wired["paper_tracker"].get_open_positions.return_value = [
        {"symbol": "MES", "action": "BUY", "quantity": 1, "entry_price": 5800.0},
        {"symbol": "MNQ", "action": "SELL", "quantity": 2, "entry_price": 20100.0},
    ]
    wired["safety_layer"].get_status.return_value = {
        "is_killed": False,
        "kill_switch_reason": None,
        "daily_realized_pnl": 125.50,
        "equity_peak": 10_000.0,
        "current_equity": 10_125.0,
        "recent_order_count": 3,
    }
    sent: list[str] = []

    async def fake_reply(recipient, message):
        sent.append(message)
        return True

    with patch.object(messaging_router, "_send_whatsapp_reply", side_effect=fake_reply):
        resp = _post_whatsapp(client, "STATUS")

    assert resp.status_code == 200
    body = sent[0]
    assert "Open positions: 2" in body
    assert "Today realized: $+125.50" in body
    assert "Mode: PAPER" in body  # LIVE_TRADING_ENABLED defaults to False


# ─────────────────────────────────────────────────────────────────────────────
# PNL command
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_pnl_aggregates_realized_and_unrealized(client, wired):
    wired["safety_layer"].get_status.return_value = {
        "is_killed": False,
        "kill_switch_reason": None,
        "daily_realized_pnl": 80.0,
        "equity_peak": 10_000.0,
        "current_equity": 10_080.0,
        "recent_order_count": 0,
    }
    wired["paper_tracker"].get_open_positions.return_value = [
        {"symbol": "MES", "unrealized_pnl": 25.0},
        {"symbol": "MNQ", "unrealized_pnl": -10.0},
    ]
    sent: list[str] = []

    async def fake_reply(recipient, message):
        sent.append(message)
        return True

    with patch.object(messaging_router, "_send_whatsapp_reply", side_effect=fake_reply):
        resp = _post_whatsapp(client, "PNL")

    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "action": "pnl"}
    body = sent[0]
    assert "JARVIS P&L (today)" in body
    assert "Realized:" in body and "$+80.00" in body
    assert "Unrealized:" in body and "$+15.00" in body  # 25 + (-10)
    assert "(2 open)" in body
    assert "Total:" in body and "$+95.00" in body


# ─────────────────────────────────────────────────────────────────────────────
# POSITIONS command
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_positions_empty_returns_no_positions_message(client, wired):
    wired["paper_tracker"].get_open_positions.return_value = []
    sent: list[str] = []

    async def fake_reply(recipient, message):
        sent.append(message)
        return True

    with patch.object(messaging_router, "_send_whatsapp_reply", side_effect=fake_reply):
        resp = _post_whatsapp(client, "POSITIONS")

    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "action": "positions"}
    assert sent[0] == "JARVIS: no open positions"


@pytest.mark.asyncio
async def test_positions_formats_list_with_sym_qty_entry(client, wired):
    wired["paper_tracker"].get_open_positions.return_value = [
        {
            "symbol": "mes",
            "action": "buy",
            "quantity": 1,
            "entry_price": 5800.25,
            "unrealized_pnl": 12.5,
        },
        {
            "symbol": "mnq",
            "side": "sell",
            "qty": 2,
            "entry_price": 20100.0,
            # no unrealized_pnl — should be omitted from line
        },
    ]
    sent: list[str] = []

    async def fake_reply(recipient, message):
        sent.append(message)
        return True

    with patch.object(messaging_router, "_send_whatsapp_reply", side_effect=fake_reply):
        resp = _post_whatsapp(client, "POSITIONS")

    body = sent[0]
    assert "JARVIS POSITIONS" in body
    # Symbols upper-cased
    assert "MES BUY x1 @ $5800.25" in body
    assert "MNQ SELL x2 @ $20100.00" in body
    # First line had a P&L number
    assert "$+12.50" in body


# ─────────────────────────────────────────────────────────────────────────────
# CONFIRM CLEAR command — kill-switch deactivation path
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_confirm_clear_noop_when_not_killed(client, wired):
    type(wired["safety_layer"]).is_killed = PropertyMock(return_value=False)
    sent: list[str] = []

    async def fake_reply(recipient, message):
        sent.append(message)
        return True

    with patch.object(messaging_router, "_send_whatsapp_reply", side_effect=fake_reply):
        resp = _post_whatsapp(client, "CONFIRM CLEAR")

    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "action": "kill_switch_cleared_noop"}
    assert sent[0] == "JARVIS: kill switch is not active — nothing to clear"
    # Critical: deactivate must NOT be called when nothing is active.
    wired["safety_layer"].deactivate_kill_switch.assert_not_called()


@pytest.mark.asyncio
async def test_confirm_clear_calls_deactivate_when_killed(client, wired):
    type(wired["safety_layer"]).is_killed = PropertyMock(return_value=True)
    sent: list[str] = []

    async def fake_reply(recipient, message):
        sent.append(message)
        return True

    with patch.object(messaging_router, "_send_whatsapp_reply", side_effect=fake_reply):
        resp = _post_whatsapp(client, "CONFIRM CLEAR")

    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "action": "kill_switch_cleared"}
    # Exactly one deactivation, authorized by whatsapp_remote.
    wired["safety_layer"].deactivate_kill_switch.assert_called_once_with(
        authorized_by="whatsapp_remote"
    )
    assert "KILL SWITCH CLEARED" in sent[0]
    assert "Trading resumed" in sent[0]


@pytest.mark.asyncio
async def test_confirm_clear_safety_layer_unavailable(client, wired):
    # Clear the safety layer to exercise the "unavailable" branch.
    messaging_router._safety_layer = None
    sent: list[str] = []

    async def fake_reply(recipient, message):
        sent.append(message)
        return True

    with patch.object(messaging_router, "_send_whatsapp_reply", side_effect=fake_reply):
        resp = _post_whatsapp(client, "CONFIRM CLEAR")

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["ok"] is False
    assert payload["error"] == "safety_layer_unavailable"
    assert "Safety layer not available" in sent[0]


# ─────────────────────────────────────────────────────────────────────────────
# Origin gate — non-admin senders fall through to LLM gateway, never trigger commands
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_non_admin_sender_does_not_trigger_confirm_clear(client, wired):
    """Hostile sender issuing CONFIRM CLEAR must NOT deactivate the kill switch."""
    type(wired["safety_layer"]).is_killed = PropertyMock(return_value=True)
    sent: list[str] = []

    async def fake_reply(recipient, message):
        sent.append(message)
        return True

    fake_reply_msg = MagicMock()
    fake_reply_msg.reply_text = "LLM fallback response"
    fake_reply_msg.agent = "openclaw"
    fake_reply_msg.health_state = "ok"

    fake_gateway = MagicMock()
    fake_gateway.handle = AsyncMock(return_value=fake_reply_msg)

    with (
        patch.object(messaging_router, "_send_whatsapp_reply", side_effect=fake_reply),
        patch.object(messaging_router, "_get_gateway", return_value=fake_gateway),
    ):
        resp = _post_whatsapp(client, "CONFIRM CLEAR", sender=NON_ADMIN_SENDER)

    assert resp.status_code == 200
    # CRITICAL invariant: non-admin sender must never trigger kill-switch deactivation.
    wired["safety_layer"].deactivate_kill_switch.assert_not_called()
    # Falls through to LLM gateway.
    fake_gateway.handle.assert_awaited_once()


@pytest.mark.asyncio
async def test_non_admin_sender_status_falls_through_to_llm(client, wired):
    """Non-admin STATUS request is treated as a free-form LLM prompt, not a command."""
    sent: list[str] = []

    async def fake_reply(recipient, message):
        sent.append(message)
        return True

    fake_reply_msg = MagicMock()
    fake_reply_msg.reply_text = "I'm not authorized to answer that."
    fake_reply_msg.agent = "openclaw"
    fake_reply_msg.health_state = "ok"

    fake_gateway = MagicMock()
    fake_gateway.handle = AsyncMock(return_value=fake_reply_msg)

    with (
        patch.object(messaging_router, "_send_whatsapp_reply", side_effect=fake_reply),
        patch.object(messaging_router, "_get_gateway", return_value=fake_gateway),
    ):
        resp = _post_whatsapp(client, "STATUS", sender=NON_ADMIN_SENDER)

    assert resp.status_code == 200
    # paper_tracker.get_open_positions should NOT be touched for non-admin.
    wired["paper_tracker"].get_open_positions.assert_not_called()
    fake_gateway.handle.assert_awaited_once()


# ─────────────────────────────────────────────────────────────────────────────
# Malformed payloads
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_missing_sender_returns_400(client, wired):
    """No From field at all → 400, no crash, no command processing."""
    resp = client.post(
        "/messaging/inbound/whatsapp",
        json={"Body": "STATUS"},  # no From
    )
    assert resp.status_code == 400
    assert "whatsapp sender missing" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_empty_body_falls_through_to_llm_safely(client, wired):
    """Admin sender + empty body — must not raise; falls through to LLM gateway."""
    sent: list[str] = []

    async def fake_reply(recipient, message):
        sent.append(message)
        return True

    fake_reply_msg = MagicMock()
    fake_reply_msg.reply_text = "Hello?"
    fake_reply_msg.agent = "openclaw"
    fake_reply_msg.health_state = "ok"

    fake_gateway = MagicMock()
    fake_gateway.handle = AsyncMock(return_value=fake_reply_msg)

    with (
        patch.object(messaging_router, "_send_whatsapp_reply", side_effect=fake_reply),
        patch.object(messaging_router, "_get_gateway", return_value=fake_gateway),
    ):
        resp = _post_whatsapp(client, "")

    assert resp.status_code == 200
    fake_gateway.handle.assert_awaited_once()
    # No state-mutating command path was hit.
    wired["safety_layer"].deactivate_kill_switch.assert_not_called()
    wired["safety_layer"].activate_kill_switch.assert_not_called()
