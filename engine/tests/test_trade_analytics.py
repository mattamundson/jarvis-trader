"""
Test suite for trade analytics module.
Tests all functions with normal data and edge cases.
"""

import math

import pytest

from analytics.trade_analytics import (
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
