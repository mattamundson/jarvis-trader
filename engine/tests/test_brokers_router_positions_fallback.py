"""Regression tests for the 2026-08-10 /brokers/positions read-only fallback.

Origin: _ibkr is the order-routing object (the real IBGatewayManager only
when IB_PAPER_BROKER_ENABLED is set; an in-process simulator otherwise).
With that flag off, GET /brokers/positions previously had NO live check
against the real broker at all -- a real position placed outside the
engine's own order path (a manually-run script) was invisible no matter
what. These tests pin the merge behavior: fall back to the data leg's
always-on connection (_real_ibkr) when the order-routing side can't supply
real data, and report which source actually served the response.

Run:
    cd engine
    .venv\\Scripts\\python.exe -m pytest tests/test_brokers_router_positions_fallback.py -v
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

import routers.brokers_router as brokers_router


@pytest.fixture(autouse=True)
def _reset_module_state():
    """brokers_router keeps connector refs as module globals -- isolate each test."""
    saved = (
        brokers_router._ibkr,
        brokers_router._real_ibkr,
        brokers_router._schwab,
        brokers_router._tracker,
    )
    yield
    (
        brokers_router._ibkr,
        brokers_router._real_ibkr,
        brokers_router._schwab,
        brokers_router._tracker,
    ) = saved


def _ibkr_position(symbol: str, qty: float) -> dict:
    return {
        "symbol": symbol,
        "sec_type": "FUT",
        "exchange": "CME",
        "currency": "USD",
        "position": qty,
        "avg_cost": 100.0,
        "account": "DUR375089",
    }


@pytest.mark.asyncio
async def test_order_routing_connected_uses_order_routing_source():
    order_router = MagicMock()
    order_router.is_connected.return_value = True
    order_router.get_positions = AsyncMock(return_value=[_ibkr_position("MES", 2.0)])
    order_router.positions_stale.return_value = False

    brokers_router._ibkr = order_router
    brokers_router._real_ibkr = None
    brokers_router._schwab = None
    brokers_router._tracker = None

    resp = await brokers_router.get_broker_positions()

    assert resp["ibkr"]["connected"] is True
    assert resp["ibkr"]["source"] == "order_routing"
    assert resp["ibkr"]["positions"][0]["symbol"] == "MES"
    order_router.get_positions.assert_awaited_once()


@pytest.mark.asyncio
async def test_order_routing_disconnected_falls_back_to_read_only_data_leg():
    """IB_PAPER_BROKER_ENABLED=False case: _ibkr is a disconnected/simulator
    no-op, but the data leg still sees the real 2026-08-10 MES position."""
    order_router = MagicMock()
    order_router.is_connected.return_value = False

    data_leg = MagicMock()
    data_leg.is_connected = True  # property, not a method, on IBKRDataConnector
    data_leg.get_positions = AsyncMock(return_value=[_ibkr_position("MES", 2.0)])
    data_leg.positions_stale.return_value = False

    brokers_router._ibkr = order_router
    brokers_router._real_ibkr = data_leg
    brokers_router._schwab = None
    brokers_router._tracker = None

    resp = await brokers_router.get_broker_positions()

    assert resp["ibkr"]["connected"] is True  # queryable via the fallback
    assert resp["ibkr"]["source"] == "read_only_data_leg"
    assert resp["ibkr"]["positions"][0]["symbol"] == "MES"
    data_leg.get_positions.assert_awaited_once()


@pytest.mark.asyncio
async def test_neither_side_queryable_reports_none_source_and_blind_reconciliation():
    order_router = MagicMock()
    order_router.is_connected.return_value = False

    brokers_router._ibkr = order_router
    brokers_router._real_ibkr = None
    brokers_router._schwab = None
    brokers_router._tracker = None

    resp = await brokers_router.get_broker_positions()

    assert resp["ibkr"]["connected"] is False
    assert resp["ibkr"]["source"] == "none"
    assert resp["ibkr"]["positions"] == []
    assert resp["reconciliation"]["health"] == "blind"


@pytest.mark.asyncio
async def test_stale_flag_from_read_only_fallback_is_surfaced():
    order_router = MagicMock()
    order_router.is_connected.return_value = False

    data_leg = MagicMock()
    data_leg.is_connected = True
    data_leg.get_positions = AsyncMock(return_value=[])
    data_leg.positions_stale.return_value = True

    brokers_router._ibkr = order_router
    brokers_router._real_ibkr = data_leg
    brokers_router._schwab = None
    brokers_router._tracker = None

    resp = await brokers_router.get_broker_positions()

    assert resp["ibkr"]["source"] == "read_only_data_leg"
    assert resp["ibkr"]["positions_stale"] is True
