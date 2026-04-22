"""IBGatewayConnector — offline tests (no IB Gateway on 4002)."""

from __future__ import annotations

import pytest

from config import settings
from execution.ib_gateway_connector import IBGatewayConnector
from execution.ib_order_manager import IBOrderManager
from portfolio.tracker import PortfolioTracker
from risk.safety_layer import SafetyLayer


def _offline_simulated_cfg():
    """Tier-3 live off + explicit simulated-paper opt-in + relaxed size limits for tests."""
    return settings.model_copy(
        update={
            "LIVE_TRADING_ENABLED": False,
            "REQUIRE_HUMAN_APPROVAL": True,
            "PAPER_TRADING": True,
            "ALLOW_PAPER_SIMULATED_ORDERS": True,
            "MAX_SINGLE_ORDER_VALUE": 500_000.0,
            "MAX_POSITION_SIZE_PCT": 5.0,
        }
    )


@pytest.mark.asyncio
async def test_submit_paper_order_routes_to_connector(tmp_path) -> None:
    cfg = _offline_simulated_cfg()
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
async def test_get_positions_list_shape(tmp_path) -> None:
    cfg = _offline_simulated_cfg()
    store = tmp_path / "book.jsonl"
    tracker = PortfolioTracker(store_path=store)
    safety = SafetyLayer(cfg, pnl_monitor=None)
    conn = IBGatewayConnector(cfg, safety, portfolio_tracker=tracker)
    await conn.connect()
    await conn.place_paper_order("MCL", "BUY", 1, "MKT", None, None)

    positions = await conn.get_positions()
    assert isinstance(positions, list)
    assert len(positions) == 1
    row = positions[0]
    assert row.get("symbol")
    assert "position" in row
    assert row["position"] != 0


@pytest.mark.asyncio
async def test_ib_order_manager_with_connector(tmp_path) -> None:
    cfg = _offline_simulated_cfg()
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
