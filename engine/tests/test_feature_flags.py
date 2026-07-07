"""
JARVIS TRADER — Feature Flags Unit Tests
==========================================
Tests for the two-layer FeatureFlags system (engine/flags/registry.py).

All tests use a mock DatabaseManager — no real SQLite required.
The mock tracks INSERT/UPDATE/DELETE/SELECT calls so tests can verify
runtime override behaviour without touching disk.

Run with:
    cd engine
    python -m pytest tests/test_feature_flags.py -v
"""

from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers — minimal stubs so we don't need a running engine
# ---------------------------------------------------------------------------


class _MockRow(dict):
    """Behaves like sqlite3.Row (subscript access by column name)."""

    def __getitem__(self, key: str) -> Any:
        return super().__getitem__(key)


class _MockConfig:
    """Minimal TradingConfig stub with feature flag defaults."""

    ENABLE_KAIROS: bool = False
    ENABLE_SPECULATION: bool = False
    ENABLE_TILT_DETECTION: bool = True
    ENABLE_DREAM_CONSOLIDATION: bool = False
    ENABLE_CONTEXT_COMPACTION: bool = True
    ENABLE_CRYPTO: bool = False
    ENABLE_POLYMARKET: bool = False
    ENABLE_RL_TRADING: bool = False
    ENABLE_SIGNAL_SANITIZATION: bool = False


class _MockDB:
    """
    Minimal DatabaseManager stub.

    Stores feature_flags rows in an in-memory dict so tests can verify
    that set_flag() and reset_flag() read/write correctly.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._flags_store: Dict[str, int] = {}  # name -> enabled (0|1)

    def _connect(self):
        """Return a mock connection that forwards queries to _flags_store."""
        conn = MagicMock()

        def _execute(sql: str, params: tuple = ()):
            sql_norm = " ".join(sql.split()).upper()

            # SELECT enabled FROM feature_flags WHERE name = ?
            if "SELECT ENABLED" in sql_norm and "WHERE NAME" in sql_norm:
                name = params[0]
                if name in self._flags_store:
                    row = _MockRow({"enabled": self._flags_store[name]})
                    conn.execute.return_value.fetchone.return_value = row
                else:
                    conn.execute.return_value.fetchone.return_value = None

            # SELECT name, enabled FROM feature_flags
            elif "SELECT NAME, ENABLED" in sql_norm:
                rows = [_MockRow({"name": k, "enabled": v}) for k, v in self._flags_store.items()]
                conn.execute.return_value.fetchall.return_value = rows

            # INSERT INTO feature_flags ... ON CONFLICT DO UPDATE
            elif "INSERT INTO FEATURE_FLAGS" in sql_norm:
                name = params[0]
                enabled_int = params[1]
                self._flags_store[name] = enabled_int

            # DELETE FROM feature_flags WHERE name = ?
            elif "DELETE FROM FEATURE_FLAGS" in sql_norm:
                name = params[0]
                self._flags_store.pop(name, None)

            return conn.execute.return_value

        conn.execute.side_effect = _execute
        conn.commit = MagicMock()
        conn.close = MagicMock()
        return conn


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def config():
    return _MockConfig()


@pytest.fixture()
def db():
    return _MockDB()


@pytest.fixture()
def flags(config, db):
    from flags.registry import FeatureFlags

    return FeatureFlags(config=config, db=db)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestFlagDefaults:
    def test_flag_default_enabled(self, flags):
        """ENABLE_TILT_DETECTION defaults to True (from config and FLAG_DEFINITIONS)."""
        assert flags.is_enabled("ENABLE_TILT_DETECTION") is True

    def test_flag_default_disabled(self, flags):
        """ENABLE_KAIROS defaults to False (from config and FLAG_DEFINITIONS)."""
        assert flags.is_enabled("ENABLE_KAIROS") is False

    def test_rl_trading_default_disabled(self, flags):
        """ENABLE_RL_TRADING defaults to False.

        Guards the main.py RL-executor autostart gate: the experimental RL
        executor must NOT start unless this flag is explicitly enabled. It
        tracks its own in-memory position and co-trading the MES paper account
        alongside the LLM pipeline contaminates execution-fidelity data.
        """
        assert flags.is_enabled("ENABLE_RL_TRADING") is False

    def test_unknown_flag_returns_false(self, flags):
        """Unknown flag names return False without raising."""
        assert flags.is_enabled("ENABLE_NONEXISTENT_FLAG") is False


class TestRuntimeOverrides:
    def test_set_flag_runtime_override(self, flags, db):
        """set_flag() persists to the mock DB and is_enabled() reflects the change."""
        # ENABLE_KAIROS is False by default
        assert flags.is_enabled("ENABLE_KAIROS") is False

        flags.set_flag("ENABLE_KAIROS", True, updated_by="test")

        # After override, should be True
        assert flags.is_enabled("ENABLE_KAIROS") is True
        # Verify it was written to the mock store
        assert db._flags_store.get("ENABLE_KAIROS") == 1

    def test_runtime_overrides_config(self, flags, db):
        """A runtime False override supersedes a config True default."""
        # ENABLE_TILT_DETECTION is True in config
        assert flags.is_enabled("ENABLE_TILT_DETECTION") is True

        # Override to False at runtime
        flags.set_flag("ENABLE_TILT_DETECTION", False, updated_by="test")

        assert flags.is_enabled("ENABLE_TILT_DETECTION") is False
        assert db._flags_store.get("ENABLE_TILT_DETECTION") == 0

    def test_reset_flag(self, flags, db):
        """reset_flag() removes the runtime override and restores config default."""
        # Set a runtime override first
        flags.set_flag("ENABLE_TILT_DETECTION", False, updated_by="test")
        assert flags.is_enabled("ENABLE_TILT_DETECTION") is False

        # Reset — should fall back to config default (True)
        flags.reset_flag("ENABLE_TILT_DETECTION")

        assert flags.is_enabled("ENABLE_TILT_DETECTION") is True
        assert "ENABLE_TILT_DETECTION" not in db._flags_store

    def test_set_flag_invalid_name_raises(self, flags):
        """set_flag() raises ValueError for unknown flag names."""
        with pytest.raises(ValueError, match="Unknown feature flag"):
            flags.set_flag("ENABLE_MADE_UP_FLAG", True)

    def test_reset_flag_invalid_name_raises(self, flags):
        """reset_flag() raises ValueError for unknown flag names."""
        with pytest.raises(ValueError, match="Unknown feature flag"):
            flags.reset_flag("ENABLE_MADE_UP_FLAG")


class TestListFlags:
    def test_list_flags_returns_all(self, flags):
        """list_flags() returns exactly one entry per FLAG_DEFINITIONS entry."""
        from flags.registry import FLAG_DEFINITIONS

        result = flags.list_flags()
        assert len(result) == len(FLAG_DEFINITIONS)

    def test_list_flags_structure(self, flags):
        """Each flag dict contains the required keys."""
        required_keys = {"name", "enabled", "description", "category", "requires_restart", "source"}
        for flag in flags.list_flags():
            assert required_keys.issubset(
                flag.keys()
            ), f"Flag {flag.get('name')!r} missing keys: {required_keys - flag.keys()}"

    def test_list_flags_source_config_when_no_override(self, flags):
        """Flags with no runtime override are sourced from 'config'."""
        result = flags.list_flags()
        for flag in result:
            assert (
                flag["source"] == "config"
            ), f"Expected source='config' for {flag['name']} (no override set)"

    def test_list_flags_source_runtime_after_override(self, flags):
        """Flags with a runtime override show source='runtime'."""
        flags.set_flag("ENABLE_KAIROS", True, updated_by="test")

        result = flags.list_flags()
        kairos = next(f for f in result if f["name"] == "ENABLE_KAIROS")
        assert kairos["source"] == "runtime"
        assert kairos["enabled"] is True

    def test_list_flags_correct_defaults(self, flags):
        """Spot-check: ENABLE_CONTEXT_COMPACTION default is True."""
        result = flags.list_flags()
        compaction = next(f for f in result if f["name"] == "ENABLE_CONTEXT_COMPACTION")
        assert compaction["enabled"] is True

    def test_list_flags_requires_restart_metadata(self, flags):
        """ENABLE_KAIROS and ENABLE_CRYPTO require restart; ENABLE_TILT_DETECTION does not."""
        result = {f["name"]: f for f in flags.list_flags()}
        assert result["ENABLE_KAIROS"]["requires_restart"] is True
        assert result["ENABLE_CRYPTO"]["requires_restart"] is True
        assert result["ENABLE_TILT_DETECTION"]["requires_restart"] is False

    def test_list_flags_categories(self, flags):
        """Verify categories are correctly assigned for a few flags."""
        result = {f["name"]: f for f in flags.list_flags()}
        assert result["ENABLE_KAIROS"]["category"] == "ai"
        assert result["ENABLE_TILT_DETECTION"]["category"] == "risk"
        assert result["ENABLE_CRYPTO"]["category"] == "market"
        assert result["ENABLE_RL_TRADING"]["category"] == "experimental"
        assert result["ENABLE_SIGNAL_SANITIZATION"]["category"] == "security"
