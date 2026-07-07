"""
US-014 — End-to-end integration test for the EOD async market_price_fn bridge.

Existing test_eod_scheduler_price_snapshot.py uses MagicMock trackers and
verifies the snapshot shape. This file exercises the full real path:
  - Real PortfolioTracker with real open_trade / flatten_all_positions
  - Real EODScheduler with async market_price_fn
  - Verifies each position gets its symbol's live price (not breakeven)
  - Verifies multi-symbol concurrency: each symbol gets its own price
  - Verifies breakeven-fallback still logs ERROR when fetcher returns None

This is the test Friday EOD flatten (~15:10 CT today) will effectively run
against live prices — a failure here would have closed positions at
$0 P&L without surfacing.

Run with:
    cd engine
    .venv\\Scripts\\python.exe -m pytest tests/test_eod_integration_market_price_fn.py -v
"""
from __future__ import annotations

import logging
import os
import sys

import pytest

_TEST_ENV = {
    "API_KEY": "test-key",
    "POSTGRES_URL": "postgresql://test:test@localhost/test",
    "REDIS_URL": "redis://localhost",
    "POLYGON_API_KEY": "test-key",
    "ANTHROPIC_API_KEY": "test-key",
    "SCHWAB_APP_KEY": "test",
    "SCHWAB_APP_SECRET": "test",
    "FINNHUB_API_KEY": "test",
    "ALPACA_API_KEY": "test",
    "ALPACA_SECRET_KEY": "test",
    "TWILIO_ACCOUNT_SID": "test",
    "TWILIO_AUTH_TOKEN": "test",
    "TWILIO_WHATSAPP_FROM": "+1234567890",
    "WHATSAPP_TO": "+0987654321",
    "TRADINGVIEW_WEBHOOK_SECRET": "jarvis_test_secret_12345",
}
for _k, _v in _TEST_ENV.items():
    os.environ.setdefault(_k, _v)

_ENGINE_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if _ENGINE_ROOT not in sys.path:
    sys.path.insert(0, _ENGINE_ROOT)


@pytest.mark.asyncio
async def test_async_price_fn_produces_real_exit_prices_not_breakeven(tmp_path, caplog):
    """
    The golden-path integration: open 2 positions, flatten via async fetcher,
    every closed trade has exit_price == fetched price (not entry_price).
    """
    from portfolio.tracker import PortfolioTracker
    from schedulers.eod_scheduler import EODScheduler

    tracker = PortfolioTracker(store_path=tmp_path / "book.jsonl")

    tracker.open_trade(symbol="MES", action="buy", quantity=1, price=7100.0)
    tracker.open_trade(symbol="MNQ", action="buy", quantity=1, price=18000.0)

    # Async fetcher mimicking MarketDataManager.get_current_price — returns a
    # dict with "price" key in the real code path.
    async def fake_price_fn(symbol: str) -> dict:
        prices = {"MES": 7150.0, "MNQ": 18050.0}
        return {"price": prices[symbol]}

    scheduler = EODScheduler(
        db_manager=None,
        portfolio_tracker=tracker,
        whatsapp_notifier=None,
        learning_consolidator=None,
        capital_allocator=None,
        market_price_fn=fake_price_fn,
    )

    with caplog.at_level(logging.INFO):
        await scheduler.run_session_flatten()

    # After flatten, both positions should be closed at the fetched prices.
    assert len(tracker._open) == 0
    assert len(tracker._closed) == 2

    by_symbol = {t.symbol: t for t in tracker._closed}
    assert by_symbol["MES"].exit_price == 7150.0
    assert by_symbol["MNQ"].exit_price == 18050.0

    # MES P&L should be +$50 × $5/pt × 1 = +$250 (not $0 from breakeven)
    # We don't check exact P&L here since the multiplier depends on contract
    # specs, but we DO assert that exit_price differs from entry_price.
    assert by_symbol["MES"].exit_price != by_symbol["MES"].entry_price
    assert by_symbol["MNQ"].exit_price != by_symbol["MNQ"].entry_price

    # Snapshot log line should surface: "market-price snapshot built: 2/2 symbols resolved"
    assert any(
        "snapshot built" in rec.message and "2/2" in rec.message
        for rec in caplog.records
    )


@pytest.mark.asyncio
async def test_fetcher_returns_none_falls_back_to_breakeven_and_logs_error(tmp_path, caplog):
    """
    Regression: when the async fetcher returns None for a symbol, the position
    is still closed — but at entry_price (breakeven) — and flatten logs ERROR
    so the failure surfaces in logs (not silently producing corrupt P&L).
    """
    from portfolio.tracker import PortfolioTracker
    from schedulers.eod_scheduler import EODScheduler

    tracker = PortfolioTracker(store_path=tmp_path / "book.jsonl")
    tracker.open_trade(symbol="MES", action="buy", quantity=1, price=7100.0)

    async def failing_price_fn(symbol: str) -> None:
        return None

    scheduler = EODScheduler(
        db_manager=None,
        portfolio_tracker=tracker,
        whatsapp_notifier=None,
        learning_consolidator=None,
        capital_allocator=None,
        market_price_fn=failing_price_fn,
    )

    with caplog.at_level(logging.ERROR):
        await scheduler.run_session_flatten()

    # Position still closed — but at entry_price (breakeven)
    assert len(tracker._closed) == 1
    closed = tracker._closed[0]
    assert closed.exit_price == closed.entry_price  # breakeven fallback fired

    # The ERROR log must surface the breakeven-fallback count
    error_messages = [rec.message for rec in caplog.records if rec.levelno >= logging.ERROR]
    assert any("breakeven fallback" in msg.lower() for msg in error_messages), (
        f"Expected breakeven-fallback ERROR log, got: {error_messages}"
    )


@pytest.mark.asyncio
async def test_multi_symbol_each_gets_own_price_no_shared_closure_state(tmp_path):
    """
    Concurrency regression: ensure the snapshot closure resolves each symbol
    to ITS price, not a shared last-value bug. This catches the canonical
    for-loop-captures-last-variable mistake.
    """
    from portfolio.tracker import PortfolioTracker
    from schedulers.eod_scheduler import EODScheduler

    tracker = PortfolioTracker(store_path=tmp_path / "book.jsonl")
    tracker.open_trade(symbol="MES", action="buy", quantity=1, price=7100.0)
    tracker.open_trade(symbol="MNQ", action="buy", quantity=1, price=18000.0)
    tracker.open_trade(symbol="MCL", action="buy", quantity=1, price=75.00)

    # Each symbol gets a distinctive price so a shared-state bug would collapse
    # them into the same value.
    price_table = {"MES": 7150.0, "MNQ": 18050.0, "MCL": 75.50}

    async def price_fn(symbol: str) -> dict:
        return {"price": price_table[symbol]}

    scheduler = EODScheduler(
        db_manager=None,
        portfolio_tracker=tracker,
        whatsapp_notifier=None,
        learning_consolidator=None,
        capital_allocator=None,
        market_price_fn=price_fn,
    )

    await scheduler.run_session_flatten()

    by_symbol = {t.symbol: t.exit_price for t in tracker._closed}
    assert by_symbol == price_table, (
        f"Multi-symbol closure leaked state: got {by_symbol}, expected {price_table}"
    )


@pytest.mark.asyncio
async def test_no_open_positions_is_noop(tmp_path):
    """
    Nothing to flatten → no errors, snapshot has 0 entries, log says 0/0.
    """
    from portfolio.tracker import PortfolioTracker
    from schedulers.eod_scheduler import EODScheduler

    tracker = PortfolioTracker(store_path=tmp_path / "book.jsonl")

    async def price_fn(symbol: str) -> dict:
        return {"price": 100.0}

    scheduler = EODScheduler(
        db_manager=None,
        portfolio_tracker=tracker,
        whatsapp_notifier=None,
        learning_consolidator=None,
        capital_allocator=None,
        market_price_fn=price_fn,
    )

    await scheduler.run_session_flatten()
    assert len(tracker._closed) == 0
    assert len(tracker._open) == 0


@pytest.mark.asyncio
async def test_async_fetcher_exception_falls_back_to_none_price(tmp_path, caplog):
    """
    If the async fetcher raises (e.g., API timeout), the per-symbol price is
    set to None in the snapshot and the position falls back to breakeven.
    """
    from portfolio.tracker import PortfolioTracker
    from schedulers.eod_scheduler import EODScheduler

    tracker = PortfolioTracker(store_path=tmp_path / "book.jsonl")
    tracker.open_trade(symbol="MES", action="buy", quantity=1, price=7100.0)

    async def raising_fn(symbol: str) -> dict:
        raise TimeoutError("API unreachable")

    scheduler = EODScheduler(
        db_manager=None,
        portfolio_tracker=tracker,
        whatsapp_notifier=None,
        learning_consolidator=None,
        capital_allocator=None,
        market_price_fn=raising_fn,
    )

    with caplog.at_level(logging.WARNING):
        await scheduler.run_session_flatten()

    assert len(tracker._closed) == 1
    closed = tracker._closed[0]
    assert closed.exit_price == closed.entry_price  # breakeven
    # Warning log about snapshot failure should surface
    assert any(
        "price snapshot failed" in rec.message.lower()
        for rec in caplog.records
        if rec.levelno >= logging.WARNING
    )
