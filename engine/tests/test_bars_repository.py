"""Tests for engine.data.bars_repository — save/load/latest_bar round-trips."""

from __future__ import annotations

import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

# Make engine root importable when pytest runs from the engine directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data.bars_repository import latest_bar, load_bars, save_bars


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_db(tmp_path: Path) -> Path:
    """Create a minimal SQLite DB with the market_data_bars table."""
    import sqlite3

    db = tmp_path / "test.db"
    conn = sqlite3.connect(str(db))
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
    return db


def _make_bars(n: int = 5, symbol: str = "MES", start_hour: int = 9) -> pd.DataFrame:
    rows = []
    for i in range(n):
        dt = datetime(2026, 5, 7, start_hour + i, 0, 0, tzinfo=timezone.utc)
        rows.append(
            {
                "timestamp": dt,
                "open": 5300.0 + i,
                "high": 5310.0 + i,
                "low": 5290.0 + i,
                "close": 5305.0 + i,
                "volume": 1000.0 + i * 10,
            }
        )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# test_save_then_load
# ---------------------------------------------------------------------------


def test_save_then_load(tmp_path):
    db = _make_db(tmp_path)
    df = _make_bars(5)
    saved = save_bars(df, "MES", "1h", "tv", db_path=db)
    assert saved == 5

    loaded = load_bars("MES", "1h", db_path=db)
    assert len(loaded) == 5
    assert list(loaded.columns) >= ["timestamp", "open", "high", "low", "close", "volume"]
    # Values round-trip correctly
    assert abs(float(loaded["close"].iloc[0]) - 5305.0) < 1e-6


# ---------------------------------------------------------------------------
# test_save_idempotent
# ---------------------------------------------------------------------------


def test_save_idempotent(tmp_path):
    db = _make_db(tmp_path)
    df = _make_bars(3)

    first = save_bars(df, "MES", "1h", "tv", db_path=db)
    second = save_bars(df, "MES", "1h", "ibkr", db_path=db)  # same ts, different source

    assert first == 3
    # INSERT OR IGNORE — all 3 rows already exist, 0 new rows
    assert second == 0

    loaded = load_bars("MES", "1h", db_path=db)
    assert len(loaded) == 3  # no duplicates


# ---------------------------------------------------------------------------
# test_latest_bar_returns_most_recent
# ---------------------------------------------------------------------------


def test_latest_bar_returns_most_recent(tmp_path):
    db = _make_db(tmp_path)
    df = _make_bars(4)
    save_bars(df, "MES", "1h", "ibkr", db_path=db)

    bar = latest_bar("MES", "1h", db_path=db)
    assert bar is not None
    # Most recent bar is the last one (start_hour=9, n=4 → ts = 12:00)
    assert "12:00:00" in bar["timestamp"]
    assert abs(float(bar["close"]) - 5308.0) < 1e-6


# ---------------------------------------------------------------------------
# test_save_bars_skips_empty_df
# ---------------------------------------------------------------------------


def test_save_bars_skips_empty_df(tmp_path):
    db = _make_db(tmp_path)
    result = save_bars(pd.DataFrame(), "MES", "1h", "tv", db_path=db)
    assert result == 0

    result_none = save_bars(None, "MES", "1h", "tv", db_path=db)  # type: ignore[arg-type]
    assert result_none == 0

    loaded = load_bars("MES", "1h", db_path=db)
    assert loaded.empty
