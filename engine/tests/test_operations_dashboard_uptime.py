"""Regression: the 7-day uptime strip must read the real pnl_snapshots column.

_get_uptime_7d queried `date(recorded_at)`, but pnl_snapshots has no
`recorded_at` column (its date column is literally named `date`; `recorded_at`
lives on a different table). The query raised `OperationalError: no such column`
on EVERY call, was swallowed by `except Exception`, and the strip silently
showed all-DOWN (7x False) even when the engine had written a snapshot that day.
These tests pin the correct column so a present snapshot reads as UP.
"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta

from api import operations_dashboard as od


def _make_db(tmp_path, dates):
    """Create a pnl_snapshots table (real schema) with a row per date in `dates`."""
    db = tmp_path / "jarvis_trader.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        """
        CREATE TABLE pnl_snapshots (
            date TEXT NOT NULL,
            daily_pnl REAL NOT NULL DEFAULT 0.0,
            portfolio_equity REAL NOT NULL DEFAULT 0.0,
            peak_equity REAL NOT NULL DEFAULT 0.0,
            consecutive_losses INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL DEFAULT (datetime('now','utc')),
            PRIMARY KEY (date)
        )
        """
    )
    for d in dates:
        conn.execute(
            "INSERT INTO pnl_snapshots(date, daily_pnl, portfolio_equity, "
            "peak_equity, consecutive_losses, updated_at) VALUES (?,0,1e4,1e4,0,?)",
            (d, d),
        )
    conn.commit()
    conn.close()
    return db


def test_present_snapshot_reads_as_up(tmp_path, monkeypatch):
    today = date.today().isoformat()
    db = _make_db(tmp_path, [today])
    monkeypatch.setattr(od, "_DB_PATH", db)

    strip = od._get_uptime_7d()
    assert len(strip) == 7
    # oldest-first; today is the last element and MUST be True (the bug made it False).
    assert strip[-1] is True
    assert any(strip), "all-False strip means the column-name regression is back"


def test_absent_snapshot_reads_as_down(tmp_path, monkeypatch):
    # A snapshot 10 days ago is outside the 7-day window -> all False (honest DOWN).
    old = (date.today() - timedelta(days=10)).isoformat()
    db = _make_db(tmp_path, [old])
    monkeypatch.setattr(od, "_DB_PATH", db)

    assert od._get_uptime_7d() == [False] * 7


def test_partial_week(tmp_path, monkeypatch):
    today = date.today()
    present = [(today - timedelta(days=i)).isoformat() for i in (0, 2)]
    db = _make_db(tmp_path, present)
    monkeypatch.setattr(od, "_DB_PATH", db)

    strip = od._get_uptime_7d()  # oldest-first index 6..0 -> days ago 6..0
    assert strip[-1] is True  # today (0 days ago)
    assert strip[-3] is True  # 2 days ago
    assert strip[-2] is False  # 1 day ago (no snapshot)
