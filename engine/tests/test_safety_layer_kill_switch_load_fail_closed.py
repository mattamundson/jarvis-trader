"""
Regression test for the kill-switch-state-load fail-open bug found by the
2026-08-11 fail-open-safety-checks audit.

Before the fix, SafetyLayer._load_kill_switch_state() caught any DB read
exception and only logged a warning, leaving _kill_switch_active at its
__init__ default of False. A locked/corrupt/unreadable DB at startup would
therefore silently resume trading even if the switch had been persisted
active=True from a prior halt. This mirrors the fail-closed hardening
already applied to the sibling get_per_account_kill_state() after the
2026-06-15 inert-kill-switch incident.
"""

import sqlite3

from risk.safety_layer import KillSwitchReason, SafetyLayer


def test_corrupt_db_fails_closed(tmp_path, mock_settings):
    """A DB that raises on read (not just 'missing') must activate the kill switch."""
    bad_db = tmp_path / "not_a_real_sqlite_file.db"
    # A file that exists but isn't a valid SQLite database — sqlite3.connect()
    # succeeds lazily, but the SELECT against it raises DatabaseError, giving
    # a genuine read-failure rather than a mocked exception.
    bad_db.write_text("this is not a sqlite database")

    safety = SafetyLayer(mock_settings, db_path=str(bad_db))

    assert safety._kill_switch_active is True, (
        "kill switch state load failed but the switch was left inactive -- "
        "fail-open regression"
    )
    assert safety._kill_switch_reason == KillSwitchReason.STATE_UNKNOWN


def test_missing_table_also_fails_closed(tmp_path, mock_settings):
    """A DB file that exists but was never migrated (no system_state table)
    is just as unverifiable as a corrupt one -- also fails closed, unlike the
    sibling get_per_account_kill_state()'s "row is None" branch (which has no
    equivalent here; see this method's docstring)."""
    unmigrated_db = tmp_path / "unmigrated.db"
    sqlite3.connect(str(unmigrated_db)).close()  # valid empty SQLite file, no tables

    safety = SafetyLayer(mock_settings, db_path=str(unmigrated_db))

    assert safety._kill_switch_active is True
    assert safety._kill_switch_reason == KillSwitchReason.STATE_UNKNOWN


def test_migrated_but_empty_db_starts_clean(tmp_path, mock_settings):
    """The real 'never triggered' case: system_state table exists (migrated)
    but has no kill_switch_active row. This must NOT fail closed -- it is a
    successful, informative read, not an error."""
    migrated_db = tmp_path / "migrated_empty.db"
    conn = sqlite3.connect(str(migrated_db))
    conn.execute(
        """
        CREATE TABLE system_state (
            key        TEXT PRIMARY KEY,
            value      TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT (datetime('now', 'utc'))
        )
        """
    )
    conn.commit()
    conn.close()

    safety = SafetyLayer(mock_settings, db_path=str(migrated_db))

    assert safety._kill_switch_active is False
    assert safety._kill_switch_reason is None
