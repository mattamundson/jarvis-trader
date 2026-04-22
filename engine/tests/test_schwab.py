"""Tests for SchwabConnector and OrderRouter — uses mocked schwab-py client."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from execution.order_router import OrderRouter
from execution.schwab_connector import ConnectionState, SchwabConnector

# ---------------------------------------------------------------------------
# Fixtures
#
# Named with schwab_ prefix to avoid shadowing conftest.py's mock_settings
# and mock_safety_layer fixtures (which return real TradingConfig/SafetyLayer).
# ---------------------------------------------------------------------------


@pytest.fixture
def schwab_settings():
    """Settings mock with SCHWAB_READY=True so connect() guard passes."""
    settings = MagicMock()
    settings.SCHWAB_READY = True
    settings.SCHWAB_APP_KEY = "test_key"
    settings.SCHWAB_APP_SECRET = "test_secret"
    settings.SCHWAB_CALLBACK_URL = "https://127.0.0.1"
    return settings


@pytest.fixture
def schwab_settings_gated():
    """Settings mock with SCHWAB_READY=False — connect() guard must raise."""
    settings = MagicMock()
    settings.SCHWAB_READY = False
    settings.SCHWAB_APP_KEY = "test_key"
    settings.SCHWAB_APP_SECRET = "test_secret"
    settings.SCHWAB_CALLBACK_URL = "https://127.0.0.1"
    return settings


@pytest.fixture
def schwab_safety():
    return MagicMock()


@pytest.fixture
def connector(schwab_settings, schwab_safety):
    return SchwabConnector(settings=schwab_settings, safety_layer=schwab_safety)


@pytest.fixture
def connector_ready(schwab_settings, schwab_safety):
    """Connector in CONNECTED state with a mocked client."""
    sc = SchwabConnector(settings=schwab_settings, safety_layer=schwab_safety)
    sc._client = MagicMock()
    sc._state = ConnectionState.CONNECTED
    sc._account_hash = "TESTHASH12345678"
    return sc


# ---------------------------------------------------------------------------
# SchwabConnector — lifecycle
# ---------------------------------------------------------------------------


def test_connector_instantiates(connector):
    assert connector is not None


def test_not_connected_initially(connector):
    """Connector starts in DISCONNECTED state — is_connected must be False."""
    assert not connector.is_connected


def test_state_is_disconnected_on_init(connector):
    assert connector._state == ConnectionState.DISCONNECTED


def test_is_connected_requires_connected_state_and_client(connector):
    """is_connected is False when state is CONNECTED but _client is None."""
    connector._state = ConnectionState.CONNECTED
    connector._client = None
    assert not connector.is_connected


def test_is_connected_true_when_state_connected_and_client_set(connector):
    """is_connected is True only when both state=CONNECTED and _client is set."""
    connector._state = ConnectionState.CONNECTED
    connector._client = MagicMock()
    assert connector.is_connected


def test_is_connected_false_for_all_non_connected_states(connector):
    """is_connected is False for every non-CONNECTED state, even with a client."""
    for state in (
        ConnectionState.DISCONNECTED,
        ConnectionState.CONNECTING,
        ConnectionState.RECONNECTING,
        ConnectionState.ERROR,
    ):
        connector._state = state
        connector._client = MagicMock()
        assert not connector.is_connected, f"Expected False for state={state}"


# ---------------------------------------------------------------------------
# SchwabConnector — SCHWAB_READY gate
# ---------------------------------------------------------------------------


def test_assert_schwab_ready_raises_when_false(schwab_settings_gated, schwab_safety):
    """_assert_schwab_ready() raises when settings.SCHWAB_READY is False."""
    sc = SchwabConnector(settings=schwab_settings_gated, safety_layer=schwab_safety)
    with pytest.raises(RuntimeError, match="SCHWAB_READY"):
        sc._assert_schwab_ready()


def test_assert_schwab_ready_passes_when_true(connector):
    """_assert_schwab_ready() must not raise when settings.SCHWAB_READY is True."""
    connector._assert_schwab_ready()  # must not raise


@pytest.mark.asyncio
async def test_initialize_blocked_when_schwab_not_ready(schwab_settings_gated, schwab_safety):
    """initialize() raises immediately when SCHWAB_READY=False (Phase 3 gate)."""
    sc = SchwabConnector(settings=schwab_settings_gated, safety_layer=schwab_safety)
    with pytest.raises(RuntimeError, match="SCHWAB_READY"):
        await sc.initialize()


# ---------------------------------------------------------------------------
# SchwabConnector — graceful returns when not connected
#
# These methods check is_connected at entry and return graceful defaults
# (error dict or empty list/int) without raising.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_account_summary_returns_error_dict_when_not_connected(connector):
    result = await connector.get_account_summary()
    assert isinstance(result, dict)
    assert "error" in result


@pytest.mark.asyncio
async def test_get_quotes_returns_empty_dict_when_not_connected(connector):
    result = await connector.get_quotes(["SPY"])
    assert result == {}


@pytest.mark.asyncio
async def test_get_options_chain_returns_error_dict_when_not_connected(connector):
    result = await connector.get_options_chain("SPY")
    assert isinstance(result, dict)
    assert "error" in result


@pytest.mark.asyncio
async def test_get_open_orders_returns_empty_list_when_not_connected(connector):
    result = await connector.get_open_orders()
    assert result == []


@pytest.mark.asyncio
async def test_cancel_all_orders_returns_zero_when_not_connected(connector):
    result = await connector.cancel_all_orders()
    assert result == 0


@pytest.mark.asyncio
async def test_place_paper_order_returns_dict_when_not_connected(connector):
    """place_paper_order must return a dict (rejected/error) and not raise."""
    order = {
        "symbol": "SPY",
        "quantity": 1,
        "side": "BUY",
        "asset_type": "equity",
        "portfolio_equity": 10000.0,
    }
    result = await connector.place_paper_order(order)
    assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# SchwabConnector — disconnect resets state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_disconnect_resets_state(connector_ready):
    assert connector_ready.is_connected
    await connector_ready.disconnect()
    assert not connector_ready.is_connected
    assert connector_ready._state == ConnectionState.DISCONNECTED
    assert connector_ready._client is None


# ---------------------------------------------------------------------------
# SchwabConnector — auth instructions
# ---------------------------------------------------------------------------


def test_get_auth_instructions_returns_string(connector):
    instructions = connector.get_auth_instructions()
    assert isinstance(instructions, str)
    assert "SCHWAB_APP_KEY" in instructions
    assert "SCHWAB_APP_SECRET" in instructions


# ---------------------------------------------------------------------------
# OrderRouter — routing logic
# ---------------------------------------------------------------------------


def test_order_router_futures_routing():
    router = OrderRouter()
    assert router.is_futures("MES")
    assert router.is_futures("MNQ")
    assert router.is_futures("MCL")
    assert not router.is_futures("SPY")
    assert not router.is_futures("QQQ")
    assert not router.is_futures("AAPL")


def test_order_router_futures_routing_case_insensitive():
    router = OrderRouter()
    assert router.is_futures("mes")
    assert router.is_futures("Mnq")


def test_order_router_options_detection():
    router = OrderRouter()
    assert router.is_options({"asset_type": "OPT"})
    assert router.is_options({"asset_type": "OPTION"})
    assert router.is_options({"asset_type": "OPTIONS"})
    assert not router.is_options({"asset_type": "equity"})
    assert not router.is_options({})


def test_order_router_status_no_brokers():
    router = OrderRouter()
    status = router.status()
    assert status["ibkr_connected"] is False
    assert status["schwab_connected"] is False
    assert status["futures_broker"] == "unavailable"
    assert status["equity_broker"] == "unavailable"


def test_order_router_status_reflects_connected_schwab():
    router = OrderRouter()
    mock_schwab = MagicMock()
    mock_schwab.is_connected = True
    router.attach_schwab(mock_schwab)
    status = router.status()
    assert status["schwab_connected"] is True
    assert status["equity_broker"] == "schwab"


def test_order_router_attach_connectors():
    router = OrderRouter()
    mock_ibkr = MagicMock()
    mock_schwab = MagicMock()
    router.attach_ibkr(mock_ibkr)
    router.attach_schwab(mock_schwab)
    assert router.ibkr is mock_ibkr
    assert router.schwab is mock_schwab


# ---------------------------------------------------------------------------
# OrderRouter — route_order raises when brokers not connected
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_order_router_raises_without_ibkr_for_futures():
    router = OrderRouter()
    order = {"symbol": "MES", "quantity": 1, "side": "BUY"}
    with pytest.raises(RuntimeError, match="IBKR not connected"):
        await router.route_order(order)


@pytest.mark.asyncio
async def test_order_router_raises_without_schwab_for_equity():
    router = OrderRouter()
    order = {"symbol": "SPY", "quantity": 1, "side": "BUY", "asset_type": "equity"}
    with pytest.raises(RuntimeError, match="Schwab not connected"):
        await router.route_order(order)


@pytest.mark.asyncio
async def test_order_router_raises_without_any_broker_for_options():
    router = OrderRouter()
    order = {"symbol": "SPY", "quantity": 1, "side": "BUY", "asset_type": "OPT"}
    with pytest.raises(RuntimeError):
        await router.route_order(order)


@pytest.mark.asyncio
async def test_order_router_routes_futures_to_ibkr_when_connected():
    router = OrderRouter()
    mock_ibkr = MagicMock()
    mock_ibkr.is_connected.return_value = True
    mock_ibkr.place_paper_order = AsyncMock(return_value={"status": "filled"})
    router.attach_ibkr(mock_ibkr)

    order = {"symbol": "MES", "quantity": 1, "action": "BUY"}
    result = await router.route_order(order)

    mock_ibkr.place_paper_order.assert_called_once_with(
        symbol="MES",
        action="BUY",
        quantity=1,
        order_type="MKT",
        limit_price=None,
    )
    assert result["status"] == "placed"
    assert result["symbol"] == "MES"
    assert result["broker"] == "ibkr"


@pytest.mark.asyncio
async def test_order_router_routes_equity_to_schwab_when_connected():
    router = OrderRouter()
    mock_schwab = MagicMock()
    mock_schwab.is_connected = True
    mock_schwab.place_paper_order = AsyncMock(return_value={"status": "placed"})
    router.attach_schwab(mock_schwab)

    order = {"symbol": "SPY", "quantity": 1, "side": "BUY", "asset_type": "equity"}
    result = await router.route_order(order)

    mock_schwab.place_paper_order.assert_called_once_with(order)
    assert result == {"status": "placed"}
