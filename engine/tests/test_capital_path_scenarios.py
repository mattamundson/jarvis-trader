"""Tests for Capital Path edge-degradation scenarios."""

from __future__ import annotations

import pytest

from backtest.capital_path_core import CapitalPathConfig, RiskPolicy
from backtest.capital_path_monte_carlo import MonteCarloSpec
from backtest.capital_path_scenarios import (
    CapitalPathScenarioError,
    EdgeScenario,
    apply_positive_payoff_haircut,
    default_edge_scenarios,
    run_edge_scenarios,
)


def _models() -> dict[str, MonteCarloSpec]:
    return {
        "iid": MonteCarloSpec(
            n_paths=200, trades_per_path=50, seed=17, resampling_method="iid"
        ),
        "moving": MonteCarloSpec(
            n_paths=200,
            trades_per_path=50,
            seed=17,
            resampling_method="moving_block",
            block_size=3,
        ),
        "stationary": MonteCarloSpec(
            n_paths=200,
            trades_per_path=50,
            seed=17,
            resampling_method="stationary",
            expected_block_length=3.0,
        ),
    }


def _config() -> CapitalPathConfig:
    return CapitalPathConfig(
        start_equity=100.0,
        target_equity=170.0,
        milestones=(120.0, 170.0),
        ruin_drawdown=0.35,
    )


def _policy() -> RiskPolicy:
    return RiskPolicy(base_risk_fraction=0.05, drawdown_bands=(), halt_drawdown=None)


def test_haircut_preserves_losses_and_scales_only_winners() -> None:
    transformed = apply_positive_payoff_haircut([-2.0, -1.0, 0.0, 1.0, 4.0], 0.5)
    assert transformed == (-2.0, -1.0, 0.0, 0.5, 2.0)


def test_invalid_multiplier_and_degenerate_sample_fail_closed() -> None:
    with pytest.raises(CapitalPathScenarioError, match="multiplier"):
        apply_positive_payoff_haircut([-1.0, 1.0], 1.1)
    with pytest.raises(CapitalPathScenarioError, match="at least two"):
        apply_positive_payoff_haircut([1.0], 0.5)
    with pytest.raises(CapitalPathScenarioError, match="finite"):
        apply_positive_payoff_haircut([1.0, float("nan")], 0.5)


def test_default_scenario_ladder_is_monotonic_in_edge_multiplier() -> None:
    multipliers = [scenario.positive_r_multiplier for scenario in default_edge_scenarios()]
    assert multipliers == sorted(multipliers, reverse=True)
    assert multipliers[0] == 1.0
    assert multipliers[-1] == 0.0


def test_scenario_success_does_not_improve_when_positive_edge_is_haircut() -> None:
    summary = run_edge_scenarios(
        [-1.0, -1.0, -0.5, 0.5, 1.0, 2.0, 3.0, -1.0, 2.5, 1.5],
        scenarios=(
            EdgeScenario("full", 1.0),
            EdgeScenario("half", 0.5),
            EdgeScenario("zero", 0.0),
        ),
        model_specs=_models(),
        config=_config(),
        risk_policy=_policy(),
    )
    success = [
        summary.results[name].ensemble.success_probability_min
        for name in ("full", "half", "zero")
    ]
    assert success[0] >= success[1] >= success[2]
    assert summary.conservative_scenario == "zero"
    assert summary.conservative_success_probability == success[-1]


def test_duplicate_or_empty_scenarios_fail_closed() -> None:
    kwargs = dict(
        empirical_r_multiples=[-1.0, 1.0, 2.0],
        model_specs=_models(),
        config=_config(),
        risk_policy=_policy(),
    )
    with pytest.raises(CapitalPathScenarioError, match="at least one"):
        run_edge_scenarios(scenarios=(), **kwargs)
    with pytest.raises(CapitalPathScenarioError, match="unique"):
        run_edge_scenarios(
            scenarios=(EdgeScenario("same", 1.0), EdgeScenario("same", 0.5)),
            **kwargs,
        )
