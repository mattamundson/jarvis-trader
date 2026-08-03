"""Paper fills must REFUSE when there is no real price basis -- even for symbols
that happen to sit in the static mock table.

Root cause (2026-07-21 forensics): the 2026-06-22 integrity fix removed the
~100.05 sentinel for *unlisted* symbols but deliberately preserved the mock table
for *listed* ones ("backward-compat guard"). ``_real_last_price`` returns None
whenever no MarketDataManager is attached or the feed fails -- and it never
raises -- so every paper fill for a listed symbol silently booked at a frozen
2024-era constant:

    mock_quotes = {"MES": {... "last": 5300.10 ...}, "MCL": {... 82.60 ...}, ...}

Measured impact before the fix: ``engine/data/paper_trades.json`` held 3,475
fills / 1,402 round-trips in which EVERY week from 2026-W19 through W30 was
0-4% sane -- MES booked at a median 5300.38 against a real market near 7490.
Because both legs of a round-trip drew the same frozen constant, trades closed
0-2 ticks apart: 161 of 163 losses in the 14-day window were under $10,
clustering on four exact values (-0.12 commission-only x43, -1.37 x41,
-2.62 x53, -3.75 x10). That mechanical signature drove the G2 readiness gate to
report a 2.3% win rate. The occasional -$11,078 row was a *mixed* round-trip
(one real leg, one phantom leg) -- the only kind the phantom detector ever saw.

The contract these tests pin down:
  1. No real price + mocks not explicitly enabled -> get_quote errors, and the
     order is REFUSED rather than booked at a fabricated price.
  2. A quote is always tagged with its provenance, so a fabricated price can
     never be mistaken for a live one downstream.
  3. The mock table remains available to tests/fixtures, but only behind an
     explicit opt-in (``ALLOW_MOCK_QUOTES``), never by default.

A paper system that declines to trade while blind is correct. One that invents a
price is worse than useless, because it manufactures a track record.
"""

from __future__ import annotations

import pytest

from config import settings
from execution.ib_gateway_connector import IBGatewayConnector
from portfolio.tracker import PortfolioTracker
from risk.safety_layer import SafetyLayer

# The exact constant that poisoned the ledger.
PHANTOM_MES_PRICE = 5300.10


def _paper_cfg(**overrides):
    base = {
        "LIVE_TRADING_ENABLED": False,
        "REQUIRE_HUMAN_APPROVAL": True,
        "PAPER_TRADING": True,
        "ALLOW_PAPER_SIMULATED_ORDERS": True,
        "MAX_SINGLE_ORDER_VALUE": 5_000_000.0,
        "MAX_POSITION_SIZE_PCT": 5.0,
    }
    base.update(overrides)
    return settings.model_copy(update=base)


class _FakeMarketData:
    def __init__(self, price: float) -> None:
        self._price = price

    async def get_tick_price(self, symbol: str, is_futures: bool = False) -> dict:
        return {"last_price": self._price, "source": "ibkr"}


class _DeadMarketData:
    """A feed that is attached but blind -- the real production failure mode."""

    async def get_tick_price(self, symbol: str, is_futures: bool = False) -> dict:
        return {"last_price": None, "source": "unavailable"}


@pytest.mark.asyncio
async def test_listed_symbol_quote_errors_without_real_price() -> None:
    """MES is in the mock table, but with mocks off and no feed it must ERROR."""
    conn = IBGatewayConnector(_paper_cfg(), SafetyLayer(_paper_cfg(), pnl_monitor=None))
    assert await conn.connect() is True

    q = await conn.get_quote("MES")
    assert "error" in q, f"expected refusal, got a quote: {q}"
    assert q.get("last") != PHANTOM_MES_PRICE


@pytest.mark.asyncio
async def test_listed_symbol_order_refused_without_real_price(tmp_path) -> None:
    """The core anti-contamination guarantee: no price basis -> no fill booked."""
    cfg = _paper_cfg()
    conn = IBGatewayConnector(
        cfg, SafetyLayer(cfg, pnl_monitor=None),
        portfolio_tracker=PortfolioTracker(store_path=tmp_path / "book.jsonl"),
    )
    assert await conn.connect() is True

    oid = await conn.place_paper_order("MES", "BUY", 1, "MKT", None)
    assert oid is None, "MES filled with no price basis -- phantom path still open"
    positions = await conn.get_positions()
    assert all(p.get("symbol") != "MES" for p in positions)


@pytest.mark.asyncio
async def test_attached_but_blind_feed_also_refuses(tmp_path) -> None:
    """A feed that returns last_price=None must behave like no feed at all.

    This is the real production shape: the manager IS attached, but the
    TradingView tier is a dead stub and the Redis fabric is stale, so
    get_tick_price yields nothing usable.
    """
    cfg = _paper_cfg()
    conn = IBGatewayConnector(
        cfg, SafetyLayer(cfg, pnl_monitor=None),
        portfolio_tracker=PortfolioTracker(store_path=tmp_path / "book.jsonl"),
    )
    conn.attach_market_data(_DeadMarketData())
    assert await conn.connect() is True

    assert "error" in await conn.get_quote("MES")
    assert await conn.place_paper_order("MES", "BUY", 1, "MKT", None) is None


@pytest.mark.asyncio
async def test_real_price_is_tagged_live_and_used() -> None:
    """The healthy path is unchanged and explicitly provenance-tagged."""
    cfg = _paper_cfg()
    conn = IBGatewayConnector(cfg, SafetyLayer(cfg, pnl_monitor=None))
    conn.attach_market_data(_FakeMarketData(7490.25))
    assert await conn.connect() is True

    q = await conn.get_quote("MES")
    assert "error" not in q
    assert q["source"] == "live"
    assert abs(q["last"] - 7490.25) < 0.01


@pytest.mark.asyncio
async def test_mock_quote_available_behind_opt_in_and_tagged_mock() -> None:
    """Fixtures may still opt into the mock table -- but it must self-identify."""
    cfg = _paper_cfg(ALLOW_MOCK_QUOTES=True)
    conn = IBGatewayConnector(cfg, SafetyLayer(cfg, pnl_monitor=None))
    assert await conn.connect() is True

    q = await conn.get_quote("MES")
    assert "error" not in q
    assert q["source"] == "mock", "a fabricated quote must never look live"
    assert q["last"] == PHANTOM_MES_PRICE


@pytest.mark.asyncio
async def test_limit_price_remains_a_valid_basis(tmp_path) -> None:
    """An explicit limit price is a real basis -- it is not fabricated, so it stays."""
    cfg = _paper_cfg()
    conn = IBGatewayConnector(
        cfg, SafetyLayer(cfg, pnl_monitor=None),
        portfolio_tracker=PortfolioTracker(store_path=tmp_path / "book.jsonl"),
    )
    assert await conn.connect() is True

    oid = await conn.place_paper_order("MES", "BUY", 1, "LMT", limit_price=7490.0)
    assert oid is not None
    assert abs(conn._open_orders[oid]["filled_price"] - 7490.0) <= 1.0
