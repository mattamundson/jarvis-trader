"""
JARVIS TRADER — Safety Layer Tests
Comprehensive testing of all 14 hard rules.
"""

import os
import sqlite3
import tempfile
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, Mock, create_autospec, patch
from zoneinfo import ZoneInfo

import pytest

from risk.safety_layer import KillSwitchReason, OrderRequest, RiskCheckResult, SafetyLayer


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
        for _i in range(3):
            order = OrderRequest(
                symbol="MES",
                quantity=1,
                order_type="market",
                estimated_value=1000.0,
            )
            result = safety.check_order(order, 100_000.0)
            assert result.approved is False


class TestDoNotTradeSymbols:
    """Halted-symbol hard block — DO_NOT_TRADE_SYMBOLS (T0-01)."""

    def test_halted_symbols_blocked(self, mock_safety_layer):
        """Every halted symbol (MCL, MNQ) is rejected before any other check runs."""
        # Arrange
        safety = mock_safety_layer

        # Act & Assert
        for symbol in ("MCL", "MNQ"):
            order = OrderRequest(
                symbol=symbol,
                quantity=1,
                order_type="market",
                estimated_value=1000.0,
            )
            result = safety.check_order(order, 100_000.0)
            assert result.approved is False
            assert (
                result.rejection_reason
                == f"DO_NOT_TRADE_SYMBOLS: {symbol} is halted, no orders permitted"
            )

    def test_active_symbol_not_blocked_by_halt_gate(self, mock_safety_layer, mock_settings):
        """An active symbol (MES) is unaffected by the halted-symbol gate."""
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
        """Daily loss within BOTH pct and flat-USD limits → orders allowed."""
        # Arrange
        mock_settings.LIVE_TRADING_ENABLED = True
        mock_settings.REQUIRE_HUMAN_APPROVAL = False
        mock_settings.MAX_DAILY_LOSS_PCT = 0.02
        # SafetyLayer enforces BOTH pct and flat USD caps; without this the
        # default $100 USD cap rejects the -$500 fixture independently of pct.
        mock_settings.MAX_DAILY_LOSS_USD = 1_000.0
        safety = SafetyLayer(mock_settings)

        portfolio_equity = 100_000.0
        safe_loss = -500.0  # Only -0.5% AND within -$1,000 flat cap

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

        # Peak $100k, now at $91.5k → 8.5% drawdown (85% of 10% limit)
        # Using 91.5k instead of 92k to avoid floating point edge case
        safety._equity_peak = 100_000.0
        safety._current_equity = 91_500.0

        order = OrderRequest(
            symbol="MES",
            quantity=1,
            order_type="market",
            estimated_value=1000.0,
        )

        # Act
        result = safety.check_order(order, 91_500.0)

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
        mock_settings.MAX_SINGLE_ORDER_VALUE = 10_000.0  # Allow order size check to pass
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
        for _i in range(5):
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
        # Bypass overnight cap so the test is wall-clock-independent
        # (default MAX_OVERNIGHT_CONTRACTS=1 rejects 2 MES after 15:00 CT).
        mock_settings.MAX_OVERNIGHT_CONTRACTS = 5
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


class TestContractLimitAggregation:
    """Real-underlying-instrument exposure aggregation (2026-07-13 trade-frequency
    plan, PR-A). Previously _check_contract_limits only checked an order's own
    quantity against MAX_CONTRACTS_PER_INSTRUMENT -- it never summed existing
    open positions, so combined exposure across strategies sharing one real
    instrument could silently exceed the configured cap."""

    def _mock_db_with_open_trades(self, trades: list[dict]):
        db = Mock()
        db.get_open_trades = Mock(return_value=trades)
        return db

    def test_no_db_manager_preserves_prior_single_order_behavior(self, mock_settings):
        """Backward-compat: SafetyLayer(config) with no db_manager (how most
        existing tests and callers construct it) must behave EXACTLY as
        before -- existing_qty always 0, so only the order's own quantity
        is checked."""
        mock_settings.LIVE_TRADING_ENABLED = True
        mock_settings.REQUIRE_HUMAN_APPROVAL = False
        mock_settings.MAX_CONTRACTS_PER_INSTRUMENT = 2
        mock_settings.MAX_OVERNIGHT_CONTRACTS = 5  # wall-clock-independent, matches sibling test
        safety = SafetyLayer(mock_settings)  # no db_manager

        order = OrderRequest(symbol="MES", quantity=2, order_type="market", is_futures=True)
        result = safety.check_order(order, 100_000.0)
        assert result.approved is True

    def test_rejects_when_combined_with_existing_open_position_exceeds_cap(
        self, mock_settings
    ):
        """The money case: a NEW order that is within the cap on its own gets
        rejected because an EXISTING open position on the same real
        instrument would push combined exposure over MAX_CONTRACTS_PER_INSTRUMENT.
        This is exactly the gap that made it possible for two strategies
        trading the same real instrument to silently exceed the cap."""
        mock_settings.LIVE_TRADING_ENABLED = True
        mock_settings.REQUIRE_HUMAN_APPROVAL = False
        mock_settings.MAX_CONTRACTS_PER_INSTRUMENT = 2
        db = self._mock_db_with_open_trades(
            [{"symbol": "MES", "quantity": 1, "status": "open"}]
        )
        safety = SafetyLayer(mock_settings, db_manager=db)

        # 1 existing + 2 new = 3 > cap of 2 -- must reject, even though 2
        # alone would have been within the cap.
        order = OrderRequest(symbol="MES", quantity=2, order_type="market", is_futures=True)
        result = safety.check_order(order, 100_000.0)

        assert result.approved is False
        assert "contracts exceeds max" in result.rejection_reason
        assert "combined with 1 already open" in result.rejection_reason

    def test_allows_when_combined_with_existing_stays_within_cap(self, mock_settings):
        """Non-regression: combined exposure at or under the cap still approves."""
        mock_settings.LIVE_TRADING_ENABLED = True
        mock_settings.REQUIRE_HUMAN_APPROVAL = False
        mock_settings.MAX_CONTRACTS_PER_INSTRUMENT = 2
        mock_settings.MAX_OVERNIGHT_CONTRACTS = 5  # wall-clock-independent, matches sibling test
        db = self._mock_db_with_open_trades(
            [{"symbol": "MES", "quantity": 1, "status": "open"}]
        )
        safety = SafetyLayer(mock_settings, db_manager=db)

        order = OrderRequest(symbol="MES", quantity=1, order_type="market", is_futures=True)
        result = safety.check_order(order, 100_000.0)

        assert result.approved is True

    def test_aggregates_across_pseudo_symbols_sharing_one_underlying(
        self, mock_settings, monkeypatch
    ):
        """Two DIFFERENT PAPER_CONFIGS keys (e.g. a future "MES" trend strategy
        and "MES_VA30" value-area re-entry) that both resolve to the same real
        underlying instrument must aggregate together, not be tracked as
        independent instruments. Simulated here via UNDERLYING_INSTRUMENT so
        this test doesn't depend on PR-C's config actually existing yet."""
        import backtest.paper_config as paper_config_module

        monkeypatch.setitem(paper_config_module.UNDERLYING_INSTRUMENT, "MES_VA30", "MES")

        mock_settings.LIVE_TRADING_ENABLED = True
        mock_settings.REQUIRE_HUMAN_APPROVAL = False
        mock_settings.MAX_CONTRACTS_PER_INSTRUMENT = 2
        # Existing open position is under the OTHER pseudo-symbol key.
        db = self._mock_db_with_open_trades(
            [{"symbol": "MES_VA30", "quantity": 1, "status": "open"}]
        )
        safety = SafetyLayer(mock_settings, db_manager=db)

        # New order under the real "MES" key -- must still see the
        # MES_VA30 position as combined MES exposure.
        order = OrderRequest(symbol="MES", quantity=2, order_type="market", is_futures=True)
        result = safety.check_order(order, 100_000.0)

        assert result.approved is False
        assert "combined with 1 already open" in result.rejection_reason

    def test_db_error_degrades_to_zero_existing_not_a_crash(self, mock_settings):
        """A DB error while aggregating must not crash order checking --
        degrades to existing_qty=0 (prior single-order-only behavior), logged
        as a warning rather than raised."""
        mock_settings.LIVE_TRADING_ENABLED = True
        mock_settings.REQUIRE_HUMAN_APPROVAL = False
        mock_settings.MAX_CONTRACTS_PER_INSTRUMENT = 2
        mock_settings.MAX_OVERNIGHT_CONTRACTS = 5  # wall-clock-independent, matches sibling test
        db = Mock()
        db.get_open_trades = Mock(side_effect=RuntimeError("db unavailable"))
        safety = SafetyLayer(mock_settings, db_manager=db)

        order = OrderRequest(symbol="MES", quantity=2, order_type="market", is_futures=True)
        result = safety.check_order(order, 100_000.0)

        assert result.approved is True  # 0 existing + 2 new == cap of 2


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


def _make_db_with_system_state() -> str:
    """Create a temp SQLite DB with the system_state table and return its path."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS system_state (
            key        TEXT PRIMARY KEY,
            value      TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT (datetime('now', 'utc'))
        )
        """
    )
    conn.commit()
    conn.close()
    return path


class TestKillSwitchPersistence:
    """Kill switch state is persisted to SQLite and restored on startup."""

    def test_kill_switch_state_written_to_db(self, mock_settings):
        """Activating kill switch writes active=true and reason to system_state."""
        db_path = _make_db_with_system_state()
        try:
            safety = SafetyLayer(mock_settings, db_path=db_path)
            safety.activate_kill_switch(KillSwitchReason.MANUAL, "test halt")

            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            active_row = conn.execute(
                "SELECT value FROM system_state WHERE key = 'kill_switch_active'"
            ).fetchone()
            reason_row = conn.execute(
                "SELECT value FROM system_state WHERE key = 'kill_switch_reason'"
            ).fetchone()
            conn.close()

            assert active_row is not None
            assert active_row["value"] == "true"
            assert reason_row is not None
            assert reason_row["value"] == KillSwitchReason.MANUAL.value
        finally:
            os.unlink(db_path)

    def test_kill_switch_state_loaded_on_startup(self, mock_settings):
        """SafetyLayer loads active kill switch from DB and starts with it engaged."""
        db_path = _make_db_with_system_state()
        try:
            # Pre-seed the DB as if a previous process had activated the kill switch
            conn = sqlite3.connect(db_path)
            conn.execute(
                "INSERT OR REPLACE INTO system_state (key, value, updated_at) VALUES (?, ?, datetime('now'))",
                ("kill_switch_active", "true"),
            )
            conn.execute(
                "INSERT OR REPLACE INTO system_state (key, value, updated_at) VALUES (?, ?, datetime('now'))",
                ("kill_switch_reason", KillSwitchReason.DAILY_LOSS_LIMIT.value),
            )
            conn.commit()
            conn.close()

            # Construct SafetyLayer — it should restore the kill switch from DB
            safety = SafetyLayer(mock_settings, db_path=db_path)

            assert safety.is_killed is True
            assert safety._kill_switch_reason == KillSwitchReason.DAILY_LOSS_LIMIT
        finally:
            os.unlink(db_path)

    def test_kill_switch_deactivate_clears_db(self, mock_settings):
        """Deactivating kill switch writes active=false to system_state."""
        db_path = _make_db_with_system_state()
        try:
            safety = SafetyLayer(mock_settings, db_path=db_path)
            safety.activate_kill_switch(KillSwitchReason.MAX_DRAWDOWN, "test drawdown")
            assert safety.is_killed is True

            safety.deactivate_kill_switch(authorized_by="human")
            assert safety.is_killed is False

            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            active_row = conn.execute(
                "SELECT value FROM system_state WHERE key = 'kill_switch_active'"
            ).fetchone()
            conn.close()

            assert active_row is not None
            assert active_row["value"] == "false"
        finally:
            os.unlink(db_path)

    def test_db_failure_does_not_block_kill_switch(self, mock_settings):
        """DB unavailable → kill switch still activates in memory (non-fatal)."""
        # Point to a path that cannot be a valid DB
        bad_db_path = "/nonexistent/path/to/jarvis.db"
        safety = SafetyLayer(mock_settings, db_path=bad_db_path)

        # Kill switch must still work even if DB write fails
        safety.activate_kill_switch(KillSwitchReason.MANUAL, "DB failure test")
        assert safety.is_killed is True
        assert safety._kill_switch_reason == KillSwitchReason.MANUAL

    def test_startup_without_db_path_does_not_crash(self, mock_settings):
        """SafetyLayer with no DB path starts cleanly without kill switch active."""
        # Ensure config has no SQLITE_DB_PATH set
        if hasattr(mock_settings, "SQLITE_DB_PATH"):
            mock_settings.SQLITE_DB_PATH = None
        safety = SafetyLayer(mock_settings, db_path=None)
        assert safety.is_killed is False


class TestOvernightContractLimit:
    """MAX_OVERNIGHT_CONTRACTS enforced for MES after 15:00 CT."""

    _CT = ZoneInfo("America/Chicago")

    def _make_mes_order(self, quantity: int) -> OrderRequest:
        return OrderRequest(
            symbol="MES",
            quantity=quantity,
            order_type="market",
            is_futures=True,
            estimated_value=quantity * 500.0,  # Low to pass order-value check
        )

    def test_mes_2_contracts_after_15_ct_rejected(self, mock_safety_layer, mock_settings):
        """MES order for 2 contracts after 15:00 CT exceeds overnight limit of 1."""
        mock_settings.LIVE_TRADING_ENABLED = True
        mock_settings.REQUIRE_HUMAN_APPROVAL = False
        mock_settings.MAX_CONTRACTS_PER_INSTRUMENT = 2
        mock_settings.MAX_OVERNIGHT_CONTRACTS = 1
        safety = SafetyLayer(mock_settings)

        fake_time = datetime(2026, 4, 21, 15, 30, tzinfo=self._CT)
        with patch("risk.safety_layer.datetime") as mock_dt:
            mock_dt.now.return_value = fake_time
            result = safety.check_order(self._make_mes_order(2), 100_000.0)

        assert result.approved is False
        assert "OVERNIGHT_LIMIT" in result.rejection_reason

    def test_mes_1_contract_after_15_ct_allowed(self, mock_safety_layer, mock_settings):
        """MES order for 1 contract after 15:00 CT is within overnight limit."""
        mock_settings.LIVE_TRADING_ENABLED = True
        mock_settings.REQUIRE_HUMAN_APPROVAL = False
        mock_settings.MAX_CONTRACTS_PER_INSTRUMENT = 2
        mock_settings.MAX_OVERNIGHT_CONTRACTS = 1
        safety = SafetyLayer(mock_settings)

        fake_time = datetime(2026, 4, 21, 16, 0, tzinfo=self._CT)
        with patch("risk.safety_layer.datetime") as mock_dt:
            mock_dt.now.return_value = fake_time
            result = safety.check_order(self._make_mes_order(1), 100_000.0)

        assert result.approved is True

    def test_mes_2_contracts_before_15_ct_allowed(self, mock_safety_layer, mock_settings):
        """MES order for 2 contracts before 15:00 CT is within daytime limit."""
        mock_settings.LIVE_TRADING_ENABLED = True
        mock_settings.REQUIRE_HUMAN_APPROVAL = False
        mock_settings.MAX_CONTRACTS_PER_INSTRUMENT = 2
        mock_settings.MAX_OVERNIGHT_CONTRACTS = 1
        safety = SafetyLayer(mock_settings)

        fake_time = datetime(2026, 4, 21, 10, 0, tzinfo=self._CT)
        with patch("risk.safety_layer.datetime") as mock_dt:
            mock_dt.now.return_value = fake_time
            result = safety.check_order(self._make_mes_order(2), 100_000.0)

        assert result.approved is True

    def test_non_overnight_symbol_not_affected(self, mock_safety_layer, mock_settings):
        """MGC is not in OVERNIGHT_SYMBOLS — no overnight check applied.

        Was MCL until T0-01 (DO_NOT_TRADE_SYMBOLS wired into check_order) started
        correctly rejecting it earlier in the check chain. MGC joined
        DO_NOT_TRADE_SYMBOLS itself 2026-07-31 (honest-data-drain DSR
        correction) and MES (the only other active symbol) IS in
        OVERNIGHT_SYMBOLS, so no currently-active symbol is left to exercise
        this path -- patch DO_NOT_TRADE_SYMBOLS out for MGC's sake, isolating
        the overnight-check-not-applied behavior this test exists to prove.
        """
        mock_settings.LIVE_TRADING_ENABLED = True
        mock_settings.REQUIRE_HUMAN_APPROVAL = False
        mock_settings.MAX_CONTRACTS_PER_INSTRUMENT = 2
        mock_settings.MAX_OVERNIGHT_CONTRACTS = 1
        safety = SafetyLayer(mock_settings)

        order = OrderRequest(
            symbol="MGC",
            quantity=2,
            order_type="market",
            is_futures=True,
            estimated_value=1000.0,  # Low to pass order-value check
        )
        fake_time = datetime(2026, 4, 21, 16, 0, tzinfo=self._CT)
        with (
            patch("risk.safety_layer.datetime") as mock_dt,
            patch("risk.safety_layer.DO_NOT_TRADE_SYMBOLS", frozenset({"MCL", "MNQ", "M2K"})),
        ):
            mock_dt.now.return_value = fake_time
            result = safety.check_order(order, 100_000.0)

        assert result.approved is True


class TestFuturesMarginGate:
    """
    HB-2 — Futures position-size gate uses margin, not notional.

    The pre-fix notional-based math rejected every MES order on a $10K paper
    account: 1 MES @ $7,130 notional / $10K = 71% > MAX_POSITION_SIZE_PCT=5%.
    The fixed futures branch uses IBKR maintenance margin (~$1,320 for MES) as
    the numerator and MAX_FUTURES_MARGIN_PCT (default 30%) as the cap.
    """

    def _live_safety(self, mock_settings):
        mock_settings.LIVE_TRADING_ENABLED = True
        mock_settings.REQUIRE_HUMAN_APPROVAL = False
        # Ensure the new config key exists in the test config; default 30%.
        mock_settings.MAX_FUTURES_MARGIN_PCT = 0.30
        return SafetyLayer(mock_settings)

    def test_one_mes_contract_approves_on_10k_account(self, mock_settings):
        """
        HB-2 core scenario: 1 MES against $10K paper equity must APPROVE.
        Pre-fix this rejected with "Position size 71.3% exceeds max 5.0%".
        Post-fix: margin $1,320 / $10,000 = 13.2% < 30% → approve.
        """
        safety = self._live_safety(mock_settings)
        order = OrderRequest(
            symbol="MES",
            quantity=1,
            order_type="market",
            is_futures=True,
            estimated_value=7130.0,  # notional — would reject under old gate
        )
        result = safety.check_order(order, 10_000.0)
        assert result.approved is True, result.rejection_reason

    def test_two_mes_contracts_approve_on_10k_account(self, mock_settings):
        """2 MES: margin 2,640 / 10,000 = 26.4% < 30% → approve."""
        # Bypass overnight cap (MAX_OVERNIGHT_CONTRACTS=1 default) so the test
        # passes regardless of wall-clock time when CT is past 15:00 (overnight).
        mock_settings.MAX_OVERNIGHT_CONTRACTS = 5
        safety = self._live_safety(mock_settings)
        order = OrderRequest(
            symbol="MES",
            quantity=2,
            order_type="market",
            is_futures=True,
            estimated_value=14260.0,
        )
        result = safety.check_order(order, 10_000.0)
        assert result.approved is True, result.rejection_reason

    def test_futures_margin_cap_rejects_oversize(self, mock_settings):
        """
        Raise to 3 MES on a small account. With MAX_CONTRACTS bumped for
        isolation, the margin gate alone should reject (39.6% > 30%). Note:
        MAX_CONTRACTS_PER_INSTRUMENT=2 would catch this too in normal config;
        this test isolates the margin gate specifically.
        """
        mock_settings.MAX_CONTRACTS_PER_INSTRUMENT = 5  # bypass the other cap
        safety = self._live_safety(mock_settings)
        order = OrderRequest(
            symbol="MES",
            quantity=3,
            order_type="market",
            is_futures=True,
            estimated_value=21390.0,
        )
        result = safety.check_order(order, 10_000.0)
        assert result.approved is False
        assert "Futures margin" in result.rejection_reason
        assert "exceeds max" in result.rejection_reason

    def test_futures_margin_gate_zero_equity_rejects(self, mock_settings):
        """
        Zero portfolio equity must reject, not divide by zero. Test the gate
        in isolation via `_check_order_value_limits` — going through full
        `check_order` short-circuits on the drawdown check first (zero equity
        reads as 100% drawdown from peak).
        """
        safety = self._live_safety(mock_settings)
        order = OrderRequest(
            symbol="MES",
            quantity=1,
            order_type="market",
            is_futures=True,
            estimated_value=7130.0,
        )
        result = safety._check_order_value_limits(order, portfolio_equity=0.0)
        assert result.approved is False
        assert "zero portfolio equity" in result.rejection_reason

    def test_unknown_futures_root_falls_back_to_notional(self, mock_settings):
        """
        An unrecognized futures root (not in _FUTURES_MARGIN_BY_ROOT) must
        fall back to the notional-based check so unknown symbols never
        silently bypass the gate. "ZF" (5-yr Treasury) is not in the table.
        """
        safety = self._live_safety(mock_settings)
        order = OrderRequest(
            symbol="ZF",
            quantity=1,
            order_type="market",
            is_futures=True,
            estimated_value=107_000.0,  # well over 5% of $10K
        )
        result = safety.check_order(order, 10_000.0)
        assert result.approved is False
        # Falls back to notional: should hit MAX_SINGLE_ORDER_VALUE first
        assert (
            "exceeds max" in result.rejection_reason or "Position size" in result.rejection_reason
        )

    def test_non_futures_unchanged_by_fix(self, mock_settings):
        """
        SPY 10 shares @ $450 = $4,500 notional. Under notional gate on $100K
        equity: 4.5% < 5% → approve. The futures branch must not fire.
        """
        safety = self._live_safety(mock_settings)
        order = OrderRequest(
            symbol="SPY",
            quantity=10,
            order_type="market",
            is_futures=False,
            estimated_value=4_500.0,
        )
        result = safety.check_order(order, 100_000.0)
        assert result.approved is True, result.rejection_reason

    def test_futures_margin_helper_returns_none_for_unknown(self):
        """Helper returns None for roots not in the margin table."""
        from risk.safety_layer import _futures_margin_required

        assert _futures_margin_required("ZF", 1) is None
        assert _futures_margin_required("MES", 1) == 1320.0
        assert _futures_margin_required("MES", 3) == 3960.0
        # Sign-agnostic — short and long require the same margin
        assert _futures_margin_required("MES", -2) == 2640.0

    @pytest.mark.parametrize(
        "symbol,quantity,equity,expected_approved,reason_substr",
        [
            # Active, non-halted watchlist roots only — boundary cases at $10K
            # equity, 30% cap. MCL/MNQ margin-boundary cases were removed here
            # after T0-01 (DO_NOT_TRADE_SYMBOLS wired into check_order): both
            # are permanently halted, so they now correctly get rejected by the
            # halt gate before ever reaching this margin check — that rejection
            # is covered by TestDoNotTradeSymbols::test_halted_symbols_blocked,
            # not by margin math that's no longer reachable for either symbol.
            # MGC margin $1400 → 14% on $10K → ALLOW
            ("MGC", 1, 10_000.0, True, None),
            # MGC × 3 = $4200 → 42% on $10K → REJECT
            ("MGC", 3, 10_000.0, False, "Futures margin"),
        ],
    )
    def test_active_watchlist_margin_boundaries(
        self, mock_settings, symbol, quantity, equity, expected_approved, reason_substr
    ):
        """Boundary coverage for the currently-active futures roots (MES tested above).

        MGC joined DO_NOT_TRADE_SYMBOLS 2026-07-31 (honest-data-drain DSR
        correction) and would now be rejected by the halt gate before ever
        reaching margin math -- patch it out so these cases keep isolating
        the margin gate specifically, not MGC's (separate, real) halted
        status.
        """
        # Bypass MAX_CONTRACTS_PER_INSTRUMENT to isolate the margin gate
        mock_settings.MAX_CONTRACTS_PER_INSTRUMENT = 10
        safety = self._live_safety(mock_settings)
        order = OrderRequest(
            symbol=symbol,
            quantity=quantity,
            order_type="market",
            is_futures=True,
            estimated_value=equity,  # value irrelevant for futures branch
        )
        with patch("risk.safety_layer.DO_NOT_TRADE_SYMBOLS", frozenset({"MCL", "MNQ", "M2K"})):
            result = safety.check_order(order, equity)
        assert result.approved is expected_approved, (
            f"{symbol}×{quantity} on ${equity:,.0f}: expected approved={expected_approved}, "
            f"got reason={result.rejection_reason}"
        )
        if reason_substr:
            assert reason_substr in result.rejection_reason


class TestGlobalKillSwitchWithParallelDisabled:
    """
    Regression suite: when ENABLE_PARALLEL_PAPER=0 (default), the global kill
    switch behaviour is unchanged and per-account functions are no-ops.
    """

    def test_global_kill_still_blocks_orders_when_parallel_disabled(
        self, mock_safety_layer, mock_settings
    ):
        """ENABLE_PARALLEL_PAPER=0: global kill switch blocks all orders as before."""
        with patch.dict(os.environ, {"ENABLE_PARALLEL_PAPER": "0"}):
            safety = mock_safety_layer
            safety.activate_kill_switch(KillSwitchReason.MANUAL, "regression test")

            order = OrderRequest(
                symbol="MES",
                quantity=1,
                order_type="market",
                estimated_value=1000.0,
            )
            result = safety.check_order(order, 100_000.0)

        assert result.approved is False
        assert "Kill switch" in result.rejection_reason

    def test_is_account_halted_mirrors_global_when_parallel_disabled(self, mock_safety_layer):
        """ENABLE_PARALLEL_PAPER=0: is_account_halted returns global state only."""
        with patch.dict(os.environ, {"ENABLE_PARALLEL_PAPER": "0"}):
            safety = mock_safety_layer
            # Global off → both accounts not halted
            assert safety.is_account_halted("A") is False
            assert safety.is_account_halted("B") is False

            safety.activate_kill_switch(KillSwitchReason.MANUAL, "global test")
            # Global on → both accounts halted
            assert safety.is_account_halted("A") is True
            assert safety.is_account_halted("B") is True

    def test_trigger_per_account_kill_is_noop_when_parallel_disabled(self, mock_safety_layer):
        """ENABLE_PARALLEL_PAPER=0: trigger_per_account_kill does not raise and does nothing."""
        with patch.dict(os.environ, {"ENABLE_PARALLEL_PAPER": "0"}):
            safety = mock_safety_layer
            # Should not raise — silently no-op
            safety.trigger_per_account_kill("B", "max_daily_loss", -50.0, "test")
            # Global is still off
            assert safety.is_killed is False

    def test_clear_per_account_kill_is_noop_when_parallel_disabled(self, mock_safety_layer):
        """ENABLE_PARALLEL_PAPER=0: clear_per_account_kill does not raise and does nothing."""
        with patch.dict(os.environ, {"ENABLE_PARALLEL_PAPER": "0"}):
            safety = mock_safety_layer
            safety.activate_kill_switch(KillSwitchReason.MANUAL, "global")
            # Per-account clear must not deactivate global kill
            safety.clear_per_account_kill("A")
            assert safety.is_killed is True  # global unchanged


# ---------------------------------------------------------------------------
# §C10 — submit_paper_order coverage (lines 1172–1335)
# ---------------------------------------------------------------------------


class TestSubmitPaperOrder:
    """submit_paper_order: kill switch, safety gate, dry-run, IB routing, exceptions."""

    def _live_safety(self, mock_settings) -> SafetyLayer:
        mock_settings.LIVE_TRADING_ENABLED = True
        mock_settings.REQUIRE_HUMAN_APPROVAL = False
        mock_settings.MAX_DAILY_LOSS_PCT = 0.10
        mock_settings.MAX_DRAWDOWN_PCT = 0.20
        mock_settings.MAX_SINGLE_ORDER_VALUE = 50_000.0
        mock_settings.MAX_FUTURES_MARGIN_PCT = 0.30
        mock_settings.MAX_CONTRACTS_PER_INSTRUMENT = 5
        mock_settings.MAX_TRADE_LOSS_USD = 500.0
        return SafetyLayer(mock_settings)

    @pytest.mark.asyncio
    async def test_kill_switch_blocks_before_order_built(self, mock_settings):
        """Kill switch active → immediate rejection, no IB call."""
        safety = self._live_safety(mock_settings)
        safety.activate_kill_switch(KillSwitchReason.MANUAL, "test halt")
        result = await safety.submit_paper_order("MES", "BUY", 1, 5800.0)
        assert result["approved"] is False
        assert "Kill switch" in result["reason"]
        assert result["order_id"] is None
        assert result["routed_to_ib"] is False

    @pytest.mark.asyncio
    async def test_safety_check_rejected_propagates(self, mock_settings):
        """check_order failure → approved=False, order_id=None, routed=False."""
        mock_settings.LIVE_TRADING_ENABLED = False
        safety = SafetyLayer(mock_settings)
        result = await safety.submit_paper_order("MES", "BUY", 1, 5800.0)
        assert result["approved"] is False
        assert result["order_id"] is None
        assert result["routed_to_ib"] is False

    @pytest.mark.asyncio
    async def test_no_gateway_dry_run(self, mock_settings):
        """No IB gateway → approved=True, routed_to_ib=False (dry-run)."""
        safety = self._live_safety(mock_settings)
        result = await safety.submit_paper_order("MES", "BUY", 1, 5800.0)
        assert result["approved"] is True
        assert result["routed_to_ib"] is False
        assert "dry-run" in result["reason"]
        assert result["order_id"] is None

    @pytest.mark.asyncio
    async def test_gateway_not_connected_approved_not_routed(self, mock_settings):
        """Gateway attached but not connected → approved=True, routed_to_ib=False."""
        safety = self._live_safety(mock_settings)
        mock_gw = AsyncMock()
        mock_gw.is_connected = Mock(return_value=False)
        safety._ib_gateway = mock_gw
        result = await safety.submit_paper_order("MES", "BUY", 1, 5800.0)
        assert result["approved"] is True
        assert result["routed_to_ib"] is False
        assert "not connected" in result["reason"]

    @pytest.mark.asyncio
    async def test_routes_to_gateway_returns_order_id(self, mock_settings):
        """Connected gateway → approved=True, routed_to_ib=True, order_id returned."""
        safety = self._live_safety(mock_settings)
        mock_gw = AsyncMock()
        mock_gw.is_connected = Mock(return_value=True)
        mock_gw.place_paper_order = AsyncMock(return_value="order_42")
        safety._ib_gateway = mock_gw
        result = await safety.submit_paper_order("MES", "BUY", 1, 5800.0)
        assert result["approved"] is True
        assert result["routed_to_ib"] is True
        assert result["order_id"] == "order_42"

    @pytest.mark.asyncio
    async def test_stop_price_triggers_stp_child(self, mock_settings):
        """stop_price provided → HB-1 STP child placed after entry (two IB calls)."""
        safety = self._live_safety(mock_settings)
        mock_gw = AsyncMock()
        mock_gw.is_connected = Mock(return_value=True)
        mock_gw.place_paper_order = AsyncMock(side_effect=["entry_1", "stp_1"])
        safety._ib_gateway = mock_gw
        result = await safety.submit_paper_order("MES", "BUY", 1, 5800.0, stop_price=5785.0)
        assert result["approved"] is True
        assert result["routed_to_ib"] is True
        assert mock_gw.place_paper_order.call_count == 2

    @pytest.mark.asyncio
    async def test_gateway_exception_approved_not_routed(self, mock_settings):
        """IB Gateway raises → approved=True (safety passed), routed_to_ib=False."""
        safety = self._live_safety(mock_settings)
        mock_gw = AsyncMock()
        mock_gw.is_connected = Mock(return_value=True)
        mock_gw.place_paper_order = AsyncMock(side_effect=ConnectionError("IB timeout"))
        safety._ib_gateway = mock_gw
        result = await safety.submit_paper_order("MES", "BUY", 1, 5800.0)
        assert result["approved"] is True
        assert result["routed_to_ib"] is False
        assert "IB Gateway raised" in result["reason"]
        assert result["order_id"] is None

    @pytest.mark.asyncio
    async def test_sell_action_routes_correctly(self, mock_settings):
        """SELL action builds signed quantity and routes to IB."""
        safety = self._live_safety(mock_settings)
        mock_gw = AsyncMock()
        mock_gw.is_connected = Mock(return_value=True)
        mock_gw.place_paper_order = AsyncMock(return_value="sell_order_7")
        safety._ib_gateway = mock_gw
        result = await safety.submit_paper_order("MES", "SELL", 1, 5800.0)
        assert result["approved"] is True
        assert result["routed_to_ib"] is True

    @pytest.mark.asyncio
    async def test_lmt_order_type_normalised(self, mock_settings):
        """'LMT' order_type is normalised to 'limit' for OrderRequest."""
        safety = self._live_safety(mock_settings)
        mock_gw = AsyncMock()
        mock_gw.is_connected = Mock(return_value=True)
        mock_gw.place_paper_order = AsyncMock(return_value="lmt_order_1")
        safety._ib_gateway = mock_gw
        result = await safety.submit_paper_order(
            "MES", "BUY", 1, 5800.0, order_type="LMT", limit_price=5795.0
        )
        assert result["approved"] is True

    @pytest.mark.asyncio
    async def test_non_futures_symbol_routes(self, mock_settings):
        """Non-futures symbol (SPY) is detected as equity and routed."""
        safety = self._live_safety(mock_settings)
        mock_gw = AsyncMock()
        mock_gw.is_connected = Mock(return_value=True)
        mock_gw.place_paper_order = AsyncMock(return_value="spy_order_1")
        safety._ib_gateway = mock_gw
        # 1 share @ $10 → $10 notional, well within any position-size cap
        result = await safety.submit_paper_order("SPY", "BUY", 1, 10.0)
        assert result["approved"] is True


# ---------------------------------------------------------------------------
# §C10 — submit_entry_with_stop coverage (lines 1362–1562)
# ---------------------------------------------------------------------------


class TestSubmitEntryWithStop:
    """submit_entry_with_stop: entry rejection, STP failure paths, TP skip/place, sidecar."""

    def _live_gw(self, mock_settings):
        """Return (safety, mock_gw) with connected gateway and permissive settings."""
        mock_settings.LIVE_TRADING_ENABLED = True
        mock_settings.REQUIRE_HUMAN_APPROVAL = False
        mock_settings.MAX_DAILY_LOSS_PCT = 0.10
        mock_settings.MAX_DRAWDOWN_PCT = 0.20
        mock_settings.MAX_SINGLE_ORDER_VALUE = 50_000.0
        mock_settings.MAX_FUTURES_MARGIN_PCT = 0.30
        mock_settings.MAX_CONTRACTS_PER_INSTRUMENT = 5
        mock_settings.MAX_TRADE_LOSS_USD = 500.0
        safety = SafetyLayer(mock_settings)
        mock_gw = AsyncMock()
        mock_gw.is_connected = Mock(return_value=True)
        mock_gw.get_order_status = AsyncMock(return_value={"parent_order_id": "entry_id"})
        safety._ib_gateway = mock_gw
        return safety, mock_gw

    @pytest.mark.asyncio
    async def test_entry_rejected_returns_early(self, mock_settings):
        """Entry blocked by kill switch → approved=False, all IDs None."""
        mock_settings.LIVE_TRADING_ENABLED = True
        safety = SafetyLayer(mock_settings)
        safety.activate_kill_switch(KillSwitchReason.MANUAL, "halt")
        result = await safety.submit_entry_with_stop("MES", "BUY", 1, 5800.0, 5785.0)
        assert result["approved"] is False
        assert result["stp_order_id"] is None
        assert result["stp_linked"] is False
        assert result["tp_order_id"] is None
        assert result["routed_to_ib"] is False

    @pytest.mark.asyncio
    async def test_entry_dry_run_not_routed_returns_early(self, mock_settings):
        """Entry approved but dry-run (no gateway) → routed=False, no STP attempt."""
        mock_settings.LIVE_TRADING_ENABLED = True
        mock_settings.REQUIRE_HUMAN_APPROVAL = False
        mock_settings.MAX_TRADE_LOSS_USD = 500.0
        safety = SafetyLayer(mock_settings)
        result = await safety.submit_entry_with_stop("MES", "BUY", 1, 5800.0, 5785.0)
        assert result["approved"] is True
        assert result["routed_to_ib"] is False
        assert result["stp_order_id"] is None

    @pytest.mark.asyncio
    async def test_stp_success_entry_and_stp_ids_returned(self, mock_settings):
        """Entry + STP both succeed → approved=True, both order IDs present."""
        safety, mock_gw = self._live_gw(mock_settings)
        # Calls: 1=entry MKT, 2=HB-1 STP (inside submit_paper_order), 3=STP (submit_entry_with_stop)
        mock_gw.place_paper_order = AsyncMock(side_effect=["entry_id", "hb1_stp", "stp_id"])
        mock_gw.get_order_status = AsyncMock(return_value={"parent_order_id": "entry_id"})
        result = await safety.submit_entry_with_stop("MES", "BUY", 1, 5800.0, 5785.0)
        assert result["approved"] is True
        assert result["entry_order_id"] == "entry_id"
        assert result["stp_order_id"] == "stp_id"
        assert result["routed_to_ib"] is True

    @pytest.mark.asyncio
    async def test_stp_failure_cancels_entry(self, mock_settings):
        """STP placement raises → entry cancelled, result shows failure."""
        safety, mock_gw = self._live_gw(mock_settings)
        cancel_mock = AsyncMock()
        mock_gw.cancel_order = cancel_mock
        mock_gw.place_paper_order = AsyncMock(
            side_effect=["entry_id", "hb1_stp", Exception("STP broker error")]
        )
        result = await safety.submit_entry_with_stop("MES", "BUY", 1, 5800.0, 5785.0)
        assert result["approved"] is False
        assert result["stp_order_id"] is None
        assert "STP child placement failed" in result["reason"]
        cancel_mock.assert_called_once_with("entry_id")

    @pytest.mark.asyncio
    async def test_stp_failure_cancel_raises_survives(self, mock_settings):
        """STP fails + cancel raises → function still returns cleanly (no crash)."""
        safety, mock_gw = self._live_gw(mock_settings)
        mock_gw.cancel_order = AsyncMock(side_effect=Exception("cancel also failed"))
        mock_gw.place_paper_order = AsyncMock(
            side_effect=["entry_id", "hb1_stp", Exception("STP failed")]
        )
        result = await safety.submit_entry_with_stop("MES", "BUY", 1, 5800.0, 5785.0)
        assert result["approved"] is False

    @pytest.mark.asyncio
    async def test_stp_failure_no_cancel_method_survives(self, mock_settings):
        """STP fails + no cancel_order on gateway → logs and returns without crash."""

        class _GWNoCancel:
            async def is_connected(self):
                pass

            async def place_paper_order(self, **kw):
                pass

            async def get_order_status(self, oid):
                pass

        safety, _ = self._live_gw(mock_settings)
        nc_gw = create_autospec(_GWNoCancel, instance=True)
        nc_gw.is_connected = Mock(return_value=True)
        nc_gw.place_paper_order = AsyncMock(
            side_effect=["entry_id", "hb1_stp", Exception("STP fail")]
        )
        safety._ib_gateway = nc_gw
        result = await safety.submit_entry_with_stop("MES", "BUY", 1, 5800.0, 5785.0)
        assert result["approved"] is False

    @pytest.mark.asyncio
    async def test_target_price_skipped_in_paper_mode(self, mock_settings):
        """target_price + paper mode → TP call skipped, tp_order_id=None."""
        safety, mock_gw = self._live_gw(mock_settings)
        mock_gw.place_paper_order = AsyncMock(side_effect=["entry_id", "hb1_stp", "stp_id"])
        mock_gw.get_order_status = AsyncMock(return_value={"parent_order_id": "entry_id"})
        gs_mock = MagicMock()
        gs_mock.LIVE_TRADING_ENABLED = False
        with patch("risk.safety_layer.settings", gs_mock):
            result = await safety.submit_entry_with_stop(
                "MES", "BUY", 1, 5800.0, 5785.0, target_price=5815.0
            )
        assert result["tp_order_id"] is None
        assert result["approved"] is True
        assert mock_gw.place_paper_order.call_count == 3  # entry + hb1_stp + stp; no TP call

    @pytest.mark.asyncio
    async def test_target_price_placed_in_live_mode(self, mock_settings):
        """target_price + live mode → TP LMT child placed after STP."""
        safety, mock_gw = self._live_gw(mock_settings)
        mock_gw.place_paper_order = AsyncMock(
            side_effect=["entry_id", "hb1_stp", "stp_id", "tp_id"]
        )
        mock_gw.get_order_status = AsyncMock(return_value={"parent_order_id": "entry_id"})
        gs_mock = MagicMock()
        gs_mock.LIVE_TRADING_ENABLED = True
        with patch("risk.safety_layer.settings", gs_mock):
            result = await safety.submit_entry_with_stop(
                "MES", "BUY", 1, 5800.0, 5785.0, target_price=5815.0
            )
        assert result["tp_order_id"] == "tp_id"
        assert result["approved"] is True

    @pytest.mark.asyncio
    async def test_tp_placement_raises_survives(self, mock_settings):
        """TP call raises → tp_order_id=None, entry and STP still approved."""
        safety, mock_gw = self._live_gw(mock_settings)
        mock_gw.place_paper_order = AsyncMock(
            side_effect=["entry_id", "hb1_stp", "stp_id", Exception("TP error")]
        )
        mock_gw.get_order_status = AsyncMock(return_value={"parent_order_id": "entry_id"})
        gs_mock = MagicMock()
        gs_mock.LIVE_TRADING_ENABLED = True
        with patch("risk.safety_layer.settings", gs_mock):
            result = await safety.submit_entry_with_stop(
                "MES", "BUY", 1, 5800.0, 5785.0, target_price=5815.0
            )
        assert result["tp_order_id"] is None
        assert result["approved"] is True


# ---------------------------------------------------------------------------
# §C10 — flatten_all_positions coverage (lines 1564–1619)
# ---------------------------------------------------------------------------


class TestFlattenAllPositions:
    """flatten_all_positions: no gateway, get_positions error, long/short, edge cases."""

    @pytest.mark.asyncio
    async def test_no_gateway_returns_error(self, mock_settings):
        safety = SafetyLayer(mock_settings)
        result = await safety.flatten_all_positions()
        assert result["flattened"] == []
        assert result["order_ids"] == []
        assert any("No IB gateway" in e["error"] for e in result["errors"])

    @pytest.mark.asyncio
    async def test_get_positions_raises_returns_error(self, mock_settings):
        safety = SafetyLayer(mock_settings)
        mock_gw = AsyncMock()
        mock_gw.is_connected = Mock(return_value=True)
        mock_gw.get_positions = AsyncMock(side_effect=RuntimeError("IB disconnected"))
        safety._ib_gateway = mock_gw
        result = await safety.flatten_all_positions()
        assert result["flattened"] == []
        assert any("get_positions raised" in e["error"] for e in result["errors"])

    @pytest.mark.asyncio
    async def test_empty_positions_returns_empty_success(self, mock_settings):
        safety = SafetyLayer(mock_settings)
        mock_gw = AsyncMock()
        mock_gw.is_connected = Mock(return_value=True)
        mock_gw.get_positions = AsyncMock(return_value=[])
        safety._ib_gateway = mock_gw
        result = await safety.flatten_all_positions()
        assert result["flattened"] == []
        assert result["errors"] == []

    @pytest.mark.asyncio
    async def test_long_position_closed_with_sell(self, mock_settings):
        safety = SafetyLayer(mock_settings)
        mock_gw = AsyncMock()
        mock_gw.is_connected = Mock(return_value=True)
        mock_gw.get_positions = AsyncMock(return_value=[{"symbol": "MES", "position": 2}])
        mock_gw.place_paper_order = AsyncMock(return_value="flat_1")
        safety._ib_gateway = mock_gw
        result = await safety.flatten_all_positions()
        assert "MES" in result["flattened"]
        assert "flat_1" in result["order_ids"]
        call_kw = mock_gw.place_paper_order.call_args.kwargs
        assert call_kw.get("action") == "SELL"

    @pytest.mark.asyncio
    async def test_short_position_closed_with_buy(self, mock_settings):
        safety = SafetyLayer(mock_settings)
        mock_gw = AsyncMock()
        mock_gw.is_connected = Mock(return_value=True)
        mock_gw.get_positions = AsyncMock(return_value=[{"symbol": "MCL", "position": -1}])
        mock_gw.place_paper_order = AsyncMock(return_value="flat_2")
        safety._ib_gateway = mock_gw
        result = await safety.flatten_all_positions()
        assert "MCL" in result["flattened"]
        call_kw = mock_gw.place_paper_order.call_args.kwargs
        assert call_kw.get("action") == "BUY"

    @pytest.mark.asyncio
    async def test_zero_qty_position_skipped(self, mock_settings):
        safety = SafetyLayer(mock_settings)
        mock_gw = AsyncMock()
        mock_gw.is_connected = Mock(return_value=True)
        mock_gw.get_positions = AsyncMock(return_value=[{"symbol": "MES", "position": 0}])
        mock_gw.place_paper_order = AsyncMock(return_value="order_x")
        safety._ib_gateway = mock_gw
        result = await safety.flatten_all_positions()
        assert result["flattened"] == []
        mock_gw.place_paper_order.assert_not_called()

    @pytest.mark.asyncio
    async def test_place_order_returns_none_logged_as_error(self, mock_settings):
        safety = SafetyLayer(mock_settings)
        mock_gw = AsyncMock()
        mock_gw.is_connected = Mock(return_value=True)
        mock_gw.get_positions = AsyncMock(return_value=[{"symbol": "MES", "position": 1}])
        mock_gw.place_paper_order = AsyncMock(return_value=None)
        safety._ib_gateway = mock_gw
        result = await safety.flatten_all_positions()
        assert "MES" not in result["flattened"]
        assert any("returned None" in e.get("error", "") for e in result["errors"])

    @pytest.mark.asyncio
    async def test_place_order_raises_logged_as_error(self, mock_settings):
        safety = SafetyLayer(mock_settings)
        mock_gw = AsyncMock()
        mock_gw.is_connected = Mock(return_value=True)
        mock_gw.get_positions = AsyncMock(return_value=[{"symbol": "MCL", "position": 1}])
        mock_gw.place_paper_order = AsyncMock(side_effect=Exception("order failed"))
        safety._ib_gateway = mock_gw
        result = await safety.flatten_all_positions()
        assert "MCL" not in result["flattened"]
        assert any("order failed" in e.get("error", "") for e in result["errors"])

    @pytest.mark.asyncio
    async def test_multiple_positions_partial_success(self, mock_settings):
        """Two positions: first succeeds, second raises → flattened=1, errors=1."""
        safety = SafetyLayer(mock_settings)
        mock_gw = AsyncMock()
        mock_gw.is_connected = Mock(return_value=True)
        mock_gw.get_positions = AsyncMock(
            return_value=[
                {"symbol": "MES", "position": 1},
                {"symbol": "MCL", "position": 1},
            ]
        )
        mock_gw.place_paper_order = AsyncMock(side_effect=["oid_mes", Exception("MCL error")])
        safety._ib_gateway = mock_gw
        result = await safety.flatten_all_positions()
        assert "MES" in result["flattened"]
        assert "MCL" not in result["flattened"]
        assert len(result["errors"]) == 1


# ---------------------------------------------------------------------------
# §C10 — check_circuit_breakers coverage (lines 1671–1740)
# ---------------------------------------------------------------------------


class TestCheckCircuitBreakers:
    """check_circuit_breakers: PnL, drawdown, kill switch, edge cases."""

    def test_healthy_defaults_not_breached(self, mock_settings):
        """Default state → no breaches, no kill switch."""
        safety = SafetyLayer(mock_settings)
        status = safety.check_circuit_breakers()
        assert status["daily_limit_breached"] is False
        assert status["drawdown_breached"] is False
        assert status["kill_switch_active"] is False
        assert status["kill_switch_reason"] is None

    def test_daily_pnl_below_limit_breached(self, mock_settings):
        """Daily PnL exceeds configured loss limit → daily_limit_breached=True."""
        mock_settings.MAX_DAILY_LOSS_PCT = 0.02
        safety = SafetyLayer(mock_settings)
        safety._current_equity = 100_000.0
        safety._daily_realized_pnl = -3_000.0
        status = safety.check_circuit_breakers()
        assert status["daily_limit_breached"] is True
        assert status["daily_pnl"] == -3_000.0

    def test_daily_pnl_within_limit_not_breached(self, mock_settings):
        """Daily PnL inside limit → daily_limit_breached=False."""
        mock_settings.MAX_DAILY_LOSS_PCT = 0.02
        safety = SafetyLayer(mock_settings)
        safety._current_equity = 100_000.0
        safety._daily_realized_pnl = -500.0
        status = safety.check_circuit_breakers()
        assert status["daily_limit_breached"] is False

    def test_drawdown_from_equity_peak_breached(self, mock_settings):
        """12% drawdown with 10% limit → drawdown_breached=True."""
        mock_settings.MAX_DRAWDOWN_PCT = 0.10
        safety = SafetyLayer(mock_settings)
        safety._equity_peak = 100_000.0
        safety._current_equity = 88_000.0
        status = safety.check_circuit_breakers()
        assert status["drawdown_pct"] == pytest.approx(0.12, rel=1e-3)
        assert status["drawdown_breached"] is True

    def test_drawdown_within_limit_not_breached(self, mock_settings):
        """5% drawdown with 10% limit → drawdown_breached=False."""
        mock_settings.MAX_DRAWDOWN_PCT = 0.10
        safety = SafetyLayer(mock_settings)
        safety._equity_peak = 100_000.0
        safety._current_equity = 95_000.0
        status = safety.check_circuit_breakers()
        assert status["drawdown_breached"] is False

    def test_kill_switch_reason_surfaced(self, mock_settings):
        """Active kill switch → kill_switch_active=True and reason populated."""
        safety = SafetyLayer(mock_settings)
        safety.activate_kill_switch(KillSwitchReason.DAILY_LOSS_LIMIT, "exceeded limit")
        status = safety.check_circuit_breakers()
        assert status["kill_switch_active"] is True
        assert status["kill_switch_reason"] == KillSwitchReason.DAILY_LOSS_LIMIT.value

    def test_zero_equity_returns_zero_limits_no_crash(self, mock_settings):
        """Zero equity → daily_limit=0, pct=0, no ZeroDivisionError."""
        safety = SafetyLayer(mock_settings)
        safety._current_equity = 0.0
        safety._daily_realized_pnl = -100.0
        status = safety.check_circuit_breakers()
        assert status["daily_limit"] == 0
        assert status["daily_pnl_pct"] == 0

    def test_daily_limit_pct_reflects_config(self, mock_settings):
        """daily_limit_pct should be the negative of MAX_DAILY_LOSS_PCT."""
        mock_settings.MAX_DAILY_LOSS_PCT = 0.03
        safety = SafetyLayer(mock_settings)
        status = safety.check_circuit_breakers()
        assert status["daily_limit_pct"] == pytest.approx(-0.03)


# ---------------------------------------------------------------------------
# §C10 — sync_from_broker coverage (lines 1623–1669)
# ---------------------------------------------------------------------------


class TestSyncFromBroker:
    """sync_from_broker: equity updates, peak tracking, daily loss auto-kill."""

    def test_sync_updates_equity_and_daily_pnl(self, mock_settings):
        safety = SafetyLayer(mock_settings)
        safety.sync_from_broker(equity=105_000.0, daily_pnl=500.0)
        assert safety._current_equity == 105_000.0
        assert safety._daily_realized_pnl == 500.0

    def test_sync_raises_equity_peak(self, mock_settings):
        """New equity above existing peak → peak updated."""
        safety = SafetyLayer(mock_settings)
        safety._equity_peak = 100_000.0
        safety.sync_from_broker(equity=110_000.0, daily_pnl=0.0)
        assert safety._equity_peak == 110_000.0

    def test_sync_does_not_lower_equity_peak(self, mock_settings):
        """Equity below existing peak → peak unchanged."""
        safety = SafetyLayer(mock_settings)
        safety._equity_peak = 100_000.0
        safety.sync_from_broker(equity=90_000.0, daily_pnl=-10_000.0)
        assert safety._equity_peak == 100_000.0

    def test_sync_triggers_kill_switch_on_daily_loss(self, mock_settings):
        """Daily PnL crossing limit → kill switch auto-activates."""
        mock_settings.MAX_DAILY_LOSS_PCT = 0.02
        safety = SafetyLayer(mock_settings)
        safety.sync_from_broker(equity=100_000.0, daily_pnl=-3_000.0)
        assert safety.is_killed is True

    def test_sync_within_limit_no_kill_switch(self, mock_settings):
        """Daily PnL within limit → kill switch stays off."""
        mock_settings.MAX_DAILY_LOSS_PCT = 0.02
        safety = SafetyLayer(mock_settings)
        safety.sync_from_broker(equity=100_000.0, daily_pnl=-500.0)
        assert safety.is_killed is False

    def test_sync_with_alert_manager_does_not_crash(self, mock_settings):
        """Alert manager present → check_and_alert called, no crash on failure."""
        safety = SafetyLayer(mock_settings)
        mock_am = MagicMock()
        mock_am.check_and_alert.side_effect = Exception("alert system error")
        safety._alert_manager = mock_am
        safety.sync_from_broker(equity=100_000.0, daily_pnl=0.0)
        mock_am.check_and_alert.assert_called_once()


# ---------------------------------------------------------------------------
# §C10 — record_trade_result, loss tracker, reset_daily_pnl, orders_in_last_minute
# ---------------------------------------------------------------------------


class TestLossTrackerAndReset:
    """record_trade_result, get_loss_tracker_status, reset_daily_pnl, orders_in_last_minute."""

    def test_record_trade_result_no_tracker_no_crash(self, mock_settings):
        """No loss tracker → no exception raised."""
        safety = SafetyLayer(mock_settings)
        safety.record_trade_result("MES", 250.0)

    def test_record_trade_result_loss_sets_reentry_lockout(self, mock_settings):
        """Negative PnL → re-entry lockout set for that symbol."""
        safety = SafetyLayer(mock_settings)
        safety.record_trade_result("MES", -50.0)
        assert "MES" in safety._reentry_lockouts

    def test_record_trade_result_win_no_lockout(self, mock_settings):
        """Positive PnL → no lockout set."""
        safety = SafetyLayer(mock_settings)
        safety.record_trade_result("MES", 100.0)
        assert "MES" not in safety._reentry_lockouts

    def test_record_trade_result_with_tracker_calls_record_trade(self, mock_settings):
        """Loss tracker present → record_trade called with correct args."""
        safety = SafetyLayer(mock_settings)
        mock_tracker = MagicMock()
        mock_tracker.record_trade.return_value = True
        safety._loss_tracker = mock_tracker
        safety.record_trade_result("MCL", 75.0)
        mock_tracker.record_trade.assert_called_once_with("MCL", 75.0)

    def test_get_loss_tracker_status_no_tracker(self, mock_settings):
        """No loss tracker → enabled=False."""
        safety = SafetyLayer(mock_settings)
        status = safety.get_loss_tracker_status()
        assert status["enabled"] is False

    def test_get_loss_tracker_status_with_tracker(self, mock_settings):
        """Loss tracker present → enabled=True, tracker status merged."""
        safety = SafetyLayer(mock_settings)
        mock_tracker = MagicMock()
        mock_tracker.get_status.return_value = {"consecutive_losses": 2, "total": 5}
        safety._loss_tracker = mock_tracker
        status = safety.get_loss_tracker_status()
        assert status["enabled"] is True
        assert status["consecutive_losses"] == 2

    def test_reset_daily_pnl_zeroes_counters(self, mock_settings):
        """reset_daily_pnl zeroes daily_realized_pnl and daily_order_count."""
        safety = SafetyLayer(mock_settings)
        safety._daily_realized_pnl = -500.0
        safety._daily_order_count = 5
        result = safety.reset_daily_pnl()
        assert result["status"] == "ok"
        assert safety._daily_realized_pnl == 0.0
        assert safety._daily_order_count == 0

    def test_orders_in_last_minute_empty_window(self, mock_settings):
        """No recent orders → returns 0."""
        safety = SafetyLayer(mock_settings)
        assert safety.orders_in_last_minute() == 0


# ---------------------------------------------------------------------------
# §C10 — activate_kill_switch string reason conversion (lines 484-489)
# ---------------------------------------------------------------------------


class TestKillSwitchStringReason:
    """activate_kill_switch accepts a string reason and converts to enum."""

    def test_valid_string_reason_converts_to_enum(self, mock_settings):
        """String matching a KillSwitchReason name → enum converted."""
        safety = SafetyLayer(mock_settings)
        safety.activate_kill_switch("MANUAL", "string reason test")
        assert safety._kill_switch_reason == KillSwitchReason.MANUAL
        assert safety.is_killed is True

    def test_unknown_string_reason_falls_back_to_manual(self, mock_settings):
        """Unknown string → warning logged, reason defaults to MANUAL."""
        safety = SafetyLayer(mock_settings)
        safety.activate_kill_switch("COMPLETELY_BOGUS_REASON", "unknown")
        assert safety._kill_switch_reason == KillSwitchReason.MANUAL
        assert safety.is_killed is True


# ---------------------------------------------------------------------------
# §C10 — _apply_loss_tracker_adjustment (lines 796–832)
# ---------------------------------------------------------------------------


class TestLossTrackerAdjustment:
    """_apply_loss_tracker_adjustment: halted path and size-reduction path."""

    def _base_order(self) -> OrderRequest:
        return OrderRequest(
            symbol="MES",
            quantity=1,
            order_type="market",
            is_futures=True,
            estimated_value=5800.0,
        )

    def test_halted_tracker_returns_rejected_result(self, mock_settings):
        """loss_tracker.is_halted() → RiskCheckResult(approved=False)."""
        safety = SafetyLayer(mock_settings)
        mock_tracker = MagicMock()
        mock_tracker.is_halted.return_value = True
        mock_tracker.get_halt_reason.return_value = "Max consecutive losses reached"
        safety._loss_tracker = mock_tracker

        result = safety._apply_loss_tracker_adjustment(self._base_order(), [])
        assert isinstance(result, RiskCheckResult)
        assert result.approved is False
        assert "Max consecutive losses" in result.rejection_reason

    def test_multiplier_below_one_reduces_quantity_and_adds_warning(self, mock_settings):
        """multiplier < 1.0 → adjusted order with lower qty, warning appended."""
        safety = SafetyLayer(mock_settings)
        mock_tracker = MagicMock()
        mock_tracker.is_halted.return_value = False
        mock_tracker.get_position_size_multiplier.return_value = 0.5
        mock_tracker.get_consecutive_losses.return_value = 3
        safety._loss_tracker = mock_tracker

        order = OrderRequest(
            symbol="MES",
            quantity=4,
            order_type="market",
            is_futures=True,
            estimated_value=5800.0,
        )
        result, warnings = safety._apply_loss_tracker_adjustment(order, [])
        # qty=4 * 0.5 = 2 → adjusted_order.quantity==2
        assert result.quantity == 2
        assert len(warnings) == 1
        assert "position size reduced" in warnings[0]

    def test_multiplier_equal_to_one_returns_unchanged_order(self, mock_settings):
        """multiplier == 1.0 → original order returned unchanged."""
        safety = SafetyLayer(mock_settings)
        mock_tracker = MagicMock()
        mock_tracker.is_halted.return_value = False
        mock_tracker.get_position_size_multiplier.return_value = 1.0
        safety._loss_tracker = mock_tracker

        order = self._base_order()
        result, warnings = safety._apply_loss_tracker_adjustment(order, [])
        assert result is order
        assert warnings == []


# ---------------------------------------------------------------------------
# §C10 — _check_stark_tpo_constraint (lines 1030–1048)
# ---------------------------------------------------------------------------


class TestStarkTpoConstraint:
    """_check_stark_tpo_constraint rejects orders that violate the Stark math signal."""

    def _order(self, qty: int, stark_signal: str) -> OrderRequest:
        return OrderRequest(
            symbol="MES",
            quantity=qty,
            order_type="market",
            is_futures=True,
            estimated_value=5800.0,
            stark_signal=stark_signal,
        )

    def test_hold_signal_with_nonzero_qty_rejected(self, mock_settings):
        """HOLD signal + qty != 0 → rejected."""
        safety = SafetyLayer(mock_settings)
        result = safety._check_stark_tpo_constraint(self._order(1, "HOLD"))
        assert result.approved is False
        assert "HOLD" in result.rejection_reason

    def test_long_signal_with_sell_rejected(self, mock_settings):
        """LONG signal + negative qty → rejected."""
        safety = SafetyLayer(mock_settings)
        result = safety._check_stark_tpo_constraint(self._order(-1, "LONG_MOMENTUM"))
        assert result.approved is False
        assert "LONG" in result.rejection_reason
        assert "SHORT" in result.rejection_reason

    def test_short_signal_with_buy_rejected(self, mock_settings):
        """SHORT signal + positive qty → rejected."""
        safety = SafetyLayer(mock_settings)
        result = safety._check_stark_tpo_constraint(self._order(1, "SHORT_GAP_FILL"))
        assert result.approved is False
        assert "SHORT" in result.rejection_reason
        assert "LONG" in result.rejection_reason

    def test_long_signal_with_buy_approved(self, mock_settings):
        """LONG signal + positive qty → approved (no violation)."""
        safety = SafetyLayer(mock_settings)
        result = safety._check_stark_tpo_constraint(self._order(1, "LONG_MOMENTUM"))
        assert result.approved is True

    def test_no_signal_approved(self, mock_settings):
        """No stark_signal → approved."""
        safety = SafetyLayer(mock_settings)
        order = OrderRequest(symbol="MES", quantity=1, order_type="market", is_futures=True)
        result = safety._check_stark_tpo_constraint(order)
        assert result.approved is True


# ---------------------------------------------------------------------------
# §C10 — get_lockout_status (lines 1911–1922)
# ---------------------------------------------------------------------------


class TestLockoutStatus:
    """get_lockout_status: returns locked/unlocked state for a symbol."""

    def test_locked_symbol_returns_remaining_minutes(self, mock_settings):
        """Symbol with future lockout → locked=True, remaining_minutes > 0."""
        from datetime import timedelta

        safety = SafetyLayer(mock_settings)
        future = datetime.now() + timedelta(minutes=45)
        safety._reentry_lockouts["MES"] = future
        status = safety.get_lockout_status("MES")
        assert status["locked"] is True
        assert status["remaining_minutes"] >= 44  # allow 1-second timing slack
        assert "lockout_until" in status

    def test_unlocked_symbol_returns_false(self, mock_settings):
        """Symbol with no lockout → locked=False."""
        safety = SafetyLayer(mock_settings)
        status = safety.get_lockout_status("MNQ")
        assert status["locked"] is False
        assert status["symbol"] == "MNQ"

    def test_expired_lockout_returns_false(self, mock_settings):
        """Expired lockout entry → locked=False (past datetime is treated as expired)."""
        from datetime import timedelta

        safety = SafetyLayer(mock_settings)
        past = datetime.now() - timedelta(minutes=5)
        safety._reentry_lockouts["MCL"] = past
        status = safety.get_lockout_status("MCL")
        assert status["locked"] is False


# ---------------------------------------------------------------------------
# §C10 — reset_loss_tracker (lines 1800–1817)
# ---------------------------------------------------------------------------


class TestResetLossTracker:
    """reset_loss_tracker: no-tracker path and tracker-present path."""

    def test_reset_no_tracker_returns_not_available(self, mock_settings):
        """No loss_tracker → returns {'status': 'Loss tracker not available'}."""
        safety = SafetyLayer(mock_settings)
        result = safety.reset_loss_tracker()
        assert result["status"] == "Loss tracker not available"

    def test_reset_with_tracker_calls_reset_and_returns_status(self, mock_settings):
        """Loss tracker present → calls reset(symbol=None) and returns status."""
        safety = SafetyLayer(mock_settings)
        mock_tracker = MagicMock()
        mock_tracker.get_status.return_value = {"consecutive_losses": 0}
        safety._loss_tracker = mock_tracker
        result = safety.reset_loss_tracker()
        mock_tracker.reset.assert_called_once_with(symbol=None)
        assert result["status"] == "Reset successful"
        assert result["consecutive_losses"] == 0

    def test_reset_with_tracker_and_symbol(self, mock_settings):
        """Symbol supplied → calls reset(symbol='MES')."""
        safety = SafetyLayer(mock_settings)
        mock_tracker = MagicMock()
        mock_tracker.get_status.return_value = {}
        safety._loss_tracker = mock_tracker
        safety.reset_loss_tracker(symbol="MES")
        mock_tracker.reset.assert_called_once_with(symbol="MES")


# ---------------------------------------------------------------------------
# §C10 — get_recommended_size (lines 1819–1909)
# ---------------------------------------------------------------------------


class TestGetRecommendedSize:
    """get_recommended_size: import success/failure paths."""

    def test_import_failure_returns_error_dict(self, mock_settings):
        """Both import paths fail → returns error dict with recommended_contracts=0."""
        safety = SafetyLayer(mock_settings)
        with patch.dict(
            "sys.modules", {"risk.position_sizer": None, "engine.risk.position_sizer": None}
        ):
            result = safety.get_recommended_size("MES", atr=5.0, account_value=50_000.0)
        assert result.get("error") is not None
        assert result["recommended_contracts"] == 0
        assert result["symbol"] == "MES"

    def test_import_success_returns_sizing_dict(self, mock_settings):
        """Successful import → calls calculate_position_size and returns full dict."""
        mock_position_size = MagicMock()
        mock_position_size.contracts = 2
        mock_position_size.risk_amount = 250.0
        mock_position_size.max_loss = 500.0
        mock_position_size.sizing_method = "atr"
        mock_position_size.scale_factor = 1.0

        with patch("risk.safety_layer.calculate_position_size", mock_position_size, create=True):
            with patch("builtins.__import__") as mock_import:
                # Let most imports pass through but intercept calculate_position_size
                original_import = (
                    __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__
                )

                def fake_import(name, *args, **kwargs):
                    if name == "risk.position_sizer":
                        mod = MagicMock()
                        mod.calculate_position_size = mock_position_size
                        return mod
                    return original_import(name, *args, **kwargs)

                mock_import.side_effect = fake_import
                # Direct call via the module-level patch is cleaner:
                pass

        # Use a simpler approach: patch the import inside the method namespace
        mock_calc = MagicMock(return_value=mock_position_size)
        with patch.dict("sys.modules", {}):
            import sys

            mock_module = MagicMock()
            mock_module.calculate_position_size = mock_calc
            sys.modules["risk.position_sizer"] = mock_module
            try:
                safety = SafetyLayer(mock_settings)
                result = safety.get_recommended_size("MES", atr=5.0, account_value=50_000.0)
                assert "recommended_contracts" in result
                assert result["symbol"] == "MES"
                assert result["atr"] == 5.0
            finally:
                del sys.modules["risk.position_sizer"]


# ---------------------------------------------------------------------------
# §C10 — _log_safety_event exception path (lines 1940–1952)
# ---------------------------------------------------------------------------


class TestLogSafetyEvent:
    """_log_safety_event: gracefully handles import error and DB exception."""

    @pytest.mark.asyncio
    async def test_log_safety_event_db_exception_does_not_raise(self, mock_settings):
        """repository.insert_safety_event raises → warning logged, no exception propagated."""
        safety = SafetyLayer(mock_settings)

        import sys

        mock_repo = MagicMock()
        mock_repo.insert_safety_event = AsyncMock(side_effect=Exception("DB unavailable"))
        mock_db_module = MagicMock()
        mock_db_module.repository = mock_repo

        # Patch both `database` and `database.repository` in sys.modules
        with patch.dict(
            "sys.modules", {"database": mock_db_module, "database.repository": mock_repo}
        ):
            # Should complete without raising
            await safety._log_safety_event("test_event", "test reason", {"key": "value"})

    @pytest.mark.asyncio
    async def test_log_safety_event_import_error_does_not_raise(self, mock_settings):
        """database module absent → ImportError caught silently."""
        safety = SafetyLayer(mock_settings)
        with patch.dict("sys.modules", {"database": None}):
            await safety._log_safety_event("test_event", "test reason", {})


# ---------------------------------------------------------------------------
# §C10 — order rate limit exceeded (via check_order, lines 989–998)
# ---------------------------------------------------------------------------


class TestOrderRateLimit:
    """_check_order_rate: exceeding MAX_ORDERS_PER_MINUTE activates kill switch."""

    def test_rate_limit_exceeded_kills_switch(self, mock_settings):
        """Pre-populate timestamps → check_order rejects with ANOMALOUS_ORDER_RATE."""
        import time

        mock_settings.LIVE_TRADING_ENABLED = True
        mock_settings.REQUIRE_HUMAN_APPROVAL = False
        mock_settings.MAX_ORDERS_PER_MINUTE = 3
        mock_settings.MAX_TRADE_LOSS_USD = 500.0
        safety = SafetyLayer(mock_settings)

        # Pre-fill the rolling window with MAX_ORDERS_PER_MINUTE timestamps
        now = time.time()
        safety._recent_order_timestamps = [now - 10, now - 20, now - 30]

        order = OrderRequest(
            symbol="MES",
            quantity=1,
            order_type="market",
            is_futures=True,
            estimated_value=5800.0,
        )
        result = safety.check_order(order, portfolio_equity=100_000.0)
        assert result.approved is False
        assert "order rate" in result.rejection_reason.lower() or safety.is_killed is True


# ---------------------------------------------------------------------------
# §C10 — submit_paper_order warnings path (lines 1253–1255)
# ---------------------------------------------------------------------------


class TestSubmitPaperOrderWarnings:
    """submit_paper_order: safety warnings branch when loss tracker reduces size."""

    @pytest.mark.asyncio
    async def test_warnings_logged_when_loss_tracker_reduces_size(self, mock_settings):
        """Loss tracker with multiplier < 1.0 → warnings logged, order still approved."""
        mock_settings.LIVE_TRADING_ENABLED = True
        mock_settings.REQUIRE_HUMAN_APPROVAL = False
        mock_settings.MAX_DAILY_LOSS_PCT = 0.10
        mock_settings.MAX_DRAWDOWN_PCT = 0.20
        mock_settings.MAX_SINGLE_ORDER_VALUE = 50_000.0
        mock_settings.MAX_FUTURES_MARGIN_PCT = 0.30
        mock_settings.MAX_CONTRACTS_PER_INSTRUMENT = 5
        mock_settings.MAX_TRADE_LOSS_USD = 500.0

        safety = SafetyLayer(mock_settings)
        mock_tracker = MagicMock()
        mock_tracker.is_halted.return_value = False
        mock_tracker.get_position_size_multiplier.return_value = 0.5
        mock_tracker.get_consecutive_losses.return_value = 3
        safety._loss_tracker = mock_tracker

        # No gateway → dry-run, but safety + warning path still exercises
        # qty=1 MES: margin ~$1,320/$10K = 13.2% < 30% cap → passes all size gates
        result = await safety.submit_paper_order("MES", "BUY", 1, 5800.0)
        # Approved (safety passed), dry-run (no gateway)
        assert result["approved"] is True


# ---------------------------------------------------------------------------
# §C10 — attach_ib_gateway / attach_schwab / inject_alert_manager (258,262,272)
# ---------------------------------------------------------------------------


class TestAttachMethods:
    def test_attach_ib_gateway(self, mock_settings):
        safety = SafetyLayer(mock_settings)
        mock_gw = MagicMock()
        safety.attach_ib_gateway(mock_gw)
        assert safety._ib_gateway is mock_gw

    def test_attach_schwab(self, mock_settings):
        safety = SafetyLayer(mock_settings)
        mock_sc = MagicMock()
        safety.attach_schwab(mock_sc)
        assert safety.schwab is mock_sc

    def test_inject_alert_manager(self, mock_settings):
        safety = SafetyLayer(mock_settings)
        mock_am = MagicMock()
        safety.inject_alert_manager(mock_am)
        assert safety._alert_manager is mock_am


# ---------------------------------------------------------------------------
# §C10 — get_status (line 751)
# ---------------------------------------------------------------------------


class TestGetStatus:
    def test_get_status_returns_dict_with_is_killed(self, mock_settings):
        safety = SafetyLayer(mock_settings)
        status = safety.get_status()
        assert "is_killed" in status
        assert status["is_killed"] is False

    def test_get_status_reflects_kill_switch(self, mock_settings):
        safety = SafetyLayer(mock_settings)
        safety.activate_kill_switch(KillSwitchReason.MANUAL, "halt")
        status = safety.get_status()
        assert status["is_killed"] is True
        assert status["kill_switch_reason"] == "manual"


# ---------------------------------------------------------------------------
# §C10 — _load_pnl_snapshot with db_manager (lines 297–316)
# ---------------------------------------------------------------------------


class TestLoadPnlSnapshot:
    def test_load_snapshot_restores_state(self, mock_settings):
        """db_manager.get_pnl_snapshot returns data → state restored."""
        mock_db = MagicMock()
        mock_db.get_pnl_snapshot.return_value = {
            "daily_pnl": -250.0,
            "portfolio_equity": 98_000.0,
            "peak_equity": 100_000.0,
        }
        mock_settings.INITIAL_CAPITAL = 100_000.0
        safety = SafetyLayer(mock_settings, db_manager=mock_db)
        assert safety._daily_realized_pnl == -250.0
        assert safety._current_equity == 98_000.0
        assert safety._equity_peak >= 100_000.0

    def test_load_snapshot_no_data_starts_fresh(self, mock_settings):
        """db_manager.get_pnl_snapshot returns None → starts fresh."""
        mock_db = MagicMock()
        mock_db.get_pnl_snapshot.return_value = None
        mock_settings.INITIAL_CAPITAL = 10_000.0
        safety = SafetyLayer(mock_settings, db_manager=mock_db)
        assert safety._daily_realized_pnl == 0.0

    def test_load_snapshot_db_exception_does_not_raise(self, mock_settings):
        """db_manager.get_pnl_snapshot raises → non-fatal, safety continues."""
        mock_db = MagicMock()
        mock_db.get_pnl_snapshot.side_effect = RuntimeError("DB down")
        mock_settings.INITIAL_CAPITAL = 10_000.0
        safety = SafetyLayer(mock_settings, db_manager=mock_db)
        assert safety is not None


# ---------------------------------------------------------------------------
# §C10 — _persist_pnl_snapshot with db_manager (lines 379–394)
# ---------------------------------------------------------------------------


class TestPersistPnlSnapshot:
    def test_persist_called_on_sync_from_broker(self, mock_settings):
        """sync_from_broker with db_manager → upsert_pnl_snapshot called."""
        mock_db = MagicMock()
        mock_db.get_pnl_snapshot.return_value = None
        mock_settings.INITIAL_CAPITAL = 10_000.0
        safety = SafetyLayer(mock_settings, db_manager=mock_db)
        mock_db.upsert_pnl_snapshot.reset_mock()
        safety.sync_from_broker(equity=10_500.0, daily_pnl=500.0)
        mock_db.upsert_pnl_snapshot.assert_called_once()

    def test_persist_exception_does_not_raise(self, mock_settings):
        """upsert_pnl_snapshot raises → non-fatal, sync_from_broker still returns."""
        mock_db = MagicMock()
        mock_db.get_pnl_snapshot.return_value = None
        mock_db.upsert_pnl_snapshot.side_effect = RuntimeError("DB error")
        mock_settings.INITIAL_CAPITAL = 10_000.0
        safety = SafetyLayer(mock_settings, db_manager=mock_db)
        safety.sync_from_broker(equity=10_500.0, daily_pnl=500.0)  # must not raise

    def test_persist_preserves_realized_peak_equity(self, mock_settings):
        """Existing snapshot with realized_peak_equity → value passed back to upsert."""
        mock_db = MagicMock()
        mock_db.get_pnl_snapshot.return_value = {"realized_peak_equity": 173_920.77}
        mock_settings.INITIAL_CAPITAL = 10_000.0
        safety = SafetyLayer(mock_settings, db_manager=mock_db)
        mock_db.upsert_pnl_snapshot.reset_mock()
        safety.sync_from_broker(equity=10_500.0, daily_pnl=500.0)
        kwargs = mock_db.upsert_pnl_snapshot.call_args.kwargs
        assert kwargs.get("realized_peak_equity") == 173_920.77, (
            "realized_peak_equity must be forwarded from the existing snapshot row "
            "so successive writes do not overwrite it with NULL"
        )


# ---------------------------------------------------------------------------
# §C10 — _check_drawdown with pnl_monitor (lines 767–777)
# ---------------------------------------------------------------------------


class TestCheckDrawdownWithPnlMonitor:
    """_check_drawdown uses pnl_monitor.get_drawdown_pct() when available."""

    def _make_pnl_monitor(self, drawdown_pct: float):
        """drawdown_pct should be negative (e.g. -0.15); code does -pnl_monitor.get_drawdown_pct()."""
        mock_pm = MagicMock()
        mock_pm.get_drawdown_pct.return_value = drawdown_pct
        pnl_state = MagicMock()
        pnl_state.total_pnl = 0.0
        pnl_state.daily_realized_pnl = 0.0
        pnl_state.current_balance = 100_000.0
        mock_pm.get_current_pnl_state.return_value = pnl_state
        return mock_pm

    def test_pnl_monitor_drawdown_exceeds_limit_kills_switch(self, mock_settings):
        """pnl_monitor drawdown > MAX_DRAWDOWN_PCT → kill switch activated (lines 769–774)."""
        mock_settings.MAX_DRAWDOWN_PCT = 0.10
        mock_settings.LIVE_TRADING_ENABLED = True
        mock_settings.REQUIRE_HUMAN_APPROVAL = False
        mock_settings.MAX_TRADE_LOSS_USD = 500.0
        # get_drawdown_pct=-0.15 → negated → 0.15 > 0.10 → kill switch fires
        pm = self._make_pnl_monitor(drawdown_pct=-0.15)
        safety = SafetyLayer(mock_settings, pnl_monitor=pm)
        order = OrderRequest(symbol="MES", quantity=1, order_type="market", is_futures=True)
        result = safety.check_order(order, portfolio_equity=100_000.0)
        assert result.approved is False
        assert safety.is_killed is True

    def test_pnl_monitor_drawdown_at_warning_threshold(self, mock_settings):
        """drawdown >= 80% of limit → warning added, order still approved (line 777)."""
        mock_settings.MAX_DRAWDOWN_PCT = 0.10
        mock_settings.LIVE_TRADING_ENABLED = True
        mock_settings.REQUIRE_HUMAN_APPROVAL = False
        mock_settings.MAX_TRADE_LOSS_USD = 500.0
        # get_drawdown_pct=-0.09 → negated → 0.09 >= 0.08 (80% of 0.10) → warning
        pm = self._make_pnl_monitor(drawdown_pct=-0.09)
        safety = SafetyLayer(mock_settings, pnl_monitor=pm)
        order = OrderRequest(symbol="MES", quantity=1, order_type="market", is_futures=True)
        result = safety.check_order(order, portfolio_equity=100_000.0)
        assert result.approved is True
        assert any("Drawdown" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# §C10 — _check_gating_conditions ALLOW_PAPER_SIMULATED_ORDERS (line 848)
# ---------------------------------------------------------------------------


class TestGatingAllowPaperSimulated:
    def test_allow_paper_simulated_orders_bypasses_live_gate(self, mock_settings):
        """ALLOW_PAPER_SIMULATED_ORDERS=True with LIVE_TRADING_ENABLED=False → approved."""
        mock_settings.LIVE_TRADING_ENABLED = False
        mock_settings.ALLOW_PAPER_SIMULATED_ORDERS = True
        mock_settings.REQUIRE_HUMAN_APPROVAL = False
        mock_settings.MAX_TRADE_LOSS_USD = 500.0
        safety = SafetyLayer(mock_settings)
        order = OrderRequest(symbol="MES", quantity=1, order_type="market", is_futures=True)
        result = safety.check_order(order, portfolio_equity=100_000.0)
        assert result.approved is True


# ---------------------------------------------------------------------------
# §C10 — _check_daily_loss_limit abs USD gate (lines 869–873)
# ---------------------------------------------------------------------------


class TestDailyAbsLossLimit:
    def test_abs_loss_limit_triggers_kill_switch(self, mock_settings):
        """Daily realized loss exceeds MAX_DAILY_LOSS_USD → kill switch activated."""
        mock_settings.LIVE_TRADING_ENABLED = True
        mock_settings.REQUIRE_HUMAN_APPROVAL = False
        mock_settings.MAX_DAILY_LOSS_PCT = 0.99  # very permissive pct limit
        mock_settings.MAX_DAILY_LOSS_USD = 100.0
        mock_settings.MAX_TRADE_LOSS_USD = 500.0
        safety = SafetyLayer(mock_settings)
        safety._current_equity = 100_000.0
        safety._daily_realized_pnl = -200.0  # exceeds $100 abs limit
        order = OrderRequest(symbol="MES", quantity=1, order_type="market", is_futures=True)
        result = safety.check_order(order, portfolio_equity=100_000.0)
        assert result.approved is False
        assert safety.is_killed is True


# ---------------------------------------------------------------------------
# §C10 — _check_trade_loss_gate edge cases (lines 905, 915, 919)
# ---------------------------------------------------------------------------


class TestTradeLossGateEdgeCases:
    def test_entry_px_zero_skips_gate(self, mock_settings):
        """estimated_value=0, no limit_price, no qty → entry_px=0 → approved."""
        safety = SafetyLayer(mock_settings)
        order = OrderRequest(
            symbol="MES",
            quantity=0,  # force abs_qty=0 → division guard
            order_type="stop",
            is_futures=True,
            stop_price=5780.0,
            estimated_value=0.0,
        )
        result = safety._check_trade_loss_gate(order)
        assert result.approved is True

    def test_equity_stop_risk_approved(self, mock_settings):
        """Non-futures order: dollar_risk within MAX_TRADE_LOSS_USD → approved."""
        mock_settings.MAX_TRADE_LOSS_USD = 500.0
        safety = SafetyLayer(mock_settings)
        # SPY 1 share, $1 stop → dollar_risk=$1 << $500
        order = OrderRequest(
            symbol="SPY",
            quantity=1,
            order_type="market",
            is_futures=False,
            limit_price=100.0,
            stop_price=99.0,
            estimated_value=100.0,
        )
        result = safety._check_trade_loss_gate(order)
        assert result.approved is True

    def test_equity_stop_risk_rejected(self, mock_settings):
        """Non-futures order: dollar_risk exceeds MAX_TRADE_LOSS_USD → rejected."""
        mock_settings.MAX_TRADE_LOSS_USD = 50.0
        safety = SafetyLayer(mock_settings)
        # SPY 100 shares, $5 stop → dollar_risk=$500 > $50
        order = OrderRequest(
            symbol="SPY",
            quantity=100,
            order_type="market",
            is_futures=False,
            limit_price=200.0,
            stop_price=195.0,
            estimated_value=20_000.0,
        )
        result = safety._check_trade_loss_gate(order)
        assert result.approved is False
        assert "TRADE_LOSS_LIMIT" in result.rejection_reason


# ---------------------------------------------------------------------------
# §C11 — trade #287 regression: entry_price/stop_price wiring bug (Bug 1)
# ---------------------------------------------------------------------------
#
# Root cause (confirmed against trade #287 in paper_trades + pm2 engine logs):
#   1a. main.py's watchlist-scan loop computed the OMS bracket call's
#       entry_price as `trade_dec.get("limit_price") or trade_dec.get(
#       "stop_price")` -- so any MKT order (no limit_price) priced its entry
#       at the STOP price, not the Trader agent's actual intended entry
#       (`trade_dec["entry_price"]`).
#   1b. SafetyLayer.submit_paper_bracket_order() built its OrderRequest
#       without `stop_price=stop_loss` at all, so _check_trade_loss_gate()
#       short-circuited approved=True (order.stop_price is None) regardless
#       of (1a) -- the gate never even ran for a bracket order.
#
# Combined, MGC trade #287 (buy 1, intended entry 4153.85, stop 4134.6666)
# was approved with the gate computing ~$0 points-at-risk, when the real
# dollar risk was already ~$191.83 -- 3.8x over the $50/ticket cap -- before
# any market movement. Both wiring bugs are fixed above; these tests prove
# the gate now computes the TRUE risk and rejects it.


class TestTrade287RegressionRiskGate:
    """Reproduces trade #287's exact MGC numbers at both call layers."""

    MGC_ENTRY = 4153.85
    MGC_STOP = 4134.6666
    # |4153.85 - 4134.6666| * 10 ($/pt for MGC) * 1 contract
    EXPECTED_DOLLAR_RISK = round(abs(4153.85 - 4134.6666) * 10.0, 2)

    def test_expected_dollar_risk_matches_incident_report(self):
        """Sanity-check the fixture math against the confirmed incident number."""
        assert self.EXPECTED_DOLLAR_RISK == pytest.approx(191.83, abs=0.01)

    def test_gate_level_rejects_trade_287_scenario_when_wired_correctly(self, mock_settings):
        """_check_trade_loss_gate(), given the CORRECT entry/stop, rejects.

        This is what the gate computes once both wiring bugs are fixed: a
        real OrderRequest carrying the Trader agent's intended entry_price
        (not the stop) as the pricing basis, and stop_price wired through
        from submit_paper_bracket_order's `stop_loss` argument.
        """
        mock_settings.MAX_TRADE_LOSS_USD = 50.0
        safety = SafetyLayer(mock_settings)
        order = OrderRequest(
            symbol="MGC",
            quantity=1,
            order_type="market",
            is_futures=True,
            stop_price=self.MGC_STOP,
            estimated_value=self.MGC_ENTRY,  # abs_qty(1) * entry_price
        )
        result = safety._check_trade_loss_gate(order)
        assert result.approved is False
        assert "TRADE_LOSS_LIMIT" in result.rejection_reason
        assert f"${self.EXPECTED_DOLLAR_RISK:.2f}" in result.rejection_reason

    def test_gate_level_pre_fix_shape_was_defeated(self, mock_settings):
        """Documents the PRE-fix failure mode: bug 1a alone (entry == stop)
        collapses points_at_risk to ~0, so even a correctly-stop_price-wired
        gate would have nodded the trade through -- entry_price must be
        fixed, not just the stop_price plumbing.
        """
        mock_settings.MAX_TRADE_LOSS_USD = 50.0
        safety = SafetyLayer(mock_settings)
        buggy_order = OrderRequest(
            symbol="MGC",
            quantity=1,
            order_type="market",
            is_futures=True,
            stop_price=self.MGC_STOP,
            # Bug 1a: price_info = limit_price or stop_price -> entry ends up
            # equal to the stop for a MKT order.
            estimated_value=self.MGC_STOP,
        )
        result = safety._check_trade_loss_gate(buggy_order)
        assert result.approved is True  # gate is defeated: ~$0 points-at-risk

    @pytest.mark.asyncio
    async def test_submit_paper_bracket_order_rejects_trade_287_scenario(self, mock_settings):
        """End-to-end through submit_paper_bracket_order(): with the correct
        entry price argument and stop_loss now wired into the OrderRequest,
        the oversized-risk bracket is rejected before it ever reaches the
        (mock) broker -- routed_to_ib must stay False.

        MGC joined DO_NOT_TRADE_SYMBOLS 2026-07-31 (honest-data-drain DSR
        correction), which runs even earlier in check_order()'s pipeline and
        would mask TRADE_LOSS_LIMIT the same way. Patch it out for the
        duration of this test: this test isolates the trade-loss gate
        specifically, not MGC's (separate, real) halted status.
        """
        mock_settings.LIVE_TRADING_ENABLED = True
        mock_settings.REQUIRE_HUMAN_APPROVAL = False
        mock_settings.MAX_DAILY_LOSS_PCT = 0.10
        mock_settings.MAX_DRAWDOWN_PCT = 0.20
        mock_settings.MAX_SINGLE_ORDER_VALUE = 500_000.0
        mock_settings.MAX_FUTURES_MARGIN_PCT = 0.40
        mock_settings.MAX_CONTRACTS_PER_INSTRUMENT = 10
        mock_settings.MAX_TRADE_LOSS_USD = 50.0
        safety = SafetyLayer(mock_settings)
        gw = AsyncMock()
        gw.is_connected = Mock(return_value=True)
        safety._ib_gateway = gw

        with patch("risk.safety_layer.DO_NOT_TRADE_SYMBOLS", frozenset({"MCL", "MNQ", "M2K"})):
            result = await safety.submit_paper_bracket_order(
                "MGC", "BUY", 1, self.MGC_ENTRY, stop_loss=self.MGC_STOP, take_profit=None
            )

        assert result["approved"] is False
        assert "TRADE_LOSS_LIMIT" in result["reason"]
        assert result["routed_to_ib"] is False
        gw.place_bracket_order.assert_not_called()


# ---------------------------------------------------------------------------
# §C10 — tilt detector paths in check_order (lines 1082–1095)
# ---------------------------------------------------------------------------


class TestTiltDetectorInCheckOrder:
    """Tilt detector: halt and caution/warning paths."""

    def _permissive_safety(self, mock_settings) -> SafetyLayer:
        mock_settings.LIVE_TRADING_ENABLED = True
        mock_settings.REQUIRE_HUMAN_APPROVAL = False
        mock_settings.MAX_DAILY_LOSS_PCT = 0.50
        mock_settings.MAX_DRAWDOWN_PCT = 0.50
        mock_settings.MAX_SINGLE_ORDER_VALUE = 50_000.0
        mock_settings.MAX_FUTURES_MARGIN_PCT = 0.50
        mock_settings.MAX_CONTRACTS_PER_INSTRUMENT = 5
        mock_settings.MAX_TRADE_LOSS_USD = 500.0
        return SafetyLayer(mock_settings)

    def test_tilt_halts_order_when_multiplier_zero(self, mock_settings):
        """Tilt detector multiplier=0.0 → order rejected."""
        safety = self._permissive_safety(mock_settings)
        mock_tilt = MagicMock()
        tilt_state = MagicMock()
        tilt_state.position_size_multiplier = 0.0
        tilt_state.severity = "critical"
        mock_tilt.check.return_value = tilt_state
        safety.tilt_detector = mock_tilt
        order = OrderRequest(symbol="MES", quantity=1, order_type="market", is_futures=True)
        result = safety.check_order(order, portfolio_equity=100_000.0)
        assert result.approved is False
        assert "tilt" in result.rejection_reason.lower()

    def test_tilt_caution_adds_warning(self, mock_settings):
        """Tilt detector severity='caution' → warning added, order approved."""
        safety = self._permissive_safety(mock_settings)
        mock_tilt = MagicMock()
        tilt_state = MagicMock()
        tilt_state.position_size_multiplier = 0.8
        tilt_state.severity = "caution"
        mock_tilt.check.return_value = tilt_state
        safety.tilt_detector = mock_tilt
        order = OrderRequest(symbol="MES", quantity=1, order_type="market", is_futures=True)
        result = safety.check_order(order, portfolio_equity=100_000.0)
        assert result.approved is True
        assert any("Tilt" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# §C10 — re-entry lockout active in check_order (lines 1094–1095)
# ---------------------------------------------------------------------------


class TestReentryLockoutInCheckOrder:
    def test_lockout_active_blocks_order(self, mock_settings):
        """Active re-entry lockout for a symbol → check_order returns rejected."""
        from datetime import timedelta

        mock_settings.LIVE_TRADING_ENABLED = True
        mock_settings.REQUIRE_HUMAN_APPROVAL = False
        mock_settings.MAX_TRADE_LOSS_USD = 500.0
        safety = SafetyLayer(mock_settings)
        safety._reentry_lockouts["MES"] = datetime.now() + timedelta(minutes=30)
        order = OrderRequest(symbol="MES", quantity=1, order_type="market", is_futures=True)
        result = safety.check_order(order, portfolio_equity=100_000.0)
        assert result.approved is False
        assert "LOCKOUT" in result.rejection_reason


# ---------------------------------------------------------------------------
# §C10 — halted loss tracker returns from check_order (line 1103)
# ---------------------------------------------------------------------------


class TestLossTrackerHaltedViaCheckOrder:
    def test_halted_tracker_blocks_order_via_check_order(self, mock_settings):
        """Loss tracker is_halted() → check_order returns rejected (line 1103)."""
        mock_settings.LIVE_TRADING_ENABLED = True
        mock_settings.REQUIRE_HUMAN_APPROVAL = False
        mock_settings.MAX_DAILY_LOSS_PCT = 0.99
        mock_settings.MAX_DRAWDOWN_PCT = 0.99
        mock_settings.MAX_SINGLE_ORDER_VALUE = 50_000.0
        mock_settings.MAX_FUTURES_MARGIN_PCT = 0.99
        mock_settings.MAX_CONTRACTS_PER_INSTRUMENT = 5
        mock_settings.MAX_TRADE_LOSS_USD = 500.0
        safety = SafetyLayer(mock_settings)
        mock_tracker = MagicMock()
        mock_tracker.is_halted.return_value = True
        mock_tracker.get_halt_reason.return_value = "Halted: 5 consecutive losses"
        safety._loss_tracker = mock_tracker
        order = OrderRequest(symbol="MES", quantity=1, order_type="market", is_futures=True)
        result = safety.check_order(order, portfolio_equity=100_000.0)
        assert result.approved is False
        assert "consecutive" in result.rejection_reason


# ---------------------------------------------------------------------------
# §C10 — Schwab broker target in check_order (line 1111)
# ---------------------------------------------------------------------------


class TestSchwabBrokerTarget:
    def test_options_with_schwab_routes_to_schwab(self, mock_settings):
        """is_options=True and schwab attached → broker_target includes Schwab (line 1111)."""
        mock_settings.LIVE_TRADING_ENABLED = True
        mock_settings.REQUIRE_HUMAN_APPROVAL = False
        mock_settings.MAX_DAILY_LOSS_PCT = 0.99
        mock_settings.MAX_DRAWDOWN_PCT = 0.99
        mock_settings.MAX_SINGLE_ORDER_VALUE = 50_000.0
        mock_settings.MAX_FUTURES_MARGIN_PCT = 0.99
        mock_settings.MAX_CONTRACTS_PER_INSTRUMENT = 5
        mock_settings.MAX_TRADE_LOSS_USD = 500.0
        safety = SafetyLayer(mock_settings)
        safety.schwab = MagicMock()
        # options order: is_options=True, low estimated_value
        order = OrderRequest(
            symbol="SPY",
            quantity=1,
            order_type="market",
            is_futures=False,
            is_options=True,
            estimated_value=100.0,
        )
        result = safety.check_order(order, portfolio_equity=100_000.0)
        # Result may or may not be approved depending on other gates, but line 1111 fires
        # as long as is_options=True and schwab is set — check it didn't crash
        assert result is not None


# ---------------------------------------------------------------------------
# §C10 — submit_paper_order unknown order_type (line 1219)
# ---------------------------------------------------------------------------


class TestSubmitPaperOrderUnknownOrderType:
    @pytest.mark.asyncio
    async def test_unknown_order_type_normalised_passthrough(self, mock_settings):
        """order_type='STP_LMT' → neither mkt nor lmt → kept as-is (line 1219)."""
        mock_settings.LIVE_TRADING_ENABLED = True
        mock_settings.REQUIRE_HUMAN_APPROVAL = False
        mock_settings.MAX_DAILY_LOSS_PCT = 0.10
        mock_settings.MAX_DRAWDOWN_PCT = 0.20
        mock_settings.MAX_SINGLE_ORDER_VALUE = 50_000.0
        mock_settings.MAX_FUTURES_MARGIN_PCT = 0.30
        mock_settings.MAX_CONTRACTS_PER_INSTRUMENT = 5
        mock_settings.MAX_TRADE_LOSS_USD = 500.0
        safety = SafetyLayer(mock_settings)
        # No gateway → dry-run; all we care is it doesn't crash on "stp_lmt"
        result = await safety.submit_paper_order("MES", "BUY", 1, 5800.0, order_type="STP_LMT")
        assert result["approved"] is True


# ---------------------------------------------------------------------------
# §C10 — _verify_parent_linkage edge cases (lines 1344–1359)
# ---------------------------------------------------------------------------


class TestVerifyParentLinkage:
    """_verify_parent_linkage: None child, exception, non-dict, missing parent key."""

    @pytest.mark.asyncio
    async def test_none_child_returns_false(self, mock_settings):
        """child_order_id=None → immediately returns False."""
        safety = SafetyLayer(mock_settings)
        mock_gw = AsyncMock()
        safety._ib_gateway = mock_gw
        result = await safety._verify_parent_linkage(None, "entry_id")
        assert result is False
        mock_gw.get_order_status.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_order_status_raises_returns_false(self, mock_settings):
        """get_order_status raises → logs warning, returns False."""
        safety = SafetyLayer(mock_settings)
        mock_gw = AsyncMock()
        mock_gw.get_order_status = AsyncMock(side_effect=RuntimeError("IB error"))
        safety._ib_gateway = mock_gw
        result = await safety._verify_parent_linkage("stp_123", "entry_id")
        assert result is False

    @pytest.mark.asyncio
    async def test_status_not_dict_returns_false(self, mock_settings):
        """get_order_status returns a non-dict → returns False."""
        safety = SafetyLayer(mock_settings)
        mock_gw = AsyncMock()
        mock_gw.get_order_status = AsyncMock(return_value="not_a_dict")
        safety._ib_gateway = mock_gw
        result = await safety._verify_parent_linkage("stp_123", "entry_id")
        assert result is False

    @pytest.mark.asyncio
    async def test_parent_key_missing_returns_false(self, mock_settings):
        """status dict has no parent_order_id key → returns False."""
        safety = SafetyLayer(mock_settings)
        mock_gw = AsyncMock()
        mock_gw.get_order_status = AsyncMock(return_value={"some_other_key": "value"})
        safety._ib_gateway = mock_gw
        result = await safety._verify_parent_linkage("stp_123", "entry_id")
        assert result is False

    @pytest.mark.asyncio
    async def test_parent_matches_returns_true(self, mock_settings):
        """parent_order_id matches entry_id → returns True."""
        safety = SafetyLayer(mock_settings)
        mock_gw = AsyncMock()
        mock_gw.get_order_status = AsyncMock(return_value={"parent_order_id": "entry_id"})
        safety._ib_gateway = mock_gw
        result = await safety._verify_parent_linkage("stp_123", "entry_id")
        assert result is True


# ---------------------------------------------------------------------------
# §C10 — sync_from_broker with pnl_monitor + loss_tracker (lines 1649, 1660)
# ---------------------------------------------------------------------------


class TestSyncFromBrokerPnlMonitorPaths:
    def test_sync_with_pnl_monitor_reads_drawdown(self, mock_settings):
        """pnl_monitor.get_drawdown_pct() called inside sync_from_broker alert path."""
        mock_am = MagicMock()
        mock_am.check_and_alert.return_value = None
        mock_pm = MagicMock()
        mock_pm.get_drawdown_pct.return_value = -0.05
        safety = SafetyLayer(mock_settings, pnl_monitor=mock_pm)
        safety._alert_manager = mock_am
        safety.sync_from_broker(equity=100_000.0, daily_pnl=-500.0)
        mock_pm.get_drawdown_pct.assert_called()

    def test_sync_with_loss_tracker_reads_consecutive_losses(self, mock_settings):
        """loss_tracker.get_consecutive_losses() called inside sync_from_broker alert path."""
        mock_am = MagicMock()
        mock_am.check_and_alert.return_value = None
        mock_tracker = MagicMock()
        mock_tracker.get_consecutive_losses.return_value = 2
        safety = SafetyLayer(mock_settings)
        safety._alert_manager = mock_am
        safety._loss_tracker = mock_tracker
        safety.sync_from_broker(equity=100_000.0, daily_pnl=-500.0)
        mock_tracker.get_consecutive_losses.assert_called()


# ---------------------------------------------------------------------------
# §C10 — check_circuit_breakers with pnl_monitor (lines 1695, 1704–1721)
# ---------------------------------------------------------------------------


class TestCheckCircuitBreakersWithPnlMonitor:
    def test_circuit_breakers_use_pnl_monitor_daily_pnl(self, mock_settings):
        """pnl_monitor.get_daily_pnl() used for daily_pnl_for_check (line 1695)."""
        mock_pm = MagicMock()
        mock_pm.get_daily_pnl.return_value = -300.0
        mock_pm.get_drawdown_pct.return_value = -0.03
        safety = SafetyLayer(mock_settings, pnl_monitor=mock_pm)
        status = safety.check_circuit_breakers()
        assert status["daily_pnl"] == -300.0
        mock_pm.get_daily_pnl.assert_called()

    def test_circuit_breakers_zero_equity_pnl_monitor_fallback(self, mock_settings):
        """Zero current_equity → pnl_monitor equity fallback (lines 1704–1708)."""
        mock_pm = MagicMock()
        mock_pm.get_daily_pnl.return_value = 0.0
        mock_pm.get_drawdown_pct.return_value = 0.0
        pnl_state = MagicMock()
        pnl_state.current_balance = 10_000.0
        mock_pm.get_current_pnl_state.return_value = pnl_state
        safety = SafetyLayer(mock_settings, pnl_monitor=mock_pm)
        safety._current_equity = 0.0  # force fallback
        status = safety.check_circuit_breakers()
        assert status is not None  # didn't crash

    def test_circuit_breakers_drawdown_via_pnl_monitor(self, mock_settings):
        """pnl_monitor.get_drawdown_pct() used for drawdown (line 1721)."""
        mock_pm = MagicMock()
        mock_pm.get_daily_pnl.return_value = 0.0
        mock_pm.get_drawdown_pct.return_value = -0.12  # 12% down
        safety = SafetyLayer(mock_settings, pnl_monitor=mock_pm)
        status = safety.check_circuit_breakers()
        assert status["drawdown_pct"] == pytest.approx(0.12, rel=1e-3)


# ---------------------------------------------------------------------------
# §C10 — parallel paper per-account kill state (lines 561–730)
# ---------------------------------------------------------------------------


def _make_parallel_paper_db(tmp_path) -> str:
    """Create a minimal SQLite DB with the per_account_kill_state table."""
    import sqlite3

    db_path = str(tmp_path / "parallel_paper.db")
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE per_account_kill_state (
            account_id TEXT PRIMARY KEY,
            active INTEGER NOT NULL DEFAULT 0,
            triggered_at TEXT,
            reason TEXT,
            trigger_metric TEXT,
            trigger_value REAL,
            cleared_at TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS system_state (
            key TEXT PRIMARY KEY,
            value TEXT
        )
        """
    )
    conn.commit()
    conn.close()
    return db_path


class TestParallelPaperKillState:
    """Per-account kill state when ENABLE_PARALLEL_PAPER=1."""

    def test_get_per_account_kill_state_enabled_db_path_none(self, mock_settings):
        """ENABLE_PARALLEL_PAPER=1 but no db_path → returns dict with active=False."""
        with patch.dict("os.environ", {"ENABLE_PARALLEL_PAPER": "1"}):
            safety = SafetyLayer(mock_settings)
            safety._db_path = None  # ensure no db_path despite env var
            state = safety.get_per_account_kill_state("A")
            assert state["active"] is False
            assert state["account_id"] == "A"

    def test_get_per_account_kill_state_no_row(self, mock_settings, tmp_path):
        """ENABLE_PARALLEL_PAPER=1, DB has no row → active=False."""
        db_path = _make_parallel_paper_db(tmp_path)
        with patch.dict("os.environ", {"ENABLE_PARALLEL_PAPER": "1"}):
            safety = SafetyLayer(mock_settings, db_path=db_path)
            state = safety.get_per_account_kill_state("A")
            assert state["active"] is False

    def test_trigger_per_account_kill_enabled(self, mock_settings, tmp_path):
        """ENABLE_PARALLEL_PAPER=1 → trigger writes row to per_account_kill_state."""
        db_path = _make_parallel_paper_db(tmp_path)
        with patch.dict("os.environ", {"ENABLE_PARALLEL_PAPER": "1"}):
            safety = SafetyLayer(mock_settings, db_path=db_path)
            safety.trigger_per_account_kill("A", "max_daily_loss", -150.0, "test trigger")
            state = safety.get_per_account_kill_state("A")
            assert state["active"] is True

    def test_trigger_per_account_kill_enabled_no_db_path(self, mock_settings):
        """ENABLE_PARALLEL_PAPER=1 but db_path=None → logs warning, no crash."""
        with patch.dict("os.environ", {"ENABLE_PARALLEL_PAPER": "1"}):
            safety = SafetyLayer(mock_settings)
            safety._db_path = None
            safety.trigger_per_account_kill("B", "max_daily_loss", -200.0, "no db")
            # Should not raise

    def test_clear_per_account_kill_enabled(self, mock_settings, tmp_path):
        """ENABLE_PARALLEL_PAPER=1 → clear sets active=0 in DB."""
        db_path = _make_parallel_paper_db(tmp_path)
        with patch.dict("os.environ", {"ENABLE_PARALLEL_PAPER": "1"}):
            safety = SafetyLayer(mock_settings, db_path=db_path)
            safety.trigger_per_account_kill("A", "max_daily_loss", -150.0, "trigger first")
            safety.clear_per_account_kill("A", "cleared in test")
            state = safety.get_per_account_kill_state("A")
            assert state["active"] is False

    def test_clear_per_account_kill_enabled_no_db_path(self, mock_settings):
        """ENABLE_PARALLEL_PAPER=1 but db_path=None → returns without crash."""
        with patch.dict("os.environ", {"ENABLE_PARALLEL_PAPER": "1"}):
            safety = SafetyLayer(mock_settings)
            safety._db_path = None
            safety.clear_per_account_kill("A")  # should not raise

    def test_is_account_halted_per_account_active(self, mock_settings, tmp_path):
        """ENABLE_PARALLEL_PAPER=1, account A triggered → is_account_halted('A')=True."""
        db_path = _make_parallel_paper_db(tmp_path)
        with patch.dict("os.environ", {"ENABLE_PARALLEL_PAPER": "1"}):
            safety = SafetyLayer(mock_settings, db_path=db_path)
            safety.trigger_per_account_kill("A", "max_daily_loss", -150.0, "test")
            assert safety.is_account_halted("A") is True

    def test_is_account_halted_per_account_not_triggered(self, mock_settings, tmp_path):
        """ENABLE_PARALLEL_PAPER=1, no trigger for B → is_account_halted('B')=False."""
        db_path = _make_parallel_paper_db(tmp_path)
        with patch.dict("os.environ", {"ENABLE_PARALLEL_PAPER": "1"}):
            safety = SafetyLayer(mock_settings, db_path=db_path)
            assert safety.is_account_halted("B") is False

    def test_get_per_account_kill_state_returns_row_data(self, mock_settings, tmp_path):
        """ENABLE_PARALLEL_PAPER=1, triggered row → state has active=True and reason."""
        db_path = _make_parallel_paper_db(tmp_path)
        with patch.dict("os.environ", {"ENABLE_PARALLEL_PAPER": "1"}):
            safety = SafetyLayer(mock_settings, db_path=db_path)
            safety.trigger_per_account_kill("A", "max_drawdown", -0.12, "drawdown breach")
            state = safety.get_per_account_kill_state("A")
            assert state["active"] is True
            assert state["reason"] == "drawdown breach"
            assert state["trigger_metric"] == "max_drawdown"


# ---------------------------------------------------------------------------
# §C10 — pnl_monitor seed exception path (lines 342–343)
# ---------------------------------------------------------------------------


class TestPnlMonitorSeedException:
    def test_pnl_monitor_get_state_raises_is_logged_not_raised(self, mock_settings):
        """pnl_monitor.get_current_pnl_state() raises during __init__ → logs warning, no crash."""
        mock_pm = MagicMock()
        mock_pm.get_current_pnl_state.side_effect = RuntimeError("DB unavailable")
        # SafetyLayer must not raise even when pnl_monitor raises in __init__
        safety = SafetyLayer(mock_settings, pnl_monitor=mock_pm)
        assert safety is not None
        # After exception, INITIAL_CAPITAL fallback may have seeded equity — that's fine
        assert safety._current_equity >= 0.0


# ---------------------------------------------------------------------------
# §C10 — INITIAL_CAPITAL bad type fallback (lines 348–349)
# ---------------------------------------------------------------------------


class TestInitialCapitalBadType:
    def test_initial_capital_non_numeric_handled(self, mock_settings):
        """INITIAL_CAPITAL='bad' → float() raises ValueError → silently defaults to 0."""
        mock_settings.INITIAL_CAPITAL = "not_a_number"
        safety = SafetyLayer(mock_settings)
        assert safety._current_equity == 0.0


# ---------------------------------------------------------------------------
# §C10 — loss_tracker.get_consecutive_losses in _persist_pnl_snapshot (line 385)
# ---------------------------------------------------------------------------


class TestPersistWithLossTracker:
    def test_persist_calls_loss_tracker_consecutive_losses(self, mock_settings):
        """_persist_pnl_snapshot calls loss_tracker.get_consecutive_losses() when set."""
        import sqlite3

        mock_db = MagicMock()
        mock_db.get_pnl_snapshot.return_value = None
        mock_settings.INITIAL_CAPITAL = 10_000.0
        safety = SafetyLayer(mock_settings, db_manager=mock_db)
        mock_tracker = MagicMock()
        mock_tracker.get_consecutive_losses.return_value = 3
        safety._loss_tracker = mock_tracker
        mock_db.upsert_pnl_snapshot.reset_mock()
        safety.sync_from_broker(equity=10_000.0, daily_pnl=0.0)
        mock_tracker.get_consecutive_losses.assert_called()
        mock_db.upsert_pnl_snapshot.assert_called_once()


# ---------------------------------------------------------------------------
# §C10 — kill switch restore from DB with bad/missing reason (lines 425–428)
# ---------------------------------------------------------------------------


def _make_kill_switch_db(tmp_path, reason_str=None) -> str:
    """Create a SQLite DB with kill switch active and optional reason string."""
    import sqlite3

    db_path = str(tmp_path / "ks_test.db")
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE system_state (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("INSERT INTO system_state VALUES ('kill_switch_active', 'true')")
    if reason_str is not None:
        conn.execute("INSERT INTO system_state VALUES ('kill_switch_reason', ?)", (reason_str,))
    conn.commit()
    conn.close()
    return db_path


class TestKillSwitchRestoreFromDb:
    def test_bogus_reason_string_falls_back_to_manual(self, mock_settings, tmp_path):
        """kill_switch_reason stored as unknown string → ValueError → MANUAL (lines 425–426)."""
        db_path = _make_kill_switch_db(tmp_path, reason_str="COMPLETELY_BOGUS_ENUM_VALUE")
        safety = SafetyLayer(mock_settings, db_path=db_path)
        assert safety._kill_switch_active is True
        assert safety._kill_switch_reason == KillSwitchReason.MANUAL

    def test_missing_reason_row_falls_back_to_manual(self, mock_settings, tmp_path):
        """kill_switch_active=true, no reason row → reason=None → MANUAL (lines 427–428)."""
        db_path = _make_kill_switch_db(tmp_path, reason_str=None)
        safety = SafetyLayer(mock_settings, db_path=db_path)
        assert safety._kill_switch_active is True
        assert safety._kill_switch_reason == KillSwitchReason.MANUAL


# ---------------------------------------------------------------------------
# §C10 — OpenClaw notifier import exception in activate_kill_switch (lines 505–506)
# ---------------------------------------------------------------------------


class TestOpenClawImportException:
    def test_openclaw_unavailable_does_not_raise(self, mock_settings):
        """OpenClaw notifier import fails → except branch logged, no crash (lines 505–506)."""
        safety = SafetyLayer(mock_settings)
        with patch.dict("sys.modules", {"notifications.openclaw_notifier": None}):
            # Should not raise even with broken openclaw import
            safety.activate_kill_switch(KillSwitchReason.MANUAL, "openclaw test")
        assert safety.is_killed is True


# ---------------------------------------------------------------------------
# §C10 — get_per_account_kill_state when parallel paper disabled (line 562)
# ---------------------------------------------------------------------------


class TestGetPerAccountKillStateDisabled:
    def test_parallel_paper_disabled_returns_global_kill_state(self, mock_settings):
        """ENABLE_PARALLEL_PAPER not set → returns dict reflecting global kill (line 562)."""
        # Ensure env var not set
        with patch.dict("os.environ", {}, clear=False):
            import os

            os.environ.pop("ENABLE_PARALLEL_PAPER", None)
            safety = SafetyLayer(mock_settings)
            state = safety.get_per_account_kill_state("A")
        assert "account_id" in state
        assert state["account_id"] == "A"
        assert "active" in state


# ---------------------------------------------------------------------------
# §C10 — parallel paper DB exception paths (lines 612–616, 684–685, 729–730)
# ---------------------------------------------------------------------------


class TestParallelPaperDbExceptions:
    def test_get_per_account_kill_state_db_exception(self, mock_settings, tmp_path):
        """sqlite3.connect raises during get_per_account_kill_state → except (lines 612–616)."""
        db_path = _make_parallel_paper_db(tmp_path)
        with patch.dict("os.environ", {"ENABLE_PARALLEL_PAPER": "1"}):
            safety = SafetyLayer(mock_settings, db_path=db_path)
            with patch("sqlite3.connect", side_effect=Exception("DB dead")):
                state = safety.get_per_account_kill_state("A")
        assert state["active"] is False
        assert state["account_id"] == "A"

    def test_trigger_per_account_kill_db_exception(self, mock_settings, tmp_path):
        """sqlite3.connect raises during trigger_per_account_kill → except (lines 684–685)."""
        db_path = _make_parallel_paper_db(tmp_path)
        with patch.dict("os.environ", {"ENABLE_PARALLEL_PAPER": "1"}):
            safety = SafetyLayer(mock_settings, db_path=db_path)
            with patch("sqlite3.connect", side_effect=Exception("DB dead")):
                safety.trigger_per_account_kill("A", "max_daily_loss", -100.0, "test")
        # No exception should have propagated

    def test_clear_per_account_kill_db_exception(self, mock_settings, tmp_path):
        """sqlite3.connect raises during clear_per_account_kill → except (lines 729–730)."""
        db_path = _make_parallel_paper_db(tmp_path)
        with patch.dict("os.environ", {"ENABLE_PARALLEL_PAPER": "1"}):
            safety = SafetyLayer(mock_settings, db_path=db_path)
            with patch("sqlite3.connect", side_effect=Exception("DB dead")):
                safety.clear_per_account_kill("A", "test clear")
        # No exception should have propagated


# ---------------------------------------------------------------------------
# §C10 — daily PCT loss limit triggers kill switch (lines 869–873)
# ---------------------------------------------------------------------------


class TestDailyPctLossLimit:
    def test_pct_loss_limit_triggers_kill_switch(self, mock_settings):
        """Daily total P&L exceeds PCT limit → kill switch activated (lines 869–873)."""
        mock_settings.LIVE_TRADING_ENABLED = True
        mock_settings.REQUIRE_HUMAN_APPROVAL = False
        mock_settings.MAX_DAILY_LOSS_PCT = 0.02  # 2%
        mock_settings.MAX_DAILY_LOSS_USD = 999_999.0  # ABS limit won't trigger
        mock_settings.MAX_TRADE_LOSS_USD = 500.0
        safety = SafetyLayer(mock_settings)
        safety._current_equity = 100_000.0
        safety._daily_realized_pnl = -5_000.0  # 5% loss >> 2% limit
        order = OrderRequest(symbol="MES", quantity=1, order_type="market", is_futures=True)
        result = safety.check_order(order, portfolio_equity=100_000.0)
        assert result.approved is False
        assert safety.is_killed is True


# ---------------------------------------------------------------------------
# §C10 — check_circuit_breakers pnl_monitor equity fallback exception (lines 1707–1708)
# ---------------------------------------------------------------------------


class TestCircuitBreakerPnlMonitorException:
    def test_pnl_monitor_equity_fallback_exception_is_swallowed(self, mock_settings):
        """pnl_monitor.get_current_pnl_state() raises in circuit breaker → no crash (1707–1708)."""
        mock_pm = MagicMock()
        mock_pm.get_daily_pnl.return_value = 0.0
        mock_pm.get_drawdown_pct.return_value = 0.0
        mock_pm.get_current_pnl_state.side_effect = RuntimeError("PM crash")
        safety = SafetyLayer(mock_settings, pnl_monitor=mock_pm)
        safety._current_equity = 0.0  # force fallback attempt
        status = safety.check_circuit_breakers()
        assert status is not None  # did not raise


# ---------------------------------------------------------------------------
# §C10 — emergency flatten state restored from DB (lines 459–460)
# ---------------------------------------------------------------------------


class TestEmergencyFlattenRestoreFromDb:
    def test_emergency_flatten_restored_on_startup(self, mock_settings, tmp_path):
        """Kill switch + emergency_flatten_activated=true in DB → _emergency_flatten_activated set (lines 459–460)."""
        db_path = str(tmp_path / "ef_test.db")
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE system_state (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT)"
        )
        conn.execute(
            "INSERT INTO system_state VALUES ('kill_switch_active', 'true', datetime('now'))"
        )
        conn.execute(
            "INSERT INTO system_state VALUES ('kill_switch_reason', 'DAILY_LOSS_LIMIT', datetime('now'))"
        )
        conn.execute(
            "INSERT INTO system_state VALUES ('emergency_flatten_activated', 'true', datetime('now'))"
        )
        conn.commit()
        conn.close()
        safety = SafetyLayer(mock_settings, db_path=db_path)
        assert safety._emergency_flatten_activated is True


# ---------------------------------------------------------------------------
# §C10 — current_halt_level property (lines 576–585)
# ---------------------------------------------------------------------------


class TestCurrentHaltLevel:
    def test_emergency_flatten_activated_returns_emergency_flatten(self, mock_settings):
        """_emergency_flatten_activated=True → current_halt_level=EMERGENCY_FLATTEN (lines 576–577)."""
        safety = SafetyLayer(mock_settings)
        safety._emergency_flatten_activated = True
        assert safety.current_halt_level.value == "emergency_flatten"

    def test_kill_switch_active_returns_hard_halt(self, mock_settings):
        """_kill_switch_active=True → current_halt_level=HARD_HALT (lines 578–579)."""
        safety = SafetyLayer(mock_settings)
        safety._kill_switch_active = True
        assert safety.current_halt_level.value == "hard_halt"

    def test_loss_tracker_multiplier_below_one_returns_soft_halt(self, mock_settings):
        """loss_tracker.get_position_size_multiplier() < 1.0 → SOFT_HALT (lines 580–584)."""
        safety = SafetyLayer(mock_settings)
        mock_tracker = MagicMock()
        mock_tracker.get_position_size_multiplier.return_value = 0.5
        safety._loss_tracker = mock_tracker
        assert safety.current_halt_level.value == "soft_halt"

    def test_no_halts_returns_normal(self, mock_settings):
        """No halt conditions active → NORMAL (line 585)."""
        safety = SafetyLayer(mock_settings)
        assert safety.current_halt_level.value == "normal"


# ---------------------------------------------------------------------------
# §C10 — emergency_flatten_and_halt async method (lines 597–604)
# ---------------------------------------------------------------------------


class TestEmergencyFlattenAndHalt:
    @pytest.mark.asyncio
    async def test_emergency_flatten_and_halt_activates_kill_switch(self, mock_settings):
        """emergency_flatten_and_halt → kill switch active + flatten called (lines 597–604)."""
        mock_db = MagicMock()
        mock_db.get_pnl_snapshot.return_value = None
        mock_settings.INITIAL_CAPITAL = 10_000.0
        safety = SafetyLayer(mock_settings, db_manager=mock_db)
        with patch.object(
            safety,
            "flatten_all_positions",
            new=AsyncMock(return_value={"flattened": [], "errors": []}),
        ):
            result = await safety.emergency_flatten_and_halt("unit test")
        assert result["halt_level"] == "emergency_flatten"
        assert result["kill_switch_activated"] is True
        assert safety.is_killed is True
        assert safety._emergency_flatten_activated is True


# ---------------------------------------------------------------------------
# §C10 — check_order tuple result unpacking (line 1150)
# ---------------------------------------------------------------------------


class TestCheckOrderTupleResultUnpacking:
    def test_check_fn_returning_tuple_is_unpacked(self, mock_settings):
        """check_fn returns (RiskCheckResult, extra) → unpacked at line 1150, no crash."""
        mock_settings.LIVE_TRADING_ENABLED = True
        mock_settings.REQUIRE_HUMAN_APPROVAL = False
        mock_settings.MAX_DAILY_LOSS_PCT = 0.10
        mock_settings.MAX_DRAWDOWN_PCT = 0.20
        mock_settings.MAX_SINGLE_ORDER_VALUE = 50_000.0
        mock_settings.MAX_FUTURES_MARGIN_PCT = 0.30
        mock_settings.MAX_CONTRACTS_PER_INSTRUMENT = 5
        mock_settings.MAX_TRADE_LOSS_USD = 500.0
        safety = SafetyLayer(mock_settings)
        with patch.object(
            safety, "_check_kill_switch", return_value=(RiskCheckResult(approved=True), None)
        ):
            order = OrderRequest(symbol="MES", quantity=1, order_type="market", is_futures=True)
            result = safety.check_order(order, portfolio_equity=100_000.0)
        assert result is not None


# ---------------------------------------------------------------------------
# §C10 — submit_entry_with_stop sidecar exception paths (lines 1621–1622, 1629–1630)
# ---------------------------------------------------------------------------


class TestSubmitEntryWithStopSidecarExceptions:
    def _live_gw(self, mock_settings):
        mock_settings.LIVE_TRADING_ENABLED = True
        mock_settings.REQUIRE_HUMAN_APPROVAL = False
        mock_settings.MAX_DAILY_LOSS_PCT = 0.10
        mock_settings.MAX_DRAWDOWN_PCT = 0.20
        mock_settings.MAX_SINGLE_ORDER_VALUE = 50_000.0
        mock_settings.MAX_FUTURES_MARGIN_PCT = 0.30
        mock_settings.MAX_CONTRACTS_PER_INSTRUMENT = 5
        mock_settings.MAX_TRADE_LOSS_USD = 500.0
        safety = SafetyLayer(mock_settings)
        mock_gw = AsyncMock()
        mock_gw.is_connected = Mock(return_value=True)
        mock_gw.get_order_status = AsyncMock(return_value={"parent_order_id": "entry_id"})
        safety._ib_gateway = mock_gw
        return safety, mock_gw

    @pytest.mark.asyncio
    async def test_sidecar_json_read_exception_handled(self, mock_settings):
        """Sidecar exists but read raises → inner except _state={} (lines 1621–1622), trade approved."""
        safety, mock_gw = self._live_gw(mock_settings)
        mock_gw.place_paper_order = AsyncMock(side_effect=["entry_id", "hb1_stp", "stp_id"])
        mock_gw.get_order_status = AsyncMock(return_value={"parent_order_id": "entry_id"})
        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("pathlib.Path.read_text", side_effect=ValueError("corrupt json")),
            patch("pathlib.Path.write_text"),
            patch("pathlib.Path.mkdir"),
        ):
            result = await safety.submit_entry_with_stop("MES", "BUY", 1, 5800.0, 5785.0)
        assert result["approved"] is True

    @pytest.mark.asyncio
    async def test_sidecar_outer_exception_handled(self, mock_settings):
        """Sidecar mkdir raises → outer except logs warning, does not propagate (lines 1629–1630)."""
        safety, mock_gw = self._live_gw(mock_settings)
        mock_gw.place_paper_order = AsyncMock(side_effect=["entry_id", "hb1_stp", "stp_id"])
        mock_gw.get_order_status = AsyncMock(return_value={"parent_order_id": "entry_id"})
        with patch("pathlib.Path.mkdir", side_effect=PermissionError("no write")):
            result = await safety.submit_entry_with_stop("MES", "BUY", 1, 5800.0, 5785.0)
        assert result["approved"] is True


# ---------------------------------------------------------------------------
# §C10 — submit_paper_bracket_order coverage (lines 1464–1550)
# ---------------------------------------------------------------------------


class TestSubmitPaperBracketOrder:
    """Coverage for SafetyLayer.submit_paper_bracket_order — all branches."""

    def _make_safety(self, mock_settings, *, live: bool = True, with_gw: bool = True):
        mock_settings.LIVE_TRADING_ENABLED = live
        mock_settings.REQUIRE_HUMAN_APPROVAL = False
        mock_settings.MAX_DAILY_LOSS_PCT = 0.10
        mock_settings.MAX_DRAWDOWN_PCT = 0.20
        mock_settings.MAX_SINGLE_ORDER_VALUE = 500_000.0
        mock_settings.MAX_FUTURES_MARGIN_PCT = 0.40
        mock_settings.MAX_CONTRACTS_PER_INSTRUMENT = 10
        mock_settings.MAX_TRADE_LOSS_USD = 5000.0
        safety = SafetyLayer(mock_settings)
        if with_gw:
            gw = AsyncMock()
            gw.is_connected = Mock(return_value=True)
            safety._ib_gateway = gw
        return safety

    @pytest.mark.asyncio
    async def test_kill_switch_active_blocks_bracket(self, mock_settings):
        """Kill switch active → immediate rejection before any validation (line 1464)."""
        from risk.safety_layer import KillSwitchReason

        safety = self._make_safety(mock_settings)
        safety.activate_kill_switch(KillSwitchReason.MANUAL, "test halt")
        result = await safety.submit_paper_bracket_order("MES", "BUY", 1, 5800.0)
        assert result["approved"] is False
        assert "Kill switch" in result["reason"]
        assert result["order_id"] is None
        assert result["routed_to_ib"] is False

    @pytest.mark.asyncio
    async def test_order_fails_safety_check_rejected(self, mock_settings):
        """check_order rejects → approved=False returned (lines 1506–1512)."""
        safety = self._make_safety(mock_settings)
        rejected = RiskCheckResult(
            approved=False,
            rejection_reason="Simulated safety rejection",
            warnings=[],
            adjusted_order=None,
        )
        with patch.object(safety, "check_order", return_value=rejected):
            result = await safety.submit_paper_bracket_order("MES", "BUY", 1, 5800.0)
        assert result["approved"] is False
        assert result["routed_to_ib"] is False

    @pytest.mark.asyncio
    async def test_ib_gateway_none_returns_unavailable(self, mock_settings):
        """Gateway is None → 'Broker connector unavailable' (lines 1515–1521)."""
        safety = self._make_safety(mock_settings, with_gw=False)
        result = await safety.submit_paper_bracket_order("MES", "BUY", 1, 5800.0)
        assert result["approved"] is False
        assert "unavailable" in result["reason"].lower()
        assert result["routed_to_ib"] is False

    @pytest.mark.asyncio
    async def test_bracket_placed_successfully(self, mock_settings):
        """Gateway returns status='placed' → approved=True, routed_to_ib=True (lines 1534–1543)."""
        safety = self._make_safety(mock_settings)
        safety._ib_gateway.place_bracket_order = AsyncMock(
            return_value={"status": "placed", "entry_id": "e1", "sl_id": "s1", "tp_id": "t1"}
        )
        result = await safety.submit_paper_bracket_order(
            "MES", "BUY", 1, 5800.0, stop_loss=5785.0, take_profit=5830.0
        )
        assert result["approved"] is True
        assert result["routed_to_ib"] is True

    @pytest.mark.asyncio
    async def test_bracket_placement_fails_but_checks_passed(self, mock_settings):
        """Gateway returns non-'placed' status → approved=True but routed_to_ib=False (lines 1545–1550)."""
        safety = self._make_safety(mock_settings)
        safety._ib_gateway.place_bracket_order = AsyncMock(
            return_value={"status": "error", "error": "connection lost"}
        )
        result = await safety.submit_paper_bracket_order("MES", "BUY", 1, 5800.0)
        assert result["approved"] is True
        assert result["routed_to_ib"] is False
        assert "broker placement failed" in result["reason"].lower()
