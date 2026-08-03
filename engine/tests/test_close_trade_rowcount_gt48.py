"""GT-48 — close_trade()/close_paper_trade() must not silently succeed when
the DB layer's close_paper_trade() reports 0 rows updated.

Background: DatabaseManager.close_paper_trade() (engine/database/_mixins_trades.py)
returns True/False based on ``cur.rowcount == 1``; it does NOT raise on a
no-op UPDATE (stale trade_id, already closed elsewhere, or a race — it just
logs a warning). Previously PortfolioTracker.close_trade() and
close_paper_trade() (engine/portfolio/tracker.py) discarded that return
value and proceeded unconditionally to pop the trade from in-memory _open,
mark it closed, and append it to _closed — so the in-memory/JSONL state and
the SQLite ledger could silently diverge while the API still reported
"closed" (POST /portfolio/paper/trade/manual).

The fix: both call sites now capture the boolean return and raise
TradeCloseNotPersistedError instead of mutating in-memory state when the DB
reports 0 rows updated.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from portfolio.tracker import PortfolioTracker, TradeCloseNotPersistedError


class _FakeDB:
    """Minimal stand-in for DatabaseManager.close_paper_trade().

    Attached to the tracker AFTER open_trade() has already populated
    in-memory state via the db_manager=None (JSONL-only) path, so no other
    DatabaseManager method needs to be implemented here — only the close
    path is under test.
    """

    def __init__(self, returns: bool):
        self._returns = returns
        self.calls: list[dict] = []

    def close_paper_trade(self, trade_id, exit_price, exit_time=None, pnl=None):
        self.calls.append({"trade_id": trade_id, "exit_price": exit_price, "pnl": pnl})
        return self._returns


@pytest.fixture()
def tracker(tmp_path: Path) -> PortfolioTracker:
    return PortfolioTracker(store_path=tmp_path / "audit.jsonl")


# ── close_trade() ────────────────────────────────────────────────────────────


def test_close_trade_succeeds_when_db_reports_row_updated(tracker: PortfolioTracker) -> None:
    """Existing success path: DB returns True -> in-memory state updates normally."""
    tid = tracker.open_trade(symbol="MES", action="buy", quantity=1, price=5200.0)
    fake_db = _FakeDB(returns=True)
    tracker._db = fake_db

    closed = tracker.close_trade(tid, exit_price=5250.0)

    assert closed.is_open is False
    assert closed.exit_price == pytest.approx(5250.0)
    assert tid not in tracker._open
    assert any(t.trade_id == tid for t in tracker._closed)
    assert len(fake_db.calls) == 1


def test_close_trade_raises_when_db_updates_zero_rows(tracker: PortfolioTracker) -> None:
    """DB rowcount==0 (stale id / already closed / race) must raise, not
    silently succeed, and must leave in-memory _open untouched."""
    tid = tracker.open_trade(symbol="MES", action="buy", quantity=1, price=5200.0)
    fake_db = _FakeDB(returns=False)
    tracker._db = fake_db

    with pytest.raises(TradeCloseNotPersistedError):
        tracker.close_trade(tid, exit_price=5250.0)

    # The trade must still be open in memory — not incorrectly popped.
    assert tid in tracker._open
    assert tracker._open[tid].is_open is True
    assert tracker._open[tid].exit_price is None
    assert not any(t.trade_id == tid for t in tracker._closed)


# ── close_paper_trade() ──────────────────────────────────────────────────────


def test_close_paper_trade_succeeds_when_db_reports_row_updated(
    tracker: PortfolioTracker,
) -> None:
    """Existing success path: DB returns True -> in-memory state updates normally."""
    tid = tracker.open_trade(symbol="MGC", action="buy", quantity=1, price=4080.0)
    fake_db = _FakeDB(returns=True)
    tracker._db = fake_db

    closed = tracker.close_paper_trade(tid, exit_price=4090.0, pnl=95.0)

    assert closed.is_open is False
    assert closed.pnl == pytest.approx(95.0)
    assert tid not in tracker._open
    assert any(t.trade_id == tid for t in tracker._closed)
    assert len(fake_db.calls) == 1


def test_close_paper_trade_raises_when_db_updates_zero_rows(tracker: PortfolioTracker) -> None:
    """DB rowcount==0 (stale id / already closed / race) must raise, not
    silently succeed, and must leave in-memory _open untouched."""
    tid = tracker.open_trade(symbol="MGC", action="buy", quantity=1, price=4080.0)
    fake_db = _FakeDB(returns=False)
    tracker._db = fake_db

    with pytest.raises(TradeCloseNotPersistedError):
        tracker.close_paper_trade(tid, exit_price=4090.0, pnl=95.0)

    assert tid in tracker._open
    assert tracker._open[tid].is_open is True
    assert not any(t.trade_id == tid for t in tracker._closed)
