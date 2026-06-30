"""
Tests for learning/confidence_scorer module.

Tests the confidence adjustment multiplier logic and database integration.
"""

import pytest

from learning.confidence_scorer import (
    _compute_multiplier,
    _compute_trade_metrics,
    get_confidence_adjustment,
)


class TestComputeMultiplier:
    """Test the multiplier scoring logic."""

    def test_strong_edge_1_35(self):
        """Returns 1.35 when win_rate >= 0.65 AND r_ratio >= 1.8."""
        assert _compute_multiplier(0.70, 2.0) == 1.35
        assert _compute_multiplier(0.65, 1.8) == 1.35

    def test_solid_edge_1_20(self):
        """Returns 1.20 when win_rate >= 0.60 AND r_ratio >= 1.5."""
        assert _compute_multiplier(0.60, 1.5) == 1.20
        assert _compute_multiplier(0.62, 1.6) == 1.20

    def test_slight_edge_1_10(self):
        """Returns 1.10 when win_rate >= 0.55 (and not higher tier)."""
        assert _compute_multiplier(0.55, 1.0) == 1.10
        assert _compute_multiplier(0.58, 1.2) == 1.10

    def test_poor_performance_0_65(self):
        """Returns 0.65 when win_rate <= 0.35."""
        assert _compute_multiplier(0.35, 1.0) == 0.65
        assert _compute_multiplier(0.30, 2.0) == 0.65

    def test_below_average_0_80(self):
        """Returns 0.80 when win_rate <= 0.42 (but > 0.35)."""
        assert _compute_multiplier(0.42, 1.0) == 0.80
        assert _compute_multiplier(0.40, 1.5) == 0.80

    def test_neutral_1_0(self):
        """Returns 1.0 for neutral cases."""
        assert _compute_multiplier(0.50, 1.0) == 1.0
        assert _compute_multiplier(0.45, 1.2) == 1.0


class TestComputeTradeMetrics:
    """Test trade metrics computation."""

    def test_empty_trades_list(self):
        """Returns (0.0, 0.0, 0.0, 1.0) for empty trades."""
        win_rate, avg_winner, avg_loser, r_ratio = _compute_trade_metrics([])
        assert win_rate == 0.0
        assert avg_winner == 0.0
        assert avg_loser == 0.0
        assert r_ratio == 1.0

    def test_single_winning_trade(self):
        """Correctly computes metrics for single winning trade."""
        trades = [{"pnl": 100.0, "outcome": "winning_trade"}]
        win_rate, avg_winner, avg_loser, r_ratio = _compute_trade_metrics(trades)
        assert win_rate == 1.0
        assert avg_winner == 100.0
        assert avg_loser == 0.0
        assert r_ratio == 1.0  # no losers, default 1.0

    def test_single_losing_trade(self):
        """Correctly computes metrics for single losing trade."""
        trades = [{"pnl": -50.0, "outcome": "losing_trade"}]
        win_rate, avg_winner, avg_loser, r_ratio = _compute_trade_metrics(trades)
        assert win_rate == 0.0
        assert avg_winner == 0.0
        assert avg_loser == 50.0
        assert r_ratio == 0.0

    def test_mixed_trades_pnl_positive(self):
        """Correctly computes metrics using positive pnl."""
        trades = [
            {"pnl": 100.0, "outcome": ""},  # win by pnl
            {"pnl": 50.0, "outcome": ""},  # win by pnl
            {"pnl": -50.0, "outcome": ""},  # loss by pnl
        ]
        win_rate, avg_winner, avg_loser, r_ratio = _compute_trade_metrics(trades)
        assert win_rate == pytest.approx(2 / 3)
        assert avg_winner == pytest.approx(75.0)  # (100 + 50) / 2
        assert avg_loser == pytest.approx(50.0)
        assert r_ratio == pytest.approx(75.0 / 50.0)

    def test_mixed_trades_outcome_field(self):
        """Correctly computes metrics using outcome field."""
        trades = [
            {"pnl": 0.0, "outcome": "winning_trade"},  # win by outcome
            {"pnl": 0.0, "outcome": "winning_trade"},  # win by outcome
            {"pnl": 0.0, "outcome": "losing_trade"},  # loss by outcome
        ]
        win_rate, avg_winner, avg_loser, r_ratio = _compute_trade_metrics(trades)
        assert win_rate == pytest.approx(2 / 3)
        assert r_ratio == 1.0 / 1.0

    def test_r_ratio_calculation(self):
        """Correctly computes R-ratio (avg_winner / avg_loser)."""
        trades = [
            {"pnl": 200.0, "outcome": "winning_trade"},
            {"pnl": -100.0, "outcome": "losing_trade"},
        ]
        win_rate, avg_winner, avg_loser, r_ratio = _compute_trade_metrics(trades)
        assert r_ratio == pytest.approx(2.0)


@pytest.mark.asyncio
class TestGetConfidenceAdjustment:
    """Test the main get_confidence_adjustment function."""

    async def test_returns_1_0_when_db_manager_is_none(self):
        """Returns 1.0 when db_manager is None."""
        result = await get_confidence_adjustment("MES", None)
        assert result == 1.0

    async def test_returns_1_0_when_invalid_symbol(self):
        """Returns 1.0 when symbol is invalid."""
        result = await get_confidence_adjustment("", None)
        assert result == 1.0

        result = await get_confidence_adjustment(None, None)
        assert result == 1.0

    async def test_returns_1_0_on_exception(self):
        """Returns 1.0 and never raises on exception."""
        # Create a bad db_manager that will cause an error
        bad_db = object()  # has no query method

        result = await get_confidence_adjustment("MES", bad_db)
        assert result == 1.0


class TestConfidenceAdjustmentMultiplierClamping:
    """Test that final conviction is properly clamped."""

    def test_conviction_clamping_upper(self):
        """Final conviction clamped to max 0.95."""
        # If initial conviction is 1.0 and multiplier is 1.35, should clamp to 0.95
        initial = 1.0
        multiplier = 1.35
        result = initial * multiplier
        clamped = max(0.05, min(0.95, result))
        assert clamped == 0.95

    def test_conviction_clamping_lower(self):
        """Final conviction clamped to min 0.05."""
        # If initial conviction is 0.06 and multiplier is 0.65, should clamp to 0.05
        initial = 0.06
        multiplier = 0.65
        result = initial * multiplier
        clamped = max(0.05, min(0.95, result))
        assert clamped == 0.05


class _FakeFetchAllDB:
    """Minimal db_manager exposing the sync fetch_all(sql, params) the live
    engine's DatabaseManager (database/manager.py) actually provides — used to
    prove the scorer no longer falls through to the no-op 1.0 multiplier."""

    def __init__(self, rows):
        self._rows = rows
        self.calls = []

    def fetch_all(self, sql, params=()):
        self.calls.append((sql, params))
        return list(self._rows)


@pytest.mark.asyncio
class TestFetchAllPath:
    """The running engine's db_manager exposes fetch_all (not query/query_async).

    Before the fix, _fetch_symbol_trades probed only query/query_async, fell to
    the else branch, logged 'db_manager has no query method', and returned []
    -> every adjustment was a silent 1.0 no-op on real trade history.
    """

    async def test_fetch_all_path_activates_multiplier(self):
        # 20 winning trades -> win_rate 1.0, no losers -> r_ratio 1.0 -> 1.10 boost
        rows = [{"pnl": 100.0} for _ in range(20)]
        db = _FakeFetchAllDB(rows)
        result = await get_confidence_adjustment("MES", db)
        assert result == 1.10
        # Proves it actually used fetch_all, scoped to this symbol's closed trades
        assert db.calls, "fetch_all was never called"
        sql, params = db.calls[0]
        assert "status = 'closed'" in sql
        assert "paper_trades" in sql
        assert params == ("MES",)

    async def test_fetch_all_below_min_trades_returns_1_0(self):
        # Fewer than MIN_TRADES_REQUIRED -> neutral 1.0
        rows = [{"pnl": 100.0} for _ in range(5)]
        db = _FakeFetchAllDB(rows)
        result = await get_confidence_adjustment("MES", db)
        assert result == 1.0

    def test_conviction_clamping_middle(self):
        """Final conviction stays in range when within bounds."""
        initial = 0.50
        multiplier = 1.20
        result = initial * multiplier
        clamped = max(0.05, min(0.95, result))
        assert clamped == pytest.approx(0.60)


class TestConfidenceScenarios:
    """Integration-style tests for realistic scenarios."""

    def test_scenario_strong_symbol(self):
        """Scenario: symbol with 70% win rate and 2.0R ratio."""
        # 20 winning trades, 10 losing trades
        trades = [{"pnl": 200.0, "outcome": "winning_trade"} for _ in range(20)]
        trades += [{"pnl": -100.0, "outcome": "losing_trade"} for _ in range(10)]

        win_rate, avg_winner, avg_loser, r_ratio = _compute_trade_metrics(trades)
        assert win_rate == pytest.approx(2 / 3)
        assert r_ratio == pytest.approx(2.0)
        multiplier = _compute_multiplier(win_rate, r_ratio)
        assert multiplier == 1.35  # strong edge

    def test_scenario_poor_symbol(self):
        """Scenario: symbol with 30% win rate."""
        # 6 winning trades, 14 losing trades
        trades = [{"pnl": 100.0, "outcome": "winning_trade"} for _ in range(6)]
        trades += [{"pnl": -100.0, "outcome": "losing_trade"} for _ in range(14)]

        win_rate, avg_winner, avg_loser, r_ratio = _compute_trade_metrics(trades)
        assert win_rate == pytest.approx(0.30)
        multiplier = _compute_multiplier(win_rate, r_ratio)
        assert multiplier == 0.65  # poor performance discount
