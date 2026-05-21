"""
Extended safety layer tests covering paths not in test_safety_layer.py:
- Consecutive loss tracker integration (half/quarter/halt via SafetyLayer)
- Stark TPO constraint checks
- ALLOW_PAPER_SIMULATED_ORDERS gate bypass
- sync_from_broker state updates
- check_circuit_breakers return values
- get_status API
- get_recommended_size
- record_trade_result + re-entry lockout
- get_loss_tracker_status / reset_loss_tracker
- orders_in_last_minute
- reset_daily_pnl
- MAX_DAILY_LOSS_USD absolute limit
- attach_ib_gateway / attach_schwab / inject_alert_manager (no-crash)
- _check_daily_loss_limit absolute USD branch
- KillSwitchReason string-to-enum conversion
"""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from risk.safety_layer import KillSwitchReason, OrderRequest, RiskCheckResult, SafetyLayer


def _live_settings(mock_settings):
    mock_settings.LIVE_TRADING_ENABLED = True
    mock_settings.REQUIRE_HUMAN_APPROVAL = False
    mock_settings.MAX_DAILY_LOSS_PCT = 0.02
    mock_settings.MAX_DAILY_LOSS_USD = 10_000.0  # large so pct fires first
    mock_settings.MAX_DRAWDOWN_PCT = 0.10
    mock_settings.MAX_SINGLE_ORDER_VALUE = 10_000.0
    mock_settings.MAX_POSITION_SIZE_PCT = 0.20
    mock_settings.MAX_ORDERS_PER_MINUTE = 100
    mock_settings.MAX_CONTRACTS_PER_INSTRUMENT = 5
    mock_settings.MAX_OVERNIGHT_CONTRACTS = 5
    mock_settings.MAX_FUTURES_MARGIN_PCT = 0.50
    return mock_settings


class TestStarkTPOConstraint:
    def test_hold_signal_blocks_non_zero_quantity(self, mock_settings):
        _live_settings(mock_settings)
        safety = SafetyLayer(mock_settings)
        order = OrderRequest(
            symbol="MES",
            quantity=1,
            order_type="market",
            estimated_value=500.0,
            stark_signal="HOLD",
        )
        result = safety.check_order(order, 100_000.0)
        assert result.approved is False
        assert "STARK_TPO_CONSTRAINT" in result.rejection_reason
        assert "HOLD" in result.rejection_reason

    def test_long_signal_blocks_short_order(self, mock_settings):
        _live_settings(mock_settings)
        safety = SafetyLayer(mock_settings)
        order = OrderRequest(
            symbol="MES",
            quantity=-1,
            order_type="market",
            estimated_value=500.0,
            stark_signal="LONG",
        )
        result = safety.check_order(order, 100_000.0)
        assert result.approved is False
        assert "STARK_TPO_CONSTRAINT" in result.rejection_reason

    def test_short_signal_blocks_long_order(self, mock_settings):
        _live_settings(mock_settings)
        safety = SafetyLayer(mock_settings)
        order = OrderRequest(
            symbol="MES",
            quantity=1,
            order_type="market",
            estimated_value=500.0,
            stark_signal="SHORT",
        )
        result = safety.check_order(order, 100_000.0)
        assert result.approved is False
        assert "STARK_TPO_CONSTRAINT" in result.rejection_reason

    def test_long_signal_allows_long_order(self, mock_settings):
        _live_settings(mock_settings)
        safety = SafetyLayer(mock_settings)
        order = OrderRequest(
            symbol="MES",
            quantity=1,
            order_type="market",
            estimated_value=500.0,
            stark_signal="LONG",
        )
        result = safety.check_order(order, 100_000.0)
        assert result.approved is True

    def test_short_signal_allows_short_order(self, mock_settings):
        _live_settings(mock_settings)
        safety = SafetyLayer(mock_settings)
        order = OrderRequest(
            symbol="MES",
            quantity=-1,
            order_type="market",
            estimated_value=500.0,
            stark_signal="SHORT",
        )
        result = safety.check_order(order, 100_000.0)
        assert result.approved is True

    def test_no_stark_signal_passes_tpo_check(self, mock_settings):
        _live_settings(mock_settings)
        safety = SafetyLayer(mock_settings)
        order = OrderRequest(
            symbol="MES",
            quantity=1,
            order_type="market",
            estimated_value=500.0,
            stark_signal=None,
        )
        result = safety.check_order(order, 100_000.0)
        assert result.approved is True


class TestPaperSimulatedOrders:
    def test_allow_paper_simulated_bypasses_live_trading_gate(self, mock_settings):
        """ALLOW_PAPER_SIMULATED_ORDERS=True → bypasses the LIVE_TRADING_ENABLED=False block."""
        mock_settings.LIVE_TRADING_ENABLED = False
        mock_settings.ALLOW_PAPER_SIMULATED_ORDERS = True
        # Other limits must be permissive
        mock_settings.MAX_DAILY_LOSS_PCT = 0.10
        mock_settings.MAX_DAILY_LOSS_USD = 10_000.0
        mock_settings.MAX_DRAWDOWN_PCT = 0.20
        mock_settings.MAX_SINGLE_ORDER_VALUE = 10_000.0
        mock_settings.MAX_POSITION_SIZE_PCT = 0.20
        mock_settings.MAX_ORDERS_PER_MINUTE = 100
        mock_settings.MAX_CONTRACTS_PER_INSTRUMENT = 5
        mock_settings.MAX_OVERNIGHT_CONTRACTS = 5
        mock_settings.MAX_FUTURES_MARGIN_PCT = 0.50
        mock_settings.REQUIRE_HUMAN_APPROVAL = False  # not checked when ALLOW_PAPER_SIMULATED
        safety = SafetyLayer(mock_settings)
        order = OrderRequest(
            symbol="MES",
            quantity=1,
            order_type="market",
            estimated_value=500.0,
        )
        result = safety.check_order(order, 100_000.0)
        # Should not reject with "Live trading is disabled"
        assert "Live trading is disabled" not in (result.rejection_reason or "")


class TestSyncFromBroker:
    def test_sync_updates_equity(self, mock_settings):
        safety = SafetyLayer(mock_settings)
        safety.sync_from_broker(equity=15000.0, daily_pnl=0.0)
        assert safety._current_equity == 15000.0

    def test_sync_updates_daily_pnl(self, mock_settings):
        safety = SafetyLayer(mock_settings)
        safety.sync_from_broker(equity=10000.0, daily_pnl=-200.0)
        assert safety._daily_realized_pnl == -200.0

    def test_sync_advances_equity_peak(self, mock_settings):
        safety = SafetyLayer(mock_settings)
        safety.sync_from_broker(equity=12000.0, daily_pnl=0.0)
        safety.sync_from_broker(equity=15000.0, daily_pnl=0.0)
        assert safety._equity_peak == 15000.0

    def test_sync_peak_does_not_decrease(self, mock_settings):
        safety = SafetyLayer(mock_settings)
        safety.sync_from_broker(equity=15000.0, daily_pnl=0.0)
        safety.sync_from_broker(equity=10000.0, daily_pnl=0.0)
        assert safety._equity_peak == 15000.0

    def test_sync_triggers_kill_switch_on_large_loss(self, mock_settings):
        mock_settings.MAX_DAILY_LOSS_PCT = 0.02
        safety = SafetyLayer(mock_settings)
        # -3% of 100k = -$3000, exceeds -2% = -$2000
        safety.sync_from_broker(equity=100_000.0, daily_pnl=-3000.0)
        assert safety.is_killed is True
        assert safety._kill_switch_reason == KillSwitchReason.DAILY_LOSS_LIMIT

    def test_sync_does_not_trigger_kill_switch_on_small_loss(self, mock_settings):
        mock_settings.MAX_DAILY_LOSS_PCT = 0.02
        safety = SafetyLayer(mock_settings)
        # -1% of 100k = -$1000, within -2% limit
        safety.sync_from_broker(equity=100_000.0, daily_pnl=-1000.0)
        assert safety.is_killed is False


class TestDailyLossUSDAbsoluteLimit:
    def test_absolute_usd_limit_triggers_kill_switch(self, mock_settings):
        """Even within pct limit, the flat USD limit fires."""
        mock_settings.LIVE_TRADING_ENABLED = True
        mock_settings.REQUIRE_HUMAN_APPROVAL = False
        mock_settings.MAX_DAILY_LOSS_PCT = 0.10  # 10% — large, won't fire
        mock_settings.MAX_DAILY_LOSS_USD = 100.0  # small flat cap
        safety = SafetyLayer(mock_settings)
        safety.sync_from_broker(equity=100_000.0, daily_pnl=-150.0)  # within 10% but over $100
        order = OrderRequest(
            symbol="MES",
            quantity=1,
            order_type="market",
            estimated_value=500.0,
        )
        result = safety.check_order(order, 100_000.0)
        assert result.approved is False
        assert safety.is_killed is True


class TestCheckCircuitBreakers:
    def test_returns_required_keys(self, mock_settings):
        safety = SafetyLayer(mock_settings)
        cb = safety.check_circuit_breakers()
        expected = {
            "daily_pnl",
            "daily_limit",
            "daily_pnl_pct",
            "daily_limit_pct",
            "daily_limit_breached",
            "drawdown_pct",
            "drawdown_limit_pct",
            "drawdown_breached",
            "kill_switch_active",
            "kill_switch_reason",
        }
        assert expected.issubset(cb.keys())

    def test_kill_switch_active_reflected(self, mock_settings):
        safety = SafetyLayer(mock_settings)
        safety.activate_kill_switch(KillSwitchReason.MANUAL)
        cb = safety.check_circuit_breakers()
        assert cb["kill_switch_active"] is True
        assert cb["kill_switch_reason"] == KillSwitchReason.MANUAL.value

    def test_not_breached_when_within_limits(self, mock_settings):
        safety = SafetyLayer(mock_settings)
        safety.sync_from_broker(equity=100_000.0, daily_pnl=-100.0)
        cb = safety.check_circuit_breakers()
        assert cb["daily_limit_breached"] is False

    def test_breached_when_over_daily_limit(self, mock_settings):
        mock_settings.MAX_DAILY_LOSS_PCT = 0.02
        safety = SafetyLayer(mock_settings)
        safety._daily_realized_pnl = -3000.0
        safety._current_equity = 100_000.0
        cb = safety.check_circuit_breakers()
        assert cb["daily_limit_breached"] is True


class TestGetStatus:
    def test_returns_required_keys(self, mock_settings):
        safety = SafetyLayer(mock_settings)
        status = safety.get_status()
        expected = {
            "is_killed",
            "kill_switch_reason",
            "daily_realized_pnl",
            "equity_peak",
            "current_equity",
            "recent_order_count",
        }
        assert expected.issubset(status.keys())

    def test_kill_switch_not_active_initially(self, mock_settings):
        safety = SafetyLayer(mock_settings)
        assert safety.get_status()["is_killed"] is False


class TestLossTrackerIntegration:
    def test_loss_tracker_status_disabled_when_none(self, mock_settings):
        safety = SafetyLayer(mock_settings)
        status = safety.get_loss_tracker_status()
        assert status["enabled"] is False

    def test_loss_tracker_status_enabled_when_injected(self, mock_settings):
        from risk.loss_tracker import ConsecutiveLossTracker

        tmpdir = tempfile.mkdtemp()
        tracker = ConsecutiveLossTracker(data_dir=tmpdir)
        safety = SafetyLayer(mock_settings, loss_tracker=tracker)
        status = safety.get_loss_tracker_status()
        assert status["enabled"] is True

    def test_record_trade_result_with_tracker(self, mock_settings):
        from risk.loss_tracker import ConsecutiveLossTracker

        tmpdir = tempfile.mkdtemp()
        tracker = ConsecutiveLossTracker(data_dir=tmpdir)
        safety = SafetyLayer(mock_settings, loss_tracker=tracker)
        safety.record_trade_result("MES", pnl=-20.0)
        assert tracker.get_consecutive_losses() == 1

    def test_record_trade_result_without_tracker_no_crash(self, mock_settings):
        safety = SafetyLayer(mock_settings)
        # Should not raise even without loss_tracker
        safety.record_trade_result("MES", pnl=-20.0)

    def test_reset_loss_tracker_no_tracker_returns_message(self, mock_settings):
        safety = SafetyLayer(mock_settings)
        result = safety.reset_loss_tracker()
        assert "not available" in result.get("status", "")

    def test_reset_loss_tracker_with_tracker(self, mock_settings):
        from risk.loss_tracker import ConsecutiveLossTracker

        tmpdir = tempfile.mkdtemp()
        tracker = ConsecutiveLossTracker(data_dir=tmpdir)
        tracker.record_trade("MES", pnl=-10.0)
        safety = SafetyLayer(mock_settings, loss_tracker=tracker)
        result = safety.reset_loss_tracker()
        assert "Reset successful" in result.get("status", "")

    def test_loss_tracker_adjustment_halted_returns_reject(self, mock_settings):
        """When loss_tracker.is_halted() is True, check_order must reject."""
        _live_settings(mock_settings)
        from risk.loss_tracker import ConsecutiveLossTracker

        tmpdir = tempfile.mkdtemp()
        # Force halt: default halt at 7 losses
        tracker = ConsecutiveLossTracker(data_dir=tmpdir, consecutive_loss_halt=7)
        for _ in range(7):
            tracker.record_trade("MES", pnl=-10.0)
        assert tracker.is_halted() is True

        safety = SafetyLayer(mock_settings, loss_tracker=tracker)
        order = OrderRequest(
            symbol="MES",
            quantity=1,
            order_type="market",
            estimated_value=500.0,
        )
        result = safety.check_order(order, 100_000.0)
        assert result.approved is False

    def test_loss_tracker_reduces_position_size(self, mock_settings):
        """3 consecutive losses → 0.5x multiplier → adjusted_order.quantity reduced."""
        _live_settings(mock_settings)
        from risk.loss_tracker import ConsecutiveLossTracker

        tmpdir = tempfile.mkdtemp()
        tracker = ConsecutiveLossTracker(
            data_dir=tmpdir,
            consecutive_loss_half_size=3,
            consecutive_loss_halt=100,  # won't halt in test
        )
        for _ in range(3):
            tracker.record_trade("MES", pnl=-10.0)

        safety = SafetyLayer(mock_settings, loss_tracker=tracker)
        order = OrderRequest(
            symbol="MES",
            quantity=4,
            order_type="market",
            estimated_value=2000.0,
        )
        result = safety.check_order(order, 100_000.0)
        assert result.approved is True
        assert result.adjusted_order is not None
        assert abs(result.adjusted_order.quantity) < 4  # reduced from 4


class TestReentryLockout:
    def test_lockout_set_after_losing_trade(self, mock_settings):
        safety = SafetyLayer(mock_settings)
        safety.record_trade_result("MES", pnl=-50.0)
        status = safety.get_lockout_status("MES")
        assert status["locked"] is True

    def test_no_lockout_after_winning_trade(self, mock_settings):
        safety = SafetyLayer(mock_settings)
        safety.record_trade_result("MES", pnl=50.0)
        status = safety.get_lockout_status("MES")
        assert status["locked"] is False

    def test_lockout_blocks_reentry(self, mock_settings):
        _live_settings(mock_settings)
        safety = SafetyLayer(mock_settings)
        # Simulate a recent stop-out — set lockout directly to avoid settings.REENTRY_LOCKOUT_MINUTES
        safety._reentry_lockouts["MES"] = datetime.now() + timedelta(hours=4)

        order = OrderRequest(
            symbol="MES",
            quantity=1,
            order_type="market",
            estimated_value=500.0,
        )
        result = safety.check_order(order, 100_000.0)
        assert result.approved is False
        assert "RE_ENTRY_LOCKOUT" in result.rejection_reason

    def test_expired_lockout_does_not_block(self, mock_settings):
        _live_settings(mock_settings)
        safety = SafetyLayer(mock_settings)
        # Expired lockout
        safety._reentry_lockouts["MES"] = datetime.now() - timedelta(seconds=1)

        order = OrderRequest(
            symbol="MES",
            quantity=1,
            order_type="market",
            estimated_value=500.0,
        )
        result = safety.check_order(order, 100_000.0)
        assert result.approved is True


class TestOrdersInLastMinute:
    def test_starts_at_zero(self, mock_settings):
        safety = SafetyLayer(mock_settings)
        assert safety.orders_in_last_minute() == 0

    def test_reflects_approved_orders(self, mock_settings):
        _live_settings(mock_settings)
        safety = SafetyLayer(mock_settings)
        order = OrderRequest(
            symbol="MES",
            quantity=1,
            order_type="market",
            estimated_value=500.0,
        )
        safety.check_order(order, 100_000.0)
        assert safety.orders_in_last_minute() == 1


class TestResetDailyPnl:
    def test_reset_clears_pnl_counter(self, mock_settings):
        safety = SafetyLayer(mock_settings)
        safety._daily_realized_pnl = -500.0
        result = safety.reset_daily_pnl()
        assert result["status"] == "ok"
        assert safety._daily_realized_pnl == 0.0


class TestGetRecommendedSize:
    def test_returns_dict_with_expected_keys(self, mock_settings):
        safety = SafetyLayer(mock_settings)
        result = safety.get_recommended_size(
            symbol="MES",
            atr=5.0,
            account_value=10_000.0,
            current_drawdown=0.0,
        )
        expected_keys = {
            "symbol",
            "recommended_contracts",
            "hardcoded_max_contracts",
            "sizing_method",
        }
        assert expected_keys.issubset(result.keys())

    def test_recommended_does_not_exceed_hard_cap(self, mock_settings):
        mock_settings.MAX_CONTRACTS_PER_INSTRUMENT = 2
        safety = SafetyLayer(mock_settings)
        result = safety.get_recommended_size(
            symbol="MES",
            atr=0.01,  # tiny ATR → large contracts_from_risk
            account_value=1_000_000.0,
            current_drawdown=0.0,
        )
        assert result["recommended_contracts"] <= 2


class TestAttachMethods:
    def test_attach_ib_gateway_sets_gateway(self, mock_settings):
        safety = SafetyLayer(mock_settings)
        mock_gw = MagicMock()
        safety.attach_ib_gateway(mock_gw)
        assert safety._ib_gateway is mock_gw

    def test_attach_schwab_sets_connector(self, mock_settings):
        safety = SafetyLayer(mock_settings)
        mock_schwab = MagicMock()
        safety.attach_schwab(mock_schwab)
        assert safety.schwab is mock_schwab

    def test_inject_alert_manager_sets_manager(self, mock_settings):
        safety = SafetyLayer(mock_settings)
        mock_am = MagicMock()
        safety.inject_alert_manager(mock_am)
        assert safety._alert_manager is mock_am


class TestKillSwitchStringConversion:
    def test_string_reason_converted_to_enum(self, mock_settings):
        safety = SafetyLayer(mock_settings)
        safety.activate_kill_switch("MANUAL", "test")
        assert safety._kill_switch_reason == KillSwitchReason.MANUAL

    def test_unknown_string_reason_falls_back_to_manual(self, mock_settings):
        safety = SafetyLayer(mock_settings)
        safety.activate_kill_switch("NONEXISTENT_REASON", "test")
        assert safety._kill_switch_reason == KillSwitchReason.MANUAL


class TestTradeLossGate:
    def test_trade_loss_gate_rejects_high_risk_order(self, mock_settings):
        """Stop too far from entry → potential loss > MAX_TRADE_LOSS_USD ($50)."""
        _live_settings(mock_settings)
        mock_settings.MAX_TRADE_LOSS_USD = 50.0
        safety = SafetyLayer(mock_settings)
        # MES: 10 pts * 5.0 multiplier * 1 contract = $50.00 (at limit, NOT over)
        # Use 11 pts → $55 > $50
        order = OrderRequest(
            symbol="MES",
            quantity=1,
            order_type="limit",
            is_futures=True,
            limit_price=5800.0,
            stop_price=5789.0,  # 11 pts from entry × $5 multiplier = $55 > $50
            estimated_value=5800.0,
        )
        result = safety.check_order(order, 100_000.0)
        assert result.approved is False
        assert "TRADE_LOSS_LIMIT" in result.rejection_reason

    def test_trade_loss_gate_allows_safe_order(self, mock_settings):
        _live_settings(mock_settings)
        mock_settings.MAX_TRADE_LOSS_USD = 50.0
        safety = SafetyLayer(mock_settings)
        # 5 pts * $5 multiplier * 1 contract = $25 < $50
        order = OrderRequest(
            symbol="MES",
            quantity=1,
            order_type="limit",
            is_futures=True,
            limit_price=5800.0,
            stop_price=5795.0,  # 5 pts × $5 = $25 < $50
            estimated_value=5800.0,
        )
        result = safety.check_order(order, 100_000.0)
        assert result.approved is True

    def test_no_stop_price_passes_gate(self, mock_settings):
        _live_settings(mock_settings)
        safety = SafetyLayer(mock_settings)
        order = OrderRequest(
            symbol="MES",
            quantity=1,
            order_type="market",
            is_futures=True,
            stop_price=None,
            estimated_value=500.0,
        )
        result = safety.check_order(order, 100_000.0)
        # No stop price → trade loss gate passes
        assert result.approved is True


class TestDrawdownWarningViaCheckOrder:
    def test_drawdown_warning_at_80pct_via_pnl_monitor(self, mock_settings):
        """When PnLMonitor is injected, drawdown check uses it."""
        _live_settings(mock_settings)
        mock_settings.MAX_DRAWDOWN_PCT = 0.10

        from risk.pnl_monitor import PnLState

        mock_monitor = MagicMock()
        # 8.5% drawdown → 85% of 10% limit → warning
        # _check_drawdown uses -pnl_monitor.get_drawdown_pct() as drawdown
        mock_monitor.get_drawdown_pct.return_value = -0.085  # negative = down 8.5%
        # _check_daily_loss_limit calls get_current_pnl_state() — return a real PnLState
        mock_monitor.get_current_pnl_state.return_value = PnLState(
            daily_realized_pnl=0.0,
            daily_unrealized_pnl=0.0,
            total_pnl=0.0,
        )

        safety = SafetyLayer(mock_settings, pnl_monitor=mock_monitor)
        order = OrderRequest(
            symbol="MES",
            quantity=1,
            order_type="market",
            estimated_value=500.0,
        )
        result = safety.check_order(order, 100_000.0)
        assert result.approved is True
        assert any("approaching" in w.lower() for w in result.warnings)

    def test_drawdown_kill_switch_via_pnl_monitor(self, mock_settings):
        """PnLMonitor reports >10% → kill switch fires."""
        _live_settings(mock_settings)
        mock_settings.MAX_DRAWDOWN_PCT = 0.10

        from risk.pnl_monitor import PnLState

        mock_monitor = MagicMock()
        # get_drawdown_pct returns negative fraction; _check_drawdown negates it
        # so drawdown = -(-0.12) = 0.12 > 0.10 limit
        mock_monitor.get_drawdown_pct.return_value = -0.12  # 12% down
        mock_monitor.get_current_pnl_state.return_value = PnLState(
            daily_realized_pnl=0.0,
            daily_unrealized_pnl=0.0,
            total_pnl=0.0,
        )

        safety = SafetyLayer(mock_settings, pnl_monitor=mock_monitor)
        order = OrderRequest(
            symbol="MES",
            quantity=1,
            order_type="market",
            estimated_value=500.0,
        )
        result = safety.check_order(order, 100_000.0)
        assert result.approved is False
        assert safety.is_killed is True
        assert safety._kill_switch_reason == KillSwitchReason.MAX_DRAWDOWN
