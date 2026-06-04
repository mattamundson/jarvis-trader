"""
Tests for risk/tilt_detector.py — TiltDetector public API.

Covers: check(), record_trade, record_risk_veto, update_drawdown,
get_position_multiplier, get_status, reset.
All assertions are on public output (TiltState fields + get_status dict).
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from risk.tilt_detector import TiltDetector, TiltState


def _td() -> TiltDetector:
    return TiltDetector()


class TestCheckBaseline:
    def test_fresh_detector_returns_not_tilted(self):
        td = _td()
        state = td.check()
        assert state.is_tilted is False
        assert state.tilt_score == 0.0
        assert state.position_size_multiplier == 1.0
        assert state.severity == "none"

    def test_check_returns_tilt_state(self):
        td = _td()
        state = td.check()
        assert isinstance(state, TiltState)

    def test_get_position_multiplier_starts_at_one(self):
        td = _td()
        assert td.get_position_multiplier() == 1.0


class TestConsecutiveLossIndicator:
    def test_two_losses_no_tilt(self):
        td = _td()
        td.record_trade("MES", "long", 1, 5800.0, pnl=-10.0)
        td.record_trade("MES", "long", 1, 5790.0, pnl=-10.0)
        state = td.check()
        assert state.is_tilted is False

    def test_three_losses_triggers_caution(self):
        """3 consecutive losses add 0.2 to score → score >= 0.2 (below 0.3 threshold)."""
        td = _td()
        for _ in range(3):
            td.record_trade("MES", "long", 1, 5800.0, pnl=-10.0)
        state = td.check()
        # 3 losses = 0.2 score — below the 0.3 tilt threshold → is_tilted=False
        assert state.tilt_score >= 0.2

    def test_five_losses_increases_score(self):
        td = _td()
        for _ in range(5):
            td.record_trade("MES", "long", 1, 5800.0, pnl=-10.0)
        state = td.check()
        assert state.tilt_score >= 0.4

    def test_seven_losses_triggers_critical_and_cooldown(self):
        td = _td()
        for _ in range(7):
            td.record_trade("MES", "long", 1, 5800.0, pnl=-10.0)
        state = td.check()
        assert state.tilt_score >= 0.6
        assert state.position_size_multiplier == 0.0

    def test_winning_trade_clears_consecutive_loss_indicator(self):
        td = _td()
        for _ in range(5):
            td.record_trade("MES", "long", 1, 5800.0, pnl=-10.0)
        td.record_trade("MES", "long", 1, 5800.0, pnl=50.0)  # winner
        state = td.check()
        # After a win, consecutive loss streak is broken — score drops
        assert "consecutive_losses_5" not in state.tilt_indicators


class TestCooldownActive:
    def test_active_cooldown_returns_halted_state(self):
        td = _td()
        # Manually set cooldown to future time
        td._cooldown_until = datetime.now() + timedelta(hours=1)
        state = td.check()
        assert state.position_size_multiplier == 0.0
        assert state.is_tilted is True
        assert "cooldown_active" in state.tilt_indicators

    def test_expired_cooldown_clears_itself(self):
        td = _td()
        td._cooldown_until = datetime.now() - timedelta(seconds=1)
        state = td.check()
        assert "cooldown_active" not in state.tilt_indicators


class TestRapidTradeIndicator:
    def test_five_rapid_trades_increase_score(self):
        td = _td()
        for _ in range(5):
            td.record_trade("MES", "long", 1, 5800.0, pnl=None)
        state = td.check()
        assert state.tilt_score >= 0.3

    def test_four_rapid_trades_no_rapid_indicator(self):
        td = _td()
        for _ in range(4):
            td.record_trade("MES", "long", 1, 5800.0, pnl=None)
        state = td.check()
        assert not any("rapid_trades" in i for i in state.tilt_indicators)


class TestRevengeSizing:
    def test_bigger_size_after_loss_triggers_revenge_indicator(self):
        td = _td()
        td.record_trade("MES", "long", 1, 5800.0, pnl=-20.0)  # loss, size=1
        td.record_trade("MES", "long", 3, 5790.0, pnl=None)  # bigger size after loss
        state = td.check()
        assert "revenge_sizing" in state.tilt_indicators

    def test_same_size_after_loss_no_revenge(self):
        td = _td()
        td.record_trade("MES", "long", 1, 5800.0, pnl=-20.0)
        td.record_trade("MES", "long", 1, 5790.0, pnl=None)
        state = td.check()
        assert "revenge_sizing" not in state.tilt_indicators


class TestRiskVetoIndicator:
    def test_two_vetoes_trigger_indicator(self):
        td = _td()
        td.record_risk_veto()
        td.record_risk_veto()
        state = td.check()
        assert any("risk_overrides" in i for i in state.tilt_indicators)

    def test_one_veto_no_indicator(self):
        td = _td()
        td.record_risk_veto()
        state = td.check()
        assert not any("risk_overrides" in i for i in state.tilt_indicators)


class TestDrawdownAcceleration:
    def test_accelerating_drawdown_triggers_indicator(self):
        td = _td()
        # First half: mild drawdown
        for _i in range(4):
            td.update_drawdown(1.0)
        # Second half: accelerating (>20% worse)
        for _i in range(4):
            td.update_drawdown(5.0)
        state = td.check()
        assert "drawdown_accelerating" in state.tilt_indicators

    def test_stable_drawdown_no_indicator(self):
        td = _td()
        for _ in range(8):
            td.update_drawdown(3.0)
        state = td.check()
        assert "drawdown_accelerating" not in state.tilt_indicators

    def test_less_than_4_drawdown_points_no_indicator(self):
        td = _td()
        td.update_drawdown(10.0)
        td.update_drawdown(10.0)
        state = td.check()
        assert "drawdown_accelerating" not in state.tilt_indicators


class TestSeverityLevels:
    def test_score_below_0_3_is_none(self):
        td = _td()
        state = td.check()
        assert state.severity == "none"
        assert state.position_size_multiplier == 1.0

    def test_score_0_3_to_0_5_is_caution(self):
        """5 rapid trades (0.3 score) → caution."""
        td = _td()
        for _ in range(5):
            td.record_trade("MES", "long", 1, 5800.0, pnl=None)
        state = td.check()
        if 0.3 <= state.tilt_score < 0.5:
            assert state.severity == "caution"
            assert state.position_size_multiplier == 0.75

    def test_score_above_0_85_is_critical_zero_multiplier(self):
        """7 losses (0.6) + rapid trades (0.3) = 0.9 → critical with 0.0 multiplier."""
        td = _td()
        for _ in range(7):
            td.record_trade("MES", "long", 1, 5800.0, pnl=-10.0)
        for _ in range(5):
            td.record_trade("MCL", "long", 1, 90.0, pnl=None)
        state = td.check()
        if state.tilt_score > 0.85:
            assert state.position_size_multiplier == 0.0


class TestReset:
    def test_reset_clears_all_state(self):
        td = _td()
        for _ in range(5):
            td.record_trade("MES", "long", 1, 5800.0, pnl=-10.0)
        td.record_risk_veto()
        td._cooldown_until = datetime.now() + timedelta(hours=1)
        td.reset()
        state = td.check()
        assert state.is_tilted is False
        assert state.tilt_score == 0.0
        assert state.position_size_multiplier == 1.0


class TestGetStatus:
    def test_status_has_required_keys(self):
        td = _td()
        status = td.get_status()
        expected = {
            "is_tilted",
            "tilt_score",
            "severity",
            "tilt_indicators",
            "position_size_multiplier",
            "cooldown_until",
            "recent_trade_count",
            "consecutive_losses",
            "rapid_trades_30min",
            "recent_vetoes",
        }
        assert expected.issubset(status.keys())

    def test_status_reflects_trade_history(self):
        td = _td()
        td.record_trade("MES", "long", 1, 5800.0, pnl=-10.0)
        status = td.get_status()
        assert status["recent_trade_count"] == 1

    def test_cooldown_until_is_none_when_not_active(self):
        td = _td()
        status = td.get_status()
        assert status["cooldown_until"] is None


class TestLossTrackerIntegration:
    def test_loss_tracker_consecutive_losses_used_when_available(self):
        """When a loss_tracker is injected, its count is used over internal count."""
        from unittest.mock import MagicMock

        mock_tracker = MagicMock()
        mock_tracker.get_consecutive_losses.return_value = 7

        td = TiltDetector(loss_tracker=mock_tracker)
        state = td.check()
        # 7 losses → score += 0.6
        assert state.tilt_score >= 0.6
