"""
JARVIS TRADER — RiskProtections Tests (T4 — close zero-test gap on safety-tier file)
====================================================================================
Covers each protection trigger in risk/protections.py:

  - check_cooldown: symbol-level cooldown blocks re-entry after a loss; expires correctly
  - activate_cooldown: stores expiry; subsequent check_cooldown reads it
  - check_max_drawdown: equity-curve drawdown gate (default 10%)
  - check_consecutive_losses: N-loss-streak trigger (default 3)
  - Edge cases: empty histories, mixed wins/losses, threshold-exact boundaries

Why this file matters: RiskProtections is a Tier-3 safety surface — every method
returns a boolean that the pipeline uses to short-circuit a trade. A silent
"return False on bad input" bug would let trades through after a streak. Per
.claude/rules/safety.md + rules/testing.md: every safety-tier file must have a
test. This file existed at 72 lines with zero tests.
"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from risk.protections import RiskProtections


@pytest.fixture
def protections(mock_db_manager):
    """RiskProtections instance with mocked db_manager."""
    return RiskProtections(db_manager=mock_db_manager)


class TestCooldown:
    """Symbol-level cooldown after loss — re-entry blocker."""

    def test_no_cooldown_when_symbol_never_locked(self, protections):
        """Fresh symbol → no cooldown active → check_cooldown returns False."""
        assert protections.check_cooldown("MES") is False

    def test_cooldown_blocks_when_active(self, protections):
        """activate_cooldown(MES, 60) → immediate check_cooldown → True (blocked)."""
        protections.activate_cooldown("MES", minutes=60)
        assert protections.check_cooldown("MES") is True

    def test_cooldown_expires_and_clears_entry(self, protections):
        """Cooldown expiry in the past → check_cooldown returns False AND deletes
        the stale entry from the internal dict (memory hygiene).
        """
        # Manually set an already-expired cooldown
        protections.cooldown_periods["MES"] = datetime.now() - timedelta(minutes=1)

        result = protections.check_cooldown("MES")

        assert result is False
        # Stale entry must be removed so the dict doesn't accumulate dead keys
        assert "MES" not in protections.cooldown_periods

    def test_cooldown_is_per_symbol(self, protections):
        """Cooldown on MES does NOT block MNQ — symbol-scoped, not global."""
        protections.activate_cooldown("MES", minutes=60)
        assert protections.check_cooldown("MES") is True
        assert protections.check_cooldown("MNQ") is False

    def test_activate_cooldown_overrides_existing_window(self, protections):
        """Re-activating a cooldown replaces the old expiry (last-write-wins)."""
        # First lock: 1 minute (almost expired)
        protections.cooldown_periods["MES"] = datetime.now() + timedelta(seconds=1)
        # Re-activate with a longer window
        protections.activate_cooldown("MES", minutes=120)

        # The second activation should be roughly +120m, not +1s
        delta = protections.cooldown_periods["MES"] - datetime.now()
        assert delta > timedelta(minutes=60)


class TestMaxDrawdown:
    """Equity-curve drawdown protection — kill switch for slow bleeds."""

    def test_no_drawdown_when_history_empty(self, protections):
        """Empty pnl_history → False (no protection trigger, no crash)."""
        assert protections.check_max_drawdown([]) is False

    def test_drawdown_within_threshold_returns_false(self, protections):
        """Equity dipped 5% from peak vs default 10% threshold → False."""
        pnl_history = [10_000.0, 10_500.0, 9_975.0]  # peak 10500, current 9975 = ~5% DD
        assert protections.check_max_drawdown(pnl_history, max_drawdown_pct=0.10) is False

    def test_drawdown_exceeds_threshold_returns_true(self, protections):
        """Equity dropped 15% from peak vs 10% threshold → True (BLOCK)."""
        pnl_history = [10_000.0, 10_000.0, 8_500.0]  # peak 10000, current 8500 = 15% DD
        assert protections.check_max_drawdown(pnl_history, max_drawdown_pct=0.10) is True

    def test_drawdown_uses_running_peak_not_starting_value(self, protections):
        """Peak tracked across the history — DD measured from highest, not first.

        Sequence rises to $12k then falls to $10k → DD = (12k-10k)/12k = ~16.7%
        even though current ($10k) is still above the start ($10k).
        """
        pnl_history = [10_000.0, 11_000.0, 12_000.0, 10_000.0]
        # 16.7% DD vs 15% threshold → True
        assert protections.check_max_drawdown(pnl_history, max_drawdown_pct=0.15) is True
        # 16.7% DD vs 20% threshold → False (within)
        assert protections.check_max_drawdown(pnl_history, max_drawdown_pct=0.20) is False

    def test_monotonic_rising_equity_no_drawdown(self, protections):
        """Strictly rising equity curve → DD == 0 → False."""
        pnl_history = [10_000.0, 10_100.0, 10_200.0, 10_300.0]
        assert protections.check_max_drawdown(pnl_history, max_drawdown_pct=0.10) is False


class TestConsecutiveLosses:
    """Loss-streak protection — psychological / regime-shift circuit breaker."""

    def test_no_trigger_when_history_too_short(self, protections):
        """Fewer than `limit` trades → False (insufficient data)."""
        last_trades = [{"pnl": -10}, {"pnl": -10}]  # only 2, default limit=3
        assert protections.check_consecutive_losses(last_trades, limit=3) is False

    def test_trigger_on_n_consecutive_losses(self, protections):
        """Last 3 trades all losses → True (BLOCK)."""
        last_trades = [{"pnl": -10}, {"pnl": -5}, {"pnl": -20}]
        assert protections.check_consecutive_losses(last_trades, limit=3) is True

    def test_winning_trade_breaks_streak(self, protections):
        """Recent win in the window → consecutive count resets → False.

        Invariant: even one positive PnL in the first `limit` slots breaks the
        streak. The source counts from the front of the list (most-recent-first
        convention) and breaks on the first non-loss.
        """
        # most-recent first: loss, win, loss → streak interrupted by the win
        last_trades = [{"pnl": -10}, {"pnl": 5}, {"pnl": -10}]
        assert protections.check_consecutive_losses(last_trades, limit=3) is False

    def test_zero_pnl_not_counted_as_loss(self, protections):
        """pnl == 0 (break-even) does NOT count as a loss; streak breaks.

        Source uses `trade.get('pnl', 0) < 0` — strict less-than, so 0 is win-side.
        """
        last_trades = [{"pnl": -10}, {"pnl": 0}, {"pnl": -10}]
        assert protections.check_consecutive_losses(last_trades, limit=3) is False

    def test_missing_pnl_key_treated_as_zero(self, protections):
        """Trade dict missing 'pnl' key → treated as 0 (break-even, not loss).

        Defensive: malformed trade records must not trigger a spurious block.
        """
        last_trades = [{"pnl": -10}, {}, {"pnl": -10}]  # middle has no 'pnl'
        assert protections.check_consecutive_losses(last_trades, limit=3) is False

    def test_custom_limit_respected(self, protections):
        """Caller-supplied limit overrides the default of 3."""
        last_trades = [{"pnl": -1}, {"pnl": -2}, {"pnl": -3}, {"pnl": -4}, {"pnl": -5}]
        # 5 losses in a row vs limit=5 → True
        assert protections.check_consecutive_losses(last_trades, limit=5) is True
        # 5 losses in a row vs limit=10 → False (insufficient history)
        assert protections.check_consecutive_losses(last_trades, limit=10) is False
