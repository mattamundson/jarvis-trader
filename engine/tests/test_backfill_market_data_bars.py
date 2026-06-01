"""
Tests for engine.scripts.backfill_market_data_bars.

Covers:
  - test_backfill_loads_csv: given a fixture CSV, loads expected row count
  - test_backfill_idempotent: running twice yields same total as first run (not 2x)
"""

from __future__ import annotations

import csv
import sqlite3
import sys
import tempfile
from pathlib import Path

import pandas as pd
import pytest

# Make engine root importable when pytest runs from the engine directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.backfill_market_data_bars import _load_csv, backfill_symbol

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_db(path: Path) -> Path:
    """Create a minimal SQLite DB with the market_data_bars table."""
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS market_data_bars (
            symbol      TEXT NOT NULL,
            interval    TEXT NOT NULL,
            ts_utc      TEXT NOT NULL,
            open        REAL NOT NULL,
            high        REAL NOT NULL,
            low         REAL NOT NULL,
            close       REAL NOT NULL,
            volume      REAL,
            source      TEXT NOT NULL,
            fetched_at  TEXT NOT NULL,
            PRIMARY KEY (symbol, interval, ts_utc)
        )
        """
    )
    conn.commit()
    conn.close()
    return path


def _make_fixture_csv(path: Path, n_rows: int = 10, symbol: str = "MES") -> Path:
    """Write a minimal 1h OHLCV CSV to *path* with *n_rows* rows."""
    rows = []
    for i in range(n_rows):
        ts = f"2026-01-01 {i:02d}:00:00"
        rows.append([ts, 5300.0 + i, 5310.0 + i, 5290.0 + i, 5305.0 + i, 1000.0 + i * 10])

    with open(path, "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["timestamp", "open", "high", "low", "close", "volume"])
        writer.writerows(rows)

    return path


def _count_rows(db_path: Path, symbol: str = "MES") -> int:
    conn = sqlite3.connect(str(db_path))
    (count,) = conn.execute(
        "SELECT COUNT(*) FROM market_data_bars WHERE symbol = ? AND interval = '1h'",
        (symbol.upper(),),
    ).fetchone()
    conn.close()
    return count


# ---------------------------------------------------------------------------
# test_backfill_loads_csv
# ---------------------------------------------------------------------------


def test_backfill_loads_csv(tmp_path, monkeypatch):
    """
    Given a fixture CSV for MES, backfill_symbol inserts exactly N rows.
    """
    db_path = _make_db(tmp_path / "test.db")
    csv_path = _make_fixture_csv(tmp_path / "MES_fixture_1h.csv", n_rows=15)

    # Patch _find_all_csvs to return our fixture file for MES
    import scripts.backfill_market_data_bars as bfm
    monkeypatch.setattr(bfm, "_find_all_csvs", lambda sym: [csv_path] if sym == "MES" else [])

    result = backfill_symbol("MES", dry_run=False, db_path=db_path)

    assert result["error"] is None, f"Expected no error, got: {result['error']}"
    assert result["total_rows"] == 15
    assert result["new_rows"] == 15
    assert result["skipped_rows"] == 0
    assert _count_rows(db_path, "MES") == 15


# ---------------------------------------------------------------------------
# test_backfill_idempotent
# ---------------------------------------------------------------------------


def test_backfill_idempotent(tmp_path, monkeypatch):
    """
    Running backfill_symbol twice yields total = first-run count, not 2x.
    Second run inserts 0 new rows and skips all.
    """
    db_path = _make_db(tmp_path / "test.db")
    csv_path = _make_fixture_csv(tmp_path / "MES_fixture_1h.csv", n_rows=20)

    import scripts.backfill_market_data_bars as bfm
    monkeypatch.setattr(bfm, "_find_all_csvs", lambda sym: [csv_path] if sym == "MES" else [])

    # First run
    r1 = backfill_symbol("MES", dry_run=False, db_path=db_path)
    assert r1["error"] is None
    assert r1["new_rows"] == 20
    assert _count_rows(db_path, "MES") == 20

    # Second run — all rows already present
    r2 = backfill_symbol("MES", dry_run=False, db_path=db_path)
    assert r2["error"] is None
    assert r2["new_rows"] == 0
    assert r2["skipped_rows"] == 20
    # Total in DB is still 20, not 40
    assert _count_rows(db_path, "MES") == 20
