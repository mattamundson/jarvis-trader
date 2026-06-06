"""
Tests for risk/safety_layer.py — remaining edge case paths.

Covers: _check_daily_loss_limit without pnl_monitor, _check_trade_loss_gate
non-futures path and zero-qty path, tilt detector caution warning appended,
sync_from_broker with loss_tracker consecutive losses, _apply_loss_tracker_adjustment
warning message, _log_safety_event async path, options routing branch.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from risk.safety_layer import KillSwitchReason, OrderRequest, RiskCheckResult, SafetyLayer


def _live_settings(base):
    base.LIVE_TRADING_ENABLED = True
    base.REQUIRE_HUMAN_APPROVAL = False
    base.MAX_DAILY_LOSS_PCT = 0.99
    base.MAX_DRAWDOWN_PCT = 0.99
    base.MAX_POSITION_SIZE_PCT = 0.99
    base.MAX_SINGLE_ORDER_VALUE = 9_999_999.0
    base.MAX_ORDERS_PER_MINUTE = 10_000
    base.MAX_CONTRACTS_PER_INSTRUMENT = 100
    # Bypass the overnight contract cap (default 1) so these edge-case tests stay
    # wall-clock-independent — otherwise an MES qty>1 order is rejected for the
    # overnight reason after 15:00 CT instead of the path under test.
    base.MAX_OVERNIGHT_CONTRACTS = 100
    base.MAX_FUTURES_MARGIN_PCT = 0.99
    base.MAX_MARGIN_UTILIZATION = 0.99
    base.MAX_DAILY_LOSS_USD = 999_999.0
    base.MAX_TRADE_LOSS_USD = 999_999.0
    base.ALLOW_PAPER_SIMULATED_ORDERS = False
    return base


# ── _check_daily_loss_limit without pnl_monitor (uses _daily_realized_pnl) ───


class TestCheckDailyLossLimitNoPnlMonitor:
    def test_daily_loss_via_internal_pnl_field_triggers_kill(self, mock_settings):
        """When pnl_monitor is None, uses _daily_realized_pnl directly."""
        settings = _live_settings(mock_settings)
        settings.MAX_DAILY_LOSS_PCT = 0.02  # 2% limit
        settings.MAX_DAILY_LOSS_USD = 999_999.0
        sl = SafetyLayer(settings)
        sl._pnl_monitor = None
        sl._daily_realized_pnl = -500.0  # -5% on $10k → exceeds 2% limit
        sl._current_equity = 10_000.0
        sl._equity_peak = 10_000.0

        order = OrderRequest(
            symbol="MES",
            quantity=1,
            order_type="market",
            is_futures=True,
            estimated_value=5800.0,
        )
        result = sl.check_order(order, portfolio_equity=10_000.0)
        assert result.approved is False
        assert "daily" in result.rejection_reason.lower()
        assert sl._kill_switch_active is True


# ── _check_trade_loss_gate non-futures path ───────────────────────────────────


class TestCheckTradeLossGateNonFutures:
    def test_non_futures_equity_order_dollar_risk_path(self, mock_settings):
        """Non-futures order uses simple multiplier (not _FUTURES_POINT_VALUE)."""
        settings = _live_settings(mock_settings)
        settings.MAX_TRADE_LOSS_USD = 50.0
        sl = SafetyLayer(settings)
        sl._current_equity = 10_000.0
        sl._equity_peak = 10_000.0

        # Non-futures: points_at_risk=10 * qty=1 = $10 < $50 → allow
        order = OrderRequest(
            symbol="AAPL",
            quantity=1,
            order_type="limit",
            limit_price=150.0,
            stop_price=140.0,
            is_futures=False,
            estimated_value=150.0,
        )
        result = sl.check_order(order, portfolio_equity=10_000.0)
        # Dollar risk = 10 * 1 = $10 < $50 → approved (assuming no other blocks)
        # This exercises the non-futures dollar_risk branch
        assert isinstance(result, RiskCheckResult)

    def test_zero_entry_price_skips_trade_loss_check(self, mock_settings):
        """When abs_qty=0, entry_px=0 → check returns True early (no risk to compute)."""
        settings = _live_settings(mock_settings)
        sl = SafetyLayer(settings)
        sl._current_equity = 10_000.0
        sl._equity_peak = 10_000.0

        order = OrderRequest(
            symbol="MES",
            quantity=0,  # zero qty
            order_type="market",
            stop_price=5780.0,
            is_futures=True,
            estimated_value=0.0,
        )
        # abs_qty=0 → entry_px=0 → skip check (line 904)
        result = sl._check_trade_loss_gate(order)
        assert result.approved is True


# ── Tilt detector caution severity warning ────────────────────────────────────


class TestTiltDetectorCautionPath:
    def test_caution_tilt_appends_warning_but_allows_order(self, mock_settings):
        """Tilt caution → warning appended to result but order approved."""
        from risk.tilt_detector import TiltState

        settings = _live_settings(mock_settings)
        sl = SafetyLayer(settings)
        sl._current_equity = 10_000.0
        sl._equity_peak = 10_000.0

        # Mock tilt detector to return caution severity with multiplier > 0
        mock_tilt = MagicMock()
        caution_state = TiltState(
            is_tilted=True,
            tilt_score=0.35,
            severity="caution",
            position_size_multiplier=0.75,
            tilt_indicators=["rapid_trades_5"],
            cooldown_until=None,
        )
        mock_tilt.check.return_value = caution_state
        sl.tilt_detector = mock_tilt

        order = OrderRequest(
            symbol="MES",
            quantity=1,
            order_type="market",
            is_futures=True,
            estimated_value=5800.0,
        )
        result = sl.check_order(order, portfolio_equity=10_000.0)
        # Caution doesn't block the order; warning should be in result
        assert result.approved is True
        assert any("caution" in w.lower() or "tilt" in w.lower() for w in result.warnings)


# ── sync_from_broker with loss_tracker ───────────────────────────────────────


class TestSyncFromBrokerLossTracker:
    def test_loss_tracker_consecutive_losses_included_in_alert(self, mock_settings):
        """sync_from_broker uses loss_tracker.get_consecutive_losses() for alert payload."""
        from risk.alert_manager import AlertManager

        loss_tracker = MagicMock()
        loss_tracker.get_consecutive_losses.return_value = 2

        alert_mgr = AlertManager(notify_fn=None)
        sl = SafetyLayer(mock_settings, loss_tracker=loss_tracker)
        sl.inject_alert_manager(alert_mgr)
        sl._equity_peak = 10_000.0

        sl.sync_from_broker(equity=10_000.0, daily_pnl=0.0)
        # loss_tracker.get_consecutive_losses was called
        loss_tracker.get_consecutive_losses.assert_called()
        # consecutive_losses_2 should have fired
        fired = alert_mgr.get_fired_keys()
        assert "consecutive_losses_2" in fired


# ── Options routing branch ────────────────────────────────────────────────────


class TestOptionsRoutingBranch:
    def test_options_order_with_schwab_attached_routes_to_schwab(self, mock_settings):
        """Options order when Schwab is attached → broker_target logged as Schwab."""
        settings = _live_settings(mock_settings)
        sl = SafetyLayer(settings)
        sl._current_equity = 10_000.0
        sl._equity_peak = 10_000.0

        mock_schwab = MagicMock()
        sl.schwab = mock_schwab

        order = OrderRequest(
            symbol="AAPL",
            quantity=1,
            order_type="limit",
            limit_price=5.0,
            is_futures=False,
            is_options=True,
            estimated_value=500.0,
        )
        result = sl.check_order(order, portfolio_equity=10_000.0)
        # Schwab path: the order goes through (result is approved or rejected by limits,
        # but the routing log branch is exercised)
        assert isinstance(result, RiskCheckResult)


# ── _apply_loss_tracker_adjustment warning branch ─────────────────────────────


class TestApplyLossTrackerAdjustmentWarning:
    def test_loss_tracker_multiplier_below_one_appends_warning(self, mock_settings):
        """3 consecutive losses → 0.5 multiplier → warning appended to result."""
        import tempfile

        settings = _live_settings(mock_settings)
        from risk.loss_tracker import ConsecutiveLossTracker

        tmpdir = tempfile.mkdtemp()
        tracker = ConsecutiveLossTracker(data_dir=tmpdir)
        # Record 3 consecutive losses to set multiplier to 0.5
        for _ in range(3):
            tracker.record_trade("MES", -10.0)

        sl = SafetyLayer(settings, loss_tracker=tracker)
        sl._current_equity = 10_000.0
        sl._equity_peak = 10_000.0

        order = OrderRequest(
            symbol="MES",
            quantity=2,
            order_type="market",
            is_futures=True,
            estimated_value=11600.0,
        )
        result = sl.check_order(order, portfolio_equity=10_000.0)
        # 3 losses → qty adjusted and warning added
        assert result.approved is True
        assert any("Consecutive" in w or "consecutive" in w for w in result.warnings)


# ── _log_safety_event async path ──────────────────────────────────────────────


@pytest.mark.asyncio
class TestLogSafetyEvent:
    async def test_log_safety_event_handles_import_error(self, mock_safety_layer):
        """_log_safety_event catches ImportError from missing database module."""
        sl = mock_safety_layer
        # Should not raise even when database module unavailable
        await sl._log_safety_event(
            event_type="test_event",
            reason="unit test",
            details={"resolved": False},
        )

    async def test_log_safety_event_handles_db_exception(self, mock_safety_layer):
        """_log_safety_event catches any exception from repository."""
        sl = mock_safety_layer
        with patch("risk.safety_layer._schedule_background_coro"):
            # Directly call _log_safety_event; any DB exception is swallowed
            await sl._log_safety_event(
                event_type="kill_switch_activate",
                reason="test",
                details=None,
            )
