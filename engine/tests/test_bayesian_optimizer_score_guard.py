"""Regression: BayesianOptimizer scorer must never reward net-losing strategies.

Roadmap Phase 1 Task S2. Before the 2026-04-20 fix, `_score_result` computed
`max(sharpe, 0) * min(pf, 20)` with no PF floor, so any strategy where the
per-period sharpe happened to be positive could score positive even with
profit_factor < 1.0 (net-losing). The optimizer would then steer toward
money-losing regions of the search space.

This file fuzzes the scorer across wide PF/Sharpe ranges and asserts the
invariant: PF < 1.0 implies score <= 0, strictly.
"""

import os
import sys
from dataclasses import dataclass

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.bayesian_optimizer import (  # noqa: E402
    _LOSING_STRATEGY_PENALTY,
    _NO_TRADE_PENALTY,
    MIN_TRADES_FOR_SCORE,
    _score_result,
)


@dataclass
class FakeResult:
    """Duck-typed BacktestResult for scorer unit tests."""
    profit_factor: float
    sharpe_ratio: float
    total_trades: int = 50
    win_rate: float = 0.5


def test_score_result_none_returns_no_trade_penalty():
    assert _score_result(None) == _NO_TRADE_PENALTY


def test_score_result_insufficient_trades_returns_no_trade_penalty():
    result = FakeResult(profit_factor=5.0, sharpe_ratio=3.0, total_trades=MIN_TRADES_FOR_SCORE - 1)
    assert _score_result(result) == _NO_TRADE_PENALTY


def test_no_trade_penalty_worse_than_losing_strategy():
    """Key invariant: zero-trade regions must score below any PF<1 run (closes escape hatch)."""
    assert _NO_TRADE_PENALTY < _LOSING_STRATEGY_PENALTY


def test_score_result_profitable_strategy_scores_positive():
    result = FakeResult(profit_factor=2.0, sharpe_ratio=1.5)
    score = _score_result(result)
    assert score == pytest.approx(2.0 * 1.5)
    assert score > 0


def test_score_result_sharpe_floor_clamps_negative_to_zero():
    # Sharpe negative but PF still >= 1.0 → score floored at 0, not penalized.
    result = FakeResult(profit_factor=1.0, sharpe_ratio=-0.5)
    assert _score_result(result) == 0.0


def test_score_result_pf_below_one_penalized_hard():
    result = FakeResult(profit_factor=0.99, sharpe_ratio=2.5)
    assert _score_result(result) == _LOSING_STRATEGY_PENALTY


def test_score_result_pf_exactly_one_is_neutral_not_penalized():
    # PF == 1.0 means break-even (sum wins == sum losses), not net-losing.
    # The gate is strict `<`, so exactly 1.0 falls through to normal scoring.
    result = FakeResult(profit_factor=1.0, sharpe_ratio=0.5)
    assert _score_result(result) == pytest.approx(0.5 * 1.0)


@pytest.mark.parametrize("pf", [0.01, 0.3, 0.5, 0.75, 0.9, 0.99, 0.999])
@pytest.mark.parametrize("sharpe", [-5.0, -0.1, 0.0, 0.5, 2.0, 10.0, 100.0])
def test_fuzz_pf_lt_one_always_penalized(pf, sharpe):
    """Across wide sharpe/PF grid, PF<1 must never score higher than 0."""
    result = FakeResult(profit_factor=pf, sharpe_ratio=sharpe)
    score = _score_result(result)
    assert score <= 0, f"PF={pf} sharpe={sharpe} scored {score} > 0 — PF gate broken"
    assert score == _LOSING_STRATEGY_PENALTY


@pytest.mark.parametrize("pf", [1.0, 1.01, 1.5, 2.5, 10.0, 19.0, 20.0, 25.0, 999.0])
@pytest.mark.parametrize("sharpe", [0.0, 0.1, 1.0, 3.0, 10.0])
def test_fuzz_pf_gte_one_scores_non_negative_and_bounded(pf, sharpe):
    result = FakeResult(profit_factor=pf, sharpe_ratio=sharpe)
    score = _score_result(result)
    assert score >= 0
    # With caps sharpe>=0 and pf capped at 20, score is bounded:
    assert score <= max(sharpe, 0.0) * 20.0 + 1e-9


def test_penalty_is_worse_than_any_realistic_winning_score():
    """Guarantee the penalty is lower than any PF>=1 result the optimizer could find."""
    best_possible_winner = FakeResult(profit_factor=20.0, sharpe_ratio=10.0)
    assert _score_result(best_possible_winner) > _LOSING_STRATEGY_PENALTY

    worst_loser = FakeResult(profit_factor=0.01, sharpe_ratio=5.0)
    assert _score_result(worst_loser) < _score_result(best_possible_winner)
