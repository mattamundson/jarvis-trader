"""Tests for DatabaseManager.ping() — the cheap liveness probe used by /health.

/health used to call health_check() (8 full COUNT(*) scans on a 325MB DB) just to
set db_ok=True, discarding the counts. ping() is an O(1) `SELECT 1` liveness check;
these confirm it returns True on a live DB and raises when the DB is unusable.
"""

from __future__ import annotations

import pytest

from database.manager import DatabaseManager


def test_ping_true_on_live_db(tmp_path):
    db = DatabaseManager(str(tmp_path / "ping.db"))
    db.initialize()
    assert db.ping() is True


def test_ping_raises_on_broken_db(tmp_path, monkeypatch):
    db = DatabaseManager(str(tmp_path / "ping2.db"))
    db.initialize()

    # Simulate an unreachable DB: _connect blows up. ping must propagate (not
    # silently return True) so /health's try/except can flip db_ok to False.
    def _boom():
        raise RuntimeError("db unreachable")

    monkeypatch.setattr(db, "_connect", _boom)
    with pytest.raises(RuntimeError):
        db.ping()
