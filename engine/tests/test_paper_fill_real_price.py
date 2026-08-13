"""Paper fills must use REAL market prices, never a fabricated sentinel.

Root cause (2026-06-22 integrity audit): in paper mode ``get_quote`` returned a
hardcoded mock table whose *default* for any unlisted symbol was
``{"bid":100.00,"ask":100.10,"last":100.05}``. MGC was never in the table, so
every MGC paper fill booked at ~100.5 -- the same "100.5 sentinel" the
bars_repository / portfolio_router already guard against. Those phantom fills
poisoned ``paper_trades`` (e.g. MGC round-trips at 100.55->100.05, -$5 each,
an incoherent +$4,686 aggregate vs 4W/17L).

The fix: paper ``get_quote`` prefers a real price from the engine's
``MarketDataManager.get_tick_price`` waterfall (attached via
``attach_market_data``); falls back to the known-symbol mock table only when no
real price is available; and NEVER fabricates a ~100 quote. ``_submit_paper_order``
refuses to book a fill when there is no price basis at all (no real price, no
mock, no limit_price) instead of defaulting to 100.0.
"""

from __future__ import annotations

import pytest

from config import settings
from execution.ib_gateway_connector import IBGatewayConnector
from portfolio.tracker import PortfolioTracker
from risk.safety_layer import SafetyLayer


def _offline_simulated_cfg():
    return settings.model_copy(
        update={
            "LIVE_TRADING_ENABLED": False,
            "REQUIRE_HUMAN_APPROVAL": True,
            "PAPER_TRADING": True,
            "ALLOW_PAPER_SIMULATED_ORDERS": True,
            "MAX_SINGLE_ORDER_VALUE": 5_000_000.0,
            "MAX_POSITION_SIZE_PCT": 5.0,
        }
    )


class _FakeMarketData:
    """Minimal stand-in for MarketDataManager.get_tick_price."""

    def __init__(self, price: float, source: str = "ibkr") -> None:
        self._price = price
        self._source = source

    async def get_tick_price(self, symbol: str, is_futures: bool = False) -> dict:
        return {
            "last_price": self._price,
            "prev_close": None,
            "change_pct": None,
            "source": self._source,
        }


@pytest.mark.asyncio
async def test_paper_fill_uses_real_market_price_when_attached(tmp_path) -> None:
    """An attached market-data source drives the fill price for an otherwise
    unlisted symbol (MGC) -- so it fills near the REAL gold price, not 100.5."""
    cfg = _offline_simulated_cfg()
    tracker = PortfolioTracker(store_path=tmp_path / "book.jsonl")
    safety = SafetyLayer(cfg, pnl_monitor=None)
    conn = IBGatewayConnector(
        cfg, safety, portfolio_tracker=tracker, trades_file=tmp_path / "paper_trades.json"
    )
    conn.attach_market_data(_FakeMarketData(2300.0))
    assert await conn.connect() is True

    oid = await conn.place_paper_order("MGC", "BUY", 1, "MKT", None)
    assert oid is not None
    filled = conn._open_orders[oid]["filled_price"]
    # Within 2 ticks (0.25*2) of the real mark, and emphatically NOT the sentinel.
    assert filled > 1000.0
    assert abs(filled - 2300.0) <= 1.0


@pytest.mark.asyncio
async def test_paper_order_rejected_when_no_price_basis(tmp_path) -> None:
    """No real price, no mock entry, no limit_price -> reject rather than book a
    phantom 100.5 fill. This is the core anti-contamination guarantee."""
    cfg = _offline_simulated_cfg()
    tracker = PortfolioTracker(store_path=tmp_path / "book.jsonl")
    safety = SafetyLayer(cfg, pnl_monitor=None)
    conn = IBGatewayConnector(
        cfg, safety, portfolio_tracker=tracker, trades_file=tmp_path / "paper_trades.json"
    )  # no market data
    assert await conn.connect() is True

    oid = await conn.place_paper_order("MGC", "BUY", 1, "MKT", None)
    assert oid is None
    positions = await conn.get_positions()
    assert all(p.get("symbol") != "MGC" for p in positions)


@pytest.mark.asyncio
async def test_get_quote_unknown_symbol_returns_error_not_sentinel() -> None:
    """get_quote must never fabricate a ~100 quote for an unknown symbol."""
    cfg = _offline_simulated_cfg()
    safety = SafetyLayer(cfg, pnl_monitor=None)
    conn = IBGatewayConnector(cfg, safety)
    assert await conn.connect() is True

    q = await conn.get_quote("MGC")
    assert "error" in q
    assert q.get("last") != 100.05
    assert q.get("mid") != 100.05


@pytest.mark.asyncio
async def test_known_symbol_refuses_to_fill_without_manager(tmp_path) -> None:
    """INTENTIONALLY REVERSED 2026-07-21.

    This test previously asserted the OPPOSITE -- that a symbol present in the
    static mock table "still fills" when no market-data manager is attached,
    retained as a backward-compat guard "so existing paper flows and tests are
    unaffected". That guard *was* the phantom-price bug.

    ``_real_last_price`` returns None whenever no manager is attached or the feed
    is blind, and never raises, so the mock table was the DEFAULT path, not a
    rare degraded one: every MES paper fill booked at the frozen constant 5300.10
    while the real market traded near 7490. By 2026-07-21 that had produced 3,475
    fills in paper_trades.json with every week from W19-W30 only 0-4% sane, and a
    G2 readiness win rate of 2.3% that measured nothing but commission scratches.

    The correct contract: with no real price basis, REFUSE. The mock table now
    lives behind ``ALLOW_MOCK_QUOTES`` for fixtures only.
    See ``test_paper_fill_refuses_mock_price.py`` for the full contract.
    """
    cfg = _offline_simulated_cfg()
    tracker = PortfolioTracker(store_path=tmp_path / "book.jsonl")
    safety = SafetyLayer(cfg, pnl_monitor=None)
    conn = IBGatewayConnector(
        cfg, safety, portfolio_tracker=tracker, trades_file=tmp_path / "paper_trades.json"
    )
    assert await conn.connect() is True

    oid = await conn.place_paper_order("MES", "BUY", 1, "MKT", None)
    assert oid is None, "listed symbol filled with no price basis -- phantom path open"


@pytest.mark.asyncio
async def test_limit_order_fills_at_limit_when_no_price(tmp_path) -> None:
    """A limit price is a valid price basis even with no quote feed -- the order
    still fills (preserves the existing 'never lose an order with a price' path)."""
    cfg = _offline_simulated_cfg()
    tracker = PortfolioTracker(store_path=tmp_path / "book.jsonl")
    safety = SafetyLayer(cfg, pnl_monitor=None)
    conn = IBGatewayConnector(
        cfg, safety, portfolio_tracker=tracker, trades_file=tmp_path / "paper_trades.json"
    )
    assert await conn.connect() is True

    oid = await conn.place_paper_order("MGC", "BUY", 1, "LMT", limit_price=2310.0)
    assert oid is not None
    filled = conn._open_orders[oid]["filled_price"]
    assert abs(filled - 2310.0) <= 1.0
