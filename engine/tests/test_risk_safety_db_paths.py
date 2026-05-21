"""
Tests for risk/safety_layer.py — database-dependent and alert paths.

Covers: _load_pnl_snapshot, _seed_equity_from_pnl_monitor, _persist_pnl_snapshot,
sync_from_broker with alert_manager, check_circuit_breakers with PnLMonitor,
per-account kill state (ENABLE_PARALLEL_PAPER=1 env var path),
get_recommended_size, get_lockout_status.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from risk.pnl_monitor import PnLState
from risk.safety_layer import KillSwitchReason, SafetyLayer


def _make_sl(settings, **kwargs) -> SafetyLayer:
    return SafetyLayer(settings, **kwargs)


# ── _seed_equity_from_pnl_monitor ─────────────────────────────────────────────


class TestSeedEquityFromPnlMonitor:
    def test_seeds_from_pnl_monitor_when_zero_equity(self, mock_settings):
        mock_settings.INITIAL_CAPITAL = 0.0
        monitor = MagicMock()
        monitor.get_current_pnl_state.return_value = PnLState(current_balance=12000.0)

        sl = SafetyLayer(mock_settings, pnl_monitor=monitor)
        # Equity should have been seeded
        assert sl._current_equity == pytest.approx(12000.0)

    def test_pnl_monitor_seed_failure_falls_to_initial_capital(self, mock_settings):
        mock_settings.INITIAL_CAPITAL = 8000.0
        monitor = MagicMock()
        monitor.get_current_pnl_state.side_effect = RuntimeError("DB unavailable")

        sl = SafetyLayer(mock_settings, pnl_monitor=monitor)
        # Fell back to INITIAL_CAPITAL
        assert sl._current_equity == pytest.approx(8000.0)

    def test_pnl_monitor_zero_balance_falls_to_initial_capital(self, mock_settings):
        mock_settings.INITIAL_CAPITAL = 5000.0
        monitor = MagicMock()
        monitor.get_current_pnl_state.return_value = PnLState(current_balance=0.0)

        sl = SafetyLayer(mock_settings, pnl_monitor=monitor)
        # current_balance=0 → condition `balance > 0` is False → falls to INITIAL_CAPITAL
        assert sl._current_equity == pytest.approx(5000.0)

    def test_initial_capital_seeds_equity_when_no_monitor(self, mock_settings):
        mock_settings.INITIAL_CAPITAL = 10000.0
        sl = SafetyLayer(mock_settings)
        assert sl._current_equity == pytest.approx(10000.0)
        assert sl._equity_peak == pytest.approx(10000.0)


# ── _persist_pnl_snapshot ─────────────────────────────────────────────────────


class TestPersistPnlSnapshot:
    def test_no_db_manager_no_op(self, mock_settings):
        """No db_manager → logs warning once, no crash."""
        sl = SafetyLayer(mock_settings)
        sl._db_manager = None
        # Should not raise
        sl._persist_pnl_snapshot()
        sl._persist_pnl_snapshot()  # second call should not re-warn

    def test_with_db_manager_calls_upsert(self, mock_settings):
        db = MagicMock()
        db.upsert_pnl_snapshot.return_value = None
        sl = SafetyLayer(mock_settings, db_manager=db)
        sl._persist_pnl_snapshot()
        db.upsert_pnl_snapshot.assert_called()

    def test_db_write_failure_does_not_raise(self, mock_settings):
        db = MagicMock()
        db.upsert_pnl_snapshot.side_effect = RuntimeError("DB write error")
        sl = SafetyLayer(mock_settings, db_manager=db)
        # Should log warning and return, never raise
        sl._persist_pnl_snapshot()


# ── _load_pnl_snapshot ────────────────────────────────────────────────────────


class TestLoadPnlSnapshot:
    def test_no_db_manager_skips(self, mock_settings):
        sl = SafetyLayer(mock_settings)
        sl._db_manager = None
        # Should not raise
        sl._load_pnl_snapshot()

    def test_snapshot_found_restores_state(self, mock_settings):
        db = MagicMock()
        db.get_pnl_snapshot.return_value = {
            "daily_pnl": -150.0,
            "portfolio_equity": 9850.0,
            "peak_equity": 10000.0,
        }
        sl = SafetyLayer(mock_settings, db_manager=db)
        # Force reload from mock
        sl._daily_realized_pnl = 0.0
        sl._current_equity = 0.0
        sl._equity_peak = 0.0
        sl._load_pnl_snapshot()
        assert sl._daily_realized_pnl == pytest.approx(-150.0)
        assert sl._current_equity == pytest.approx(9850.0)

    def test_no_snapshot_for_today_keeps_defaults(self, mock_settings):
        db = MagicMock()
        db.get_pnl_snapshot.return_value = None
        sl = SafetyLayer(mock_settings, db_manager=db)
        sl._daily_realized_pnl = 0.0
        sl._load_pnl_snapshot()
        assert sl._daily_realized_pnl == 0.0

    def test_db_exception_handled_gracefully(self, mock_settings):
        db = MagicMock()
        db.get_pnl_snapshot.side_effect = RuntimeError("DB crash")
        sl = SafetyLayer(mock_settings, db_manager=db)
        # Should not raise
        sl._load_pnl_snapshot()


# ── sync_from_broker with alert_manager ────────────────────────────────────────


class TestSyncFromBrokerAlerts:
    def test_alert_manager_called_during_sync(self, mock_settings):
        from risk.alert_manager import AlertManager

        alert_mgr = AlertManager(notify_fn=None)
        sl = SafetyLayer(mock_settings)
        sl.inject_alert_manager(alert_mgr)
        sl._equity_peak = 10000.0
        sl.sync_from_broker(equity=10000.0, daily_pnl=0.0)
        # No exception; alert_manager.check_and_alert was called (dedup will drop it)

    def test_alert_manager_with_pnl_monitor_drawdown(self, mock_settings):
        from risk.alert_manager import AlertManager

        alert_mgr = AlertManager(notify_fn=None)
        monitor = MagicMock()
        monitor.get_drawdown_pct.return_value = -0.06

        sl = SafetyLayer(mock_settings, pnl_monitor=monitor)
        sl.inject_alert_manager(alert_mgr)
        sl._equity_peak = 10000.0
        # sync_from_broker uses pnl_monitor.get_drawdown_pct() for drawdown
        sl.sync_from_broker(equity=9400.0, daily_pnl=-600.0)
        # drawdown_5pct should fire
        fired = alert_mgr.get_fired_keys()
        assert "drawdown_5pct" in fired

    def test_alert_manager_exception_does_not_crash_sync(self, mock_settings):
        alert_mgr = MagicMock()
        alert_mgr.check_and_alert.side_effect = RuntimeError("alert crash")
        sl = SafetyLayer(mock_settings)
        sl.inject_alert_manager(alert_mgr)
        # Should log warning and not re-raise
        sl.sync_from_broker(equity=10000.0, daily_pnl=0.0)

    def test_sync_uses_equity_peak_for_drawdown_when_no_monitor(self, mock_settings):
        from risk.alert_manager import AlertManager

        alert_mgr = AlertManager(notify_fn=None)
        sl = SafetyLayer(mock_settings)
        sl.inject_alert_manager(alert_mgr)
        # Set peak high so drawdown calc fires
        sl._equity_peak = 10000.0
        sl.sync_from_broker(equity=9400.0, daily_pnl=-600.0)
        # drawdown via equity_peak fallback branch (no pnl_monitor)
        fired = alert_mgr.get_fired_keys()
        assert "drawdown_5pct" in fired


# ── check_circuit_breakers with PnLMonitor equity fallback ────────────────────


class TestCheckCircuitBreakersExtended:
    def test_pnl_monitor_equity_fallback_when_current_equity_zero(self, mock_settings):
        monitor = MagicMock()
        monitor.get_daily_pnl.return_value = -100.0
        monitor.get_drawdown_pct.return_value = -0.01
        monitor.get_current_pnl_state.return_value = PnLState(current_balance=9000.0)

        sl = SafetyLayer(mock_settings, pnl_monitor=monitor)
        sl._current_equity = 0.0  # force the fallback path

        cb = sl.check_circuit_breakers()
        # Should have used PnLMonitor's current_balance (9000) for limits
        assert cb["daily_limit"] != 0  # non-zero because equity was found

    def test_pnl_monitor_equity_fallback_exception_handled(self, mock_settings):
        monitor = MagicMock()
        monitor.get_daily_pnl.return_value = 0.0
        monitor.get_drawdown_pct.return_value = 0.0
        monitor.get_current_pnl_state.side_effect = RuntimeError("state unavailable")

        sl = SafetyLayer(mock_settings, pnl_monitor=monitor)
        sl._current_equity = 0.0

        # Should not raise; falls back to equity=0
        cb = sl.check_circuit_breakers()
        assert cb["daily_limit"] == 0


# ── per-account kill state ────────────────────────────────────────────────────


class TestPerAccountKillState:
    def test_without_env_var_returns_global_state(self, mock_settings, mock_safety_layer):
        """ENABLE_PARALLEL_PAPER not set → mirrors global kill switch state."""
        sl = mock_safety_layer
        # Kill switch off → active should be False
        state = sl.get_per_account_kill_state("A")
        assert state["account_id"] == "A"
        assert state["active"] == sl._kill_switch_active

    def test_is_account_halted_mirrors_kill_switch_without_env(
        self, mock_settings, mock_safety_layer
    ):
        sl = mock_safety_layer
        sl.activate_kill_switch(KillSwitchReason.MANUAL, "test")
        assert sl.is_account_halted("A") is True

    def test_is_account_halted_false_when_no_kill_switch(self, mock_settings, mock_safety_layer):
        sl = mock_safety_layer
        assert sl.is_account_halted("A") is False

    def test_trigger_per_account_no_env_is_noop(self, mock_settings, mock_safety_layer):
        """trigger_per_account_kill is no-op when ENABLE_PARALLEL_PAPER not set."""
        sl = mock_safety_layer
        # Should not raise even though no DB
        sl.trigger_per_account_kill("A", "max_daily_loss", -150.0, "Test halt")

    def test_clear_per_account_no_env_is_noop(self, mock_settings, mock_safety_layer):
        """clear_per_account_kill is no-op when ENABLE_PARALLEL_PAPER not set."""
        sl = mock_safety_layer
        sl.clear_per_account_kill("A", notes="resumed")


# ── get_lockout_status ────────────────────────────────────────────────────────


class TestGetLockoutStatus:
    def test_no_lockout_returns_not_locked(self, mock_safety_layer):
        sl = mock_safety_layer
        status = sl.get_lockout_status("MES")
        assert status["locked"] is False
        assert status["symbol"] == "MES"

    def test_active_lockout_returns_locked(self, mock_safety_layer):
        from datetime import datetime, timedelta

        sl = mock_safety_layer
        sl._reentry_lockouts["MES"] = datetime.now() + timedelta(minutes=30)
        status = sl.get_lockout_status("MES")
        assert status["locked"] is True
        assert status["remaining_minutes"] > 0

    def test_expired_lockout_returns_not_locked(self, mock_safety_layer):
        from datetime import datetime, timedelta

        sl = mock_safety_layer
        sl._reentry_lockouts["MES"] = datetime.now() - timedelta(minutes=1)
        status = sl.get_lockout_status("MES")
        assert status["locked"] is False


# ── get_recommended_size ──────────────────────────────────────────────────────


class TestGetRecommendedSizeExtended:
    def test_returns_sizing_dict(self, mock_settings, mock_safety_layer):
        sl = mock_safety_layer
        result = sl.get_recommended_size(
            symbol="MES",
            atr=5.0,
            account_value=10000.0,
            current_drawdown=0.0,
        )
        assert "symbol" in result
        assert "recommended_contracts" in result

    def test_unknown_symbol_uses_default_multiplier(self, mock_settings, mock_safety_layer):
        sl = mock_safety_layer
        result = sl.get_recommended_size(
            symbol="UNKNOWN",
            atr=5.0,
            account_value=10000.0,
            current_drawdown=0.0,
        )
        assert "recommended_contracts" in result
        assert result["symbol"] == "UNKNOWN"

    def test_zero_atr_returns_zero_contracts(self, mock_settings, mock_safety_layer):
        sl = mock_safety_layer
        result = sl.get_recommended_size(
            symbol="MES",
            atr=0.0,
            account_value=10000.0,
            current_drawdown=0.0,
        )
        assert result["recommended_contracts"] == 0
