"""
JARVIS TRADER — Startup Validation Tests
Tests for engine startup checks against misconfigurations.
"""

import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from startup_checks import (
    CheckResult,
    _check_api_key,
    _check_autonomous_active_symbols,
    _check_database,
    _check_disk_space,
    _check_fred_key,
    _check_human_approval,
    _check_ibkr_port,
    _check_live_trading_disabled,
    _check_polygon_key,
    run_startup_checks,
)


class TestCheckResultDataclass:
    """CheckResult struct and string representation."""

    def test_check_result_creation(self):
        """CheckResult can be created with status and message."""
        result = CheckResult(
            name="Test Check",
            status="pass",
            message="Everything OK",
        )
        assert result.name == "Test Check"
        assert result.status == "pass"

    def test_check_result_string_representation(self):
        """CheckResult formats as [STATUS] Name: message."""
        result = CheckResult(
            name="Test Check",
            status="fail",
            message="Something broke",
        )
        assert str(result) == "[FAIL] Test Check: Something broke"


class TestAPIKeyCheck:
    """API key validation — must be set and not placeholder."""

    def test_api_key_not_set_fails(self):
        """Missing API_KEY returns FAIL."""
        result = _check_api_key(SimpleNamespace(API_KEY=None))
        assert result.status == "fail"

    def test_api_key_placeholder_fails(self):
        """Placeholder value returns FAIL."""
        result = _check_api_key(SimpleNamespace(API_KEY="CHANGE_ME_BEFORE_DEPLOY"))
        assert result.status == "fail"
        assert "placeholder" in result.message.lower()

    def test_api_key_valid_passes(self):
        """Valid API_KEY returns PASS."""
        result = _check_api_key(SimpleNamespace(API_KEY="valid"))
        assert result.status == "pass"


class TestIBKRPortCheck:
    """IBKR port validation — 4002 (paper) OK, 4001 (live) FAIL."""

    def test_ibkr_port_4002_passes(self):
        """Port 4002 (paper) returns PASS."""
        result = _check_ibkr_port(SimpleNamespace(IBKR_PORT=4002))
        assert result.status == "pass"
        assert "4002" in result.message
        assert "paper" in result.message.lower()

    def test_ibkr_port_4001_fails(self):
        """Port 4001 (live) returns FAIL."""
        result = _check_ibkr_port(SimpleNamespace(IBKR_PORT=4001))
        assert result.status == "fail"
        assert "4001" in result.message
        assert "live" in result.message.lower()

    def test_ibkr_port_unexpected_warns(self):
        """Port 9999 (unexpected) returns WARN."""
        result = _check_ibkr_port(SimpleNamespace(IBKR_PORT=9999))
        assert result.status == "warn"


class TestLiveTradingCheck:
    """Live trading disabled — FAIL if enabled."""

    def test_live_trading_enabled_fails(self):
        """LIVE_TRADING_ENABLED=True returns FAIL."""
        result = _check_live_trading_disabled(SimpleNamespace(LIVE_TRADING_ENABLED=True))
        assert result.status == "fail"

    def test_live_trading_disabled_passes(self):
        """LIVE_TRADING_ENABLED=False returns PASS."""
        result = _check_live_trading_disabled(SimpleNamespace(LIVE_TRADING_ENABLED=False))
        assert result.status == "pass"


class TestHumanApprovalCheck:
    """Human approval required — WARN (non-blocking) if disabled.

    Updated during the family-fdr-campaign integration: disabling
    REQUIRE_HUMAN_APPROVAL is now a loud WARN (autonomous paper mode boots)
    rather than a boot-blocking FAIL. See engine/startup_checks.py.
    """

    def test_human_approval_disabled_warns(self):
        """REQUIRE_HUMAN_APPROVAL=False returns WARN (non-blocking autonomous boot)."""
        result = _check_human_approval(SimpleNamespace(REQUIRE_HUMAN_APPROVAL=False))
        assert result.status == "warn"

    def test_human_approval_enabled_passes(self):
        """REQUIRE_HUMAN_APPROVAL=True returns PASS."""
        result = _check_human_approval(SimpleNamespace(REQUIRE_HUMAN_APPROVAL=True))
        assert result.status == "pass"


class TestDatabaseCheck:
    """SQLite database file existence check."""

    def test_database_exists_passes(self):
        """Existing database file returns PASS."""
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp_path = tmp.name
        try:
            result = _check_database(SimpleNamespace(SQLITE_DB_PATH=tmp_path))
            assert result.status == "pass"
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_database_missing_warns(self):
        """Missing database file returns WARN."""
        result = _check_database(SimpleNamespace(SQLITE_DB_PATH="/tmp/nonexistent_12345.db"))
        assert result.status == "warn"


class TestPolygonKeyCheck:
    """Polygon API key validation — optional, warns if missing."""

    def test_polygon_key_set_passes(self):
        """POLYGON_API_KEY set returns PASS."""
        result = _check_polygon_key(SimpleNamespace(POLYGON_API_KEY="test-key"))
        assert result.status == "pass"

    def test_polygon_key_missing_warns(self):
        """POLYGON_API_KEY not set returns WARN."""
        result = _check_polygon_key(SimpleNamespace(POLYGON_API_KEY=None))
        assert result.status == "warn"


class TestFREDKeyCheck:
    """FRED API key validation — optional, warns if missing."""

    def test_fred_key_set_passes(self):
        """FRED_API_KEY set returns PASS."""
        result = _check_fred_key(SimpleNamespace(FRED_API_KEY="test-key"))
        assert result.status == "pass"

    def test_fred_key_missing_warns(self):
        """FRED_API_KEY not set returns WARN."""
        result = _check_fred_key(SimpleNamespace(FRED_API_KEY=None))
        assert result.status == "warn"


class TestDiskSpaceCheck:
    """Disk space validation — warn if < 1GB free."""

    def test_disk_space_check_succeeds(self):
        """Disk space check runs and returns result."""
        result = _check_disk_space()
        assert result.status in ("pass", "warn")
        assert "GB" in result.message


class TestRunAllStartupChecks:
    """Full startup validation suite."""

    def test_run_all_checks_with_good_config(self):
        """All checks run and return results with valid config."""
        config = SimpleNamespace(
            API_KEY="valid-key",
            IBKR_PORT=4002,
            LIVE_TRADING_ENABLED=False,
            REQUIRE_HUMAN_APPROVAL=True,
            SQLITE_DB_PATH="data/jarvis_trader.db",
            POLYGON_API_KEY="test-key",
            FRED_API_KEY="test-key",
        )
        results = run_startup_checks(config)
        assert len(results) == 10  # +1 _check_autonomous_active_symbols (2026-06-06)
        assert all(isinstance(r, CheckResult) for r in results)

    def test_run_all_checks_detects_failures(self):
        """Checks detect critical failures."""
        config = SimpleNamespace(
            API_KEY=None,
            IBKR_PORT=4001,
            LIVE_TRADING_ENABLED=True,
            REQUIRE_HUMAN_APPROVAL=False,
            SQLITE_DB_PATH="/tmp/test.db",
            POLYGON_API_KEY=None,
            FRED_API_KEY=None,
        )
        results = run_startup_checks(config)
        failures = [r for r in results if r.status == "fail"]
        # human-approval downgraded fail->warn in family-fdr integration, so the
        # critical FAILs are now API, port, live (approval emits WARN instead).
        assert len(failures) >= 3  # API, port, live


class TestAutonomousActiveSymbolsCheck:
    """Autonomous dead-path guard: WARN when active symbols are all DO_NOT_TRADE."""

    def test_disabled_pipeline_skips_check(self, monkeypatch):
        monkeypatch.delenv("ENABLE_AUTONOMOUS_PIPELINE", raising=False)
        result = _check_autonomous_active_symbols()
        assert result.status == "pass"
        assert "disabled" in result.message.lower()

    def test_all_blocked_symbols_warns(self, monkeypatch):
        monkeypatch.setenv("ENABLE_AUTONOMOUS_PIPELINE", "1")
        monkeypatch.setenv("AUTONOMOUS_ACTIVE_SYMBOLS", "MCL,MNQ")  # both DO_NOT_TRADE
        result = _check_autonomous_active_symbols()
        assert result.status == "warn"
        assert "NEVER" in result.message

    def test_partial_block_warns(self, monkeypatch):
        monkeypatch.setenv("ENABLE_AUTONOMOUS_PIPELINE", "1")
        monkeypatch.setenv("AUTONOMOUS_ACTIVE_SYMBOLS", "MES,MCL")  # MES ok, MCL blocked
        result = _check_autonomous_active_symbols()
        assert result.status == "warn"
        assert "MCL" in result.message

    def test_all_tradeable_passes(self, monkeypatch):
        monkeypatch.setenv("ENABLE_AUTONOMOUS_PIPELINE", "1")
        # MGC joined DO_NOT_TRADE_SYMBOLS 2026-07-31 (honest-data-drain DSR
        # correction) -- MES is the only currently-tradeable symbol left.
        monkeypatch.setenv("AUTONOMOUS_ACTIVE_SYMBOLS", "MES")
        result = _check_autonomous_active_symbols()
        assert result.status == "pass"
