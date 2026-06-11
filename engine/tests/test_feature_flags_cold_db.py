"""B3 regression: FeatureFlags must self-create its SQLite table on a cold DB.

Before 2026-06-11 nothing in the schema bootstrap created feature_flags, so
every engine boot logged 'no such table: feature_flags' and runtime flag
overrides (the registry's whole purpose) were broken.
"""

import os
import sqlite3
import sys
import threading

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flags.registry import FeatureFlags  # noqa: E402


class _RealSqliteDB:
    """Minimal DatabaseManager shape backed by a real (cold) SQLite file."""

    def __init__(self, path: str) -> None:
        self._path = path
        self._lock = threading.Lock()

    def _connect(self):
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn


class _Config:
    ENABLE_TILT_DETECTION = True


@pytest.fixture()
def cold_db(tmp_path):
    return _RealSqliteDB(str(tmp_path / "cold.db"))


class TestColdDatabase:
    def test_init_creates_table(self, cold_db):
        FeatureFlags(config=_Config(), db=cold_db)
        conn = cold_db._connect()
        try:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='feature_flags'"
            ).fetchone()
        finally:
            conn.close()
        assert row is not None

    def test_is_enabled_works_on_cold_db(self, cold_db):
        flags = FeatureFlags(config=_Config(), db=cold_db)
        assert flags.is_enabled("ENABLE_RL_TRADING") is False  # definition default
        assert flags.is_enabled("ENABLE_TILT_DETECTION") is True  # config layer

    def test_set_and_reset_roundtrip_on_cold_db(self, cold_db):
        flags = FeatureFlags(config=_Config(), db=cold_db)
        flags.set_flag("ENABLE_RL_TRADING", True, updated_by="test")
        assert flags.is_enabled("ENABLE_RL_TRADING") is True
        flags.reset_flag("ENABLE_RL_TRADING")
        assert flags.is_enabled("ENABLE_RL_TRADING") is False

    def test_reinit_idempotent(self, cold_db):
        FeatureFlags(config=_Config(), db=cold_db)
        flags2 = FeatureFlags(config=_Config(), db=cold_db)  # second init: no error
        assert flags2.list_flags()
