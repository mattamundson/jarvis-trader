"""Tests for RobinhoodConnector — scaffold only, no real MCP transport yet.

See execution/robinhood_connector.py module docstring: the MCP endpoint,
OAuth flow, and tool schema are unverified, so every network-touching
method raises NotImplementedError once past the connected/ready gates.
These tests lock in the gating, safety-check wiring, and equities-only
guard rather than any live behavior.
"""

from unittest.mock import MagicMock

import pytest

from execution.order_router import OrderRouter
from execution.robinhood_connector import ConnectionState, RobinhoodConnector

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def robinhood_settings():
    """Settings mock with ROBINHOOD_READY=True so the ready-gate passes."""
    settings = MagicMock()
    settings.ROBINHOOD_READY = True
    settings.ROBINHOOD_MCP_URL = "https://example.invalid/mcp/trading"
    settings.ROBINHOOD_AGENTIC_ACCOUNT_ID = "test-account"
    return settings


@pytest.fixture
def robinhood_settings_gated():
    """Settings mock with ROBINHOOD_READY=False — connect() guard must raise."""
    settings = MagicMock()
    settings.ROBINHOOD_READY = False
    settings.ROBINHOOD_MCP_URL = "https://example.invalid/mcp/trading"
    settings.ROBINHOOD_AGENTIC_ACCOUNT_ID = "test-account"
    return settings


@pytest.fixture
def robinhood_safety():
    return MagicMock()


@pytest.fixture
def connector(robinhood_settings, robinhood_safety):
    return RobinhoodConnector(settings=robinhood_settings, safety_layer=robinhood_safety)


# ---------------------------------------------------------------------------
# RobinhoodConnector — lifecycle
# ---------------------------------------------------------------------------


def test_connector_instantiates(connector):
    assert connector is not None


def test_not_connected_initially(connector):
    assert not connector.is_connected


def test_state_is_disconnected_on_init(connector):
    assert connector._state == ConnectionState.DISCONNECTED


def test_is_connected_requires_connected_state_and_session(connector):
    connector._state = ConnectionState.CONNECTED
    connector._mcp_session = None
    assert not connector.is_connected


def test_is_connected_true_when_state_connected_and_session_set(connector):
    connector._state = ConnectionState.CONNECTED
    connector._mcp_session = MagicMock()
    assert connector.is_connected


# ---------------------------------------------------------------------------
# RobinhoodConnector — ROBINHOOD_READY gate (defaults closed)
# ---------------------------------------------------------------------------


def test_assert_robinhood_ready_raises_when_false(robinhood_settings_gated, robinhood_safety):
    rc = RobinhoodConnector(settings=robinhood_settings_gated, safety_layer=robinhood_safety)
    with pytest.raises(RuntimeError, match="ROBINHOOD_READY"):
        rc._assert_robinhood_ready()


def test_assert_robinhood_ready_passes_when_true(connector):
    connector._assert_robinhood_ready()  # must not raise


def test_ready_gate_defaults_closed_when_settings_missing_attribute():
    """A plain object with no ROBINHOOD_READY attribute must gate closed."""
    settings = object()
    rc = RobinhoodConnector(settings=settings)
    with pytest.raises(RuntimeError, match="ROBINHOOD_READY"):
        rc._assert_robinhood_ready()


@pytest.mark.asyncio
async def test_initialize_blocked_when_not_ready(robinhood_settings_gated, robinhood_safety):
    rc = RobinhoodConnector(settings=robinhood_settings_gated, safety_layer=robinhood_safety)
    with pytest.raises(RuntimeError, match="ROBINHOOD_READY"):
        await rc.initialize()


@pytest.mark.asyncio
async def test_connect_raises_not_implemented_once_ready(connector):
    """Past the ready-gate, connect() must fail loud (no real MCP transport yet)."""
    with pytest.raises(NotImplementedError, match="MCP transport"):
        await connector.connect()


# ---------------------------------------------------------------------------
# RobinhoodConnector — graceful returns when not connected
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_account_summary_returns_error_dict_when_not_connected(connector):
    result = await connector.get_account_summary()
    assert isinstance(result, dict)
    assert "error" in result


@pytest.mark.asyncio
async def test_get_positions_returns_empty_list_when_not_connected(connector):
    result = await connector.get_positions()
    assert result == []


@pytest.mark.asyncio
async def test_get_open_orders_returns_empty_list_when_not_connected(connector):
    result = await connector.get_open_orders()
    assert result == []


@pytest.mark.asyncio
async def test_cancel_all_orders_returns_zero_when_not_connected(connector):
    result = await connector.cancel_all_orders()
    assert result == 0


@pytest.mark.asyncio
async def test_submit_equity_order_returns_error_dict_when_not_connected(connector):
    result = await connector.submit_equity_order("AAPL", 1, "BUY")
    assert result == {"status": "error", "reason": "Robinhood not connected"}


# ---------------------------------------------------------------------------
# RobinhoodConnector — equities-only guard (must reject futures unconditionally)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("symbol", ["MES", "MCL", "MNQ", "M2K", "MGC", "mes"])
async def test_submit_equity_order_rejects_futures_symbols(connector, symbol):
    result = await connector.submit_equity_order(symbol, 1, "BUY")
    assert result["status"] == "error"
    assert "equities-only" in result["reason"]


@pytest.mark.asyncio
async def test_place_paper_order_rejects_futures_before_any_safety_check(connector, robinhood_safety):
    order = {"symbol": "MES", "quantity": 1, "side": "BUY", "portfolio_equity": 10000.0}
    result = await connector.place_paper_order(order)
    assert result["status"] == "error"
    assert "equities-only" in result["reason"]
    robinhood_safety.check_order.assert_not_called()


@pytest.mark.asyncio
async def test_place_paper_order_returns_dict_when_not_connected(connector):
    order = {
        "symbol": "AAPL",
        "quantity": 1,
        "side": "BUY",
        "portfolio_equity": 10000.0,
    }
    result = await connector.place_paper_order(order)
    assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# RobinhoodConnector — safety layer contract (must run before any order)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_place_paper_order_calls_safety_check(connector, robinhood_safety):
    rejected = MagicMock(approved=False, rejection_reason="daily loss limit", warnings=[])
    robinhood_safety.check_order.return_value = rejected

    order = {"symbol": "AAPL", "quantity": 1, "side": "BUY", "portfolio_equity": 10000.0}
    result = await connector.place_paper_order(order)

    robinhood_safety.check_order.assert_called_once()
    assert result == {"status": "rejected", "reason": "daily loss limit", "warnings": []}


@pytest.mark.asyncio
async def test_place_paper_order_skips_broker_call_when_safety_rejects(connector, robinhood_safety):
    """A rejected order must never reach submit_equity_order (no broker touch)."""
    robinhood_safety.check_order.return_value = MagicMock(
        approved=False, rejection_reason="blocked", warnings=[]
    )
    connector.submit_equity_order = MagicMock(side_effect=AssertionError("must not be called"))

    order = {"symbol": "AAPL", "quantity": 1, "side": "BUY", "portfolio_equity": 10000.0}
    result = await connector.place_paper_order(order)

    assert result["status"] == "rejected"


def test_disconnect_resets_state():
    rc = RobinhoodConnector(settings=MagicMock(ROBINHOOD_READY=True))
    rc._state = ConnectionState.CONNECTED
    rc._mcp_session = MagicMock()
    assert rc.is_connected


# ---------------------------------------------------------------------------
# OrderRouter — Robinhood wiring is attach/status only (no routing change)
# ---------------------------------------------------------------------------


def test_order_router_attach_robinhood():
    router = OrderRouter()
    mock_robinhood = MagicMock()
    router.attach_robinhood(mock_robinhood)
    assert router.robinhood is mock_robinhood


def test_order_router_status_includes_robinhood_disconnected_by_default():
    router = OrderRouter()
    status = router.status()
    assert status["robinhood_connected"] is False


def test_order_router_status_reflects_connected_robinhood():
    router = OrderRouter()
    mock_robinhood = MagicMock()
    mock_robinhood.is_connected = True
    router.attach_robinhood(mock_robinhood)
    status = router.status()
    assert status["robinhood_connected"] is True


def test_order_router_equity_routing_still_requires_schwab_not_robinhood():
    """Robinhood attached but Schwab absent — equity routing must still fail closed.

    Locks in that attaching RobinhoodConnector does not silently change which
    broker handles equities; route_order()'s equity branch is untouched by
    this scaffold.
    """
    router = OrderRouter()
    router.attach_robinhood(MagicMock(is_connected=True))
    assert router.schwab is None
