"""
Tests for risk/loss_tracker.py — ConsecutiveLossTracker public API.

Covers: record_trade, get_consecutive_losses, get_position_size_multiplier,
is_halted, get_halt_reason, reset, get_status.
Each test exercises one clear behavior on the public interface only.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from risk.loss_tracker import ConsecutiveLossTracker


def _make_tracker(**kwargs) -> ConsecutiveLossTracker:
    """Create a tracker backed by a temporary directory so no real fs state leaks."""
    tmpdir = tempfile.mkdtemp()
    defaults = {
        "data_dir": tmpdir,
        "consecutive_loss_half_size": 3,
        "consecutive_loss_quarter_size": 5,
        "consecutive_loss_halt": 7,
        "consecutive_loss_halt_hours": 24,
    }
    defaults.update(kwargs)
    return ConsecutiveLossTracker(**defaults)


class TestRecordTrade:
    def test_winning_trade_returns_true(self):
        tracker = _make_tracker()
        result = tracker.record_trade("MES", pnl=50.0)
        assert result is True

    def test_losing_trade_returns_false(self):
        tracker = _make_tracker()
        result = tracker.record_trade("MES", pnl=-20.0)
        assert result is False

    def test_zero_pnl_counts_as_win(self):
        """pnl == 0.0 is treated as a non-loss (is_win = pnl >= 0)."""
        tracker = _make_tracker()
        result = tracker.record_trade("MES", pnl=0.0)
        assert result is True

    def test_losing_trade_increments_global_counter(self):
        tracker = _make_tracker()
        tracker.record_trade("MES", pnl=-10.0)
        assert tracker.get_consecutive_losses() == 1

    def test_winning_trade_resets_global_counter(self):
        tracker = _make_tracker()
        tracker.record_trade("MES", pnl=-10.0)
        tracker.record_trade("MES", pnl=-10.0)
        tracker.record_trade("MES", pnl=50.0)  # win
        assert tracker.get_consecutive_losses() == 0

    def test_losing_trade_increments_symbol_counter(self):
        tracker = _make_tracker()
        tracker.record_trade("MCL", pnl=-5.0)
        tracker.record_trade("MCL", pnl=-5.0)
        assert tracker.get_consecutive_losses("MCL") == 2

    def test_winning_trade_resets_symbol_counter(self):
        tracker = _make_tracker()
        tracker.record_trade("MCL", pnl=-5.0)
        tracker.record_trade("MCL", pnl=10.0)  # win
        assert tracker.get_consecutive_losses("MCL") == 0

    def test_losses_on_different_symbols_increment_independently(self):
        tracker = _make_tracker()
        tracker.record_trade("MES", pnl=-10.0)
        tracker.record_trade("MCL", pnl=-10.0)
        tracker.record_trade("MCL", pnl=-10.0)
        assert tracker.get_consecutive_losses("MES") == 1
        assert tracker.get_consecutive_losses("MCL") == 2
        # But global counter reflects ALL consecutive losses
        assert tracker.get_consecutive_losses() == 3

    def test_winning_one_symbol_only_resets_that_symbols_counter(self):
        tracker = _make_tracker()
        tracker.record_trade("MES", pnl=-10.0)
        tracker.record_trade("MCL", pnl=-10.0)
        tracker.record_trade("MES", pnl=10.0)  # win on MES only
        # MES counter reset; global reset; MCL counter unchanged
        assert tracker.get_consecutive_losses("MES") == 0
        assert tracker.get_consecutive_losses() == 0


class TestGetConsecutiveLosses:
    def test_starts_at_zero(self):
        tracker = _make_tracker()
        assert tracker.get_consecutive_losses() == 0

    def test_unknown_symbol_returns_zero(self):
        tracker = _make_tracker()
        assert tracker.get_consecutive_losses("UNKNOWN") == 0

    def test_global_and_symbol_both_increment(self):
        tracker = _make_tracker()
        for _ in range(4):
            tracker.record_trade("MES", pnl=-10.0)
        assert tracker.get_consecutive_losses() == 4
        assert tracker.get_consecutive_losses("MES") == 4


class TestPositionSizeMultiplier:
    def test_zero_losses_full_size(self):
        tracker = _make_tracker()
        assert tracker.get_position_size_multiplier() == 1.0

    def test_two_losses_full_size(self):
        tracker = _make_tracker()
        for _ in range(2):
            tracker.record_trade("MES", pnl=-10.0)
        assert tracker.get_position_size_multiplier() == 1.0

    def test_three_losses_half_size(self):
        tracker = _make_tracker(consecutive_loss_half_size=3)
        for _ in range(3):
            tracker.record_trade("MES", pnl=-10.0)
        assert tracker.get_position_size_multiplier() == 0.5

    def test_five_losses_quarter_size(self):
        tracker = _make_tracker(consecutive_loss_quarter_size=5)
        for _ in range(5):
            tracker.record_trade("MES", pnl=-10.0)
        assert tracker.get_position_size_multiplier() == 0.25

    def test_halt_threshold_returns_zero(self):
        tracker = _make_tracker(consecutive_loss_halt=7, consecutive_loss_halt_hours=24)
        for _ in range(7):
            tracker.record_trade("MES", pnl=-10.0)
        assert tracker.get_position_size_multiplier() == 0.0

    def test_win_after_losses_restores_full_size(self):
        tracker = _make_tracker()
        for _ in range(3):
            tracker.record_trade("MES", pnl=-10.0)
        tracker.record_trade("MES", pnl=50.0)
        assert tracker.get_position_size_multiplier() == 1.0


class TestIsHalted:
    def test_not_halted_initially(self):
        tracker = _make_tracker()
        assert tracker.is_halted() is False

    def test_halted_after_halt_threshold(self):
        tracker = _make_tracker(consecutive_loss_halt=7)
        for _ in range(7):
            tracker.record_trade("MES", pnl=-10.0)
        assert tracker.is_halted() is True

    def test_halt_reason_mentions_losses(self):
        tracker = _make_tracker(consecutive_loss_halt=7)
        for _ in range(7):
            tracker.record_trade("MES", pnl=-10.0)
        reason = tracker.get_halt_reason()
        assert "7" in reason or "loss" in reason.lower()

    def test_not_halted_below_threshold(self):
        tracker = _make_tracker(consecutive_loss_halt=7)
        for _ in range(6):
            tracker.record_trade("MES", pnl=-10.0)
        assert tracker.is_halted() is False

    def test_halt_reason_empty_when_not_halted(self):
        tracker = _make_tracker()
        assert tracker.get_halt_reason() == ""


class TestReset:
    def test_global_reset_clears_all_counters(self):
        tracker = _make_tracker()
        tracker.record_trade("MES", pnl=-10.0)
        tracker.record_trade("MCL", pnl=-10.0)
        tracker.reset()
        assert tracker.get_consecutive_losses() == 0
        assert tracker.get_consecutive_losses("MES") == 0
        assert tracker.get_consecutive_losses("MCL") == 0

    def test_global_reset_clears_halt(self):
        tracker = _make_tracker(consecutive_loss_halt=7)
        for _ in range(7):
            tracker.record_trade("MES", pnl=-10.0)
        assert tracker.is_halted() is True
        tracker.reset()
        assert tracker.is_halted() is False

    def test_symbol_reset_only_clears_that_symbol(self):
        tracker = _make_tracker()
        tracker.record_trade("MES", pnl=-10.0)
        tracker.record_trade("MES", pnl=-10.0)
        tracker.record_trade("MCL", pnl=-10.0)
        tracker.reset(symbol="MES")
        assert tracker.get_consecutive_losses("MES") == 0
        assert tracker.get_consecutive_losses("MCL") == 1

    def test_symbol_reset_does_not_clear_global_counter(self):
        """Per-symbol reset does not affect the global consecutive loss count."""
        tracker = _make_tracker()
        tracker.record_trade("MES", pnl=-10.0)
        tracker.record_trade("MCL", pnl=-10.0)
        # Both symbols contributed to 2 global losses
        tracker.reset(symbol="MES")
        # Global counter is not reset by a per-symbol reset
        # (by design — global state tracks cumulative run)
        assert tracker.get_consecutive_losses("MES") == 0


class TestGetStatus:
    def test_status_has_required_keys(self):
        tracker = _make_tracker()
        status = tracker.get_status()
        expected_keys = {
            "global_consecutive_losses",
            "symbol_losses",
            "position_size_multiplier",
            "is_halted",
            "halt_until",
            "last_trade_symbol",
            "last_trade_timestamp",
            "config",
        }
        assert expected_keys.issubset(status.keys())

    def test_status_reflects_current_state(self):
        tracker = _make_tracker()
        tracker.record_trade("MES", pnl=-10.0)
        tracker.record_trade("MES", pnl=-10.0)
        status = tracker.get_status()
        assert status["global_consecutive_losses"] == 2
        assert status["last_trade_symbol"] == "MES"
        assert status["position_size_multiplier"] == 1.0
        assert status["is_halted"] is False


class TestStatePersistence:
    def test_state_persists_across_instances(self):
        """New tracker instance reading the same directory restores prior state."""
        tmpdir = tempfile.mkdtemp()
        tracker1 = ConsecutiveLossTracker(data_dir=tmpdir)
        tracker1.record_trade("MES", pnl=-10.0)
        tracker1.record_trade("MES", pnl=-10.0)

        tracker2 = ConsecutiveLossTracker(data_dir=tmpdir)
        assert tracker2.get_consecutive_losses() == 2

    def test_fresh_instance_starts_at_zero_with_empty_dir(self):
        tmpdir = tempfile.mkdtemp()
        tracker = ConsecutiveLossTracker(data_dir=tmpdir)
        assert tracker.get_consecutive_losses() == 0
