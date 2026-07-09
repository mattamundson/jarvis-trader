"""
Test suite for trade analytics module.
Tests all functions with normal data and edge cases.
"""

import math
import random

import pytest

from analytics.trade_analytics import (
    DEFAULT_STARTING_CAPITAL,
    TradeAnalytics,
    calculate_analytics,
    calculate_expectancy,
    calculate_max_drawdown,
    calculate_profit_factor,
    calculate_sharpe_ratio,
    calculate_win_rate,
)


class TestCalculateSharpeRatio:
    def test_sharpe_positive(self):
        returns = [0.01, 0.02, 0.01, 0.02, 0.01]
        sharpe = calculate_sharpe_ratio(returns)
        assert sharpe > 0 and isinstance(sharpe, float)

    def test_sharpe_zero_std_positive(self):
        # float("inf") is not JSON-serializable; sentinel value 9999.0 is used instead
        assert calculate_sharpe_ratio([0.01, 0.01, 0.01]) == 9999.0

    def test_sharpe_zero_std_zero(self):
        assert calculate_sharpe_ratio([0.0, 0.0, 0.0]) == 0.0

    def test_sharpe_negative(self):
        assert calculate_sharpe_ratio([-0.01, -0.02, -0.01]) < 0

    def test_sharpe_empty(self):
        assert calculate_sharpe_ratio([]) == 0.0

    def test_sharpe_single(self):
        assert calculate_sharpe_ratio([0.01]) == 0.0

    def test_sharpe_with_rf(self):
        returns = [0.01, 0.02, 0.01, 0.015, 0.012]
        s1 = calculate_sharpe_ratio(returns, risk_free_rate=0.0)
        s2 = calculate_sharpe_ratio(returns, risk_free_rate=0.005)
        assert s1 > s2


class TestCalculateProfitFactor:
    def test_pf_normal(self):
        trades = [{"pnl": 100}, {"pnl": 50}, {"pnl": -30}, {"pnl": -20}]
        pf = calculate_profit_factor(trades)
        assert pf == pytest.approx(150 / 50, rel=0.01)

    def test_pf_no_losses(self):
        # float("inf") is not JSON-serializable; sentinel value 9999.0 is used instead
        assert calculate_profit_factor([{"pnl": 100}, {"pnl": 50}]) == 9999.0

    def test_pf_no_wins(self):
        assert calculate_profit_factor([{"pnl": -100}, {"pnl": -50}]) == 0.0

    def test_pf_empty(self):
        assert calculate_profit_factor([]) == 0.0

    def test_pf_breakeven(self):
        assert calculate_profit_factor([{"pnl": 100}, {"pnl": -100}]) == 1.0


class TestCalculateMaxDrawdown:
    def test_dd_normal(self):
        equity = [10000, 12000, 11000, 10500, 9000, 11000]
        dd = calculate_max_drawdown(equity)
        assert dd == pytest.approx(25.0, rel=0.01)

    def test_dd_monotonic(self):
        assert calculate_max_drawdown([10000, 11000, 12000, 13000]) == 0.0

    def test_dd_full_loss(self):
        assert calculate_max_drawdown([10000, 0]) == pytest.approx(100.0, rel=0.01)

    def test_dd_half_loss(self):
        assert calculate_max_drawdown([10000, 5000]) == pytest.approx(50.0, rel=0.01)

    def test_dd_empty(self):
        assert calculate_max_drawdown([]) == 0.0

    def test_dd_single(self):
        assert calculate_max_drawdown([10000]) == 0.0

    def test_dd_t0_03_repro_trivial_early_peak(self):
        """
        T0-03 regression: calculate_analytics() feeds a cumulative-P&L curve
        that starts at 0.0 (see _build_equity_curve), so a tiny early win
        must not become the percentage denominator for a much larger later
        loss. Before the fix this exact fixture reported 1900.0% (equity_curve
        [0.0, 50.0, -900.0] used the trivial $50 peak as the denominator:
        (50 - -900) / 50 * 100 = 1900%). Post-fix the denominator floors at
        DEFAULT_STARTING_CAPITAL, giving the correct $950 loss / $10,000 = 9.5%.
        """
        equity_curve = [0.0, 50.0, -900.0]
        dd = calculate_max_drawdown(equity_curve)
        assert dd == pytest.approx(9.5, rel=0.001)

    def test_dd_t0_03_repro_via_calculate_analytics(self):
        """Same regression exercised through the real call path (calculate_analytics)."""
        trades = [{"pnl": 50}, {"pnl": -950}]
        a = calculate_analytics(trades)
        assert a.max_drawdown_pct == pytest.approx(9.5, rel=0.001)

    def test_dd_invariant_bounded_0_to_100(self):
        """
        MANDATORY invariant (T0-03 closure): max drawdown must always be in
        [0, 100] for ANY equity curve -- guards the class of bug (unbounded
        percentage from an unfloored/mis-scaled peak), not just one fixture.
        Property-style: generate many equity curves across several realistic
        and adversarial regimes (absolute-balance style, cumulative-P&L-from
        -zero style like the real caller, deeply negative runs, and
        catastrophic single-step losses shaped exactly like the T0-03 defect)
        and assert the bound holds for every one. Seeded for determinism.
        """
        rng = random.Random(20260709)

        def assert_bounded(curve):
            dd = calculate_max_drawdown(curve)
            assert 0.0 <= dd <= 100.0, f"drawdown {dd} out of [0,100] for curve {curve}"

        # Regime 1: classic absolute-balance curves starting near $10k.
        for _ in range(50):
            length = rng.randint(2, 30)
            curve = [10_000.0]
            for _ in range(length - 1):
                curve.append(curve[-1] + rng.uniform(-3000, 3000))
            assert_bounded(curve)

        # Regime 2: cumulative-P&L-from-zero curves (the real calculate_analytics
        # path) with random trade sizes, including runs that go deeply negative.
        for _ in range(50):
            length = rng.randint(2, 30)
            curve = [0.0]
            for _ in range(length - 1):
                curve.append(curve[-1] + rng.uniform(-2000, 500))
            assert_bounded(curve)

        # Regime 3: adversarial -- catastrophic single-step loss far exceeding
        # DEFAULT_STARTING_CAPITAL right after a trivial early peak (the exact
        # shape of the T0-03 defect, pushed further to confirm the [0,100]
        # clamp holds even when the dollar loss dwarfs the floored denominator).
        for _ in range(20):
            early_peak = rng.uniform(1, 500)
            catastrophic_loss = rng.uniform(-500_000, -1000)
            curve = [0.0, early_peak, early_peak + catastrophic_loss]
            assert_bounded(curve)

        # Regime 4: monotonic, all-negative, and exact-floor edge cases.
        assert_bounded([1.0, 2.0, 3.0, 4.0])
        assert_bounded([-100.0, -50.0, -10.0])
        assert_bounded([5_000_000.0, 0.0])
        assert_bounded([DEFAULT_STARTING_CAPITAL, -DEFAULT_STARTING_CAPITAL])


class TestCalculateWinRate:
    def test_wr_normal(self):
        trades = [{"pnl": 100}, {"pnl": 50}, {"pnl": -30}, {"pnl": 20}]
        wr = calculate_win_rate(trades)
        assert wr == pytest.approx(75.0, rel=0.01)

    def test_wr_all_wins(self):
        trades = [{"pnl": 100}, {"pnl": 50}, {"pnl": 25}]
        assert calculate_win_rate(trades) == pytest.approx(100.0, rel=0.01)

    def test_wr_all_losses(self):
        trades = [{"pnl": -100}, {"pnl": -50}]
        assert calculate_win_rate(trades) == pytest.approx(0.0, rel=0.01)

    def test_wr_empty(self):
        assert calculate_win_rate([]) == 0.0

    def test_wr_with_zero_pnl(self):
        trades = [{"pnl": 100}, {"pnl": 0}, {"pnl": -50}]
        assert calculate_win_rate(trades) == pytest.approx(33.33, rel=0.01)


class TestCalculateExpectancy:
    def test_exp_normal(self):
        trades = [{"pnl": 100}, {"pnl": 50}, {"pnl": -30}]
        assert calculate_expectancy(trades) == pytest.approx(40.0, rel=0.01)

    def test_exp_losses(self):
        trades = [{"pnl": -100}, {"pnl": -50}, {"pnl": -25}]
        assert calculate_expectancy(trades) == pytest.approx(-58.33, rel=0.01)

    def test_exp_breakeven(self):
        trades = [{"pnl": 100}, {"pnl": -100}]
        assert calculate_expectancy(trades) == pytest.approx(0.0, rel=0.01)

    def test_exp_empty(self):
        assert calculate_expectancy([]) == 0.0


class TestCalculateAnalytics:
    def test_analytics_normal(self):
        trades = [
            {"pnl": 100, "date": "2026-04-01"},
            {"pnl": 150, "date": "2026-04-01"},
            {"pnl": -50, "date": "2026-04-02"},
            {"pnl": 75, "date": "2026-04-02"},
            {"pnl": -25, "date": "2026-04-03"},
        ]
        a = calculate_analytics(trades)
        assert a.total_trades == 5 and a.total_pnl == 250.0
        assert a.win_rate == pytest.approx(60.0, rel=0.01)
        assert a.expectancy == pytest.approx(50.0, rel=0.01)

    def test_analytics_empty(self):
        a = calculate_analytics([])
        assert a.total_trades == 0 and a.total_pnl == 0.0

    def test_analytics_single_win(self):
        trades = [{"pnl": 100, "date": "2026-04-01"}]
        a = calculate_analytics(trades)
        assert a.total_trades == 1 and a.win_rate == 100.0

    def test_analytics_all_losses(self):
        trades = [{"pnl": -50, "date": "2026-04-01"}, {"pnl": -75, "date": "2026-04-02"}]
        a = calculate_analytics(trades)
        assert a.total_trades == 2 and a.win_rate == 0.0

    def test_analytics_fails_gates(self):
        trades = [{"pnl": -1000, "date": "2026-04-01"}, {"pnl": -500, "date": "2026-04-02"}]
        a = calculate_analytics(trades)
        assert a.profit_factor < 2.0 and a.win_rate < 55.0

    def test_analytics_passes_gates(self):
        trades = [
            {"pnl": 200, "date": "2026-04-01"},
            {"pnl": 300, "date": "2026-04-01"},
            {"pnl": 150, "date": "2026-04-02"},
            {"pnl": -50, "date": "2026-04-02"},
        ]
        a = calculate_analytics(trades)
        assert a.win_rate >= 50.0 and a.profit_factor >= 1.0

    def test_analytics_missing_pnl(self):
        trades = [{"date": "2026-04-01"}, {"pnl": 100, "date": "2026-04-02"}]
        a = calculate_analytics(trades)
        assert a.total_trades == 2 and a.total_pnl == 100.0

    def test_analytics_fields(self):
        a = calculate_analytics([{"pnl": 100}])
        assert all(
            hasattr(a, f)
            for f in [
                "sharpe_ratio",
                "profit_factor",
                "max_drawdown_pct",
                "win_rate",
                "expectancy",
                "total_trades",
                "total_pnl",
                "avg_win",
                "avg_loss",
                "best_trade",
                "worst_trade",
            ]
        )
