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
    """Relaxed Tier-3 gates — paper simulated, no live IB required.

    ``ALLOW_MOCK_QUOTES`` is required (2026-07-21, see
    ``test_ib_gateway_connector_offline.py``): no market-data manager is
    attached here, so the static quote table is needed to produce a fill at
    all. Production leaves this False and refuses to fill without a real
    price basis -- see ``test_paper_fill_refuses_mock_price.py``.
    """
    return settings.model_copy(
        update={
            "LIVE_TRADING_ENABLED": False,
            "REQUIRE_HUMAN_APPROVAL": False,
            "PAPER_TRADING": True,
            "ALLOW_PAPER_SIMULATED_ORDERS": True,
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
    # Symbol was MNQ; switched to MES (PRB-03/PRB-22, 2026-07-29). MNQ is
    # both a DO_NOT_TRADE_SYMBOLS halt-list member (backtest/signals.py) and
    # carries paper_config.enabled=False (backtest/paper_config.py) — since
    # check_order() now gates on both directly, it's rejected before ever
    # reaching the IBOrderManager/connector plumbing this test exists to
    # exercise. MES is unaffected by either check and preserves the original
    # intent.
    res = await om.submit_order(
        symbol="MES",
        action="BUY",
        quantity=1,
        price=5300.0,
        order_type="MKT",
        limit_price=None,
    )

    assert res["approved"] is True
    assert res["routed_to_ib"] is True

    st = om.get_status()
    assert st["ib_gateway_connected"] is True
