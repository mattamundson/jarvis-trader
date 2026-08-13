"""Regression tests for T1-14 (dashboard-integrity audit): breakeven-trade
classification must agree across engine/portfolio/tracker.py's
PortfolioTracker.get_performance() and engine/scripts/repair_daily_pnl.py's
build_rows().

Bug: tracker.py bucketed a $0.00 P&L trade as a LOSS (`pnl <= 0`), while
repair_daily_pnl.py excluded it from both the win and loss buckets (true
breakeven, `pnl > 0` / `pnl < 0`). Same underlying ledger row, two different
classifications depending which code path rendered it.

Convention (established elsewhere in the codebase, with a real prior incident
and regression test -- see engine/paper/validation_tracker.py's
_build_instrument_metrics and engine/tests/test_paper_validation.py's
test_breakeven_trades_do_not_count_as_losses): pnl == 0 is a true breakeven --
neither a win nor a loss -- but still counts toward the total trade count.
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from portfolio.tracker import PaperTrade, PortfolioTracker  # noqa: E402
from scripts.repair_daily_pnl import build_rows  # noqa: E402


def _make_closed_trade(pnl: float, trade_id: str) -> PaperTrade:
    now = datetime.now(timezone.utc).isoformat()
    return PaperTrade(
        trade_id=trade_id,
        symbol="MES",
        action="buy",
        quantity=1,
        entry_price=7100.0,
        entry_time=now,
        exit_price=7100.0 + pnl,
        exit_time=now,
        pnl=pnl,
        is_open=False,
    )


def _make_paper_trades_db(tmp_path: Path) -> sqlite3.Connection:
    """One win (+100), one loss (-50), one breakeven (0.0) closed the same day."""
    conn = sqlite3.connect(str(tmp_path / "test.db"))
    conn.execute(
        "CREATE TABLE paper_trades (trade_id TEXT, status TEXT, exit_time TEXT, pnl REAL)"
    )
    conn.executemany(
        "INSERT INTO paper_trades (trade_id, status, exit_time, pnl) VALUES (?,?,?,?)",
        [
            ("t1", "closed", "2026-07-01T10:00:00", 100.0),
            ("t2", "closed", "2026-07-01T11:00:00", -50.0),
            ("t3", "closed", "2026-07-01T12:00:00", 0.0),
        ],
    )
    conn.commit()
    return conn


@pytest.fixture()
def tracker(tmp_path: Path) -> PortfolioTracker:
    # store_path-only -> _db is None -> get_performance uses in-memory _closed.
    return PortfolioTracker(store_path=tmp_path / "audit.jsonl")


def test_tracker_breakeven_excluded_from_loss_bucket(tracker: PortfolioTracker) -> None:
    """A $0.00 trade must not dilute avg_loss -- it belongs in neither bucket."""
    tracker._closed.append(_make_closed_trade(100.0, "t1"))
    tracker._closed.append(_make_closed_trade(-50.0, "t2"))
    tracker._closed.append(_make_closed_trade(0.0, "t3"))

    perf = tracker.get_performance()

    assert perf["num_trades"] == 3, "breakeven still counts toward total trades"
    # Pre-fix: losses = [-50, 0.0] -> avg_loss = -25.0 (diluted by the breakeven).
    # Post-fix: losses = [-50] -> avg_loss = -50.0 (breakeven excluded).
    assert perf["avg_loss"] == pytest.approx(-50.0)
    assert perf["avg_win"] == pytest.approx(100.0)


def test_repair_daily_pnl_breakeven_excluded_from_both_buckets(tmp_path: Path) -> None:
    conn = _make_paper_trades_db(tmp_path)
    try:
        rows = build_rows(conn)
    finally:
        conn.close()

    assert len(rows) == 1
    row = rows[0]
    assert row["total_trades"] == 3
    assert row["winning_trades"] == 1
    assert row["losing_trades"] == 1
    # 1 win + 1 loss + 1 breakeven == 3 total; the breakeven trade is
    # unaccounted for in winning_trades + losing_trades by design.
    assert row["winning_trades"] + row["losing_trades"] == 2


def test_tracker_and_repair_daily_pnl_agree_on_breakeven_classification(
    tracker: PortfolioTracker, tmp_path: Path
) -> None:
    """T1-14: the same 3-trade ledger (1 win, 1 loss, 1 breakeven) must
    classify identically whether read through tracker.py's get_performance()
    or repair_daily_pnl.py's build_rows()."""
    tracker._closed.append(_make_closed_trade(100.0, "t1"))
    tracker._closed.append(_make_closed_trade(-50.0, "t2"))
    tracker._closed.append(_make_closed_trade(0.0, "t3"))
    perf = tracker.get_performance()

    conn = _make_paper_trades_db(tmp_path)
    try:
        row = build_rows(conn)[0]
    finally:
        conn.close()

    assert perf["num_trades"] == row["total_trades"] == 3
    assert row["losing_trades"] == 1
    # tracker.py's loss bucket (proxied via avg_loss, since get_performance()
    # does not expose a raw losing_trades count) must reflect exactly the one
    # real -50 loss, not the -50 diluted by a folded-in $0.00 breakeven.
    assert perf["avg_loss"] == pytest.approx(-50.0)


class _FakeDBBreakeven:
    """Minimal stand-in for the SQLite db_manager, exposing only the one
    method get_performance()'s DB-path calls: get_closed_trades(). Mirrors
    the real paper_trades row shape -- there is no 'realized_pnl' column on
    that table (see engine/database/migrations.py's paper_trades DDL), only
    'pnl'."""

    def get_closed_trades(self, limit: int = 10000):
        return [
            {"trade_id": "t1", "pnl": 100.0, "exit_time": "2026-07-01T10:00:00+00:00"},
            {"trade_id": "t2", "pnl": -50.0, "exit_time": "2026-07-01T11:00:00+00:00"},
            {"trade_id": "t3", "pnl": 0.0, "exit_time": "2026-07-01T12:00:00+00:00"},
        ]


def test_tracker_dbpath_breakeven_trade_not_dropped(tmp_path: Path) -> None:
    """DB-read path variant of T1-14: get_performance()'s SQLite branch reads
    ``t.pnl = row.get("pnl") or row.get("realized_pnl")``. Because 0.0 is
    falsy in Python, a genuine $0.00 breakeven trade falls through to
    row.get("realized_pnl") -- a key that does not exist on a paper_trades
    row -- yielding None. get_performance() then filters `t.pnl is not None`,
    so the breakeven trade is not merely misclassified (as T1-14 found for
    the in-memory path) -- it vanishes from num_trades entirely, silently
    undercounting total trades read from SQLite (the production code path,
    since PortfolioTracker prefers self._db when set).
    """
    tracker = PortfolioTracker(store_path=tmp_path / "audit.jsonl", db_manager=_FakeDBBreakeven())

    perf = tracker.get_performance()

    assert perf["num_trades"] == 3, (
        "breakeven trade (pnl=0.0) silently dropped by the SQLite read path's "
        "`row.get('pnl') or row.get('realized_pnl')` falsy-zero fallback"
    )
    assert perf["total_pnl"] == pytest.approx(50.0)
