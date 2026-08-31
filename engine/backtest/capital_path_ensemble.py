"""Model-risk ensemble for Capital Path bootstrap forecasts."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Iterable, Mapping

from backtest.capital_path_core import CapitalPathConfig, RiskPolicy
from backtest.capital_path_monte_carlo import (
    CapitalPathMonteCarloSummary,
    MonteCarloSpec,
    run_empirical_bootstrap,
)


class CapitalPathEnsembleError(ValueError):
    """Raised when a model-risk ensemble is not meaningfully specified."""


@dataclass(frozen=True)
class CapitalPathEnsembleSummary:
    model_summaries: dict[str, CapitalPathMonteCarloSummary]
    success_probability_min: float
    success_probability_median: float
    success_probability_max: float
    success_probability_spread: float
    ruin_probability_max: float
    max_drawdown_p95_max: float
    conservative_model: str
    optimistic_model: str


def run_resampling_ensemble(
    empirical_r_multiples: Iterable[float],
    *,
    model_specs: Mapping[str, MonteCarloSpec],
    config: CapitalPathConfig | None = None,
    risk_policy: RiskPolicy | None = None,
) -> CapitalPathEnsembleSummary:
    """Run several bootstrap geometries and summarize model disagreement.

    ``success_probability_min`` is deliberately exposed as a conservative model
    bound, not a calibrated confidence limit. Large spread is model-risk evidence
    that should reduce forecast credibility rather than be averaged away.
    """
    if len(model_specs) < 2:
        raise CapitalPathEnsembleError("at least two model specifications are required")
    if any(not name.strip() for name in model_specs):
        raise CapitalPathEnsembleError("model names must be non-empty")

    empirical = tuple(float(value) for value in empirical_r_multiples)
    summaries: dict[str, CapitalPathMonteCarloSummary] = {}
    for name, spec in model_specs.items():
        summaries[name] = run_empirical_bootstrap(
            empirical,
            config=config,
            risk_policy=risk_policy,
            spec=spec,
            retain_paths=False,
        ).summary

    success_by_model = {
        name: summary.success_probability for name, summary in summaries.items()
    }
    min_success = min(success_by_model.values())
    max_success = max(success_by_model.values())
    conservative_model = min(success_by_model, key=success_by_model.get)
    optimistic_model = max(success_by_model, key=success_by_model.get)

    return CapitalPathEnsembleSummary(
        model_summaries=summaries,
        success_probability_min=min_success,
        success_probability_median=float(median(success_by_model.values())),
        success_probability_max=max_success,
        success_probability_spread=max_success - min_success,
        ruin_probability_max=max(summary.ruin_probability for summary in summaries.values()),
        max_drawdown_p95_max=max(summary.max_drawdown.p95 for summary in summaries.values()),
        conservative_model=conservative_model,
        optimistic_model=optimistic_model,
    )
