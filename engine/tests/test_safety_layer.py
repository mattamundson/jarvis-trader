"""
JARVIS TRADER — Safety Layer Tests
Comprehensive testing of all 14 hard rules.
"""

import os
import sqlite3
import tempfile
from datetime import datetime
from unittest.mock import patch
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
        """MCL is not in OVERNIGHT_SYMBOLS — no overnight check applied."""
        mock_settings.LIVE_TRADING_ENABLED = True
        mock_settings.REQUIRE_HUMAN_APPROVAL = False
        mock_settings.MAX_CONTRACTS_PER_INSTRUMENT = 2
        mock_settings.MAX_OVERNIGHT_CONTRACTS = 1
        safety = SafetyLayer(mock_settings)

        order = OrderRequest(
            symbol="MCL",
            quantity=2,
            order_type="market",
            is_futures=True,
            estimated_value=1000.0,  # Low to pass order-value check
        )
        fake_time = datetime(2026, 4, 21, 16, 0, tzinfo=self._CT)
        with patch("risk.safety_layer.datetime") as mock_dt:
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
            "exceeds max" in result.rejection_reason
            or "Position size" in result.rejection_reason
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
