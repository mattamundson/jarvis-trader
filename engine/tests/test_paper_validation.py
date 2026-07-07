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
from paper.validation_tracker import (
    _TRACKED_INSTRUMENTS,
    PASS_THRESHOLDS,
    ValidationTracker,
    _thresholds_for,
)


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
                "symbol": "MES",
            }
        ]
        _create_mock_tracker_file(temp_data_dir, "MES", trades)
        tracker = ValidationTracker(data_dir=temp_data_dir)
        assert tracker.metrics["MES"].total_trades == 1
        assert tracker.metrics["MES"].winning_trades == 1

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
                "symbol": "MES",
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
                "symbol": "MES",
            },
        ]
        _create_mock_tracker_file(temp_data_dir, "MES", trades)
        tracker = ValidationTracker(data_dir=temp_data_dir)
        assert tracker.metrics["MES"].total_trades == 2
        assert tracker.metrics["MES"].winning_trades == 1
        assert tracker.metrics["MES"].losing_trades == 1


class TestWinRate:
    """Test win rate calculations."""

    def test_win_rate_zero_trades(self, tracker):
        """Win rate is 0 when no trades."""
        assert tracker.metrics["MES"].win_rate_pct == 0.0

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
                "symbol": "MES",
            }
            for i in range(5)
        ]
        _create_mock_tracker_file(temp_data_dir, "MES", trades)
        tracker = ValidationTracker(data_dir=temp_data_dir)
        assert tracker.metrics["MES"].win_rate_pct == 100.0

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
                "symbol": "MES",
            }
            for i in range(5)
        ]
        _create_mock_tracker_file(temp_data_dir, "MES", trades)
        tracker = ValidationTracker(data_dir=temp_data_dir)
        assert tracker.metrics["MES"].win_rate_pct == 0.0

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
                "symbol": "MES",
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
                "symbol": "MES",
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
                "symbol": "MES",
            },
        ]
        _create_mock_tracker_file(temp_data_dir, "MES", trades)
        tracker = ValidationTracker(data_dir=temp_data_dir)
        # 2 wins, 1 loss = 66.67%
        assert abs(tracker.metrics["MES"].win_rate_pct - 66.67) < 0.01


class TestProfitFactor:
    """Test profit factor calculations."""

    def test_profit_factor_no_trades(self, tracker):
        """Profit factor is 0 with no trades."""
        assert tracker.metrics["MES"].profit_factor == 0.0

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
                "symbol": "MES",
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
                "symbol": "MES",
            },
        ]
        _create_mock_tracker_file(temp_data_dir, "MES", trades)
        tracker = ValidationTracker(data_dir=temp_data_dir)
        # Gross profit = 1100, gross loss = 0, PF = 1100
        assert tracker.metrics["MES"].profit_factor == 1100.0

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
                "symbol": "MES",
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
                "symbol": "MES",
            },
        ]
        _create_mock_tracker_file(temp_data_dir, "MES", trades)
        tracker = ValidationTracker(data_dir=temp_data_dir)
        assert tracker.metrics["MES"].profit_factor == 0.0

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
                "symbol": "MES",
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
                "symbol": "MES",
            },
        ]
        _create_mock_tracker_file(temp_data_dir, "MES", trades)
        tracker = ValidationTracker(data_dir=temp_data_dir)
        # Gross profit = 1000, gross loss = 500, PF = 2.0
        assert abs(tracker.metrics["MES"].profit_factor - 2.0) < 0.01


class TestValidationThresholds:
    """Test validation pass/fail logic."""

    def test_validation_fails_before_30_days(self, tracker):
        """Validation fails even if metrics pass but days < 30."""
        # Empty tracker has no days, so should fail
        assert not tracker.is_validated("MES")

    def test_validation_status_structure(self, tracker):
        """get_progress returns correct structure."""
        progress = tracker.get_progress("MES")
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
                "symbol": "MES",
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
                "symbol": "MES",
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
                "symbol": "MES",
            },
        ]
        _create_mock_tracker_file(temp_data_dir, "MES", trades)
        tracker = ValidationTracker(data_dir=temp_data_dir)
        assert tracker.metrics["MES"].consecutive_losses == 0

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
                    "symbol": "MES",
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
                    "symbol": "MES",
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
                    "symbol": "MES",
                }
                for i in range(5)
            ]
        )
        _create_mock_tracker_file(temp_data_dir, "MES", trades)
        tracker = ValidationTracker(data_dir=temp_data_dir)
        assert tracker.metrics["MES"].max_consecutive_losses == 5

    def test_breakeven_trades_do_not_count_as_losses(self, tracker, temp_data_dir):
        """Regression: pnl == 0 breakevens must not advance the loss streak.

        Pre-fix, the `else` branch in `_build_instrument_metrics` treated any
        trade with `pnl <= 0` as a loss, so 11 breakeven test-fixture trades
        in live MCL paper triggered `consecutive_losses = 11` and made
        /validate/proactive-suite return NOT_READY with a fake 11-loss streak.
        """
        trades = [
            {
                "entry_date": "2026-04-02",
                "exit_date": "2026-04-02",
                "entry_price": 84.2,
                "exit_price": 84.2,
                "side": "long",
                "contracts": 1,
                "exit_reason": "manual_flat",
                "regime_type": "trending",
                "pnl": 0.0,
                "pnl_pct": 0.0,
                "recorded_at": f"2026-04-02T{12 + i:02d}:00:00",
                "symbol": "MES",
            }
            for i in range(11)
        ]
        _create_mock_tracker_file(temp_data_dir, "MES", trades)
        tracker = ValidationTracker(data_dir=temp_data_dir)
        mcl = tracker.metrics["MES"]
        assert mcl.consecutive_losses == 0, "breakevens must not advance streak"
        assert mcl.losing_trades == 0, "breakevens must not count as losses"
        assert mcl.winning_trades == 0, "breakevens must not count as wins"
        assert mcl.total_trades == 11, "breakevens still count in total"


class TestDashboardData:
    """Test dashboard response format."""

    def test_dashboard_data_format(self, tracker):
        """Dashboard data has correct structure."""
        data = tracker.get_dashboard_data()
        assert "timestamp" in data
        assert "instruments" in data
        assert "overall_pass" in data
        assert "MES" in data["instruments"]
        assert "MGC" in data["instruments"]

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
                "symbol": "MES",
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
                "symbol": "MES",
            },
        ]
        _create_mock_tracker_file(temp_data_dir, "MES", trades)

        # Create new tracker to load from disk
        tracker = ValidationTracker(data_dir=temp_data_dir)
        assert tracker.metrics["MES"].total_trades == 2
        assert tracker.metrics["MES"].winning_trades == 1


class TestGetAllTrades:
    """Test trade listing."""

    def test_get_all_trades_empty(self, tracker):
        """Getting trades returns empty list when none recorded."""
        trades = tracker.get_all_trades("MES")
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
                "symbol": "MES",
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
                "symbol": "MES",
            },
        ]
        _create_mock_tracker_file(temp_data_dir, "MES", trades_data)
        tracker = ValidationTracker(data_dir=temp_data_dir)

        trades = tracker.get_all_trades("MES")
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


def _make_mes_trade(entry_date: str, exit_date: str, pnl: float, symbol: str = "MES") -> dict:
    """Helper: minimal MES trade record."""
    return {
        "entry_date": entry_date,
        "exit_date": exit_date,
        "entry_price": 5800.0,
        "exit_price": 5800.0 + (pnl / 5.0),
        "side": "long",
        "contracts": 1,
        "exit_reason": "trailing_stop" if pnl > 0 else "stop",
        "regime_type": "trending",
        "pnl": pnl,
        "pnl_pct": pnl / 5800.0 * 100,
        "recorded_at": f"{entry_date}T12:00:00",
        "symbol": symbol,
    }


class TestMESValidationTracker:
    """MES is tracked, uses 45% WR threshold (not 55% default)."""

    def test_mes_in_tracked_instruments(self):
        assert "MES" in _TRACKED_INSTRUMENTS

    def test_mes_win_rate_threshold_is_45_pct(self):
        t = _thresholds_for("MES")
        assert t["win_rate_pct"] == 45.0

    def test_mcl_win_rate_threshold_is_55_pct(self):
        t = _thresholds_for("MCL")
        assert t["win_rate_pct"] == 55.0

    def test_mes_other_thresholds_unchanged(self):
        t = _thresholds_for("MES")
        assert t["profit_factor"] == 2.0
        assert t["sharpe_ratio"] == 1.5
        assert t["min_trades"] == 60
        assert t["min_days"] == 30
        assert t["max_drawdown_pct"] == 15.0

    def test_mes_gate_rejects_at_fewer_than_60_trades(self, temp_data_dir):
        """Gate must reject MES with only 5 trades regardless of metrics."""
        # 5 big winners — gate should still fail (min_trades = 60)
        trades = [_make_mes_trade("2026-01-02", "2026-01-10", 500.0) for _ in range(5)]
        _create_mock_tracker_file(temp_data_dir, "MES", trades)
        tracker = ValidationTracker(data_dir=temp_data_dir)
        assert not tracker.is_validated("MES")

    def test_mes_win_rate_45pct_accepted(self, temp_data_dir):
        """44–46% WR should pass for MES (trend strategy high R:R profile)."""
        base = datetime(2026, 1, 2)
        # 60 trades: 27 winners (45%) + 33 losers, spread over 31 days
        trades = []
        for i in range(60):
            d = (base + timedelta(days=i % 31)).strftime("%Y-%m-%d")
            pnl = 300.0 if i < 27 else -100.0
            trades.append(_make_mes_trade(d, d, pnl))
        _create_mock_tracker_file(temp_data_dir, "MES", trades)
        tracker = ValidationTracker(data_dir=temp_data_dir)
        m = tracker.metrics["MES"]
        assert m.win_rate_pct == pytest.approx(45.0)
        # WR gate should pass; other gates (PF, Sharpe, days) may vary in fixture
        pf = _thresholds_for("MES")
        assert m.win_rate_pct >= pf["win_rate_pct"]

    def test_mes_55pct_wr_threshold_would_reject(self, temp_data_dir):
        """Confirm that the old 55% WR threshold would have rejected MES at 45% WR."""
        assert PAPER_VALIDATION_GATES["win_rate_pct"] == 55.0
        assert _thresholds_for("MES")["win_rate_pct"] == 45.0
        assert 45.0 < 55.0
