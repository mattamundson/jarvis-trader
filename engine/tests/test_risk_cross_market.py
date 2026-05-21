"""
Tests for risk/cross_market_risk.py — CrossMarketRiskManager public API.

Covers: update_pnl (market halt, portfolio halt), is_market_halted,
is_portfolio_halted, reset_daily, get_status, register_halt_callback,
MarketRiskState.daily_loss_pct, PortfolioRiskState.portfolio_loss_pct.
"""

from __future__ import annotations

import pytest

from risk.cross_market_risk import (
    CrossMarketRiskManager,
    MarketRiskState,
    PortfolioRiskState,
)


def _mgr(
    markets: dict | None = None,
    max_market_loss_pct: float = 2.0,
    max_portfolio_loss_pct: float = 5.0,
) -> CrossMarketRiskManager:
    if markets is None:
        markets = {"MCL": 5000.0, "MNQ": 5000.0}
    return CrossMarketRiskManager(
        market_capitals=markets,
        max_market_loss_pct=max_market_loss_pct,
        max_portfolio_loss_pct=max_portfolio_loss_pct,
    )


class TestMarketRiskState:
    def test_daily_loss_pct_zero_when_capital_zero(self):
        state = MarketRiskState(market="MCL", capital=0.0, daily_pnl=-100.0)
        assert state.daily_loss_pct == 0.0

    def test_daily_loss_pct_positive_for_gain(self):
        state = MarketRiskState(market="MCL", capital=5000.0, daily_pnl=100.0)
        assert abs(state.daily_loss_pct - 2.0) < 0.001

    def test_daily_loss_pct_negative_for_loss(self):
        state = MarketRiskState(market="MCL", capital=5000.0, daily_pnl=-100.0)
        assert abs(state.daily_loss_pct - (-2.0)) < 0.001


class TestPortfolioRiskState:
    def test_portfolio_loss_pct_zero_when_capital_zero(self):
        state = PortfolioRiskState(total_capital=0.0, total_pnl=-50.0)
        assert state.portfolio_loss_pct == 0.0

    def test_portfolio_loss_pct_negative_for_loss(self):
        state = PortfolioRiskState(total_capital=10000.0, total_pnl=-500.0)
        assert abs(state.portfolio_loss_pct - (-5.0)) < 0.001


class TestUpdatePnL:
    def test_update_known_market_returns_empty_when_ok(self):
        mgr = _mgr()
        result = mgr.update_pnl("MCL", daily_pnl=-50.0)
        assert result == {} or "market_halted" not in result

    def test_update_unknown_market_returns_empty(self):
        mgr = _mgr()
        result = mgr.update_pnl("NONEXISTENT", daily_pnl=-1000.0)
        assert result == {}

    def test_market_halt_triggers_at_loss_threshold(self):
        """MCL has $5000 capital and 2% limit = -$100 threshold."""
        mgr = _mgr()
        result = mgr.update_pnl("MCL", daily_pnl=-150.0)  # -3% > 2% limit
        assert "market_halted" in result
        assert result["market_halted"]["market"] == "MCL"

    def test_market_not_halted_within_threshold(self):
        mgr = _mgr()
        result = mgr.update_pnl("MCL", daily_pnl=-50.0)  # -1% < 2% limit
        assert "market_halted" not in result

    def test_is_market_halted_true_after_halt(self):
        mgr = _mgr()
        mgr.update_pnl("MCL", daily_pnl=-300.0)
        assert mgr.is_market_halted("MCL") is True

    def test_is_market_halted_false_for_unaffected_market(self):
        mgr = _mgr()
        mgr.update_pnl("MCL", daily_pnl=-300.0)
        # MNQ was not halted individually
        assert mgr.is_market_halted("MNQ") is False or mgr.is_portfolio_halted()

    def test_portfolio_halt_triggers_at_portfolio_threshold(self):
        """Combined portfolio loss > 5% halts all."""
        mgr = _mgr()
        mgr.update_pnl("MCL", daily_pnl=-300.0)  # -6% of MCL cap
        # Even if just MCL halted, portfolio total = -300 / 10000 = -3% so far.
        # Push MNQ to -300 too: total -600 / 10000 = -6% > 5%
        result = mgr.update_pnl("MNQ", daily_pnl=-300.0)
        # Portfolio halt may come from either call
        assert mgr.is_portfolio_halted() is True

    def test_portfolio_halt_makes_all_markets_halted(self):
        mgr = _mgr()
        mgr.update_pnl("MCL", daily_pnl=-300.0)
        mgr.update_pnl("MNQ", daily_pnl=-300.0)
        assert mgr.is_market_halted("MCL") is True
        assert mgr.is_market_halted("MNQ") is True

    def test_market_halt_fires_only_once(self):
        """Second update_pnl call on already-halted market does not re-fire."""
        calls = []
        mgr = _mgr()
        mgr.register_halt_callback(lambda market, reason, halt_type: calls.append(halt_type))
        mgr.update_pnl("MCL", daily_pnl=-300.0)
        n_after_first = len(calls)
        mgr.update_pnl("MCL", daily_pnl=-400.0)  # already halted
        assert len(calls) == n_after_first  # no second halt callback


class TestIsMarketHalted:
    def test_portfolio_halt_overrides_all_markets(self):
        mgr = _mgr()
        mgr.update_pnl("MCL", daily_pnl=-300.0)
        mgr.update_pnl("MNQ", daily_pnl=-300.0)
        # Both are halted because portfolio is halted
        assert mgr.is_market_halted("MCL") is True
        assert mgr.is_market_halted("MNQ") is True

    def test_unknown_market_returns_false(self):
        mgr = _mgr()
        assert mgr.is_market_halted("UNKNOWN") is False


class TestResetDaily:
    def test_reset_clears_pnl(self):
        mgr = _mgr()
        mgr.update_pnl("MCL", daily_pnl=-300.0)
        mgr.reset_daily()
        status = mgr.get_status()
        assert status["total_daily_pnl"] == 0.0

    def test_reset_clears_portfolio_halt(self):
        mgr = _mgr()
        mgr.update_pnl("MCL", daily_pnl=-300.0)
        mgr.update_pnl("MNQ", daily_pnl=-300.0)
        assert mgr.is_portfolio_halted() is True
        mgr.reset_daily()
        assert mgr.is_portfolio_halted() is False

    def test_reset_clears_individual_market_halt(self):
        mgr = _mgr()
        mgr.update_pnl("MCL", daily_pnl=-300.0)
        mgr.reset_daily()
        assert mgr.is_market_halted("MCL") is False

    def test_after_reset_new_losses_trigger_halt_again(self):
        mgr = _mgr()
        mgr.update_pnl("MCL", daily_pnl=-300.0)
        mgr.reset_daily()
        result = mgr.update_pnl("MCL", daily_pnl=-300.0)
        assert "market_halted" in result


class TestGetStatus:
    def test_status_has_expected_keys(self):
        mgr = _mgr()
        status = mgr.get_status()
        expected_keys = {
            "date",
            "total_capital",
            "total_daily_pnl",
            "portfolio_loss_pct",
            "portfolio_halted",
            "halt_reason",
            "max_market_loss_pct",
            "max_portfolio_loss_pct",
            "markets",
        }
        assert expected_keys.issubset(status.keys())

    def test_status_markets_includes_each_registered_market(self):
        mgr = _mgr(markets={"MCL": 5000.0, "MNQ": 5000.0})
        status = mgr.get_status()
        assert "MCL" in status["markets"]
        assert "MNQ" in status["markets"]

    def test_status_total_capital_matches_sum(self):
        mgr = _mgr(markets={"MCL": 3000.0, "MNQ": 7000.0})
        status = mgr.get_status()
        assert abs(status["total_capital"] - 10000.0) < 0.01

    def test_status_reflects_halt_state(self):
        mgr = _mgr()
        mgr.update_pnl("MCL", daily_pnl=-300.0)
        mgr.update_pnl("MNQ", daily_pnl=-300.0)
        status = mgr.get_status()
        assert status["portfolio_halted"] is True


class TestRegisterHaltCallback:
    def test_callback_called_on_market_halt(self):
        received = []
        mgr = _mgr()
        mgr.register_halt_callback(
            lambda market, reason, halt_type: received.append((market, halt_type))
        )
        mgr.update_pnl("MCL", daily_pnl=-300.0)
        assert any(m == "MCL" for m, _ in received)

    def test_multiple_callbacks_all_called(self):
        calls_a: list = []
        calls_b: list = []
        mgr = _mgr()
        mgr.register_halt_callback(lambda market, reason, halt_type: calls_a.append(market))
        mgr.register_halt_callback(lambda market, reason, halt_type: calls_b.append(market))
        mgr.update_pnl("MCL", daily_pnl=-300.0)
        assert len(calls_a) > 0
        assert len(calls_b) > 0

    def test_callback_exception_does_not_crash_manager(self):
        """A failing callback must not propagate — halt must still complete."""
        mgr = _mgr()
        mgr.register_halt_callback(lambda market, reason, halt_type: 1 / 0)
        # Should not raise
        mgr.update_pnl("MCL", daily_pnl=-300.0)
        assert mgr.is_market_halted("MCL") is True
