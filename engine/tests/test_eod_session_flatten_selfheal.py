"""Regression test for the 2026-07-09 daily_pnl / session_flatten timing gap.

Root cause (found via the daily-pnl-reconcile loop's persistent RED alerts on
2026-07-07/07-08): the daily_pnl self-heal (reconcile_daily_pnl + repair on
drift) previously ran ONLY inside run_eod_snapshot, fired by APScheduler at
20:05 UTC. run_session_flatten force-closes any still-open positions 40
minutes later, at 20:45 UTC. Any trade closed in that window landed in the
closed paper_trades ledger with today's exit_time but was never counted by
daily_pnl until the NEXT day's EOD self-heal happened to rebuild the whole
table again -- a guaranteed one-day-stale drift on any day a position
survived to end of session (most trading days), which is exactly what the
daily-pnl-reconcile loop flagged every morning.

This test proves the fix: EODScheduler._reconcile_and_heal_daily_pnl is now
also called at the end of run_session_flatten, so a position closed ONLY by
the flatten job is reflected in daily_pnl the SAME day, with no run_eod_snapshot
call required.
"""

from __future__ import annotations

import os
import sys

import pytest

_TEST_ENV = {
    "API_KEY": "test-key",
    "POSTGRES_URL": "postgresql://test:test@localhost/test",
    "REDIS_URL": "redis://localhost",
    "POLYGON_API_KEY": "test-key",
    "ANTHROPIC_API_KEY": "test-key",
    "TRADINGVIEW_WEBHOOK_SECRET": "jarvis_test_secret_12345",
}
for _k, _v in _TEST_ENV.items():
    os.environ.setdefault(_k, _v)

_ENGINE_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if _ENGINE_ROOT not in sys.path:
    sys.path.insert(0, _ENGINE_ROOT)


@pytest.fixture()
def dbp(tmp_path):
    """Real DatabaseManager against a fresh on-disk SQLite file."""
    from database.schema import DatabaseManager

    path = str(tmp_path / "session_flatten_selfheal.db")
    manager = DatabaseManager(db_path=path)
    manager.initialize()
    return manager


@pytest.mark.asyncio
async def test_session_flatten_alone_heals_daily_pnl_same_day(tmp_path, dbp):
    """
    A position that is only closed by run_session_flatten (run_eod_snapshot
    is NEVER called in this test) must still produce a correct, reconciled
    daily_pnl row for today -- proving the self-heal no longer waits for
    tomorrow's EOD run to see trades closed after 20:05 UTC.
    """
    from portfolio.tracker import PortfolioTracker
    from schedulers.eod_scheduler import EODScheduler

    db = dbp
    tracker = PortfolioTracker(store_path=tmp_path / "book.jsonl", db_manager=db)
    tracker.open_trade(symbol="MES", action="buy", quantity=1, price=7100.0)

    async def price_fn(symbol: str) -> dict:
        return {"price": 7150.0}

    scheduler = EODScheduler(
        db_manager=db,
        portfolio_tracker=tracker,
        market_price_fn=price_fn,
    )

    # Sanity: before flatten, nothing is stored or closed yet.
    assert db.reconcile_daily_pnl()["ok"] is True
    assert db.get_daily_pnl() == []

    await scheduler.run_session_flatten()

    # The position was actually closed by the flatten job (not run_eod_snapshot).
    assert len(tracker._closed) == 1
    closed_pnl = tracker._closed[0].pnl

    # The self-heal fired inside run_session_flatten and wrote/repaired a
    # daily_pnl row TODAY -- with no run_eod_snapshot call anywhere in this test.
    rows = db.get_daily_pnl()
    assert len(rows) == 1, f"expected exactly one daily_pnl row, got {rows}"
    row = rows[0]
    assert row["total_trades"] == 1
    assert row["realized_pnl"] == pytest.approx(closed_pnl)
    assert row["starting_balance"] + row["realized_pnl"] == pytest.approx(row["ending_balance"])

    # Detective control is clean -- no drift left for tomorrow's reconcile loop.
    recon = db.reconcile_daily_pnl()
    assert recon["ok"] is True
    assert recon["drift_count"] == 0


@pytest.mark.asyncio
async def test_session_flatten_selfheal_is_noop_when_db_missing(tmp_path):
    """db_manager=None must not crash run_session_flatten (existing behavior)."""
    from portfolio.tracker import PortfolioTracker
    from schedulers.eod_scheduler import EODScheduler

    tracker = PortfolioTracker(store_path=tmp_path / "book.jsonl")
    tracker.open_trade(symbol="MES", action="buy", quantity=1, price=7100.0)

    async def price_fn(symbol: str) -> dict:
        return {"price": 7150.0}

    scheduler = EODScheduler(db_manager=None, portfolio_tracker=tracker, market_price_fn=price_fn)
    await scheduler.run_session_flatten()

    assert len(tracker._closed) == 1
