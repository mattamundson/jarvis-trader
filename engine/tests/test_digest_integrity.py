"""Calibration-integrity field in the daily Discord digest (analytics/outcome_hygiene).

Standing detector for a repeat of the 2026-06-02 trade_outcomes pollution. The
daily digest now carries corrupt/duplicate counts + an alert flag so a future
pollution event surfaces in the Discord digest instead of waiting for a manual
investigation. DB-isolated via tmp_path.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta, timezone

from discord.digest_generator import _calibration_integrity


def _make_feedback_db(path, rows):
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE trade_outcomes (trade_id TEXT PRIMARY KEY, timestamp TEXT, "
            "symbol TEXT, pnl_usd REAL)"
        )
        conn.executemany(
            "INSERT INTO trade_outcomes (trade_id, timestamp, symbol, pnl_usd) "
            "VALUES (?, ?, ?, ?)",
            rows,
        )


def test_calibration_integrity_clean(tmp_path):
    now = datetime.now(timezone.utc).isoformat()
    _make_feedback_db(
        tmp_path / "agent_feedback.db",
        [("t1", now, "MES", -20.0), ("t2", now, "MGC", 35.0)],
    )
    rep = _calibration_integrity(str(tmp_path / "jarvis_trader.db"), date.today())
    assert rep["alert"] is False
    assert rep["rows_excluded_corrupt"] == 0
    assert rep["rows_excluded_duplicate"] == 0
    assert rep["total_outcomes"] == 2


def test_calibration_integrity_flags_corrupt_and_duplicate(tmp_path):
    now = datetime.now(timezone.utc).isoformat()
    rows = [
        ("corrupt", now, "MES", 10102.98),  # |pnl| > bound
        ("dupA", now, "MGC", -20.0),
        ("dupB", now, "MGC", -20.0),  # logical duplicate of dupA
    ]
    _make_feedback_db(tmp_path / "agent_feedback.db", rows)
    rep = _calibration_integrity(str(tmp_path / "jarvis_trader.db"), date.today())
    assert rep["alert"] is True
    assert rep["rows_excluded_corrupt"] == 1
    assert rep["rows_excluded_duplicate"] == 1


def test_calibration_integrity_missing_db_is_safe(tmp_path):
    rep = _calibration_integrity(str(tmp_path / "jarvis_trader.db"), date.today())
    assert rep == {
        "total_outcomes": 0,
        "rows_excluded_corrupt": 0,
        "rows_excluded_duplicate": 0,
        "alert": False,
        "window_days": 30,
    }


def test_calibration_integrity_respects_window(tmp_path):
    old = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
    _make_feedback_db(
        tmp_path / "agent_feedback.db",
        [("old_corrupt", old, "MES", 10102.98)],  # outside the 30d window
    )
    rep = _calibration_integrity(str(tmp_path / "jarvis_trader.db"), date.today())
    assert rep["alert"] is False
    assert rep["total_outcomes"] == 0
