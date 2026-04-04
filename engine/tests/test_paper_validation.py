"""
Tests for paper trading validation tracker (US-303 consolidation).

NOTE: ValidationTracker is now READ-ONLY. It reads from PaperTradeTracker's
JSON files (engine/backtest/results/paper_trades_{symbol}.json).

Validates:
  - Metric computation from source trades
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

from paper.validation_gate_config import PAPER_VALIDATION_GATES
from paper.validation_tracker import PASS_THRESHOLDS, ValidationTracker


def _create_mock_tracker_file(data_dir: Path, symbol: str, trades: list) -> None:
    """Create a mock PaperTradeTracker JSON file for testing."""
    results_dir = data_dir / "backtest" / "results"
    results_dir.mkdir(parents=True, exist_ok=True)

    tracker_file = results_dir / f"paper_trades_{symbol}.json"
    payload = {
        "symbol": symbol,
        "config": {
            "initial_capital": 5000.0,
            "risk_per_trade": 0.0025,
            "adaptive_regime": False,
            "interval": "1h",
        },
        "updated_at": datetime.utcnow().isoformat(),
        "total_trades": len(trades),
        "trades": trades,
    }
    tracker_file.write_text(json.dumps(payload, indent=2))


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
    """Test reading trades from PaperTradeTracker files."""

    def test_load_single_winning_trade(self, temp_data_dir):
        """Loading a single winning trade updates metrics."""
        trades = [
            {
                "entry_date": "2026-04-02",
                "exit_date": "2026-04-02",
                "entry_price": 100.0,
                "exit_price": 105.0,
                "side": "long",
                "contracts": 1,
                "exit_reason": "target_1",
                "regime_type": "trending",
                "pnl": 500.0,
                "pnl_pct": 10.0,
                "recorded_at": "2026-04-02T12:00:00",
                "symbol": "MCL",
            }
        ]
        _create_mock_tracker_file(temp_data_dir, "MCL", trades)
        tracker = ValidationTracker(data_dir=temp_data_dir)
        assert tracker.metrics["MCL"].total_trades == 1
        assert tracker.metrics["MCL"].winning_trades == 1

    def test_load_winning_and_losing_trades(self, temp_data_dir):
        """Loading multiple trades computes correct counts."""
        trades = [
            {
                "entry_date": "2026-04-02",
                "exit_date": "2026-04-02",
                "entry_price": 100.0,
                "exit_price": 105.0,
                "side": "long",
                "contracts": 1,
                "exit_reason": "target_1",
                "regime_type": "trending",
                "pnl": 500.0,
                "pnl_pct": 10.0,
                "recorded_at": "2026-04-02T12:00:00",
                "symbol": "MCL",
            },
            {
                "entry_date": "2026-04-02",
                "exit_date": "2026-04-02",
                "entry_price": 110.0,
                "exit_price": 108.0,
                "side": "long",
                "contracts": 1,
                "exit_reason": "stop",
                "regime_type": "ranging",
                "pnl": -400.0,
                "pnl_pct": -8.0,
                "recorded_at": "2026-04-02T13:00:00",
                "symbol": "MCL",
            },
        ]
        _create_mock_tracker_file(temp_data_dir, "MCL", trades)
        tracker = ValidationTracker(data_dir=temp_data_dir)
        assert tracker.metrics["MCL"].total_trades == 2
        assert tracker.metrics["MCL"].winning_trades == 1
        assert tracker.metrics["MCL"].losing_trades == 1


class TestWinRate:
    """Test win rate calculations."""

    def test_win_rate_zero_trades(self, tracker):
        """Win rate is 0 when no trades."""
        assert tracker.metrics["MCL"].win_rate_pct == 0.0

    def test_win_rate_all_winning(self, tracker, temp_data_dir):
        """Win rate is 100% with all winners."""
        trades = [
            {
                "entry_date": "2026-04-02",
                "exit_date": "2026-04-02",
                "entry_price": 100.0,
                "exit_price": 105.0,
                "side": "long",
                "contracts": 1,
                "exit_reason": "target_1",
                "regime_type": "trending",
                "pnl": 500.0,
                "pnl_pct": 10.0,
                "recorded_at": f"2026-04-02T{12 + i}:00:00",
                "symbol": "MCL",
            }
            for i in range(5)
        ]
        _create_mock_tracker_file(temp_data_dir, "MCL", trades)
        tracker = ValidationTracker(data_dir=temp_data_dir)
        assert tracker.metrics["MCL"].win_rate_pct == 100.0

    def test_win_rate_all_losing(self, tracker, temp_data_dir):
        """Win rate is 0% with all losers."""
        trades = [
            {
                "entry_date": "2026-04-02",
                "exit_date": "2026-04-02",
                "entry_price": 100.0,
                "exit_price": 95.0,
                "side": "long",
                "contracts": 1,
                "exit_reason": "stop",
                "regime_type": "ranging",
                "pnl": -500.0,
                "pnl_pct": -10.0,
                "recorded_at": f"2026-04-02T{12 + i}:00:00",
                "symbol": "MCL",
            }
            for i in range(5)
        ]
        _create_mock_tracker_file(temp_data_dir, "MCL", trades)
        tracker = ValidationTracker(data_dir=temp_data_dir)
        assert tracker.metrics["MCL"].win_rate_pct == 0.0

    def test_win_rate_mixed(self, tracker, temp_data_dir):
        """Win rate is correct with mixed trades."""
        trades = [
            {
                "entry_date": "2026-04-02",
                "exit_date": "2026-04-02",
                "entry_price": 100.0,
                "exit_price": 105.0,
                "side": "long",
                "contracts": 1,
                "exit_reason": "target_1",
                "regime_type": "trending",
                "pnl": 500.0,
                "pnl_pct": 10.0,
                "recorded_at": "2026-04-02T12:00:00",
                "symbol": "MCL",
            },
            {
                "entry_date": "2026-04-02",
                "exit_date": "2026-04-02",
                "entry_price": 110.0,
                "exit_price": 108.0,
                "side": "long",
                "contracts": 1,
                "exit_reason": "stop",
                "regime_type": "ranging",
                "pnl": -400.0,
                "pnl_pct": -8.0,
                "recorded_at": "2026-04-02T13:00:00",
                "symbol": "MCL",
            },
            {
                "entry_date": "2026-04-02",
                "exit_date": "2026-04-02",
                "entry_price": 109.0,
                "exit_price": 115.0,
                "side": "long",
                "contracts": 1,
                "exit_reason": "target_2",
                "regime_type": "trending",
                "pnl": 600.0,
                "pnl_pct": 12.0,
                "recorded_at": "2026-04-02T14:00:00",
                "symbol": "MCL",
            },
        ]
        _create_mock_tracker_file(temp_data_dir, "MCL", trades)
        tracker = ValidationTracker(data_dir=temp_data_dir)
        # 2 wins, 1 loss = 66.67%
        assert abs(tracker.metrics["MCL"].win_rate_pct - 66.67) < 0.01


class TestProfitFactor:
    """Test profit factor calculations."""

    def test_profit_factor_no_trades(self, tracker):
        """Profit factor is 0 with no trades."""
        assert tracker.metrics["MCL"].profit_factor == 0.0

    def test_profit_factor_only_winners(self, tracker, temp_data_dir):
        """Profit factor is high with only winners."""
        trades = [
            {
                "entry_date": "2026-04-02",
                "exit_date": "2026-04-02",
                "entry_price": 100.0,
                "exit_price": 105.0,
                "side": "long",
                "contracts": 1,
                "exit_reason": "target_1",
                "regime_type": "trending",
                "pnl": 500.0,
                "pnl_pct": 10.0,
                "recorded_at": "2026-04-02T12:00:00",
                "symbol": "MCL",
            },
            {
                "entry_date": "2026-04-02",
                "exit_date": "2026-04-02",
                "entry_price": 110.0,
                "exit_price": 115.0,
                "side": "long",
                "contracts": 1,
                "exit_reason": "target_2",
                "regime_type": "trending",
                "pnl": 600.0,
                "pnl_pct": 12.0,
                "recorded_at": "2026-04-02T13:00:00",
                "symbol": "MCL",
            },
        ]
        _create_mock_tracker_file(temp_data_dir, "MCL", trades)
        tracker = ValidationTracker(data_dir=temp_data_dir)
        # Gross profit = 1100, gross loss = 0, PF = 1100
        assert tracker.metrics["MCL"].profit_factor == 1100.0

    def test_profit_factor_only_losers(self, tracker, temp_data_dir):
        """Profit factor is 0 with only losers."""
        trades = [
            {
                "entry_date": "2026-04-02",
                "exit_date": "2026-04-02",
                "entry_price": 100.0,
                "exit_price": 95.0,
                "side": "long",
                "contracts": 1,
                "exit_reason": "stop",
                "regime_type": "ranging",
                "pnl": -500.0,
                "pnl_pct": -10.0,
                "recorded_at": "2026-04-02T12:00:00",
                "symbol": "MCL",
            },
            {
                "entry_date": "2026-04-02",
                "exit_date": "2026-04-02",
                "entry_price": 110.0,
                "exit_price": 105.0,
                "side": "long",
                "contracts": 1,
                "exit_reason": "stop",
                "regime_type": "ranging",
                "pnl": -600.0,
                "pnl_pct": -12.0,
                "recorded_at": "2026-04-02T13:00:00",
                "symbol": "MCL",
            },
        ]
        _create_mock_tracker_file(temp_data_dir, "MCL", trades)
        tracker = ValidationTracker(data_dir=temp_data_dir)
        assert tracker.metrics["MCL"].profit_factor == 0.0

    def test_profit_factor_mixed(self, tracker, temp_data_dir):
        """Profit factor is gross_profit / gross_loss."""
        trades = [
            {
                "entry_date": "2026-04-02",
                "exit_date": "2026-04-02",
                "entry_price": 100.0,
                "exit_price": 110.0,
                "side": "long",
                "contracts": 1,
                "exit_reason": "target_3",
                "regime_type": "trending",
                "pnl": 1000.0,
                "pnl_pct": 20.0,
                "recorded_at": "2026-04-02T12:00:00",
                "symbol": "MCL",
            },
            {
                "entry_date": "2026-04-02",
                "exit_date": "2026-04-02",
                "entry_price": 110.0,
                "exit_price": 108.0,
                "side": "long",
                "contracts": 1,
                "exit_reason": "stop",
                "regime_type": "ranging",
                "pnl": -500.0,
                "pnl_pct": -10.0,
                "recorded_at": "2026-04-02T13:00:00",
                "symbol": "MCL",
            },
        ]
        _create_mock_tracker_file(temp_data_dir, "MCL", trades)
        tracker = ValidationTracker(data_dir=temp_data_dir)
        # Gross profit = 1000, gross loss = 500, PF = 2.0
        assert abs(tracker.metrics["MCL"].profit_factor - 2.0) < 0.01


class TestValidationThresholds:
    """Test validation pass/fail logic."""

    def test_validation_fails_before_30_days(self, tracker):
        """Validation fails even if metrics pass but days < 30."""
        # Empty tracker has no days, so should fail
        assert not tracker.is_validated("MCL")

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

    def test_consecutive_loss_counter_resets_on_win(self, tracker, temp_data_dir):
        """Consecutive loss counter resets on winning trade."""
        trades = [
            {
                "entry_date": "2026-04-02",
                "exit_date": "2026-04-02",
                "entry_price": 100.0,
                "exit_price": 95.0,
                "side": "long",
                "contracts": 1,
                "exit_reason": "stop",
                "regime_type": "ranging",
                "pnl": -500.0,
                "pnl_pct": -10.0,
                "recorded_at": "2026-04-02T12:00:00",
                "symbol": "MCL",
            },
            {
                "entry_date": "2026-04-02",
                "exit_date": "2026-04-02",
                "entry_price": 100.0,
                "exit_price": 95.0,
                "side": "long",
                "contracts": 1,
                "exit_reason": "stop",
                "regime_type": "ranging",
                "pnl": -500.0,
                "pnl_pct": -10.0,
                "recorded_at": "2026-04-02T13:00:00",
                "symbol": "MCL",
            },
            {
                "entry_date": "2026-04-02",
                "exit_date": "2026-04-02",
                "entry_price": 100.0,
                "exit_price": 105.0,
                "side": "long",
                "contracts": 1,
                "exit_reason": "target_1",
                "regime_type": "trending",
                "pnl": 500.0,
                "pnl_pct": 10.0,
                "recorded_at": "2026-04-02T14:00:00",
                "symbol": "MCL",
            },
        ]
        _create_mock_tracker_file(temp_data_dir, "MCL", trades)
        tracker = ValidationTracker(data_dir=temp_data_dir)
        assert tracker.metrics["MCL"].consecutive_losses == 0

    def test_max_consecutive_losses_tracked(self, tracker, temp_data_dir):
        """Max consecutive losses is recorded."""
        trades = (
            [
                {
                    "entry_date": "2026-04-02",
                    "exit_date": "2026-04-02",
                    "entry_price": 100.0,
                    "exit_price": 95.0,
                    "side": "long",
                    "contracts": 1,
                    "exit_reason": "stop",
                    "regime_type": "ranging",
                    "pnl": -500.0,
                    "pnl_pct": -10.0,
                    "recorded_at": f"2026-04-02T{12 + i}:00:00",
                    "symbol": "MCL",
                }
                for i in range(3)
            ]
            + [
                {
                    "entry_date": "2026-04-02",
                    "exit_date": "2026-04-02",
                    "entry_price": 100.0,
                    "exit_price": 105.0,
                    "side": "long",
                    "contracts": 1,
                    "exit_reason": "target_1",
                    "regime_type": "trending",
                    "pnl": 500.0,
                    "pnl_pct": 10.0,
                    "recorded_at": "2026-04-02T16:00:00",
                    "symbol": "MCL",
                }
            ]
            + [
                {
                    "entry_date": "2026-04-02",
                    "exit_date": "2026-04-02",
                    "entry_price": 100.0,
                    "exit_price": 95.0,
                    "side": "long",
                    "contracts": 1,
                    "exit_reason": "stop",
                    "regime_type": "ranging",
                    "pnl": -500.0,
                    "pnl_pct": -10.0,
                    "recorded_at": f"2026-04-02T{17 + i}:00:00",
                    "symbol": "MCL",
                }
                for i in range(5)
            ]
        )
        _create_mock_tracker_file(temp_data_dir, "MCL", trades)
        tracker = ValidationTracker(data_dir=temp_data_dir)
        assert tracker.metrics["MCL"].max_consecutive_losses == 5


class TestDashboardData:
    """Test dashboard response format."""

    def test_dashboard_data_format(self, tracker):
        """Dashboard data has correct structure."""
        data = tracker.get_dashboard_data()
        assert "timestamp" in data
        assert "instruments" in data
        assert "overall_pass" in data
        assert "MCL" in data["instruments"]
        assert "MNQ" in data["instruments"]

    def test_dashboard_overall_pass(self, tracker):
        """overall_pass is False when instruments don't pass."""
        # Initially both should fail (0 trades)
        data = tracker.get_dashboard_data()
        assert data["overall_pass"] is False


class TestSerialization:
    """Test reading from PaperTradeTracker files."""

    def test_load_metrics_from_tracker_file(self, temp_data_dir):
        """Metrics load from PaperTradeTracker JSON files."""
        trades = [
            {
                "entry_date": "2026-04-02",
                "exit_date": "2026-04-02",
                "entry_price": 100.0,
                "exit_price": 105.0,
                "side": "long",
                "contracts": 1,
                "exit_reason": "target_1",
                "regime_type": "trending",
                "pnl": 500.0,
                "pnl_pct": 10.0,
                "recorded_at": "2026-04-02T12:00:00",
                "symbol": "MCL",
            },
            {
                "entry_date": "2026-04-02",
                "exit_date": "2026-04-02",
                "entry_price": 110.0,
                "exit_price": 108.0,
                "side": "long",
                "contracts": 1,
                "exit_reason": "stop",
                "regime_type": "ranging",
                "pnl": -400.0,
                "pnl_pct": -8.0,
                "recorded_at": "2026-04-02T13:00:00",
                "symbol": "MCL",
            },
        ]
        _create_mock_tracker_file(temp_data_dir, "MCL", trades)

        # Create new tracker to load from disk
        tracker = ValidationTracker(data_dir=temp_data_dir)
        assert tracker.metrics["MCL"].total_trades == 2
        assert tracker.metrics["MCL"].winning_trades == 1


class TestGetAllTrades:
    """Test trade listing."""

    def test_get_all_trades_empty(self, tracker):
        """Getting trades returns empty list when none recorded."""
        trades = tracker.get_all_trades("MCL")
        assert trades == []

    def test_get_all_trades_populated(self, tracker, temp_data_dir):
        """Getting trades returns all recorded trades."""
        trades_data = [
            {
                "entry_date": "2026-04-02",
                "exit_date": "2026-04-02",
                "entry_price": 100.0,
                "exit_price": 105.0,
                "side": "long",
                "contracts": 1,
                "exit_reason": "target_1",
                "regime_type": "trending",
                "pnl": 500.0,
                "pnl_pct": 10.0,
                "recorded_at": "2026-04-02T12:00:00",
                "symbol": "MCL",
            },
            {
                "entry_date": "2026-04-02",
                "exit_date": "2026-04-02",
                "entry_price": 110.0,
                "exit_price": 108.0,
                "side": "long",
                "contracts": 1,
                "exit_reason": "stop",
                "regime_type": "ranging",
                "pnl": -400.0,
                "pnl_pct": -8.0,
                "recorded_at": "2026-04-02T13:00:00",
                "symbol": "MCL",
            },
        ]
        _create_mock_tracker_file(temp_data_dir, "MCL", trades_data)
        tracker = ValidationTracker(data_dir=temp_data_dir)

        trades = tracker.get_all_trades("MCL")
        assert len(trades) == 2
        assert trades[0]["pnl"] == 500.0
        assert trades[1]["pnl"] == -400.0


class TestValidationGateConfig:
    """Canonical gates must stay aligned between config and ValidationTracker."""

    def test_pass_thresholds_is_shared_config_object(self):
        assert PASS_THRESHOLDS is PAPER_VALIDATION_GATES

    def test_canonical_numeric_targets(self):
        assert PAPER_VALIDATION_GATES["profit_factor"] == 2.0
        assert PAPER_VALIDATION_GATES["sharpe_ratio"] == 1.5
        assert PAPER_VALIDATION_GATES["win_rate_pct"] == 55.0
        assert PAPER_VALIDATION_GATES["min_trades"] == 60
        assert PAPER_VALIDATION_GATES["min_days"] == 30
        assert PAPER_VALIDATION_GATES["max_drawdown_pct"] == 15.0
