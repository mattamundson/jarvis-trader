"""P0-2 — order-gateway factory + OrderRouter real-gateway guards.

Runnable without a live IB Gateway: the factory only *constructs* the gateway
object (IBGatewayManager.__init__ does not open a socket), so we can assert which
class is returned and how it is configured. The live broker-observed proof lives
in test_ib_paper_order_path_integration.py (marked integration_ib).
"""

from __future__ import annotations

import pytest


class _Settings:
    """Minimal settings stand-in exposing only what build_order_gateway reads."""

    def __init__(self, **overrides):
        self.PAPER_TRADING = True
        self.IB_PAPER_BROKER_ENABLED = False
        self.IBKR_HOST = "127.0.0.1"
        self.IBKR_PORT = 4002
        self.IBKR_CLIENT_ID = 244
        self.IB_ACCOUNT_ID = "DU1234567"
        self.IBKR_CONNECT_TIMEOUT_SECONDS = 5.0
        for k, v in overrides.items():
            setattr(self, k, v)


# ── factory selection ─────────────────────────────────────────────────────────


def test_default_returns_simulator(monkeypatch):
    """Flag off → in-process IBGatewayConnector (the safe default)."""
    import execution.ib_gateway_connector as conn_mod
    from execution.order_gateway_factory import build_order_gateway

    sentinel = object()
    monkeypatch.setattr(conn_mod, "IBGatewayConnector", lambda *a, **k: sentinel)
    gw = build_order_gateway(_Settings(IB_PAPER_BROKER_ENABLED=False), safety_layer=object())
    assert gw is sentinel


def test_flag_on_but_paper_off_stays_simulator(monkeypatch):
    """Real gateway requires BOTH the flag and paper mode; flag alone must not arm it."""
    import execution.ib_gateway_connector as conn_mod
    from execution.order_gateway_factory import build_order_gateway

    sentinel = object()
    monkeypatch.setattr(conn_mod, "IBGatewayConnector", lambda *a, **k: sentinel)
    gw = build_order_gateway(
        _Settings(IB_PAPER_BROKER_ENABLED=True, PAPER_TRADING=False), safety_layer=object()
    )
    assert gw is sentinel


def test_flag_on_returns_real_manager():
    """Flag on + paper → real IBGatewayManager, configured for the order leg."""
    from execution.ib_gateway import IBGatewayManager
    from execution.order_gateway_factory import build_order_gateway

    gw = build_order_gateway(_Settings(IB_PAPER_BROKER_ENABLED=True), safety_layer=object())
    assert isinstance(gw, IBGatewayManager)
    assert gw._config.port == 4002
    assert gw._config.client_id == 244  # order leg; data leg resolves to 245
    assert gw._config.account == "DU1234567"


def test_clientid_collision_raises(monkeypatch):
    """If the data leg would claim the order leg's clientId, refuse (IB evicts one socket)."""
    import data.market_data as md
    from execution.order_gateway_factory import build_order_gateway

    monkeypatch.setattr(md, "resolve_data_client_id", lambda cfg: 244)
    with pytest.raises(ValueError, match="clientId collision"):
        build_order_gateway(
            _Settings(IB_PAPER_BROKER_ENABLED=True, IBKR_CLIENT_ID=244), safety_layer=object()
        )


def test_live_port_rejected():
    """A live-trading port must be refused at construction (IBGatewayConfig guard)."""
    from execution.order_gateway_factory import build_order_gateway

    with pytest.raises(ValueError):
        build_order_gateway(
            _Settings(IB_PAPER_BROKER_ENABLED=True, IBKR_PORT=4001), safety_layer=object()
        )


# ── OrderRouter fail-loud guards for gateways missing optional methods ──────────
#
# NB: the real IBGatewayManager DOES implement place_bracket_order (native OCA
# bracket, ib_gateway.py:774) but does NOT implement modify_order. These stubs
# model a gateway *missing* a given optional method to exercise the defensive
# guards — they are not a faithful mirror of the real gateway's full surface.


class _GatewayMissingOptionalMethods:
    """Minimal gateway exposing only place_paper_order — lacks place_bracket_order/modify_order."""

    def is_connected(self):
        return True

    async def place_paper_order(self, **kwargs):
        return 1


async def test_route_bracket_order_fails_loud_when_gateway_lacks_bracket():
    """A gateway without place_bracket_order must fail loud (not opaque AttributeError)."""
    from execution.order_router import OrderRouter

    router = OrderRouter(ibkr=_GatewayMissingOptionalMethods())
    with pytest.raises(RuntimeError, match="place_bracket_order"):
        await router.route_bracket_order(
            symbol="MES", action="BUY", quantity=1, stop_loss=5690.0, take_profit=5710.0
        )


async def test_modify_order_returns_error_when_gateway_lacks_modify():
    """The real IBGatewayManager has no modify_order — OrderRouter returns a clear error dict."""
    from execution.order_router import OrderRouter

    router = OrderRouter(ibkr=_GatewayMissingOptionalMethods())
    out = await router.modify_order("abc", 5700.0)
    assert out["status"] == "error"
    assert "modify_order" in out["reason"]
