"""
Offline equivalents of the 3 tests in test_ib_gateway_connector_safety_wiring.py
that skip when IB Gateway is unreachable.

These tests use IBGatewayConnector (paper simulator) instead of IBGatewayManager,
so they pass without a real IB connection on port 4002.
"""

from __future__ import annotations

import pytest

from config import settings
from execution.ib_gateway_connector import IBGatewayConnector
from execution.ib_order_manager import IBOrderManager
from portfolio.tracker import PortfolioTracker
from risk.safety_layer import SafetyLayer


def _paper_offline_cfg():
    """Relaxed Tier-3 gates — paper simulated, no live IB required."""
    return settings.model_copy(
        update={
            "LIVE_TRADING_ENABLED": False,
            "REQUIRE_HUMAN_APPROVAL": False,
            "PAPER_TRADING": True,
            "ALLOW_PAPER_SIMULATED_ORDERS": True,
            # Order-routing fixtures: these exercise bracket/stop wiring with no
            # market-data manager attached, so they need the static quote table to
            # produce a fill at all. Production leaves this False and REFUSES to fill
            # without a real price basis (2026-07-21) -- see
            # tests/test_paper_fill_refuses_mock_price.py.
            "ALLOW_MOCK_QUOTES": True,
            "MAX_SINGLE_ORDER_VALUE": 500_000.0,
            "MAX_POSITION_SIZE_PCT": 5.0,
        }
    )


@pytest.mark.asyncio
async def test_place_paper_order_after_safety_no_double_reject(tmp_path) -> None:
    """SafetyLayer does not double-reject — offline equivalent of the IB integration test."""
    cfg = _paper_offline_cfg()
    store = tmp_path / "book.jsonl"
    tracker = PortfolioTracker(store_path=store)
    safety = SafetyLayer(cfg, pnl_monitor=None)
    conn = IBGatewayConnector(cfg, safety, portfolio_tracker=tracker)

    assert await conn.connect() is True
    assert conn.is_connected() is True
    safety.attach_ib_gateway(conn)

    out = await safety.submit_paper_order(
        symbol="MES",
        action="BUY",
        quantity=1,
        price=5300.0,
        order_type="MKT",
        limit_price=None,
    )

    assert out["approved"] is True
    assert out["routed_to_ib"] is True
    assert out.get("order_id")


@pytest.mark.asyncio
async def test_get_positions_list_shape_for_order_manager(tmp_path) -> None:
    """get_positions() returns a list — offline equivalent of the IB integration test."""
    cfg = _paper_offline_cfg()
    store = tmp_path / "book.jsonl"
    tracker = PortfolioTracker(store_path=store)
    safety = SafetyLayer(cfg, pnl_monitor=None)
    conn = IBGatewayConnector(cfg, safety, portfolio_tracker=tracker)

    await conn.connect()
    # Place an order to create a position
    await conn.place_paper_order("MCL", "BUY", 1, "MKT", None, None)

    positions = await conn.get_positions()
    assert isinstance(positions, list)
    if positions:
        row = positions[0]
        assert row.get("symbol")
        assert "position" in row


@pytest.mark.asyncio
async def test_ib_order_manager_uses_gateway(tmp_path) -> None:
    """IBOrderManager delegates to the gateway — offline equivalent of the IB integration test."""
    cfg = _paper_offline_cfg()
    store = tmp_path / "book.jsonl"
    tracker = PortfolioTracker(store_path=store)
    safety = SafetyLayer(cfg, pnl_monitor=None)
    conn = IBGatewayConnector(cfg, safety, portfolio_tracker=tracker)

    await conn.connect()
    safety.attach_ib_gateway(conn)

    om = IBOrderManager(safety, ib_gateway=conn, portfolio_tracker=tracker)
    res = await om.submit_order(
        symbol="MNQ",
        action="BUY",
        quantity=1,
        price=17500.0,
        order_type="MKT",
        limit_price=None,
    )

    assert res["approved"] is True
    assert res["routed_to_ib"] is True

    st = om.get_status()
    assert st["ib_gateway_connected"] is True
