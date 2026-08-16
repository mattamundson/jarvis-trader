"""Unit tests for routers/whatsapp_router.py (Phase 4.1 Twilio interactive webhook).

IMPORTANT — this file documents real bugs found while writing these tests
(see the module docstrings on the "keyerror_bug" and "endpoint_always_errors"
tests below, and the run's findings report). Per task instructions the router
is NOT modified; tests assert the *actual current* behavior so regressions
are caught, while flagging the defects for a human fix decision:

  1. `receive_whatsapp_reply` ends with
     `return Request(scope={"type": "http"})._headers.update(...)` — this
     unconditionally raises AttributeError (Starlette's Request lazily sets
     `_headers` only via the `.headers` property, which is never touched
     here), so the endpoint 500s for every inbound command. The real
     Response-returning code right below it is unreachable dead code.
  2. `_handle_approve` / `_handle_reject` read `row["id"]`, but
     `get_latest_pending_approval_row` (approval/service.py) returns rows
     keyed `"approval_id"` (confirmed in tests/test_pending_approvals.py and
     mirrored correctly by the sibling routers/openclaw_router.py). Any real
     pending approval row raises KeyError.
  3. `_handle_approve`'s confirmation string reads
     `result.get('trade_id', 'unknown')`, but `approve_pending_trade` returns
     the id under `"paper_trade_id"` — the confirmation always prints
     "Trade ID: unknown".

Tests call the private `_handle_*` helpers directly (bypassing the broken
endpoint wrapper) to get real coverage of their logic, plus one endpoint-level
test that pins down the current 500 behavior.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routers.whatsapp_router as whatsapp_router
from approval.service import ApprovalFlowError
from routers.whatsapp_router import inject_dependencies
from routers.whatsapp_router import router as whatsapp_api_router


@pytest.fixture
def app_with_router():
    app = FastAPI()
    app.include_router(whatsapp_api_router)
    return app


@pytest.fixture
def client(app_with_router):
    # raise_server_exceptions=False so the (currently-broken) endpoint's
    # AttributeError surfaces as a real HTTP 500 response instead of
    # propagating into the test process — this is what Twilio actually sees.
    return TestClient(app_with_router, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def _wired():
    """Inject MagicMock dependencies and restore module globals after each test."""
    prior_db = whatsapp_router._db_manager
    prior_pt = whatsapp_router._paper_tracker
    prior_sl = whatsapp_router._safety_layer
    prior_dm = whatsapp_router._data_manager
    prior_kill_confirm = set(whatsapp_router._pending_kill_confirm)
    inject_dependencies(MagicMock(), MagicMock(), MagicMock())
    yield
    whatsapp_router._db_manager = prior_db
    whatsapp_router._paper_tracker = prior_pt
    whatsapp_router._safety_layer = prior_sl
    whatsapp_router._data_manager = prior_dm
    whatsapp_router._pending_kill_confirm.clear()
    whatsapp_router._pending_kill_confirm.update(prior_kill_confirm)


# ─────────────────────────────────────────────────────────────────────────────
# _handle_approve
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_handle_approve_components_not_initialized():
    whatsapp_router._safety_layer = None
    result = await whatsapp_router._handle_approve()
    assert result == "❌ Approval system components not initialized."


@pytest.mark.asyncio
async def test_handle_approve_realistic_row_raises_keyerror_bug():
    """BUG: a real pending-approval row (keyed 'approval_id', not 'id') crashes this handler."""
    real_row = {"approval_id": "abc-123", "symbol": "MES", "action": "buy", "quantity": 1.0}
    with patch.object(whatsapp_router, "get_latest_pending_approval_row", return_value=real_row):
        with pytest.raises(KeyError):
            await whatsapp_router._handle_approve()


@pytest.mark.asyncio
async def test_handle_approve_success_message_format():
    """Exercises the confirmation-message formatting logic (row shaped to the
    handler's current — buggy — 'id' key expectation, since a realistic row
    can't reach this code path; see test_handle_approve_realistic_row_raises_keyerror_bug)."""
    row = {"id": "abc-123", "symbol": "MES", "action": "buy"}
    approve_result = {"trade_id": "paper-uuid-12345678", "status": "approved"}
    with (
        patch.object(whatsapp_router, "get_latest_pending_approval_row", return_value=row),
        patch.object(
            whatsapp_router, "approve_pending_trade", new=AsyncMock(return_value=approve_result)
        ),
    ):
        result = await whatsapp_router._handle_approve()

    assert result == "✅ *APPROVED:* buy MES\nTrade ID: paper-uu"


@pytest.mark.asyncio
async def test_handle_approve_service_error_returns_failure_message():
    row = {"id": "abc-123", "symbol": "MES", "action": "buy"}
    with (
        patch.object(whatsapp_router, "get_latest_pending_approval_row", return_value=row),
        patch.object(
            whatsapp_router,
            "approve_pending_trade",
            new=AsyncMock(side_effect=ApprovalFlowError(409, "Kill switch active")),
        ),
    ):
        result = await whatsapp_router._handle_approve()

    assert result == "❌ *Approval Failed:* Kill switch active"


# ─────────────────────────────────────────────────────────────────────────────
# _handle_reject
# ─────────────────────────────────────────────────────────────────────────────
def test_handle_reject_no_db_manager():
    whatsapp_router._db_manager = None
    result = whatsapp_router._handle_reject()
    assert result == "❌ System error: DB not initialized."


def test_handle_reject_realistic_row_raises_keyerror_bug():
    """BUG: same row['id'] vs row['approval_id'] mismatch as _handle_approve."""
    real_row = {"approval_id": "abc-123", "symbol": "MCL", "action": "sell"}
    with patch.object(whatsapp_router, "get_latest_pending_approval_row", return_value=real_row):
        with pytest.raises(KeyError):
            whatsapp_router._handle_reject()


def test_handle_reject_success_message_format():
    row = {"id": "abc-123", "symbol": "MCL", "action": "sell"}
    with (
        patch.object(whatsapp_router, "get_latest_pending_approval_row", return_value=row),
        patch.object(whatsapp_router, "reject_pending_trade", return_value={"status": "rejected"}),
    ):
        result = whatsapp_router._handle_reject()

    assert result == "🚫 *REJECTED:* sell MCL"


def test_handle_reject_service_error_returns_failure_message():
    row = {"id": "abc-123", "symbol": "MCL", "action": "sell"}
    with (
        patch.object(whatsapp_router, "get_latest_pending_approval_row", return_value=row),
        patch.object(
            whatsapp_router,
            "reject_pending_trade",
            side_effect=ApprovalFlowError(404, "Approval not found"),
        ),
    ):
        result = whatsapp_router._handle_reject()

    assert result == "❌ *Rejection Failed:* Approval not found"


# ─────────────────────────────────────────────────────────────────────────────
# _handle_kill
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_handle_kill_no_safety_layer():
    whatsapp_router._safety_layer = None
    result = await whatsapp_router._handle_kill()
    assert result == "❌ Safety layer not initialized."


@pytest.mark.asyncio
async def test_handle_kill_activates_kill_switch():
    mock_sl = MagicMock()
    mock_sl.activate_kill_switch = AsyncMock(return_value=None)
    whatsapp_router._safety_layer = mock_sl

    result = await whatsapp_router._handle_kill()

    assert "KILL SWITCH ACTIVATED" in result
    mock_sl.activate_kill_switch.assert_awaited_once_with(reason="Emergency stop via WhatsApp")


# ─────────────────────────────────────────────────────────────────────────────
# _handle_status
# ─────────────────────────────────────────────────────────────────────────────
def test_handle_status_no_safety_layer():
    whatsapp_router._safety_layer = None
    result = whatsapp_router._handle_status()
    assert result == "❌ Status unavailable."


def test_handle_status_formats_off_status():
    mock_sl = MagicMock()
    mock_sl.get_status.return_value = {
        "kill_switch_active": False,
        "daily_pnl": 125.5,
        "current_equity": 10125.0,
    }
    whatsapp_router._safety_layer = mock_sl

    result = whatsapp_router._handle_status()

    assert "Kill Switch: OFF 🟢" in result
    assert "Daily P&L: $125.50" in result
    assert "Equity: $10,125" in result


def test_handle_status_formats_active_kill_switch():
    mock_sl = MagicMock()
    mock_sl.get_status.return_value = {
        "kill_switch_active": True,
        "daily_pnl": -50.0,
        "current_equity": 9950.0,
    }
    whatsapp_router._safety_layer = mock_sl

    result = whatsapp_router._handle_status()

    assert "Kill Switch: ACTIVE 🔴" in result


# ─────────────────────────────────────────────────────────────────────────────
# Endpoint-level — pins down the current (broken) HTTP contract.
# ─────────────────────────────────────────────────────────────────────────────
def test_endpoint_always_500s_due_to_broken_return_statement(client):
    """BUG: every inbound webhook — even a trivial STATUS request with a fully
    wired, healthy safety layer — 500s because of the broken final `return`
    statement in receive_whatsapp_reply (see module docstring, bug #1). This
    test pins the current behavior so a future fix is visible as a diff here,
    not a silent regression."""
    mock_sl = MagicMock()
    mock_sl.get_status.return_value = {
        "kill_switch_active": False,
        "daily_pnl": 0.0,
        "current_equity": 10000.0,
    }
    whatsapp_router._safety_layer = mock_sl

    resp = client.post(
        "/webhook/whatsapp/reply",
        data={"Body": "STATUS", "From": "whatsapp:+15551234567"},
    )

    assert resp.status_code == 500
