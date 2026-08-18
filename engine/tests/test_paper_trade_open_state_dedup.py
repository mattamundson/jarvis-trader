"""Open-state write guard for insert_paper_trade.

The idempotency_key guard only collapses re-submissions inside a 5-second key
window. Re-logs of a still-open position arrive 42s-1h apart (an hourly review
job re-emits every open position), so they receive DISTINCT idempotency keys and
would each mint a fresh open row — the ~6x paper_trades over-count.

These tests pin the second guard: any existing status='open' row for the same
(symbol, side) IS this fill, so a re-log with a different key collapses to the
existing row, while a genuine RE-ENTRY after the position closes is allowed.
"""

import sqlite3
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from database._mixins_trades import TradesMixin  # noqa: E402


class _FakeLock:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


class _FakeDB(TradesMixin):
    """Minimal DatabaseManager satisfying TradesMixin against real SQLite."""

    def __init__(self, path):
        self._db_path = path
        self._lock = _FakeLock()
        conn = self._connect()
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_trades (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_id        TEXT    NOT NULL UNIQUE,
                symbol          TEXT    NOT NULL,
                side            TEXT    NOT NULL,
                quantity        REAL    NOT NULL,
                entry_price     REAL    NOT NULL,
                exit_price      REAL,
                entry_time      TEXT    NOT NULL,
                exit_time       TEXT,
                pnl             REAL,
                status          TEXT    NOT NULL DEFAULT 'open',
                stop_loss       REAL,
                take_profit     REAL,
                strategy_params TEXT,
                notes           TEXT    DEFAULT '',
                idempotency_key TEXT    NOT NULL,
                strategy_id     TEXT
            )
            """
        )
        conn.commit()
        conn.close()

    def _connect(self):
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _count(self, **where):
        clause = " AND ".join(f"{k}=?" for k in where)
        sql = "SELECT COUNT(*) n FROM paper_trades"
        if clause:
            sql += " WHERE " + clause
        conn = self._connect()
        try:
            return conn.execute(sql, tuple(where.values())).fetchone()["n"]
        finally:
            conn.close()


def test_relog_of_open_position_collapses_to_one_row(tmp_path):
    """Two re-emits of the same open (symbol, side) with DIFFERENT keys -> 1 row."""
    db = _FakeDB(str(tmp_path / "guard.db"))
    id1 = db.insert_paper_trade(
        trade_id=str(uuid.uuid4()),
        symbol="MES",
        side="buy",
        quantity=2.0,
        entry_price=7398.55,
        idempotency_key="key-window-A",  # first submission
    )
    # Same open position re-logged ~1h later -> a DIFFERENT idempotency key, so
    # the key guard does NOT catch it; the open-state guard must.
    id2 = db.insert_paper_trade(
        trade_id=str(uuid.uuid4()),
        symbol="MES",
        side="buy",
        quantity=2.0,
        entry_price=7401.10,  # price drifted — must not matter
        idempotency_key="key-window-B",
    )
    assert id1 == id2
    assert db._count(symbol="MES", side="buy", status="open") == 1
    assert db._count() == 1


def test_reentry_after_close_is_allowed(tmp_path):
    """Close the position, then a genuine re-entry -> TWO distinct rows."""
    db = _FakeDB(str(tmp_path / "reentry.db"))
    tid1 = str(uuid.uuid4())
    db.insert_paper_trade(
        trade_id=tid1,
        symbol="MGC",
        side="sell",
        quantity=1.0,
        entry_price=5591.0,
        idempotency_key="entry-1",
    )
    assert db.close_paper_trade(tid1, exit_price=5580.0, pnl=110.0) is True

    # Position is flat now — a new sell is a legitimate re-entry, not a re-log.
    id2 = db.insert_paper_trade(
        trade_id=str(uuid.uuid4()),
        symbol="MGC",
        side="sell",
        quantity=1.0,
        entry_price=5570.0,
        idempotency_key="entry-2",
    )
    assert id2 is not None
    assert db._count(symbol="MGC", side="sell") == 2
    assert db._count(symbol="MGC", side="sell", status="open") == 1


def test_distinct_symbols_and_sides_not_collapsed(tmp_path):
    """The guard is per (symbol, side): different pairs each get their own row."""
    db = _FakeDB(str(tmp_path / "distinct.db"))
    db.insert_paper_trade(
        trade_id=str(uuid.uuid4()), symbol="MES", side="buy",
        quantity=1.0, entry_price=7400.0, idempotency_key="a",
    )
    db.insert_paper_trade(
        trade_id=str(uuid.uuid4()), symbol="MES", side="sell",
        quantity=1.0, entry_price=7400.0, idempotency_key="b",
    )
    db.insert_paper_trade(
        trade_id=str(uuid.uuid4()), symbol="MGC", side="buy",
        quantity=1.0, entry_price=5591.0, idempotency_key="c",
    )
    assert db._count() == 3
