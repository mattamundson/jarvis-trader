"""OrderRouter — dispatch/routing coverage (offline, no broker connections).

Drives execution/order_router.py with lightweight fakes. Covers the per-asset
routing rules (futures->IBKR, equity->Schwab, options->Schwab/IBKR fallback,
crypto-spot->module), the not-connected RuntimeError guards, bracket routing,
and cancel/modify dispatch. Pure logic — no IB Gateway, no network.
"""

from __future__ import annotations

import pytest

from execution.order_router import FUTURES_SYMBOLS, OrderRouter


class FakeIBKR:
    """IBGatewayConnector stand-in. Note: is_connected() is a METHOD here
    (the router calls `self.ibkr.is_connected()`)."""

    def __init__(self, connected: bool = True):
        self._connected = connected
        self.calls: list = []

    def is_connected(self) -> bool:
        return self._connected

    async def place_paper_order(self, **kwargs):
        self.calls.append(("place_paper_order", kwargs))
        return "ib-fill-1"

    async def place_bracket_order(self, **kwargs):
        self.calls.append(("place_bracket_order", kwargs))
        return {"status": "placed", "order_id": "entry-1", "sl_id": "sl-1", "tp_id": "tp-1"}

    async def cancel_order(self, order_id):
        self.calls.append(("cancel_order", order_id))
        return {"status": "cancelled", "order_id": order_id}

    async def modify_order(self, order_id, new_price):
        self.calls.append(("modify_order", order_id, new_price))
        return {"status": "modified", "order_id": order_id, "new_price": new_price}


class FakeSchwab:
    """SchwabConnector stand-in. Note: is_connected is a PROPERTY here
    (the router reads `self.schwab.is_connected` with no parens)."""

    def __init__(self, connected: bool = True):
        self.is_connected = connected
        self.calls: list = []

    async def place_paper_order(self, order):
        self.calls.append(("place_paper_order", order))
        return {"status": "placed", "broker": "schwab"}

    async def submit_options_order(self, order, portfolio_equity):
        self.calls.append(("submit_options_order", order, portfolio_equity))
        return {"status": "placed", "broker": "schwab", "kind": "option"}

    async def submit_options_spread_order(self, order, portfolio_equity):
        self.calls.append(("submit_options_spread_order", order, portfolio_equity))
        return {"status": "placed", "broker": "schwab", "kind": "spread"}

    async def cancel_order(self, order_id):
        return {"status": "cancelled", "order_id": order_id}

    async def modify_order(self, order_id, new_price):
        return {"status": "modified", "order_id": order_id}


# ── predicates ────────────────────────────────────────────────────────────


def test_is_futures_is_case_insensitive_and_table_driven():
    r = OrderRouter()
    assert r.is_futures("MES") is True
    assert r.is_futures("mes") is True
    assert r.is_futures("SPY") is False
    # every symbol in the table is recognized
    assert all(r.is_futures(s) for s in FUTURES_SYMBOLS)


def test_is_crypto_spot_and_is_options_predicates():
    r = OrderRouter()
    assert r.is_crypto_spot("BTCUSD") is True
    assert r.is_crypto_spot("btcusd") is True
    assert r.is_crypto_spot("MES") is False
    assert r.is_options({"asset_type": "OPT"}) is True
    assert r.is_options({"asset_type": "option"}) is True
    assert r.is_options({"asset_type": "STK"}) is False
    assert r.is_options({}) is False


# ── route_order: futures ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_route_order_futures_goes_to_ibkr():
    ib = FakeIBKR(connected=True)
    r = OrderRouter(ibkr=ib)
    out = await r.route_order({"symbol": "MES", "action": "BUY", "quantity": 2})
    assert out["status"] == "placed"
    assert out["broker"] == "ibkr"
    assert out["fill_id"] == "ib-fill-1"
    assert ib.calls and ib.calls[0][0] == "place_paper_order"


@pytest.mark.asyncio
async def test_route_order_futures_not_connected_raises():
    r = OrderRouter(ibkr=FakeIBKR(connected=False))
    with pytest.raises(RuntimeError, match="IBKR not connected"):
        await r.route_order({"symbol": "MNQ", "action": "BUY", "quantity": 1})


@pytest.mark.asyncio
async def test_route_order_futures_no_fill_id_reports_error_status():
    class NoFillIBKR(FakeIBKR):
        async def place_paper_order(self, **kwargs):
            return None

    r = OrderRouter(ibkr=NoFillIBKR(connected=True))
    out = await r.route_order({"symbol": "MES", "action": "BUY", "quantity": 1})
    assert out["status"] == "error"
    assert out["fill_id"] is None


# ── route_order: equity ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_route_order_equity_goes_to_schwab():
    sc = FakeSchwab(connected=True)
    r = OrderRouter(schwab=sc)
    out = await r.route_order({"symbol": "SPY", "action": "BUY", "quantity": 10})
    assert out["status"] == "placed"
    assert out["broker"] == "schwab"


@pytest.mark.asyncio
async def test_route_order_equity_not_connected_raises():
    r = OrderRouter(schwab=FakeSchwab(connected=False))
    with pytest.raises(RuntimeError, match="Schwab not connected"):
        await r.route_order({"symbol": "AAPL", "action": "BUY", "quantity": 1})


# ── route_order: options ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_route_order_option_prefers_schwab():
    sc = FakeSchwab(connected=True)
    r = OrderRouter(schwab=sc)
    out = await r.route_order(
        {"symbol": "SPY", "asset_type": "OPT", "action": "BUY", "quantity": 1}
    )
    assert out == {"status": "placed", "broker": "schwab", "kind": "option"}


@pytest.mark.asyncio
async def test_route_order_option_spread_uses_spread_endpoint():
    sc = FakeSchwab(connected=True)
    r = OrderRouter(schwab=sc)
    out = await r.route_order(
        {"symbol": "SPX", "asset_type": "OPT", "is_spread": True, "quantity": 1}
    )
    assert out["kind"] == "spread"


@pytest.mark.asyncio
async def test_route_order_option_no_broker_raises():
    r = OrderRouter()  # neither schwab nor ibkr
    with pytest.raises(RuntimeError, match="No broker connected for options"):
        await r.route_order({"symbol": "SPY", "asset_type": "OPT", "quantity": 1})


# ── route_order: crypto spot ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_route_order_crypto_spot_without_module_raises():
    r = OrderRouter()
    with pytest.raises(RuntimeError, match="Crypto module not attached"):
        await r.route_order({"symbol": "BTCUSD", "action": "buy", "quantity": 1})


# ── route_bracket_order ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_route_bracket_futures_goes_to_ibkr_bracket():
    ib = FakeIBKR(connected=True)
    r = OrderRouter(ibkr=ib)
    out = await r.route_bracket_order(
        symbol="MES", action="BUY", quantity=1, stop_loss=5280.0, take_profit=5350.0
    )
    assert out["status"] == "placed"
    assert out["sl_id"] == "sl-1"
    assert out["tp_id"] == "tp-1"
    assert any(c[0] == "place_bracket_order" for c in ib.calls)


@pytest.mark.asyncio
async def test_route_bracket_futures_not_connected_raises():
    r = OrderRouter(ibkr=FakeIBKR(connected=False))
    with pytest.raises(RuntimeError, match="IBKR not connected"):
        await r.route_bracket_order(symbol="MES", action="BUY", quantity=1)


@pytest.mark.asyncio
async def test_route_bracket_nonfutures_not_implemented():
    r = OrderRouter(ibkr=FakeIBKR(connected=True))
    with pytest.raises(NotImplementedError):
        await r.route_bracket_order(symbol="SPY", action="BUY", quantity=1)


# ── cancel / modify dispatch ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cancel_order_prefers_ibkr_when_connected():
    ib = FakeIBKR(connected=True)
    r = OrderRouter(ibkr=ib, schwab=FakeSchwab(connected=True))
    out = await r.cancel_order("abc")
    assert out["status"] == "cancelled"
    assert any(c[0] == "cancel_order" for c in ib.calls)


@pytest.mark.asyncio
async def test_cancel_order_no_broker_returns_error_dict():
    r = OrderRouter()
    out = await r.cancel_order("abc")
    assert out["status"] == "error"
    assert "No connected broker" in out["reason"]


@pytest.mark.asyncio
async def test_modify_order_ibkr_path():
    ib = FakeIBKR(connected=True)
    r = OrderRouter(ibkr=ib)
    out = await r.modify_order("abc", 101.5)
    assert out["status"] == "modified"
    assert out["new_price"] == 101.5


@pytest.mark.asyncio
async def test_modify_order_no_broker_returns_error_dict():
    r = OrderRouter()
    out = await r.modify_order("abc", 100.0)
    assert out["status"] == "error"


# ── status ────────────────────────────────────────────────────────────────


def test_status_reflects_connection_state():
    r = OrderRouter(ibkr=FakeIBKR(connected=True), schwab=FakeSchwab(connected=False))
    s = r.status()
    assert s["ibkr_connected"] is True
    assert s["schwab_connected"] is False
    assert s["futures_broker"] == "ibkr"
    assert s["equity_broker"] == "unavailable"
