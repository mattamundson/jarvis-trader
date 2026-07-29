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
from unittest.mock import patch

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

    def test_db_path_none_returns_active_fail_closed(self, mock_settings):
        """GT-49 follow-up: no db_path is an unknown state, fails CLOSED."""
        os.environ["ENABLE_PARALLEL_PAPER"] = "1"
        try:
            sl = SafetyLayer(mock_settings)  # no db_path → _db_path=None
            sl._db_path = None
            state = sl.get_per_account_kill_state("A")
            assert state["active"] is True
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
    def test_corrupt_db_path_returns_active_fail_closed(self, mock_settings):
        """When DB connect fails (bad path chars on Windows), FAILS CLOSED (GT-49).

        A DB read failure is an unknown state, not a safe one — the account
        must be reported as halted (active=True) until a real read succeeds,
        matching the fail-closed contract enforced in the except block of
        get_per_account_kill_state.
        """
        os.environ["ENABLE_PARALLEL_PAPER"] = "1"
        try:
            sl = SafetyLayer(mock_settings)
            sl._db_path = "Z:\\nonexistent\\path\\db.sqlite"
            state = sl.get_per_account_kill_state("A")
            assert state["active"] is True
            assert state["reason"] is not None
        finally:
            del os.environ["ENABLE_PARALLEL_PAPER"]

    def test_db_exception_makes_real_caller_treat_account_as_halted(
        self, mock_settings, parallel_paper_db
    ):
        """Real-caller trace (GT-49): is_account_halted must block orders on a DB
        read failure, not just the raw dict shape from get_per_account_kill_state.

        is_account_halted() is the function order-emission paths actually call
        (see risk/safety_layer.py::is_account_halted, docstring: "Return True if
        this account should NOT emit orders"). Before the fix, a DB exception
        here would have returned active=False, meaning is_account_halted("A")
        also returned False — i.e. an unreadable kill-state DB would have let
        this account keep trading. After the fix it must return True.
        """
        os.environ["ENABLE_PARALLEL_PAPER"] = "1"
        try:
            sl = SafetyLayer(mock_settings, db_path=parallel_paper_db)
            with patch("sqlite3.connect", side_effect=Exception("DB dead")):
                assert sl.is_account_halted("A") is True, (
                    "is_account_halted must fail CLOSED (block orders) when the "
                    "per-account kill-state DB read raises, not fail open"
                )
        finally:
            del os.environ["ENABLE_PARALLEL_PAPER"]

    def test_no_db_path_makes_real_caller_treat_account_as_halted(self, mock_settings):
        """Real-caller trace for the sibling `_db_path is None` branch (GT-49
        follow-up): is_account_halted must block orders when no DB path is
        configured at all, not just when a configured DB read raises.
        """
        os.environ["ENABLE_PARALLEL_PAPER"] = "1"
        try:
            sl = SafetyLayer(mock_settings)
            sl._db_path = None
            assert sl.is_account_halted("A") is True, (
                "is_account_halted must fail CLOSED (block orders) when no "
                "per-account kill-state DB path is configured, not fail open"
            )
        finally:
            del os.environ["ENABLE_PARALLEL_PAPER"]


class TestDormantEarlyReturnUnaffectedByFailClosedFix:
    """GT-49 regression guard: the ENABLE_PARALLEL_PAPER-disabled early return
    (get_per_account_kill_state line ~699) must NOT be touched or weakened by
    the except-block fail-closed fix. Live .env has ENABLE_PARALLEL_PAPER=0
    today, so this early-return path is the one actually exercised in
    production — it must keep mirroring the global kill switch exactly as
    before, even when the underlying DB is completely unreachable.
    """

    def test_disabled_flag_mirrors_global_kill_switch_even_if_db_would_raise(
        self, mock_settings
    ):
        """ENABLE_PARALLEL_PAPER unset → returns synthetic global-mirror record
        without ever touching the DB, regardless of whether the DB read would
        succeed or raise. This proves the dormant branch short-circuits before
        reaching the except block changed by GT-49.
        """
        os.environ.pop("ENABLE_PARALLEL_PAPER", None)
        try:
            sl = SafetyLayer(mock_settings)
            sl.activate_kill_switch(KillSwitchReason.MANUAL, "test global halt")
            with patch("sqlite3.connect", side_effect=Exception("should never be called")):
                state = sl.get_per_account_kill_state("A")
            assert state["active"] == sl._kill_switch_active
            assert state["active"] is True
            assert state["reason"] == sl._kill_switch_reason.value
            # Fail-closed diagnostic reason text must NOT appear — proves the
            # except block (the code path this fix touched) was never reached.
            assert "kill-state read failed" not in (state["reason"] or "")
        finally:
            os.environ.pop("ENABLE_PARALLEL_PAPER", None)

    def test_explicit_zero_flag_mirrors_global_kill_switch_inactive(self, mock_settings):
        """ENABLE_PARALLEL_PAPER=0 (today's live .env value) → inactive mirror,
        unaffected by the fail-closed except-block fix.
        """
        os.environ["ENABLE_PARALLEL_PAPER"] = "0"
        try:
            sl = SafetyLayer(mock_settings)
            state = sl.get_per_account_kill_state("A")
            assert state["active"] is False
            assert state["active"] == sl._kill_switch_active
        finally:
            del os.environ["ENABLE_PARALLEL_PAPER"]
