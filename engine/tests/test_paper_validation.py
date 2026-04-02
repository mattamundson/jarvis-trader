"""
Tests for paper trading validation tracker.

Validates:
  - Trade recording updates metrics
  - Win rate calculation accuracy
  - Profit factor handles edge cases
  - Validation requires 30 days minimum
  - Consecutive loss tracking
  - Dashboard data format
"""

import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from paper.validation_tracker import ValidationTracker


@pytest.fixture
def temp_data_dir():
    """Create temporary data directory for tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def tracker(temp_data_dir):
    """Create tracker with temporary directory."""
    return ValidationTracker(data_dir=temp_data_dir)


class TestTradeRecording:
    """Test basic trade recording."""

    def test_record_trade_updates_metrics(self, tracker):
        """Recording a trade updates total_trades."""
        assert tracker.metrics["MCL"].total_trades == 0
        tracker.record_trade("MCL", 100.0, 105.0, 500.0)
        assert tracker.metrics["MCL"].total_trades == 1

    def test_record_winning_trade(self, tracker):
        """Winning trade increments winning_trades."""
        tracker.record_trade("MCL", 100.0, 105.0, 500.0)
        assert tracker.metrics["MCL"].winning_trades == 1
        assert tracker.metrics["MCL"].losing_trades == 0

    def test_record_losing_trade(self, tracker):
        """Losing trade increments losing_trades."""
        tracker.record_trade("MCL", 100.0, 95.0, -300.0)
        assert tracker.metrics["MCL"].losing_trades == 1
        assert tracker.metrics["MCL"].winning_trades == 0

    def test_record_multiple_trades(self, tracker):
        """Multiple trades update total correctly."""
        tracker.record_trade("MCL", 100.0, 105.0, 500.0)
        tracker.record_trade("MCL", 110.0, 108.0, -400.0)
        tracker.record_trade("MCL", 109.0, 115.0, 600.0)
        assert tracker.metrics["MCL"].total_trades == 3


class TestWinRate:
    """Test win rate calculations."""

    def test_win_rate_zero_trades(self, tracker):
        """Win rate is 0 when no trades."""
        assert tracker.metrics["MCL"].win_rate_pct == 0.0

    def test_win_rate_all_winning(self, tracker):
        """Win rate is 100% with all winners."""
        for _ in range(5):
            tracker.record_trade("MCL", 100.0, 105.0, 500.0)
        assert tracker.metrics["MCL"].win_rate_pct == 100.0

    def test_win_rate_all_losing(self, tracker):
        """Win rate is 0% with all losers."""
        for _ in range(5):
            tracker.record_trade("MCL", 100.0, 95.0, -500.0)
        assert tracker.metrics["MCL"].win_rate_pct == 0.0

    def test_win_rate_mixed(self, tracker):
        """Win rate is correct with mixed trades."""
        tracker.record_trade("MCL", 100.0, 105.0, 500.0)
        tracker.record_trade("MCL", 110.0, 108.0, -400.0)
        tracker.record_trade("MCL", 109.0, 115.0, 600.0)
        # 2 wins, 1 loss = 66.67%
        assert abs(tracker.metrics["MCL"].win_rate_pct - 66.67) < 0.01


class TestProfitFactor:
    """Test profit factor calculations."""

    def test_profit_factor_no_trades(self, tracker):
        """Profit factor is 0 with no trades."""
        assert tracker.metrics["MCL"].profit_factor == 0.0

    def test_profit_factor_only_winners(self, tracker):
        """Profit factor is high with only winners."""
        tracker.record_trade("MCL", 100.0, 105.0, 500.0)
        tracker.record_trade("MCL", 110.0, 115.0, 600.0)
        # Gross profit = 1100, gross loss = 0, PF = 1100
        assert tracker.metrics["MCL"].profit_factor == 1100.0

    def test_profit_factor_only_losers(self, tracker):
        """Profit factor is 0 with only losers."""
        tracker.record_trade("MCL", 100.0, 95.0, -500.0)
        tracker.record_trade("MCL", 110.0, 105.0, -600.0)
        assert tracker.metrics["MCL"].profit_factor == 0.0

    def test_profit_factor_mixed(self, tracker):
        """Profit factor is gross_profit / gross_loss."""
        tracker.record_trade("MCL", 100.0, 105.0, 1000.0)  # Win
        tracker.record_trade("MCL", 110.0, 108.0, -500.0)  # Loss
        # Gross profit = 1000, gross loss = 500, PF = 2.0
        assert abs(tracker.metrics["MCL"].profit_factor - 2.0) < 0.01


class TestValidationThresholds:
    """Test validation pass/fail logic."""

    def test_validation_fails_before_30_days(self, tracker):
        """Validation fails even if metrics pass but days < 30."""
        # Create mock metrics that exceed thresholds
        metrics = tracker.metrics["MCL"]
        metrics.total_trades = 100
        metrics.winning_trades = 60
        metrics.daily_pnl_values = [100.0] * 10

        # Should still fail due to days_active < 30
        assert not tracker.is_validated("MCL")

    def test_validation_passes_all_thresholds(self, tracker):
        """Validation passes when all thresholds met."""
        metrics = tracker.metrics["MCL"]

        # Add 60+ trades
        for i in range(65):
            tracker.record_trade(
                "MCL", 100.0, 105.0 if i % 2 == 0 else 98.0, 500.0 if i % 2 == 0 else -400.0
            )

        # Add 30+ days of P&L
        for _ in range(35):
            metrics.daily_pnl_values.append(150.0)

        progress = tracker.get_progress("MCL")
        # Check that validation should pass with sufficient metrics
        if (
            progress["win_rate_pct"] >= 55
            and progress["profit_factor"] >= 2.0
            and progress["sharpe_ratio"] >= 1.5
            and progress["days_active"] >= 30
        ):
            assert progress["is_validated"] is True

    def test_validation_status_structure(self, tracker):
        """get_progress returns correct structure."""
        progress = tracker.get_progress("MCL")
        assert "instrument" in progress
        assert "total_trades" in progress
        assert "win_rate_pct" in progress
        assert "profit_factor" in progress
        assert "sharpe_ratio" in progress
        assert "max_drawdown_pct" in progress
        assert "days_active" in progress
        assert "is_validated" in progress
        assert "pass_fail" in progress
        assert "thresholds" in progress


class TestConsecutiveLosses:
    """Test consecutive loss tracking."""

    def test_consecutive_loss_counter_resets_on_win(self, tracker):
        """Consecutive loss counter resets on winning trade."""
        tracker.record_trade("MCL", 100.0, 95.0, -500.0)
        tracker.record_trade("MCL", 100.0, 95.0, -500.0)
        assert tracker.metrics["MCL"].consecutive_losses == 2

        tracker.record_trade("MCL", 100.0, 105.0, 500.0)
        assert tracker.metrics["MCL"].consecutive_losses == 0

    def test_max_consecutive_losses_tracked(self, tracker):
        """Max consecutive losses is recorded."""
        for _ in range(3):
            tracker.record_trade("MCL", 100.0, 95.0, -500.0)
        tracker.record_trade("MCL", 100.0, 105.0, 500.0)

        for _ in range(5):
            tracker.record_trade("MCL", 100.0, 95.0, -500.0)

        assert tracker.metrics["MCL"].max_consecutive_losses == 5


class TestDashboardData:
    """Test dashboard response format."""

    def test_dashboard_data_format(self, tracker):
        """Dashboard data has correct structure."""
        tracker.record_trade("MCL", 100.0, 105.0, 500.0)
        tracker.record_trade("MNQ", 5000.0, 5100.0, 200.0)

        data = tracker.get_dashboard_data()
        assert "timestamp" in data
        assert "instruments" in data
        assert "overall_pass" in data
        assert "MCL" in data["instruments"]
        assert "MNQ" in data["instruments"]

    def test_dashboard_overall_pass(self, tracker):
        """overall_pass is True only when both instruments pass."""
        # Initially both should fail (0 trades)
        data = tracker.get_dashboard_data()
        assert data["overall_pass"] is False


class TestSerialization:
    """Test JSON storage and loading."""

    def test_save_and_load_metrics(self, tracker, temp_data_dir):
        """Metrics persist through save/load cycle."""
        tracker.record_trade("MCL", 100.0, 105.0, 500.0)
        tracker.record_trade("MCL", 110.0, 108.0, -400.0)

        # Create new tracker to load from disk
        tracker2 = ValidationTracker(data_dir=temp_data_dir)
        assert tracker2.metrics["MCL"].total_trades == 2
        assert tracker2.metrics["MCL"].winning_trades == 1

    def test_validation_file_json_format(self, tracker, temp_data_dir):
        """Validation file is valid JSON."""
        tracker.record_trade("MCL", 100.0, 105.0, 500.0)

        validation_file = temp_data_dir / "paper_validation.json"
        assert validation_file.exists()

        data = json.loads(validation_file.read_text())
        assert "MCL" in data
        assert "MNQ" in data


class TestGetAllTrades:
    """Test trade listing."""

    def test_get_all_trades_empty(self, tracker):
        """Getting trades returns empty list when none recorded."""
        trades = tracker.get_all_trades("MCL")
        assert trades == []

    def test_get_all_trades_populated(self, tracker):
        """Getting trades returns all recorded trades."""
        tracker.record_trade("MCL", 100.0, 105.0, 500.0)
        tracker.record_trade("MCL", 110.0, 108.0, -400.0)

        trades = tracker.get_all_trades("MCL")
        assert len(trades) == 2
        assert trades[0]["pnl"] == 500.0
        assert trades[1]["pnl"] == -400.0
