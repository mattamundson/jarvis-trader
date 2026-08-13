"""IBGatewayConnector — offline tests (no IB Gateway on 4002)."""

from __future__ import annotations

import pytest

from config import settings
from execution.ib_gateway_connector import IBGatewayConnector
from execution.ib_order_manager import IBOrderManager
from portfolio.tracker import PortfolioTracker
from risk.safety_layer import SafetyLayer


def _offline_simulated_cfg():
    """Tier-3 live off + explicit simulated-paper opt-in + relaxed size limits for tests.

    ``ALLOW_MOCK_QUOTES`` is required here (2026-07-21): these tests exercise the
    order-routing plumbing with no market-data manager attached, so they need the
    static quote table to produce a fill at all. Production leaves this False and
    REFUSES to fill without a real price basis -- see
    ``test_paper_fill_refuses_mock_price.py``.
    """
    return settings.model_copy(
        update={
            "LIVE_TRADING_ENABLED": False,
            "REQUIRE_HUMAN_APPROVAL": True,
            "PAPER_TRADING": True,
            "ALLOW_PAPER_SIMULATED_ORDERS": True,
            "ALLOW_MOCK_QUOTES": True,
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
    conn = IBGatewayConnector(
        cfg, safety, portfolio_tracker=tracker, trades_file=tmp_path / "paper_trades.json"
    )
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
    conn = IBGatewayConnector(
        cfg, safety, portfolio_tracker=tracker, trades_file=tmp_path / "paper_trades.json"
    )
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
    conn = IBGatewayConnector(
        cfg, safety, portfolio_tracker=tracker, trades_file=tmp_path / "paper_trades.json"
    )
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


@pytest.mark.asyncio
async def test_get_options_greeks_returns_unavailable_not_attribute_error() -> None:
    """Regression: _gateway is never assigned on the connector, so a bare
    `if self._gateway:` raised AttributeError on every call instead of the
    intended graceful 'Gateway unavailable' error. Must return the error dict."""
    cfg = _offline_simulated_cfg()
    safety = SafetyLayer(cfg, pnl_monitor=None)
    conn = IBGatewayConnector(cfg, safety)
    assert await conn.connect() is True

    out = await conn.get_options_greeks("MES")  # must not raise AttributeError
    assert out == {"error": "Gateway unavailable"}


@pytest.mark.asyncio
async def test_paper_order_survives_get_quote_raise(tmp_path) -> None:
    """Regression: a transient ``get_quote()`` *exception* (not just an
    error-dict) must not abort the simulated fill. The no-quote branch already
    falls back to ``limit_price or 100.0``; an unguarded raise instead propagated
    out of ``_submit_paper_order`` and lost the order entirely. The fill must
    proceed at the fallback price."""
    cfg = _offline_simulated_cfg()
    store = tmp_path / "book.jsonl"
    tracker = PortfolioTracker(store_path=store)
    safety = SafetyLayer(cfg, pnl_monitor=None)
    conn = IBGatewayConnector(
        cfg, safety, portfolio_tracker=tracker, trades_file=tmp_path / "paper_trades.json"
    )
    assert await conn.connect() is True

    async def _boom(_symbol: str) -> dict:
        raise RuntimeError("quote feed down")

    conn.get_quote = _boom  # type: ignore[assignment]

    # Without the guard this call raises RuntimeError; with it, the order fills.
    order_id = await conn.place_paper_order("MES", "BUY", 1, "MKT", limit_price=5300.0)
    assert order_id is not None
    assert isinstance(order_id, str)

    positions = await conn.get_positions()
    assert any(p.get("symbol") == "MES" for p in positions)
