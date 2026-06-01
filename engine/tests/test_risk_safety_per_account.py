"""
Tests for risk/safety_layer.py — per-account kill state with ENABLE_PARALLEL_PAPER=1.

These tests set the env var and use a real SQLite in-memory file to exercise
get_per_account_kill_state, trigger_per_account_kill, clear_per_account_kill,
and is_account_halted with actual DB reads/writes.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile

import pytest

from risk.safety_layer import KillSwitchReason, SafetyLayer


@pytest.fixture()
def parallel_paper_db(tmp_path):
    """Create a SQLite DB with per_account_kill_state table; yield its path."""
    db_path = str(tmp_path / "jarvis_test.db")
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS per_account_kill_state (
            account_id   TEXT PRIMARY KEY,
            active       INTEGER NOT NULL DEFAULT 0,
            triggered_at TEXT,
            reason       TEXT,
            trigger_metric TEXT,
            trigger_value  REAL,
            cleared_at   TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS system_state (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TEXT
        )
        """
    )
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture()
def sl_parallel(mock_settings, parallel_paper_db):
    """SafetyLayer with ENABLE_PARALLEL_PAPER=1 env var and a real SQLite DB."""
    os.environ["ENABLE_PARALLEL_PAPER"] = "1"
    try:
        sl = SafetyLayer(mock_settings, db_path=parallel_paper_db)
        yield sl
    finally:
        del os.environ["ENABLE_PARALLEL_PAPER"]


class TestGetPerAccountKillStateWithDb:
    def test_no_row_returns_inactive(self, sl_parallel):
        state = sl_parallel.get_per_account_kill_state("A")
        assert state["account_id"] == "A"
        assert state["active"] is False

    def test_db_path_none_returns_inactive(self, mock_settings):
        os.environ["ENABLE_PARALLEL_PAPER"] = "1"
        try:
            sl = SafetyLayer(mock_settings)  # no db_path → _db_path=None
            sl._db_path = None
            state = sl.get_per_account_kill_state("A")
            assert state["active"] is False
        finally:
            del os.environ["ENABLE_PARALLEL_PAPER"]

    def test_triggered_account_returns_active(self, sl_parallel, parallel_paper_db):
        """Pre-insert an active row and verify get_per_account_kill_state reads it."""
        conn = sqlite3.connect(parallel_paper_db)
        conn.execute(
            """
            INSERT INTO per_account_kill_state
                (account_id, active, triggered_at, reason, trigger_metric, trigger_value)
            VALUES ('B', 1, '2026-01-01T00:00:00', 'max_daily_loss', 'daily_pnl', -200.0)
            """
        )
        conn.commit()
        conn.close()

        state = sl_parallel.get_per_account_kill_state("B")
        assert state["active"] is True
        assert state["reason"] == "max_daily_loss"
        assert state["trigger_value"] == pytest.approx(-200.0)


class TestTriggerPerAccountKillWithDb:
    def test_trigger_creates_active_row(self, sl_parallel, parallel_paper_db):
        sl_parallel.trigger_per_account_kill("A", "max_daily_loss", -150.0, "Daily loss exceeded")

        conn = sqlite3.connect(parallel_paper_db)
        row = conn.execute(
            "SELECT active, reason FROM per_account_kill_state WHERE account_id='A'"
        ).fetchone()
        conn.close()

        assert row is not None
        assert row[0] == 1  # active
        assert row[1] == "Daily loss exceeded"

    def test_trigger_idempotent_on_double_call(self, sl_parallel, parallel_paper_db):
        sl_parallel.trigger_per_account_kill("A", "max_daily_loss", -100.0, "First halt")
        sl_parallel.trigger_per_account_kill("A", "max_daily_loss", -200.0, "Second halt")

        conn = sqlite3.connect(parallel_paper_db)
        rows = conn.execute(
            "SELECT COUNT(*) FROM per_account_kill_state WHERE account_id='A'"
        ).fetchone()
        conn.close()
        assert rows[0] == 1  # only one row (upsert)

    def test_trigger_updates_state_for_is_account_halted(self, sl_parallel):
        sl_parallel.trigger_per_account_kill("A", "max_daily_loss", -150.0, "Halt A")
        assert sl_parallel.is_account_halted("A") is True


class TestClearPerAccountKillWithDb:
    def test_clear_sets_active_false(self, sl_parallel, parallel_paper_db):
        sl_parallel.trigger_per_account_kill("A", "max_daily_loss", -150.0, "Halt")
        sl_parallel.clear_per_account_kill("A", notes="Manually cleared")

        conn = sqlite3.connect(parallel_paper_db)
        row = conn.execute(
            "SELECT active, cleared_at FROM per_account_kill_state WHERE account_id='A'"
        ).fetchone()
        conn.close()
        assert row[0] == 0  # active=0
        assert row[1] is not None  # cleared_at set

    def test_is_account_halted_false_after_clear(self, sl_parallel):
        sl_parallel.trigger_per_account_kill("A", "max_daily_loss", -150.0, "Halt")
        sl_parallel.clear_per_account_kill("A")
        assert sl_parallel.is_account_halted("A") is False

    def test_clear_without_prior_trigger_no_crash(self, sl_parallel):
        """Clear on account that was never triggered should not raise."""
        sl_parallel.clear_per_account_kill("C", notes="cleanup")

    def test_db_path_none_clear_is_noop(self, mock_settings):
        os.environ["ENABLE_PARALLEL_PAPER"] = "1"
        try:
            sl = SafetyLayer(mock_settings)
            sl._db_path = None
            sl.clear_per_account_kill("A")  # should not raise
        finally:
            del os.environ["ENABLE_PARALLEL_PAPER"]


class TestGetPerAccountKillStateException:
    def test_corrupt_db_path_returns_inactive(self, mock_settings):
        """When DB connect fails (bad path chars on Windows), returns safe default."""
        os.environ["ENABLE_PARALLEL_PAPER"] = "1"
        try:
            sl = SafetyLayer(mock_settings)
            sl._db_path = "Z:\\nonexistent\\path\\db.sqlite"
            state = sl.get_per_account_kill_state("A")
            assert state["active"] is False
        finally:
            del os.environ["ENABLE_PARALLEL_PAPER"]
