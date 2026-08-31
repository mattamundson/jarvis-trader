"""Risk-policy frontier evaluation for Capital Path.

Policies are compared on conservative success probability and adverse risk
statistics across edge-degradation scenarios and resampling models.  The module
reports a Pareto frontier; it does not autonomously change production risk.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from backtest.capital_path_core import CapitalPathConfig, RiskPolicy
from backtest.capital_path_monte_carlo import MonteCarloSpec
from backtest.capital_path_scenarios import (
    CapitalPathScenarioSummary,
    EdgeScenario,
    run_edge_scenarios,
)


class CapitalPathRiskFrontierError(ValueError):
    """Raised when risk-policy comparison inputs are invalid."""


@dataclass(frozen=True)
class RiskPolicyCandidate:
    policy_id: str
    policy: RiskPolicy

    def __post_init__(self) -> None:
        if not self.policy_id.strip():
            raise CapitalPathRiskFrontierError("policy_id must be non-empty")


@dataclass(frozen=True)
class RiskPolicyMetrics:
    policy_id: str
    conservative_success_probability: float
    worst_ruin_probability: float
    worst_max_drawdown_p95: float
    conservative_scenario: str
    conservative_model: str
    median_target_time_conditional: float | None
    pareto_efficient: bool


@dataclass(frozen=True)
class RiskPolicyFrontierResult:
    metrics: tuple[RiskPolicyMetrics, ...]
    pareto_policy_ids: tuple[str, ...]
    scenario_results: dict[str, CapitalPathScenarioSummary]


def _dominates(left: RiskPolicyMetrics, right: RiskPolicyMetrics) -> bool:
    """True when left is no worse on all primary objectives and better on one."""
    no_worse = (
        left.conservative_success_probability >= right.conservative_success_probability
        and left.worst_ruin_probability <= right.worst_ruin_probability
        and left.worst_max_drawdown_p95 <= right.worst_max_drawdown_p95
    )
    strictly_better = (
        left.conservative_success_probability > right.conservative_success_probability
        or left.worst_ruin_probability < right.worst_ruin_probability
        or left.worst_max_drawdown_p95 < right.worst_max_drawdown_p95
    )
    return no_worse and strictly_better


def evaluate_risk_policy_frontier(
    empirical_r_multiples: Iterable[float],
    *,
    policies: Iterable[RiskPolicyCandidate],
    scenarios: Iterable[EdgeScenario],
    model_specs: Mapping[str, MonteCarloSpec],
    config: CapitalPathConfig | None = None,
) -> RiskPolicyFrontierResult:
    """Evaluate policies under identical scenario/model assumptions.

    Pareto efficiency uses three explicit primary objectives:
    - maximize conservative success probability;
    - minimize worst modeled ruin probability;
    - minimize worst modeled p95 maximum drawdown.

    Conditional time-to-target is reported for interpretation but is not allowed
    to compensate for worse survival/risk in the frontier calculation.
    """
    policy_list = tuple(policies)
    if len(policy_list) < 2:
        raise CapitalPathRiskFrontierError("at least two risk policies are required")
    ids = [candidate.policy_id for candidate in policy_list]
    if len(ids) != len(set(ids)):
        raise CapitalPathRiskFrontierError("policy_id values must be unique")

    scenario_list = tuple(scenarios)
    if not scenario_list:
        raise CapitalPathRiskFrontierError("at least one edge scenario is required")
    empirical = tuple(float(value) for value in empirical_r_multiples)

    scenario_results: dict[str, CapitalPathScenarioSummary] = {}
    provisional: list[RiskPolicyMetrics] = []
    for candidate in policy_list:
        result = run_edge_scenarios(
            empirical,
            scenarios=scenario_list,
            model_specs=model_specs,
            config=config,
            risk_policy=candidate.policy,
        )
        scenario_results[candidate.policy_id] = result
        conservative = result.results[result.conservative_scenario].ensemble
        conservative_model = conservative.conservative_model
        target_time = conservative.model_summaries[conservative_model].target_time_conditional
        provisional.append(
            RiskPolicyMetrics(
                policy_id=candidate.policy_id,
                conservative_success_probability=result.conservative_success_probability,
                worst_ruin_probability=result.worst_ruin_probability,
                worst_max_drawdown_p95=result.worst_max_drawdown_p95,
                conservative_scenario=result.conservative_scenario,
                conservative_model=conservative_model,
                median_target_time_conditional=(
                    None if target_time is None else target_time.median
                ),
                pareto_efficient=False,
            )
        )

    metrics: list[RiskPolicyMetrics] = []
    for candidate in provisional:
        efficient = not any(
            _dominates(other, candidate)
            for other in provisional
            if other.policy_id != candidate.policy_id
        )
        metrics.append(
            RiskPolicyMetrics(
                **{
                    **candidate.__dict__,
                    "pareto_efficient": efficient,
                }
            )
        )

    pareto_ids = tuple(metric.policy_id for metric in metrics if metric.pareto_efficient)
    return RiskPolicyFrontierResult(
        metrics=tuple(metrics),
        pareto_policy_ids=pareto_ids,
        scenario_results=scenario_results,
    )
