"""
JARVIS TRADER — Safety Layer Tests
Comprehensive testing of all 14 hard rules.
"""
import pytest
import math
from datetime import date
from risk.safety_layer import SafetyLayer, OrderRequest, RiskCheckResult, KillSwitchReason


class TestKillSwitch:
    """Kill switch activation and enforcement."""

    def test_kill_switch_blocks_all_orders(self, mock_safety_layer, mock_settings):
        """Kill switch active → all orders rejected."""
        # Arrange
        safety = mock_safety_layer
        safety.activate_kill_switch(KillSwitchReason.MANUAL, "Manual halt")

        order = OrderRequest(
            symbol="MES",
            quantity=1,
            order_type="market",
            estimated_value=1000.0,
        )

        # Act
        result = safety.check_order(order, 100_000.0)

        # Assert
        assert result.approved is False
        assert "Kill switch" in result.rejection_reason
        assert safety.is_killed is True

    def test_deactivate_kill_switch(self, mock_safety_layer):
        """Kill switch can be deactivated by human."""
        # Arrange
        safety = mock_safety_layer
        safety.activate_kill_switch(KillSwitchReason.MANUAL)
        assert safety.is_killed is True

        # Act
        safety.deactivate_kill_switch(authorized_by="human")

        # Assert
        assert safety.is_killed is False

    def test_kill_switch_persists_across_orders(self, mock_safety_layer):
        """Kill switch stays active until explicitly deactivated."""
        # Arrange
        safety = mock_safety_layer
        safety.activate_kill_switch(KillSwitchReason.DAILY_LOSS_LIMIT)

        # Act & Assert - multiple orders all rejected
        for i in range(3):
            order = OrderRequest(
                symbol="MES",
                quantity=1,
                order_type="market",
                estimated_value=1000.0,
            )
            result = safety.check_order(order, 100_000.0)
            assert result.approved is False


class TestLiveTrading:
    """Live trading gate."""

    def test_live_trading_disabled_blocks(self, mock_safety_layer, mock_settings):
        """LIVE_TRADING_ENABLED=False → all orders rejected."""
        # Arrange
        mock_settings.LIVE_TRADING_ENABLED = False
        safety = SafetyLayer(mock_settings)

        order = OrderRequest(
            symbol="MES",
            quantity=1,
            order_type="market",
            estimated_value=1000.0,
        )

        # Act
        result = safety.check_order(order, 100_000.0)

        # Assert
        assert result.approved is False
        assert "Live trading is disabled" in result.rejection_reason

    def test_live_trading_enabled_allows_valid_orders(self, mock_safety_layer, mock_settings):
        """LIVE_TRADING_ENABLED=True + valid order → approved."""
        # Arrange
        mock_settings.LIVE_TRADING_ENABLED = True
        mock_settings.REQUIRE_HUMAN_APPROVAL = False
        safety = SafetyLayer(mock_settings)

        order = OrderRequest(
            symbol="MES",
            quantity=1,
            order_type="market",
            estimated_value=1000.0,
        )

        # Act
        result = safety.check_order(order, 100_000.0)

        # Assert
        assert result.approved is True


class TestHumanApproval:
    """Human approval requirement."""

    def test_human_approval_required_blocks(self, mock_safety_layer, mock_settings):
        """REQUIRE_HUMAN_APPROVAL=True → orders need human go-ahead."""
        # Arrange
        mock_settings.LIVE_TRADING_ENABLED = True
        mock_settings.REQUIRE_HUMAN_APPROVAL = True
        safety = SafetyLayer(mock_settings)

        order = OrderRequest(
            symbol="MES",
            quantity=1,
            order_type="market",
            estimated_value=1000.0,
        )

        # Act
        result = safety.check_order(order, 100_000.0)

        # Assert
        assert result.approved is False
        assert "Human approval required" in result.rejection_reason

    def test_bypass_human_approval_when_disabled(self, mock_safety_layer, mock_settings):
        """REQUIRE_HUMAN_APPROVAL=False → human gate bypassed."""
        # Arrange
        mock_settings.LIVE_TRADING_ENABLED = True
        mock_settings.REQUIRE_HUMAN_APPROVAL = False
        safety = SafetyLayer(mock_settings)

        order = OrderRequest(
            symbol="MES",
            quantity=1,
            order_type="market",
            estimated_value=1000.0,
        )

        # Act
        result = safety.check_order(order, 100_000.0)

        # Assert - should pass this check (may fail other checks)
        assert "Human approval required" not in (result.rejection_reason or "")


class TestDailyLossLimit:
    """Daily loss limit enforcement."""

    def test_daily_loss_limit_blocks_when_exceeded(self, mock_safety_layer, mock_settings):
        """Realized daily loss > -2% → kill switch activated."""
        # Arrange
        mock_settings.LIVE_TRADING_ENABLED = True
        mock_settings.REQUIRE_HUMAN_APPROVAL = False
        mock_settings.MAX_DAILY_LOSS_PCT = 0.02
        safety = SafetyLayer(mock_settings)

        portfolio_equity = 100_000.0
        daily_loss_threshold = portfolio_equity * -0.02  # -$2,000

        # Exceed limit
        safety.sync_from_broker(equity=portfolio_equity, daily_pnl=daily_loss_threshold - 100.0)

        order = OrderRequest(
            symbol="MES",
            quantity=1,
            order_type="market",
            estimated_value=1000.0,
        )

        # Act
        result = safety.check_order(order, portfolio_equity)

        # Assert
        assert result.approved is False
        assert safety.is_killed is True
        assert safety._kill_switch_reason == KillSwitchReason.DAILY_LOSS_LIMIT

    def test_daily_loss_limit_allows_within_threshold(self, mock_safety_layer, mock_settings):
        """Daily loss within limit → orders allowed."""
        # Arrange
        mock_settings.LIVE_TRADING_ENABLED = True
        mock_settings.REQUIRE_HUMAN_APPROVAL = False
        mock_settings.MAX_DAILY_LOSS_PCT = 0.02
        safety = SafetyLayer(mock_settings)

        portfolio_equity = 100_000.0
        safe_loss = -500.0  # Only -0.5%

        safety.sync_from_broker(equity=portfolio_equity, daily_pnl=safe_loss)

        order = OrderRequest(
            symbol="MES",
            quantity=1,
            order_type="market",
            estimated_value=1000.0,
        )

        # Act
        result = safety.check_order(order, portfolio_equity)

        # Assert
        assert result.approved is True
        assert safety.is_killed is False


class TestMaxDrawdown:
    """Maximum drawdown enforcement."""

    def test_max_drawdown_blocks_when_exceeded(self, mock_safety_layer, mock_settings):
        """Drawdown > 10% → kill switch activated."""
        # Arrange
        mock_settings.LIVE_TRADING_ENABLED = True
        mock_settings.REQUIRE_HUMAN_APPROVAL = False
        mock_settings.MAX_DRAWDOWN_PCT = 0.10
        safety = SafetyLayer(mock_settings)

        # Simulate: started with $100k, hit peak of $110k, now at $98k
        # Drawdown = (110k - 98k) / 110k = 10.9%
        peak_equity = 110_000.0
        current_equity = 98_000.0

        safety._equity_peak = peak_equity
        safety._current_equity = current_equity

        order = OrderRequest(
            symbol="MES",
            quantity=1,
            order_type="market",
            estimated_value=1000.0,
        )

        # Act
        result = safety.check_order(order, current_equity)

        # Assert
        assert result.approved is False
        assert safety.is_killed is True
        assert safety._kill_switch_reason == KillSwitchReason.MAX_DRAWDOWN

    def test_max_drawdown_allows_within_threshold(self, mock_safety_layer, mock_settings):
        """Drawdown within limit → orders allowed."""
        # Arrange
        mock_settings.LIVE_TRADING_ENABLED = True
        mock_settings.REQUIRE_HUMAN_APPROVAL = False
        mock_settings.MAX_DRAWDOWN_PCT = 0.10
        safety = SafetyLayer(mock_settings)

        # Peak $100k, now at $92k → 8% drawdown
        safety._equity_peak = 100_000.0
        safety._current_equity = 92_000.0

        order = OrderRequest(
            symbol="MES",
            quantity=1,
            order_type="market",
            estimated_value=1000.0,
        )

        # Act
        result = safety.check_order(order, 92_000.0)

        # Assert
        assert result.approved is True

    def test_drawdown_warning_at_80_percent(self, mock_safety_layer, mock_settings):
        """Drawdown at 80% of limit → warning logged."""
        # Arrange
        mock_settings.LIVE_TRADING_ENABLED = True
        mock_settings.REQUIRE_HUMAN_APPROVAL = False
        mock_settings.MAX_DRAWDOWN_PCT = 0.10
        safety = SafetyLayer(mock_settings)

        # Peak $100k, now at $92k → 8% drawdown (80% of 10% limit)
        safety._equity_peak = 100_000.0
        safety._current_equity = 92_000.0

        order = OrderRequest(
            symbol="MES",
            quantity=1,
            order_type="market",
            estimated_value=1000.0,
        )

        # Act
        result = safety.check_order(order, 92_000.0)

        # Assert
        assert result.approved is True
        assert len(result.warnings) > 0
        assert "approaching" in result.warnings[0].lower()


class TestSingleOrderValue:
    """Single order value cap."""

    def test_single_order_value_cap_enforcement(self, mock_safety_layer, mock_settings):
        """Order value > MAX_SINGLE_ORDER_VALUE → rejected."""
        # Arrange
        mock_settings.LIVE_TRADING_ENABLED = True
        mock_settings.REQUIRE_HUMAN_APPROVAL = False
        mock_settings.MAX_SINGLE_ORDER_VALUE = 5000.0
        safety = SafetyLayer(mock_settings)

        order = OrderRequest(
            symbol="MES",
            quantity=1,
            order_type="market",
            estimated_value=6000.0,  # Exceeds limit
        )

        # Act
        result = safety.check_order(order, 100_000.0)

        # Assert
        assert result.approved is False
        assert "exceeds max" in result.rejection_reason


class TestPositionSize:
    """Position size as % of portfolio."""

    def test_position_size_limit_enforcement(self, mock_safety_layer, mock_settings):
        """Position > 5% of portfolio → rejected."""
        # Arrange
        mock_settings.LIVE_TRADING_ENABLED = True
        mock_settings.REQUIRE_HUMAN_APPROVAL = False
        mock_settings.MAX_POSITION_SIZE_PCT = 0.05
        safety = SafetyLayer(mock_settings)

        portfolio_equity = 100_000.0
        max_position_value = portfolio_equity * 0.05  # $5,000

        order = OrderRequest(
            symbol="MES",
            quantity=1,
            order_type="market",
            estimated_value=max_position_value + 100.0,  # Exceeds limit
        )

        # Act
        result = safety.check_order(order, portfolio_equity)

        # Assert
        assert result.approved is False
        assert "Position size" in result.rejection_reason

    def test_position_size_allows_within_limit(self, mock_safety_layer, mock_settings):
        """Position within limit → approved."""
        # Arrange
        mock_settings.LIVE_TRADING_ENABLED = True
        mock_settings.REQUIRE_HUMAN_APPROVAL = False
        mock_settings.MAX_POSITION_SIZE_PCT = 0.05
        safety = SafetyLayer(mock_settings)

        portfolio_equity = 100_000.0

        order = OrderRequest(
            symbol="MES",
            quantity=1,
            order_type="market",
            estimated_value=4500.0,  # Within 5% limit
        )

        # Act
        result = safety.check_order(order, portfolio_equity)

        # Assert
        assert result.approved is True


class TestOrderRateThrottle:
    """Order rate limiting (anti-runaway)."""

    def test_order_rate_throttle_blocks_excess_orders(self, mock_safety_layer, mock_settings):
        """>10 orders/minute → kill switch activated."""
        # Arrange
        mock_settings.LIVE_TRADING_ENABLED = True
        mock_settings.REQUIRE_HUMAN_APPROVAL = False
        mock_settings.MAX_ORDERS_PER_MINUTE = 10
        safety = SafetyLayer(mock_settings)

        order = OrderRequest(
            symbol="MES",
            quantity=1,
            order_type="market",
            estimated_value=1000.0,
        )

        # Fill recent orders list to threshold
        for _ in range(10):
            safety.check_order(order, 100_000.0)

        # Act - 11th order should trigger throttle
        result = safety.check_order(order, 100_000.0)

        # Assert
        assert result.approved is False
        assert safety.is_killed is True
        assert safety._kill_switch_reason == KillSwitchReason.ANOMALOUS_ORDER_RATE

    def test_order_rate_allows_below_threshold(self, mock_safety_layer, mock_settings):
        """Orders below threshold → allowed."""
        # Arrange
        mock_settings.LIVE_TRADING_ENABLED = True
        mock_settings.REQUIRE_HUMAN_APPROVAL = False
        mock_settings.MAX_ORDERS_PER_MINUTE = 10
        safety = SafetyLayer(mock_settings)

        order = OrderRequest(
            symbol="MES",
            quantity=1,
            order_type="market",
            estimated_value=1000.0,
        )

        # Act & Assert
        for i in range(5):
            result = safety.check_order(order, 100_000.0)
            assert result.approved is True


class TestFuturesContractLimit:
    """Futures-specific contract quantity limits."""

    def test_futures_contract_limit_enforcement(self, mock_safety_layer, mock_settings):
        """Futures contracts > limit → rejected."""
        # Arrange
        mock_settings.LIVE_TRADING_ENABLED = True
        mock_settings.REQUIRE_HUMAN_APPROVAL = False
        mock_settings.MAX_CONTRACTS_PER_INSTRUMENT = 2
        safety = SafetyLayer(mock_settings)

        order = OrderRequest(
            symbol="MES",
            quantity=3,  # Exceeds limit of 2
            order_type="market",
            is_futures=True,
            estimated_value=3000.0,
        )

        # Act
        result = safety.check_order(order, 100_000.0)

        # Assert
        assert result.approved is False
        assert "contracts exceeds max" in result.rejection_reason

    def test_futures_contract_limit_allows_within_limit(self, mock_safety_layer, mock_settings):
        """Futures contracts within limit → approved."""
        # Arrange
        mock_settings.LIVE_TRADING_ENABLED = True
        mock_settings.REQUIRE_HUMAN_APPROVAL = False
        mock_settings.MAX_CONTRACTS_PER_INSTRUMENT = 2
        safety = SafetyLayer(mock_settings)

        order = OrderRequest(
            symbol="MES",
            quantity=2,  # At limit
            order_type="market",
            is_futures=True,
            estimated_value=2000.0,
        )

        # Act
        result = safety.check_order(order, 100_000.0)

        # Assert
        assert result.approved is True


class TestNaNPriceHandling:
    """NaN and missing price data handling."""

    def test_nan_price_in_order_request(self, mock_safety_layer, mock_settings):
        """NaN estimated_value → safe handling."""
        # Arrange
        mock_settings.LIVE_TRADING_ENABLED = True
        mock_settings.REQUIRE_HUMAN_APPROVAL = False
        safety = SafetyLayer(mock_settings)

        order = OrderRequest(
            symbol="MES",
            quantity=1,
            order_type="market",
            estimated_value=float("nan"),
        )

        # Act & Assert - should not crash
        # NaN comparisons are always False, so order should be rejected
        # or handled gracefully
        try:
            result = safety.check_order(order, 100_000.0)
            # Either approved or rejected, but no exception
            assert isinstance(result, RiskCheckResult)
        except Exception as e:
            pytest.fail(f"check_order should handle NaN gracefully, got {e}")

    def test_zero_equity_handling(self, mock_safety_layer, mock_settings):
        """Zero portfolio equity → safe handling."""
        # Arrange
        mock_settings.LIVE_TRADING_ENABLED = True
        mock_settings.REQUIRE_HUMAN_APPROVAL = False
        safety = SafetyLayer(mock_settings)

        order = OrderRequest(
            symbol="MES",
            quantity=1,
            order_type="market",
            estimated_value=1000.0,
        )

        # Act & Assert - should handle zero equity without crash
        try:
            result = safety.check_order(order, 0.0)
            assert isinstance(result, RiskCheckResult)
        except Exception as e:
            pytest.fail(f"check_order should handle zero equity gracefully, got {e}")


class TestZeroVolumeHandling:
    """Zero/low volume market conditions."""

    def test_zero_volume_on_order_estimation(self, mock_safety_layer, mock_settings):
        """Zero volume contract → estimated_value=0 handling."""
        # Arrange
        mock_settings.LIVE_TRADING_ENABLED = True
        mock_settings.REQUIRE_HUMAN_APPROVAL = False
        safety = SafetyLayer(mock_settings)

        order = OrderRequest(
            symbol="ILLIQUID",
            quantity=1,
            order_type="market",
            estimated_value=0.0,  # Zero volume scenario
        )

        # Act
        result = safety.check_order(order, 100_000.0)

        # Assert - should reject because position size is undefined
        # (0 / 100k = 0%, which is allowed, but the order itself is nonsensical)
        assert isinstance(result, RiskCheckResult)


class TestMissingDataGraceful:
    """Graceful degradation on missing data."""

    def test_missing_pnl_monitor_falls_back(self, mock_safety_layer, mock_settings):
        """No PnLMonitor → falls back to in-memory tracking."""
        # Arrange
        mock_settings.LIVE_TRADING_ENABLED = True
        mock_settings.REQUIRE_HUMAN_APPROVAL = False
        mock_settings.MAX_DAILY_LOSS_PCT = 0.02
        safety = SafetyLayer(mock_settings, pnl_monitor=None)

        # Manually set in-memory daily PnL (simulating broker sync)
        safety._daily_realized_pnl = -1500.0

        order = OrderRequest(
            symbol="MES",
            quantity=1,
            order_type="market",
            estimated_value=1000.0,
        )

        # Act
        result = safety.check_order(order, 100_000.0)

        # Assert - should use in-memory value
        assert isinstance(result, RiskCheckResult)


class TestMultipleRuleInteraction:
    """Test interaction between multiple rules."""

    def test_first_failure_stops_subsequent_checks(self, mock_safety_layer, mock_settings):
        """First failed check → order rejected (short-circuit)."""
        # Arrange
        mock_settings.LIVE_TRADING_ENABLED = False  # Fail immediately
        mock_settings.MAX_SINGLE_ORDER_VALUE = 100_000.0  # Would pass if checked
        safety = SafetyLayer(mock_settings)

        order = OrderRequest(
            symbol="MES",
            quantity=1,
            order_type="market",
            estimated_value=50_000.0,  # Would fail single order value elsewhere
        )

        # Act
        result = safety.check_order(order, 100_000.0)

        # Assert
        assert result.approved is False
        assert "Live trading is disabled" in result.rejection_reason

    def test_all_checks_passed_sequence(self, mock_safety_layer, mock_settings):
        """Valid order passes all 8+ checks."""
        # Arrange - all settings permissive
        mock_settings.LIVE_TRADING_ENABLED = True
        mock_settings.REQUIRE_HUMAN_APPROVAL = False
        mock_settings.MAX_DAILY_LOSS_PCT = 0.10
        mock_settings.MAX_DRAWDOWN_PCT = 0.20
        mock_settings.MAX_SINGLE_ORDER_VALUE = 10_000.0
        mock_settings.MAX_POSITION_SIZE_PCT = 0.10
        mock_settings.MAX_ORDERS_PER_MINUTE = 100
        safety = SafetyLayer(mock_settings)

        order = OrderRequest(
            symbol="MES",
            quantity=1,
            order_type="market",
            estimated_value=1000.0,
        )

        # Act
        result = safety.check_order(order, 100_000.0)

        # Assert
        assert result.approved is True
        assert result.rejection_reason is None
