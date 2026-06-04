"""Regression tests for the outcome-hygiene guards on the live accuracy/weight
path (W2) and the record_outcome write chokepoint (W3).

Background: the 2026-06-02 agent_feedback.db pollution -- three byte-identical
MES rows with an impossible +$10,102.98 P&L plus test fixtures -- skewed both
the Brier surface and the live directional-accuracy agent weights. These tests
pin the guards that now reject such rows at write and ignore them at read.

DB-isolated: every test patches the module-level DB_PATH to a tmp file (the
same isolation the production-DB-leak fix in test_new_features.py uses).
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from analytics.agent_feedback import AgentFeedbackTracker

# Patch the module the class actually lives in (robust to engine.* vs bare alias).
_AF_MOD = sys.modules[AgentFeedbackTracker.__module__]


def _iso(second: int = 0) -> str:
    return datetime(2026, 6, 1, 12, 0, second % 60, tzinfo=timezone.utc).isoformat()


def _count(db_path) -> int:
    with sqlite3.connect(db_path) as conn:
        return conn.execute("SELECT COUNT(*) FROM trade_outcomes").fetchone()[0]


def _seed_raw(db_path, rows) -> None:
    """Insert rows directly, bypassing record_outcome guards, to simulate the
    historical pollution the READ path (W2) must tolerate."""
    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO trade_outcomes "
            "(trade_id, timestamp, symbol, direction, pnl_usd, pnl_pct, outcome, "
            "technical_signal, news_signal, social_signal, fundamental_signal, "
            "corey_signal, breakout_signal, harmonic_signal, regime) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )


def test_write_guard_rejects_corrupt_pnl(tmp_path):
    db = tmp_path / "agent_feedback.db"
    with patch.object(_AF_MOD, "DB_PATH", db):
        t = AgentFeedbackTracker()
        t.record_outcome(
            trade_id="corrupt-1", symbol="MES", direction="SHORT",
            pnl_usd=10102.98, analyst_signals={"technical": 0.6},
        )
        assert _count(db) == 0, "corrupt-P&L row must not be recorded"
        t.record_outcome(
            trade_id="ok-1", symbol="MES", direction="LONG",
            pnl_usd=150.0, analyst_signals={"technical": 0.6},
        )
        assert _count(db) == 1


def test_write_guard_rejects_logical_duplicate(tmp_path):
    db = tmp_path / "agent_feedback.db"
    ts = _iso(0)
    with patch.object(_AF_MOD, "DB_PATH", db):
        t = AgentFeedbackTracker()
        t.record_outcome(trade_id="a", symbol="MES", direction="SHORT",
                         pnl_usd=42.0, analyst_signals={"technical": 0.6}, timestamp=ts)
        # different trade_id, same symbol+second+pnl -> logical duplicate, skipped
        t.record_outcome(trade_id="b", symbol="MES", direction="SHORT",
                         pnl_usd=42.0, analyst_signals={"technical": 0.6}, timestamp=ts)
        assert _count(db) == 1, "logical duplicate must be skipped"
        # same trade_id re-record is allowed (INSERT OR REPLACE), still 1 row
        t.record_outcome(trade_id="a", symbol="MES", direction="SHORT",
                         pnl_usd=42.0, analyst_signals={"technical": 0.6}, timestamp=ts)
        assert _count(db) == 1
        # a genuinely distinct trade (different pnl) records
        t.record_outcome(trade_id="c", symbol="MES", direction="SHORT",
                         pnl_usd=43.0, analyst_signals={"technical": 0.6}, timestamp=ts)
        assert _count(db) == 2


def test_accuracy_ignores_corrupt_and_duplicate_rows(tmp_path):
    db = tmp_path / "agent_feedback.db"
    ts_dup = _iso(0)
    with patch.object(_AF_MOD, "DB_PATH", db):
        t = AgentFeedbackTracker()  # creates the schema
        rows = []
        # 5 clean, correctly-called rows (technical LONG, WIN) at distinct seconds
        for i in range(5):
            rows.append((f"good{i}", _iso(i + 1), "MES", "LONG", 50.0, 0.0, "WIN",
                         0.9, 0, 0, 0, 0, 0, 0, None))
        # one wrong call (technical LONG signal, but a SHORT-WIN... here LOSS),
        # logged 3x with identical second + (signal, pnl) -> must collapse to 1
        for k in range(3):
            rows.append((f"dup{k}", ts_dup, "MES", "SHORT", -20.0, 0.0, "LOSS",
                         0.9, 0, 0, 0, 0, 0, 0, None))
        # corrupt-magnitude row that would read as a correct WIN -> must be dropped
        rows.append(("corrupt", _iso(40), "MES", "LONG", 10102.98, 0.0, "WIN",
                     0.9, 0, 0, 0, 0, 0, 0, None))
        _seed_raw(db, rows)

        acc = t.compute_accuracy("technical", window_days=3650)
        # Hygiene -> 5 correct + 1 deduped-wrong = 6 rows, 5 correct -> ~0.833.
        # Without guards it would be 6/9 ~= 0.667 (corrupt counts correct, dups x3).
        assert 0.80 < acc < 0.87, f"expected deduped accuracy ~0.83, got {acc}"
