"""Capital Path V1 empirical Monte Carlo with selectable bootstrap geometry.

Every sampled path is fed through the same dynamic R-based Capital Path accounting
engine. Resampling may be IID, fixed moving-block, or stationary bootstrap so
model disagreement can be measured rather than hidden behind one assumption.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from typing import Iterable

import numpy as np

from backtest.capital_path_core import (
    CapitalPathConfig,
    CapitalPathResult,
    RiskPolicy,
    simulate_r_path,
)
from backtest.capital_path_resampling import ResamplingMethod, ResamplingError, resample_indices


class CapitalPathMonteCarloError(ValueError):
    """Raised when Monte Carlo inputs are invalid."""


@dataclass(frozen=True)
class MonteCarloSpec:
    n_paths: int = 10_000
    trades_per_path: int = 1_000
    seed: int = 42
    resampling_method: ResamplingMethod = "iid"
    block_size: int | None = None
    expected_block_length: float | None = None

    def __post_init__(self) -> None:
        if self.n_paths < 1:
            raise CapitalPathMonteCarloError("n_paths must be >= 1")
        if self.trades_per_path < 1:
            raise CapitalPathMonteCarloError("trades_per_path must be >= 1")
        if self.resampling_method not in {"iid", "moving_block", "stationary"}:
            raise CapitalPathMonteCarloError(
                f"unknown resampling_method: {self.resampling_method}"
            )
        if self.resampling_method == "moving_block" and self.block_size is None:
            raise CapitalPathMonteCarloError("moving_block requires block_size")
        if self.resampling_method == "stationary" and self.expected_block_length is None:
            raise CapitalPathMonteCarloError(
                "stationary requires expected_block_length"
            )


@dataclass(frozen=True)
class QuantileSummary:
    p05: float
    p25: float
    median: float
    p75: float
    p95: float


@dataclass(frozen=True)
class CapitalPathMonteCarloSummary:
    n_paths: int
    trades_per_path: int
    empirical_sample_size: int
    seed: int
    resampling_method: ResamplingMethod
    block_size: int | None
    expected_block_length: float | None
    success_probability: float
    ruin_probability: float
    halt_probability: float
    exhausted_probability: float
    success_probability_mc_se: float
    milestone_probabilities: dict[float, float]
    target_time_conditional: QuantileSummary | None
    max_drawdown: QuantileSummary
    terminal_equity: QuantileSummary
    minimum_equity: QuantileSummary


@dataclass(frozen=True)
class CapitalPathMonteCarloResult:
    summary: CapitalPathMonteCarloSummary
    paths: tuple[CapitalPathResult, ...]


def _quantiles(values: Iterable[float]) -> QuantileSummary:
    array = np.asarray(list(values), dtype=float)
    if len(array) == 0:
        raise CapitalPathMonteCarloError("cannot summarize empty values")
    return QuantileSummary(
        p05=float(np.percentile(array, 5)),
        p25=float(np.percentile(array, 25)),
        median=float(np.percentile(array, 50)),
        p75=float(np.percentile(array, 75)),
        p95=float(np.percentile(array, 95)),
    )


def run_empirical_bootstrap(
    empirical_r_multiples: Iterable[float],
    *,
    config: CapitalPathConfig | None = None,
    risk_policy: RiskPolicy | None = None,
    spec: MonteCarloSpec | None = None,
    retain_paths: bool = True,
) -> CapitalPathMonteCarloResult:
    """Bootstrap empirical net-R paths and apply dynamic Capital Path accounting."""
    empirical = np.asarray(list(empirical_r_multiples), dtype=float)
    if len(empirical) < 2:
        raise CapitalPathMonteCarloError("at least two empirical R observations are required")
    if not np.isfinite(empirical).all():
        raise CapitalPathMonteCarloError("empirical R observations must be finite")

    cfg = config or CapitalPathConfig()
    policy = risk_policy or RiskPolicy()
    mc = spec or MonteCarloSpec()
    rng = np.random.default_rng(mc.seed)
    paths: list[CapitalPathResult] = []

    try:
        for _ in range(mc.n_paths):
            sample_indices = resample_indices(
                mc.resampling_method,
                len(empirical),
                mc.trades_per_path,
                rng,
                block_size=mc.block_size,
                expected_block_length=mc.expected_block_length,
            )
            sampled_r = empirical[sample_indices]
            paths.append(simulate_r_path(sampled_r, config=cfg, risk_policy=policy))
    except ResamplingError as exc:
        raise CapitalPathMonteCarloError(str(exc)) from exc

    success = np.asarray([path.terminal_state == "SUCCESS" for path in paths], dtype=bool)
    ruin = np.asarray([path.terminal_state == "RUIN" for path in paths], dtype=bool)
    halted = np.asarray([path.terminal_state == "HALTED" for path in paths], dtype=bool)
    exhausted = np.asarray([path.terminal_state == "EXHAUSTED" for path in paths], dtype=bool)
    success_probability = float(np.mean(success))
    mc_se = sqrt(success_probability * (1.0 - success_probability) / mc.n_paths)

    milestones = tuple(sorted(set(cfg.milestones + (cfg.target_equity,))))
    milestone_probabilities = {
        milestone: float(
            np.mean(
                [
                    path.milestone_first_passage.get(milestone) is not None
                    for path in paths
                ]
            )
        )
        for milestone in milestones
    }

    target_times = [
        float(path.target_first_passage_trade)
        for path in paths
        if path.target_first_passage_trade is not None
    ]
    target_time_summary = _quantiles(target_times) if target_times else None

    summary = CapitalPathMonteCarloSummary(
        n_paths=mc.n_paths,
        trades_per_path=mc.trades_per_path,
        empirical_sample_size=len(empirical),
        seed=mc.seed,
        resampling_method=mc.resampling_method,
        block_size=mc.block_size,
        expected_block_length=mc.expected_block_length,
        success_probability=success_probability,
        ruin_probability=float(np.mean(ruin)),
        halt_probability=float(np.mean(halted)),
        exhausted_probability=float(np.mean(exhausted)),
        success_probability_mc_se=mc_se,
        milestone_probabilities=milestone_probabilities,
        target_time_conditional=target_time_summary,
        max_drawdown=_quantiles(path.max_drawdown for path in paths),
        terminal_equity=_quantiles(path.terminal_equity for path in paths),
        minimum_equity=_quantiles(path.minimum_equity for path in paths),
    )
    retained = tuple(paths) if retain_paths else tuple()
    return CapitalPathMonteCarloResult(summary=summary, paths=retained)
