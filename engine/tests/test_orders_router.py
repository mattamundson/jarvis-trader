"""
Tests for engine/routers/orders_router.py (POST /orders/place, GET /orders/status).

Mounts ONLY the router on a minimal FastAPI app and injects fake OrderRouter /
SafetyLayer / DataManager module-level dependencies (mirrors main.py's
inject_dependencies() wiring at startup) so the tests exercise real router
logic without a live IB Gateway or Schwab connection.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import risk.entry_price_sanity as sanity_mod
import routers.orders_router as mod
from routers.orders_router import router


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    return app


def _client() -> TestClient:
    return TestClient(_app())


@pytest.fixture(autouse=True)
def _reset_module_state():
    """Every test starts from a clean (uninjected) slate and restores globals after."""
    original = (mod._order_router, mod._safety_layer, mod._data_manager)
    mod._order_router = None
    mod._safety_layer = None
    mod._data_manager = None
    yield
    mod._order_router, mod._safety_layer, mod._data_manager = original


# ── POST /orders/place ──────────────────────────────────────────────────────


def test_place_order_not_initialised_returns_503():
    """Before inject_dependencies() runs (engine still starting up), placing an
    order must fail closed with 503, never a silent no-op or 500."""
    r = _client().post(
        "/orders/place",
        json={"symbol": "MES", "direction": "BUY", "quantity": 1},
    )
    assert r.status_code == 503
    assert "not initialised" in r.json()["detail"].lower()


def test_place_futures_order_routes_through_safety_layer():
    """Futures symbols MUST go through SafetyLayer.submit_paper_order (the 6
    risk checks), never OrderRouter.route_order directly."""
    safety = MagicMock()
    safety.is_killed = False
    safety.submit_paper_order = AsyncMock(
        return_value={"status": "placed", "fill_id": "FILL-1", "broker": "ibkr"}
    )
    order_router = MagicMock()
    order_router.route_order = AsyncMock()
    mod.inject_dependencies(order_router, safety_layer=safety, data_manager=None)

    r = _client().post(
        "/orders/place",
        json={"symbol": "mes", "direction": "BUY", "quantity": 2, "order_type": "MARKET"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "placed"
    assert body["fill_id"] == "FILL-1"
    assert body["broker"] == "ibkr"
    assert body["symbol"] == "MES"  # normalized upper-case

    safety.submit_paper_order.assert_awaited_once()
    call_kwargs = safety.submit_paper_order.call_args.kwargs
    assert call_kwargs["symbol"] == "MES"
    assert call_kwargs["action"] == "BUY"
    assert call_kwargs["quantity"] == 2
    assert call_kwargs["order_type"] == "MKT"
    order_router.route_order.assert_not_awaited()


def test_place_equity_order_routes_through_order_router_with_side_key():
    """Regression guard for the documented Schwab bug fix: the order dict sent
    to OrderRouter must carry a 'side' key equal to action. Schwab's connector
    reads order.get('side', 'BUY'); a missing 'side' silently turns every SELL
    equity order into a BUY."""
    safety = MagicMock()
    safety.is_killed = False
    order_router = MagicMock()
    order_router.route_order = AsyncMock(
        return_value={"status": "placed", "fill_id": "SCHWAB-9", "broker": "schwab"}
    )
    mod.inject_dependencies(order_router, safety_layer=safety, data_manager=None)

    r = _client().post(
        "/orders/place",
        json={"symbol": "AAPL", "direction": "SELL", "quantity": 5, "order_type": "MARKET"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "placed"
    assert body["broker"] == "schwab"

    order_router.route_order.assert_awaited_once()
    order_dict = order_router.route_order.call_args.args[0]
    assert order_dict["action"] == "SELL"
    assert order_dict["side"] == "SELL"
    assert order_dict["strategy"] == "manual_dashboard"


def test_place_equity_order_blocked_by_kill_switch():
    safety = MagicMock()
    safety.is_killed = True
    order_router = MagicMock()
    order_router.route_order = AsyncMock()
    mod.inject_dependencies(order_router, safety_layer=safety, data_manager=None)

    r = _client().post(
        "/orders/place",
        json={"symbol": "SPY", "direction": "BUY", "quantity": 1, "order_type": "MARKET"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "blocked"
    assert body["error"] == "kill_switch_active"
    order_router.route_order.assert_not_awaited()


def test_place_order_limit_without_price_rejected_by_validation():
    """order_type=LIMIT without limit_price fails Pydantic validation (422)
    before any dependency is touched."""
    safety = MagicMock()
    order_router = MagicMock()
    order_router.route_order = AsyncMock()
    mod.inject_dependencies(order_router, safety_layer=safety, data_manager=None)

    r = _client().post(
        "/orders/place",
        json={"symbol": "MES", "direction": "BUY", "quantity": 1, "order_type": "LIMIT"},
    )
    assert r.status_code == 422
    order_router.route_order.assert_not_awaited()


def test_place_limit_order_garbage_price_rejected_by_sanity_check(monkeypatch):
    """Regression guard for the 2026-08-03 incident: a resting BUY 1 MES LMT
    @1000.00 against a ~$7,610 market (87% deviation) reached IB Gateway
    because this endpoint had zero price-sanity validation on a client-supplied
    limit_price. The sanity check must now reject it before SafetyLayer/IB."""
    safety = MagicMock()
    safety.is_killed = False
    safety.submit_paper_order = AsyncMock(return_value={"status": "placed", "fill_id": "SHOULD-NOT-FILL"})
    order_router = MagicMock()
    data_manager = MagicMock()
    mod.inject_dependencies(order_router, safety_layer=safety, data_manager=data_manager)

    monkeypatch.setattr(
        sanity_mod,
        "check_entry_price_sanity",
        AsyncMock(
            return_value=(
                False,
                "[MES] entry_price=1000.0 is 87.32 ATR units from market=7610.0; max allowed=1.00",
            )
        ),
    )

    r = _client().post(
        "/orders/place",
        json={
            "symbol": "MES",
            "direction": "BUY",
            "quantity": 1,
            "order_type": "LIMIT",
            "limit_price": 1000.0,
        },
    )
    assert r.status_code == 422, r.text
    assert "sanity" in r.json()["detail"].lower()
    safety.submit_paper_order.assert_not_awaited()


def test_place_limit_order_sane_price_passes_through(monkeypatch):
    """A plausible limit_price must not be blocked by the new sanity gate."""
    safety = MagicMock()
    safety.is_killed = False
    safety.submit_paper_order = AsyncMock(
        return_value={"status": "placed", "fill_id": "FILL-2", "broker": "ibkr"}
    )
    order_router = MagicMock()
    data_manager = MagicMock()
    mod.inject_dependencies(order_router, safety_layer=safety, data_manager=data_manager)

    monkeypatch.setattr(
        sanity_mod, "check_entry_price_sanity", AsyncMock(return_value=(True, ""))
    )

    r = _client().post(
        "/orders/place",
        json={
            "symbol": "MES",
            "direction": "BUY",
            "quantity": 1,
            "order_type": "LIMIT",
            "limit_price": 7600.0,
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "placed"
    safety.submit_paper_order.assert_awaited_once()


def test_place_limit_order_sanity_check_error_fails_closed(monkeypatch):
    """An exception while verifying the price must reject the order (fail
    closed), never fall through to submission."""
    safety = MagicMock()
    safety.is_killed = False
    safety.submit_paper_order = AsyncMock(return_value={"status": "placed"})
    order_router = MagicMock()
    data_manager = MagicMock()
    mod.inject_dependencies(order_router, safety_layer=safety, data_manager=data_manager)

    monkeypatch.setattr(
        sanity_mod,
        "check_entry_price_sanity",
        AsyncMock(side_effect=RuntimeError("data manager unreachable")),
    )

    r = _client().post(
        "/orders/place",
        json={
            "symbol": "MES",
            "direction": "BUY",
            "quantity": 1,
            "order_type": "LIMIT",
            "limit_price": 7600.0,
        },
    )
    assert r.status_code == 422, r.text
    safety.submit_paper_order.assert_not_awaited()


def test_place_market_order_skips_sanity_check(monkeypatch):
    """MARKET orders have no client-supplied entry price to validate against
    market — the sanity gate must not run (and must not require data_manager)."""
    safety = MagicMock()
    safety.is_killed = False
    safety.submit_paper_order = AsyncMock(
        return_value={"status": "placed", "fill_id": "FILL-3", "broker": "ibkr"}
    )
    order_router = MagicMock()
    mock_check = AsyncMock(return_value=(True, ""))
    monkeypatch.setattr(sanity_mod, "check_entry_price_sanity", mock_check)
    mod.inject_dependencies(order_router, safety_layer=safety, data_manager=MagicMock())

    r = _client().post(
        "/orders/place",
        json={"symbol": "MES", "direction": "BUY", "quantity": 1, "order_type": "MARKET"},
    )
    assert r.status_code == 200, r.text
    mock_check.assert_not_awaited()


def test_place_order_broker_not_connected_returns_503():
    """A RuntimeError from OrderRouter.route_order (broker not connected)
    surfaces as a 503, not an unhandled 500."""
    safety = MagicMock()
    safety.is_killed = False
    order_router = MagicMock()
    order_router.route_order = AsyncMock(side_effect=RuntimeError("Schwab not connected"))
    mod.inject_dependencies(order_router, safety_layer=safety, data_manager=None)

    r = _client().post(
        "/orders/place",
        json={"symbol": "SPY", "direction": "BUY", "quantity": 1, "order_type": "MARKET"},
    )
    assert r.status_code == 503
    assert "not connected" in r.json()["detail"].lower()


# ── GET /orders/status ──────────────────────────────────────────────────────


def test_order_status_not_initialised():
    r = _client().get("/orders/status")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "not_initialised"
    assert body["ibkr_connected"] is False
    assert body["schwab_connected"] is False
    assert body["futures_broker"] == "unavailable"
    assert body["equity_broker"] == "unavailable"


def test_order_status_reports_ibkr_and_schwab_connected_via_safety_layer():
    ib_gateway = MagicMock()
    ib_gateway.is_connected = MagicMock(return_value=True)
    safety = MagicMock()
    safety._ib_gateway = ib_gateway

    order_router = MagicMock()
    schwab = MagicMock()
    schwab.is_connected = True
    order_router.schwab = schwab

    mod.inject_dependencies(order_router, safety_layer=safety, data_manager=None)

    r = _client().get("/orders/status")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["ibkr_connected"] is True
    assert body["schwab_connected"] is True
    assert body["futures_broker"] == "ibkr"
    assert body["equity_broker"] == "schwab"
    assert body["source"] == "execution_connector"
