"""Tests for Capital Path risk-policy frontier evaluation."""

from __future__ import annotations

import pytest

from backtest.capital_path_core import CapitalPathConfig, RiskPolicy
from backtest.capital_path_monte_carlo import MonteCarloSpec
from backtest.capital_path_risk_frontier import (
    CapitalPathRiskFrontierError,
    RiskPolicyCandidate,
    evaluate_risk_policy_frontier,
)
from backtest.capital_path_scenarios import EdgeScenario


def _models() -> dict[str, MonteCarloSpec]:
    return {
        "iid": MonteCarloSpec(
            n_paths=150, trades_per_path=30, seed=23, resampling_method="iid"
        ),
        "moving": MonteCarloSpec(
            n_paths=150,
            trades_per_path=30,
            seed=23,
            resampling_method="moving_block",
            block_size=2,
        ),
    }


def test_requires_multiple_unique_policy_candidates() -> None:
    common = dict(
        empirical_r_multiples=[-1.0, 1.0, 2.0],
        scenarios=(EdgeScenario("full", 1.0),),
        model_specs=_models(),
        config=CapitalPathConfig(
            start_equity=100.0,
            target_equity=150.0,
            milestones=(150.0,),
            ruin_drawdown=0.30,
        ),
    )
    with pytest.raises(CapitalPathRiskFrontierError, match="at least two"):
        evaluate_risk_policy_frontier(
            policies=(RiskPolicyCandidate("only", RiskPolicy(base_risk_fraction=0.05)),),
            **common,
        )
    with pytest.raises(CapitalPathRiskFrontierError, match="unique"):
        evaluate_risk_policy_frontier(
            policies=(
                RiskPolicyCandidate("dup", RiskPolicy(base_risk_fraction=0.03)),
                RiskPolicyCandidate("dup", RiskPolicy(base_risk_fraction=0.05)),
            ),
            **common,
        )


def test_lower_risk_dominates_when_no_upside_exists() -> None:
    result = evaluate_risk_policy_frontier(
        [-1.0, 0.0],
        policies=(
            RiskPolicyCandidate(
                "low",
                RiskPolicy(base_risk_fraction=0.01, drawdown_bands=(), halt_drawdown=None),
            ),
            RiskPolicyCandidate(
                "high",
                RiskPolicy(base_risk_fraction=0.10, drawdown_bands=(), halt_drawdown=None),
            ),
        ),
        scenarios=(EdgeScenario("no_upside", 0.0),),
        model_specs=_models(),
        config=CapitalPathConfig(
            start_equity=100.0,
            target_equity=200.0,
            milestones=(200.0,),
            ruin_drawdown=None,
        ),
    )
    metrics = {metric.policy_id: metric for metric in result.metrics}
    assert metrics["low"].conservative_success_probability == 0.0
    assert metrics["high"].conservative_success_probability == 0.0
    assert metrics["low"].worst_ruin_probability == 0.0
    assert metrics["high"].worst_ruin_probability == 0.0
    assert metrics["low"].worst_max_drawdown_p95 < metrics["high"].worst_max_drawdown_p95
    assert metrics["low"].pareto_efficient is True
    assert metrics["high"].pareto_efficient is False
    assert result.pareto_policy_ids == ("low",)


def test_frontier_reports_conservative_scenario_model_and_time() -> None:
    result = evaluate_risk_policy_frontier(
        [-1.0, -0.5, 0.5, 1.0, 2.0, 3.0],
        policies=(
            RiskPolicyCandidate(
                "conservative",
                RiskPolicy(base_risk_fraction=0.03, drawdown_bands=(), halt_drawdown=None),
            ),
            RiskPolicyCandidate(
                "aggressive",
                RiskPolicy(base_risk_fraction=0.08, drawdown_bands=(), halt_drawdown=None),
            ),
        ),
        scenarios=(EdgeScenario("full", 1.0), EdgeScenario("half", 0.5)),
        model_specs=_models(),
        config=CapitalPathConfig(
            start_equity=100.0,
            target_equity=150.0,
            milestones=(120.0, 150.0),
            ruin_drawdown=0.35,
        ),
    )
    assert len(result.metrics) == 2
    assert result.pareto_policy_ids
    for metric in result.metrics:
        assert metric.conservative_scenario in {"full", "half"}
        assert metric.conservative_model in {"iid", "moving"}
        assert 0.0 <= metric.conservative_success_probability <= 1.0
        assert 0.0 <= metric.worst_ruin_probability <= 1.0
        assert 0.0 <= metric.worst_max_drawdown_p95 <= 1.0
        if metric.median_target_time_conditional is not None:
            assert metric.median_target_time_conditional >= 1.0


def test_empty_scenario_set_fails_closed() -> None:
    with pytest.raises(CapitalPathRiskFrontierError, match="edge scenario"):
        evaluate_risk_policy_frontier(
            [-1.0, 1.0],
            policies=(
                RiskPolicyCandidate("a", RiskPolicy(base_risk_fraction=0.03)),
                RiskPolicyCandidate("b", RiskPolicy(base_risk_fraction=0.05)),
            ),
            scenarios=(),
            model_specs=_models(),
            config=CapitalPathConfig(
                start_equity=100.0,
                target_equity=150.0,
                milestones=(150.0,),
                ruin_drawdown=0.30,
            ),
        )
