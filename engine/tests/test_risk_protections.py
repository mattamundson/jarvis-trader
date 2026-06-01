"""
Tests for risk/protections.py — RiskProtections public API.

Covers: check_cooldown, activate_cooldown, check_max_drawdown,
check_consecutive_losses.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from risk.protections import RiskProtections


def _protections() -> RiskProtections:
    db = MagicMock()
    return RiskProtections(db_manager=db)


class TestCooldown:
    def test_no_cooldown_initially(self):
        p = _protections()
        assert p.check_cooldown("MES") is False

    def test_cooldown_active_after_activation(self):
        p = _protections()
        p.activate_cooldown("MES", minutes=60)
        assert p.check_cooldown("MES") is True

    def test_cooldown_inactive_for_different_symbol(self):
        p = _protections()
        p.activate_cooldown("MES", minutes=60)
        assert p.check_cooldown("MCL") is False

    def test_cooldown_expires_after_zero_minutes(self):
        """A 0-minute cooldown expires immediately — next check returns False."""
        from datetime import datetime, timedelta

        p = _protections()
        # Manually set an already-expired cooldown

        p.cooldown_periods["MES"] = datetime.now() - timedelta(seconds=1)
        assert p.check_cooldown("MES") is False

    def test_cooldown_removed_after_expiry(self):
        """After a cooldown expires, the symbol key should be gone."""
        from datetime import datetime, timedelta

        p = _protections()
        p.cooldown_periods["MES"] = datetime.now() - timedelta(seconds=1)
        p.check_cooldown("MES")
        assert "MES" not in p.cooldown_periods

    def test_multiple_symbols_independent_cooldowns(self):
        p = _protections()
        p.activate_cooldown("MES", minutes=60)
        p.activate_cooldown("MCL", minutes=30)
        assert p.check_cooldown("MES") is True
        assert p.check_cooldown("MCL") is True


class TestMaxDrawdown:
    def test_empty_history_returns_false(self):
        p = _protections()
        assert p.check_max_drawdown([]) is False

    def test_no_drawdown_returns_false(self):
        p = _protections()
        assert p.check_max_drawdown([100.0, 100.0, 100.0]) is False

    def test_drawdown_below_threshold_returns_false(self):
        p = _protections()
        # Peak=100, valley=95 → DD=5%, threshold=10%
        history = [100.0, 98.0, 96.0, 95.0]
        assert p.check_max_drawdown(history, max_drawdown_pct=0.10) is False

    def test_drawdown_above_threshold_returns_true(self):
        p = _protections()
        # Peak=100, valley=85 → DD=15%, threshold=10%
        history = [100.0, 95.0, 90.0, 85.0]
        assert p.check_max_drawdown(history, max_drawdown_pct=0.10) is True

    def test_drawdown_exactly_at_threshold_returns_false(self):
        """The check is strict >; equal-to-threshold should not trigger."""
        p = _protections()
        # Peak=100, valley=90 → DD=10%, threshold=10%
        history = [100.0, 90.0]
        assert p.check_max_drawdown(history, max_drawdown_pct=0.10) is False

    def test_recovery_after_drawdown_does_not_trigger(self):
        """Even if there was a dip, recovery means no current breach."""
        p = _protections()
        # Peak=100, dip to 92 (8% DD), then recovery to 102 → new peak
        history = [100.0, 92.0, 102.0]
        assert p.check_max_drawdown(history, max_drawdown_pct=0.10) is False


class TestConsecutiveLosses:
    def test_no_trades_returns_false(self):
        p = _protections()
        assert p.check_consecutive_losses([], limit=3) is False

    def test_fewer_trades_than_limit_returns_false(self):
        p = _protections()
        trades = [{"pnl": -10.0}, {"pnl": -5.0}]
        assert p.check_consecutive_losses(trades, limit=3) is False

    def test_three_consecutive_losses_returns_true(self):
        p = _protections()
        trades = [{"pnl": -10.0}, {"pnl": -5.0}, {"pnl": -20.0}]
        assert p.check_consecutive_losses(trades, limit=3) is True

    def test_streak_broken_by_winner_returns_false(self):
        p = _protections()
        # First two are losses but third is a winner — streak broken
        trades = [{"pnl": -10.0}, {"pnl": 5.0}, {"pnl": -20.0}]
        assert p.check_consecutive_losses(trades, limit=3) is False

    def test_exactly_at_limit_returns_true(self):
        p = _protections()
        trades = [{"pnl": -1.0}, {"pnl": -2.0}, {"pnl": -3.0}]
        assert p.check_consecutive_losses(trades, limit=3) is True

    def test_more_than_limit_consecutive_losses_returns_true(self):
        p = _protections()
        trades = [{"pnl": -1.0}] * 5
        assert p.check_consecutive_losses(trades, limit=3) is True

    def test_zero_pnl_is_not_a_loss(self):
        """pnl=0.0 is not < 0 so it breaks the streak."""
        p = _protections()
        trades = [{"pnl": -10.0}, {"pnl": 0.0}, {"pnl": -10.0}]
        assert p.check_consecutive_losses(trades, limit=3) is False
