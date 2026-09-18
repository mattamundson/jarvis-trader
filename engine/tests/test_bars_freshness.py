"""Regression tests for persisted-bar freshness (data/bars_repository.bars_freshness).

Context -- why this file exists (2026-09-18)
-------------------------------------------
The engine served for ~38 hours with a dead data leg: the IB data connector
could not connect because its clientId was held by an orphaned session
("Error 326: Unable to connect as the client id is already in use").

During that entire window:
  * ``market_data_bars`` held no MES bar newer than 2026-09-16T16:00,
  * ``/health`` reported ``market_data_fresh: true`` with
    ``market_data_stale_symbols: []``,
  * and the dashboard rendered that two-day-old close (7618.25) as the live
    price, complete with indicator scores and "Look for LONG entries".

The pre-existing freshness check reads the Redis fabric (``market:latest:{sym}``
within 900s) and fails OPEN -- a missing entry, or a lookup that raises, both
report ``stale=False``. So nothing in the system asked the only question that
matters before a decision: *how old is the newest bar?*

These tests pin the answer. Keep them hermetic: a temp SQLite file, no engine
startup, no network, no IB, no Redis.
"""
from __future__ import annotations

import datetime as dt
import sqlite3
import sys
from pathlib import Path

import pytest

ENGINE_ROOT = Path(__file__).resolve().parent.parent
if str(ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(ENGINE_ROOT))

from data.bars_repository import bars_freshness  # noqa: E402

_DDL = """
CREATE TABLE market_data_bars (
    symbol TEXT NOT NULL,
    interval TEXT NOT NULL,
    ts_utc TEXT NOT NULL,
    open REAL, high REAL, low REAL, close REAL, volume REAL,
    source TEXT,
    fetched_at TEXT,
    PRIMARY KEY (symbol, interval, ts_utc)
)
"""


def _db(tmp_path: Path, rows: list[tuple]) -> Path:
    """rows: (symbol, interval, hours_ago, close)"""
    p = tmp_path / "bars.db"
    con = sqlite3.connect(p)
    try:
        con.execute(_DDL)
        now = dt.datetime.now(dt.timezone.utc)
        for symbol, interval, hours_ago, close in rows:
            ts = (now - dt.timedelta(hours=hours_ago)).isoformat()
            con.execute(
                "INSERT INTO market_data_bars (symbol, interval, ts_utc, open, high, low, close,"
                " volume, source, fetched_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (symbol, interval, ts, close, close, close, close, 1.0, "test", ts),
            )
        con.commit()
    finally:
        con.close()
    return p


# ── the regression: a frozen feed must be reported stale ────────────────────


def test_bar_38_hours_old_is_stale(tmp_path):
    """The exact 2026-09-18 shape: newest bar two days old => stale."""
    db = _db(tmp_path, [("MES", "1h", 38.7, 7618.25)])
    out = bars_freshness(["MES"], interval="1h", max_age_hours=3.0, db_path=db)
    assert out["MES"]["present"] is True
    assert out["MES"]["stale"] is True, "a 38-hour-old bar must never read fresh"
    assert out["MES"]["age_hours"] > 38


def test_current_bar_is_fresh(tmp_path):
    db = _db(tmp_path, [("MES", "1h", 0.75, 7636.25)])  # observed write lag ~45 min
    out = bars_freshness(["MES"], interval="1h", max_age_hours=3.0, db_path=db)
    assert out["MES"]["present"] is True
    assert out["MES"]["stale"] is False
    assert 0.0 <= out["MES"]["age_hours"] <= 1.0


def test_threshold_boundary(tmp_path):
    db = _db(tmp_path, [("MES", "1h", 2.0, 7600.0), ("MGC", "1h", 4.0, 4300.0)])
    out = bars_freshness(["MES", "MGC"], interval="1h", max_age_hours=3.0, db_path=db)
    assert out["MES"]["stale"] is False   # inside the ceiling
    assert out["MGC"]["stale"] is True    # outside it


# ── "nothing at all" is stale here, unlike the Redis check ──────────────────


def test_symbol_with_no_bars_is_stale_and_present_false(tmp_path):
    db = _db(tmp_path, [("MES", "1h", 0.5, 7600.0)])
    out = bars_freshness(["MES", "MGC"], interval="1h", max_age_hours=3.0, db_path=db)
    assert out["MGC"] == {"present": False, "ts": None, "age_hours": None, "stale": True}


def test_missing_db_file_does_not_raise(tmp_path):
    out = bars_freshness(["MES"], interval="1h", max_age_hours=3.0, db_path=tmp_path / "nope.db")
    assert out["MES"]["stale"] is True
    assert out["MES"]["present"] is False


def test_interval_is_respected(tmp_path):
    """A fresh 1m bar must not make a stale 1h series look fresh."""
    db = _db(tmp_path, [("MES", "1m", 0.1, 7636.0), ("MES", "1h", 40.0, 7618.25)])
    out_1h = bars_freshness(["MES"], interval="1h", max_age_hours=3.0, db_path=db)
    out_1m = bars_freshness(["MES"], interval="1m", max_age_hours=3.0, db_path=db)
    assert out_1h["MES"]["stale"] is True
    assert out_1m["MES"]["stale"] is False


def test_naive_timestamp_is_treated_as_utc(tmp_path):
    """Bars written without a tz offset must not be read as decades stale."""
    p = tmp_path / "naive.db"
    con = sqlite3.connect(p)
    try:
        con.execute(_DDL)
        ts = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None).isoformat()
        con.execute(
            "INSERT INTO market_data_bars (symbol, interval, ts_utc, open, high, low, close,"
            " volume, source, fetched_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            ("MES", "1h", ts, 1, 1, 1, 1, 1.0, "test", ts),
        )
        con.commit()
    finally:
        con.close()
    out = bars_freshness(["MES"], interval="1h", max_age_hours=3.0, db_path=p)
    assert out["MES"]["stale"] is False


@pytest.mark.parametrize("symbols", [["MES"], ["MES", "MGC"], ()])
def test_never_raises_on_any_symbol_set(tmp_path, symbols):
    db = _db(tmp_path, [("MES", "1h", 1.0, 7600.0)])
    out = bars_freshness(symbols, interval="1h", max_age_hours=3.0, db_path=db)
    assert set(out) == {s.upper() for s in symbols}
