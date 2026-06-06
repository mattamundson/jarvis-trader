"""
Tests for ConsecutiveLossTracker and SafetyLayer integration
"""

import tempfile

import pytest

from config import TradingConfig
from risk.loss_tracker import ConsecutiveLossTracker
from risk.safety_layer import OrderRequest, SafetyLayer

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def loss_tracker_settings(mock_settings):
    """Override conftest mock_settings for loss tracker tests."""
    # Enable live trading mode for loss tracker order-approval tests
    mock_settings.LIVE_TRADING_ENABLED = True
    mock_settings.REQUIRE_HUMAN_APPROVAL = False
    # Configure consecutive-loss thresholds
    mock_settings.CONSECUTIVE_LOSS_HALF_SIZE = 3
    mock_settings.CONSECUTIVE_LOSS_QUARTER_SIZE = 5
    mock_settings.CONSECUTIVE_LOSS_HALT = 7
    mock_settings.CONSECUTIVE_LOSS_HALT_HOURS = 24
    # Bypass the overnight contract cap so these consecutive-loss / position-
    # sizing tests are wall-clock-independent. The default MAX_OVERNIGHT_CONTRACTS=1
    # rejects the qty=2 MES orders below whenever the suite runs after 15:00 CT,
    # masking the consecutive-loss reason the assertions expect. Same idiom as
    # test_safety_layer.py (TestContractLimits bypass at MAX_OVERNIGHT_CONTRACTS=5).
    mock_settings.MAX_OVERNIGHT_CONTRACTS = 5
    return mock_settings


class TestConsecutiveLossTracker:
    """Unit tests for ConsecutiveLossTracker"""

    @pytest.fixture
    def tracker(self):
        """Create a tracker with temporary data dir"""
        with tempfile.TemporaryDirectory() as tmpdir:
            t = ConsecutiveLossTracker(
                data_dir=tmpdir,
                consecutive_loss_half_size=3,
                consecutive_loss_quarter_size=5,
                consecutive_loss_halt=7,
                consecutive_loss_halt_hours=24,
            )
            yield t

    def test_initial_state(self, tracker):
        """Test tracker starts with zero losses"""
        assert tracker.get_consecutive_losses() == 0
        assert tracker.get_consecutive_losses("MES") == 0
        assert tracker.get_position_size_multiplier() == 1.0
        assert not tracker.is_halted()

    def test_record_single_loss(self, tracker):
        """Test recording a single losing trade"""
        is_win = tracker.record_trade("MES", -100.0)
        assert not is_win
        assert tracker.get_consecutive_losses() == 1
        assert tracker.get_consecutive_losses("MES") == 1
        assert tracker.get_position_size_multiplier() == 1.0

    def test_record_multiple_losses(self, tracker):
        """Test recording multiple consecutive losses"""
        for i in range(5):
            is_win = tracker.record_trade("MES", -100.0)
            assert not is_win
            assert tracker.get_consecutive_losses() == i + 1

    def test_position_size_half(self, tracker):
        """Test position size reduction to 0.5x at 3 losses"""
        for _i in range(3):
            tracker.record_trade("MES", -100.0)
        assert tracker.get_consecutive_losses() == 3
        assert tracker.get_position_size_multiplier() == 0.5

    def test_position_size_quarter(self, tracker):
        """Test position size reduction to 0.25x at 5 losses"""
        for _i in range(5):
            tracker.record_trade("MES", -100.0)
        assert tracker.get_consecutive_losses() == 5
        assert tracker.get_position_size_multiplier() == 0.25

    def test_trading_halt_at_threshold(self, tracker):
        """Test trading halt triggered at 7+ losses"""
        for _i in range(7):
            tracker.record_trade("MES", -100.0)
        assert tracker.get_consecutive_losses() == 7
        assert tracker.is_halted()
        assert tracker.get_position_size_multiplier() == 0.0

    def test_halt_reason(self, tracker):
        """Test halt reason message"""
        for _i in range(7):
            tracker.record_trade("MES", -100.0)
        reason = tracker.get_halt_reason()
        assert "7 losses" in reason
        assert "trading paused" in reason.lower()

    def test_winner_resets_counter(self, tracker):
        """Test that a winning trade resets the global counter"""
        for _i in range(3):
            tracker.record_trade("MES", -100.0)
        assert tracker.get_consecutive_losses() == 3

        is_win = tracker.record_trade("MES", +200.0)
        assert is_win
        assert tracker.get_consecutive_losses() == 0
        assert tracker.get_position_size_multiplier() == 1.0

    def test_symbol_isolation(self, tracker):
        """Test that loss counters are tracked per symbol"""
        # Lose on MES
        tracker.record_trade("MES", -100.0)
        tracker.record_trade("MES", -100.0)

        # Lose on MNQ (separate counter)
        tracker.record_trade("MNQ", -100.0)

        assert tracker.get_consecutive_losses("MES") == 2
        assert tracker.get_consecutive_losses("MNQ") == 1
        assert tracker.get_consecutive_losses() == 3  # global

    def test_manual_reset_global(self, tracker):
        """Test manual reset of global counter"""
        for _i in range(5):
            tracker.record_trade("MES", -100.0)
        assert tracker.get_consecutive_losses() == 5

        tracker.reset()
        assert tracker.get_consecutive_losses() == 0
        assert tracker.get_position_size_multiplier() == 1.0

    def test_manual_reset_symbol(self, tracker):
        """Test manual reset of symbol-specific counter"""
        tracker.record_trade("MES", -100.0)
        tracker.record_trade("MES", -100.0)
        tracker.record_trade("MNQ", -100.0)

        tracker.reset(symbol="MES")
        assert tracker.get_consecutive_losses("MES") == 0
        assert tracker.get_consecutive_losses("MNQ") == 1

    def test_state_persistence(self):
        """Test that state is persisted to and loaded from JSON"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create tracker and record some trades
            t1 = ConsecutiveLossTracker(data_dir=tmpdir)
            t1.record_trade("MES", -100.0)
            t1.record_trade("MES", -100.0)
            t1.record_trade("MNQ", -50.0)

            # Create new tracker from same directory - should load state
            t2 = ConsecutiveLossTracker(data_dir=tmpdir)
            assert t2.get_consecutive_losses() == 3
            assert t2.get_consecutive_losses("MES") == 2
            assert t2.get_consecutive_losses("MNQ") == 1

    def test_status_report(self, tracker):
        """Test comprehensive status report"""
        tracker.record_trade("MES", -100.0)
        tracker.record_trade("MES", -100.0)
        tracker.record_trade("MNQ", -50.0)

        status = tracker.get_status()
        assert status["global_consecutive_losses"] == 3
        assert status["symbol_losses"]["MES"] == 2
        assert status["symbol_losses"]["MNQ"] == 1
        # 3 global losses crosses consecutive_loss_half_size=3, so multiplier is 0.5
        assert status["position_size_multiplier"] == 0.5
        assert "last_trade_symbol" in status
        assert "config" in status


class TestSafetyLayerWithLossTracker:
    """Integration tests for SafetyLayer with ConsecutiveLossTracker"""

    @pytest.fixture
    def components(self, loss_tracker_settings):
        """Create SafetyLayer with loss tracker using isolated test config."""
        # Allow larger quantities so contract-limit check does not mask loss-tracker tests
        loss_tracker_settings.MAX_CONTRACTS_PER_INSTRUMENT = 10
        with tempfile.TemporaryDirectory() as tmpdir:
            tracker = ConsecutiveLossTracker(
                data_dir=tmpdir,
                consecutive_loss_half_size=3,
                consecutive_loss_quarter_size=5,
                consecutive_loss_halt=7,
            )
            layer = SafetyLayer(loss_tracker_settings, loss_tracker=tracker)
            yield layer, tracker

    def test_order_approved_with_no_losses(self, components):
        """Test order approval with no consecutive losses"""
        layer, tracker = components
        order = OrderRequest(
            symbol="MES",
            quantity=2,
            order_type="market",
            estimated_value=500.0,
            is_futures=True,
        )
        result = layer.check_order(order, portfolio_equity=50000.0)
        assert result.approved
        assert not result.warnings

    def test_position_size_reduction_warning(self, components):
        """Test warning when position size is reduced"""
        layer, tracker = components

        # Record 3 losses to trigger 0.5x position size
        for _i in range(3):
            tracker.record_trade("MES", -100.0)

        order = OrderRequest(
            symbol="MES",
            quantity=4,
            order_type="market",
            estimated_value=1000.0,
            is_futures=True,
        )
        result = layer.check_order(order, portfolio_equity=50000.0)
        assert result.approved
        assert len(result.warnings) > 0
        assert "position size reduced" in result.warnings[0].lower()

    def test_order_rejected_when_halted(self, components):
        """Test order rejection when trading is halted"""
        layer, tracker = components

        # Record 7 losses to trigger halt
        for _i in range(7):
            tracker.record_trade("MES", -100.0)

        order = OrderRequest(
            symbol="MES",
            quantity=2,
            order_type="market",
            estimated_value=500.0,
            is_futures=True,
        )
        result = layer.check_order(order, portfolio_equity=50000.0)
        assert not result.approved
        # get_halt_reason() returns: "Consecutive loss limit reached (N losses) — trading paused..."
        assert "consecutive loss" in result.rejection_reason.lower()
        assert "trading paused" in result.rejection_reason.lower()

    def test_record_trade_result_api(self, components):
        """Test recording trade results via SafetyLayer API"""
        layer, tracker = components

        layer.record_trade_result("MES", -100.0)
        assert tracker.get_consecutive_losses() == 1

        layer.record_trade_result("MES", -50.0)
        assert tracker.get_consecutive_losses() == 2

    def test_loss_tracker_status_api(self, components):
        """Test loss tracker status API"""
        layer, tracker = components

        tracker.record_trade("MES", -100.0)
        status = layer.get_loss_tracker_status()

        assert status["enabled"]
        assert status["global_consecutive_losses"] == 1
        assert status["symbol_losses"]["MES"] == 1

    def test_reset_loss_tracker_api(self, components):
        """Test loss tracker reset via SafetyLayer API"""
        layer, tracker = components

        tracker.record_trade("MES", -100.0)
        tracker.record_trade("MNQ", -100.0)

        layer.reset_loss_tracker(symbol="MES")
        assert tracker.get_consecutive_losses("MES") == 0
        assert tracker.get_consecutive_losses("MNQ") == 1

        layer.reset_loss_tracker()
        assert tracker.get_consecutive_losses() == 0


class TestPositionSizingReduction:
    """Test position sizing reduction logic in detail"""

    @pytest.fixture
    def components(self, loss_tracker_settings):
        """Create SafetyLayer with loss tracker using isolated test config."""
        # Allow larger quantities so contract-limit check does not mask loss-tracker tests
        loss_tracker_settings.MAX_CONTRACTS_PER_INSTRUMENT = 10
        with tempfile.TemporaryDirectory() as tmpdir:
            tracker = ConsecutiveLossTracker(
                data_dir=tmpdir,
                consecutive_loss_half_size=3,
                consecutive_loss_quarter_size=5,
                consecutive_loss_halt=7,
            )
            layer = SafetyLayer(loss_tracker_settings, loss_tracker=tracker)
            yield layer, tracker

    def test_quantity_reduced_with_multiplier(self, components):
        """Test that order quantity is reduced based on multiplier"""
        layer, tracker = components

        # Trigger 0.5x reduction
        for _i in range(3):
            tracker.record_trade("MES", -100.0)

        # Original order: 4 contracts
        order = OrderRequest(
            symbol="MES",
            quantity=4,
            order_type="market",
            estimated_value=1000.0,
            is_futures=True,
        )

        result = layer.check_order(order, portfolio_equity=50000.0)
        assert result.approved
        # Quantity should be reduced from 4 to 2 (50% reduction)
        if result.adjusted_order:
            assert result.adjusted_order.quantity == 2
        assert "reduced" in str(result.warnings).lower()

    def test_quarter_size_reduction(self, components):
        """Test quarter-size position reduction"""
        layer, tracker = components

        # Trigger 0.25x reduction
        for _i in range(5):
            tracker.record_trade("MES", -100.0)

        order = OrderRequest(
            symbol="MES",
            quantity=4,
            order_type="market",
            estimated_value=1000.0,
            is_futures=True,
        )

        result = layer.check_order(order, portfolio_equity=50000.0)
        assert result.approved
        # Quantity should be reduced from 4 to 1 (75% reduction)
        if result.adjusted_order:
            assert result.adjusted_order.quantity == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
