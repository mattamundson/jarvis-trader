"""Capital Path edge-degradation scenario engine.

Historical strategy outcomes are not assumed to persist unchanged.  This module
creates explicit positive-payoff haircuts while leaving losses unchanged, then
reruns the full resampling-model ensemble for every scenario.

A positive-payoff haircut is deliberately asymmetric:
    R > 0  -> haircut * R
    R <= 0 -> R

Scaling *all* R values would also shrink losses and can make a supposedly adverse
scenario safer.  That is not the stress semantics intended here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from backtest.capital_path_core import CapitalPathConfig, RiskPolicy
from backtest.capital_path_ensemble import CapitalPathEnsembleSummary, run_resampling_ensemble
from backtest.capital_path_monte_carlo import MonteCarloSpec


class CapitalPathScenarioError(ValueError):
    """Raised when scenario definitions are invalid."""


@dataclass(frozen=True)
class EdgeScenario:
    name: str
    positive_r_multiplier: float

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise CapitalPathScenarioError("scenario name must be non-empty")
        if not 0.0 <= self.positive_r_multiplier <= 1.0:
            raise CapitalPathScenarioError("positive_r_multiplier must be in [0,1]")


@dataclass(frozen=True)
class EdgeScenarioResult:
    scenario: EdgeScenario
    transformed_empirical_r: tuple[float, ...]
    ensemble: CapitalPathEnsembleSummary


@dataclass(frozen=True)
class CapitalPathScenarioSummary:
    results: dict[str, EdgeScenarioResult]
    conservative_scenario: str
    conservative_success_probability: float
    worst_ruin_probability: float
    worst_max_drawdown_p95: float


def apply_positive_payoff_haircut(
    empirical_r_multiples: Iterable[float],
    multiplier: float,
) -> tuple[float, ...]:
    """Haircut winners while preserving losses exactly."""
    if not 0.0 <= multiplier <= 1.0:
        raise CapitalPathScenarioError("multiplier must be in [0,1]")
    values = tuple(float(value) for value in empirical_r_multiples)
    if len(values) < 2:
        raise CapitalPathScenarioError("at least two empirical R observations are required")
    if any(value != value or value in (float("inf"), float("-inf")) for value in values):
        raise CapitalPathScenarioError("empirical R observations must be finite")
    return tuple(value * multiplier if value > 0.0 else value for value in values)


def run_edge_scenarios(
    empirical_r_multiples: Iterable[float],
    *,
    scenarios: Iterable[EdgeScenario],
    model_specs: Mapping[str, MonteCarloSpec],
    config: CapitalPathConfig | None = None,
    risk_policy: RiskPolicy | None = None,
) -> CapitalPathScenarioSummary:
    """Run every edge-haircut scenario through the same model-risk ensemble."""
    empirical = tuple(float(value) for value in empirical_r_multiples)
    scenario_list = tuple(scenarios)
    if not scenario_list:
        raise CapitalPathScenarioError("at least one scenario is required")
    names = [scenario.name for scenario in scenario_list]
    if len(names) != len(set(names)):
        raise CapitalPathScenarioError("scenario names must be unique")

    results: dict[str, EdgeScenarioResult] = {}
    for scenario in scenario_list:
        transformed = apply_positive_payoff_haircut(
            empirical,
            scenario.positive_r_multiplier,
        )
        ensemble = run_resampling_ensemble(
            transformed,
            model_specs=model_specs,
            config=config,
            risk_policy=risk_policy,
        )
        results[scenario.name] = EdgeScenarioResult(
            scenario=scenario,
            transformed_empirical_r=transformed,
            ensemble=ensemble,
        )

    conservative_scenario = min(
        results,
        key=lambda name: results[name].ensemble.success_probability_min,
    )
    return CapitalPathScenarioSummary(
        results=results,
        conservative_scenario=conservative_scenario,
        conservative_success_probability=(
            results[conservative_scenario].ensemble.success_probability_min
        ),
        worst_ruin_probability=max(
            result.ensemble.ruin_probability_max for result in results.values()
        ),
        worst_max_drawdown_p95=max(
            result.ensemble.max_drawdown_p95_max for result in results.values()
        ),
    )


def default_edge_scenarios() -> tuple[EdgeScenario, ...]:
    """Canonical research stress ladder; not a claim about future degradation."""
    return (
        EdgeScenario("historical_100pct", 1.00),
        EdgeScenario("mild_75pct", 0.75),
        EdgeScenario("conservative_50pct", 0.50),
        EdgeScenario("severe_25pct", 0.25),
        EdgeScenario("positive_edge_removed", 0.00),
    )
