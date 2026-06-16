"""Tests for the read-only stored-bar audit CLI (scripts/bar_quality_fp_audit.py).

The audit must:
- return 0 when the *traded* symbols are clean (even if a non-traded symbol is dirty),
- return 1 when a traded symbol carries rejects,
- return 2 when the database is missing,
- never write to the database (it opens read-only).
"""

from __future__ import annotations

import sqlite3

from scripts.bar_quality_fp_audit import audit

_DDL = """
CREATE TABLE market_data_bars (
    symbol TEXT NOT NULL, interval TEXT NOT NULL, ts_utc TEXT NOT NULL,
    open REAL NOT NULL, high REAL NOT NULL, low REAL NOT NULL,
    close REAL NOT NULL, volume REAL, source TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (symbol, interval, ts_utc)
)
"""


def _row(symbol, ts, *, close=100.0, high=101.0, low=99.0, source="ibkr"):
    return (symbol, "1h", ts, 100.0, high, low, close, 1.0, source, "2026-06-16T00:00:00Z")


def _make_db(path, rows):
    conn = sqlite3.connect(str(path))
    conn.execute(_DDL)
    conn.executemany(
        "INSERT INTO market_data_bars VALUES (?,?,?,?,?,?,?,?,?,?)", rows
    )
    conn.commit()
    conn.close()


def test_traded_clean_returns_zero(tmp_path):
    db = tmp_path / "j.db"
    rows = [_row("MES", f"2026-06-15T{h:02d}:00:00Z") for h in range(20)]
    _make_db(db, rows)
    assert audit(str(db), {"MES"}) == 0


def test_non_traded_dirty_still_zero_for_traded(tmp_path):
    """A dirty non-traded symbol does not flip the traded exit code."""
    db = tmp_path / "j.db"
    rows = [_row("MES", f"2026-06-15T{h:02d}:00:00Z") for h in range(20)]
    # SPY (non-traded) carries a blocked-source contamination row.
    rows += [_row("SPY", "2026-06-15T00:00:00Z", source="smoke_test")]
    _make_db(db, rows)
    assert audit(str(db), {"MES"}) == 0


def test_traded_dirty_returns_one(tmp_path):
    db = tmp_path / "j.db"
    rows = [_row("MES", f"2026-06-15T{h:02d}:00:00Z") for h in range(20)]
    # One MES row from a blocked source -> traded contamination.
    rows += [_row("MES", "2026-06-16T00:00:00Z", source="smoke_test")]
    _make_db(db, rows)
    assert audit(str(db), {"MES"}) == 1


def test_range_explosion_on_traded_returns_one(tmp_path):
    db = tmp_path / "j.db"
    rows = [_row("MGC", f"2026-06-15T{h:02d}:00:00Z") for h in range(20)]
    # A bar whose high/low span is 100% of price -> RANGE_EXPLOSION.
    rows += [_row("MGC", "2026-06-16T00:00:00Z", high=200.0, low=100.0, close=150.0)]
    _make_db(db, rows)
    assert audit(str(db), {"MGC"}) == 1


def test_missing_db_returns_two(tmp_path):
    assert audit(str(tmp_path / "does_not_exist.db"), {"MES"}) == 2
