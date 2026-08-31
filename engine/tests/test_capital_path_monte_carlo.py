"""Tests for empirical-bootstrap Capital Path Monte Carlo."""

from __future__ import annotations

import pytest

from backtest.capital_path_core import CapitalPathConfig, RiskPolicy
from backtest.capital_path_monte_carlo import (
    CapitalPathMonteCarloError,
    MonteCarloSpec,
    run_empirical_bootstrap,
)


def _policy() -> RiskPolicy:
    return RiskPolicy(base_risk_fraction=0.10, drawdown_bands=(), halt_drawdown=None)


def test_all_winner_distribution_has_certain_success_and_deterministic_time() -> None:
    result = run_empirical_bootstrap(
        [1.0, 1.0],
        config=CapitalPathConfig(
            start_equity=100,
            target_equity=200,
            milestones=(150.0, 200.0),
            ruin_drawdown=None,
        ),
        risk_policy=_policy(),
        spec=MonteCarloSpec(n_paths=100, trades_per_path=20, seed=7),
    )
    summary = result.summary
    assert summary.success_probability == 1.0
    assert summary.ruin_probability == 0.0
    assert summary.success_probability_mc_se == 0.0
    assert summary.milestone_probabilities[150.0] == 1.0
    assert summary.milestone_probabilities[200.0] == 1.0
    assert summary.target_time_conditional is not None
    assert summary.target_time_conditional.p05 == summary.target_time_conditional.p95


def test_all_loser_distribution_hits_ruin_before_target() -> None:
    result = run_empirical_bootstrap(
        [-1.0, -1.0],
        config=CapitalPathConfig(
            start_equity=100,
            target_equity=200,
            milestones=(150.0, 200.0),
            ruin_drawdown=0.20,
        ),
        risk_policy=_policy(),
        spec=MonteCarloSpec(n_paths=50, trades_per_path=20, seed=11),
    )
    summary = result.summary
    assert summary.success_probability == 0.0
    assert summary.ruin_probability == 1.0
    assert summary.target_time_conditional is None
    assert summary.milestone_probabilities[150.0] == 0.0


def test_seed_reproduces_pathwise_results_exactly() -> None:
    kwargs = dict(
        empirical_r_multiples=[-1.0, -0.5, 1.0, 2.0, 3.0],
        config=CapitalPathConfig(
            start_equity=100,
            target_equity=180,
            milestones=(130.0, 180.0),
            ruin_drawdown=0.40,
        ),
        risk_policy=RiskPolicy(base_risk_fraction=0.05, drawdown_bands=(), halt_drawdown=None),
        spec=MonteCarloSpec(n_paths=200, trades_per_path=40, seed=1234),
    )
    first = run_empirical_bootstrap(**kwargs)
    second = run_empirical_bootstrap(**kwargs)
    assert first.summary == second.summary
    assert first.paths == second.paths


def test_milestone_probabilities_are_nonincreasing_with_higher_targets() -> None:
    result = run_empirical_bootstrap(
        [-1.0, 0.5, 1.0, 2.0],
        config=CapitalPathConfig(
            start_equity=100,
            target_equity=200,
            milestones=(120.0, 150.0, 200.0),
            ruin_drawdown=0.50,
        ),
        risk_policy=RiskPolicy(base_risk_fraction=0.05, drawdown_bands=(), halt_drawdown=None),
        spec=MonteCarloSpec(n_paths=500, trades_per_path=30, seed=4),
    )
    p = result.summary.milestone_probabilities
    assert p[120.0] >= p[150.0] >= p[200.0]


def test_terminal_state_probabilities_sum_to_one() -> None:
    result = run_empirical_bootstrap(
        [-2.0, -1.0, 1.0, 4.0],
        config=CapitalPathConfig(
            start_equity=100,
            target_equity=250,
            milestones=(250.0,),
            ruin_drawdown=0.30,
        ),
        risk_policy=RiskPolicy(base_risk_fraction=0.05),
        spec=MonteCarloSpec(n_paths=300, trades_per_path=50, seed=8),
    )
    s = result.summary
    total = s.success_probability + s.ruin_probability + s.halt_probability + s.exhausted_probability
    assert total == pytest.approx(1.0)


def test_paths_can_be_dropped_after_streaming_summary() -> None:
    result = run_empirical_bootstrap(
        [-1.0, 1.0],
        config=CapitalPathConfig(
            start_equity=100,
            target_equity=200,
            milestones=(200.0,),
            ruin_drawdown=0.50,
        ),
        risk_policy=RiskPolicy(base_risk_fraction=0.01, drawdown_bands=(), halt_drawdown=None),
        spec=MonteCarloSpec(n_paths=20, trades_per_path=10, seed=1),
        retain_paths=False,
    )
    assert result.paths == ()
    assert result.summary.n_paths == 20


def test_degenerate_or_nonfinite_empirical_sample_fails_closed() -> None:
    with pytest.raises(CapitalPathMonteCarloError, match="at least two"):
        run_empirical_bootstrap([1.0])
    with pytest.raises(CapitalPathMonteCarloError, match="finite"):
        run_empirical_bootstrap([1.0, float("nan")])
