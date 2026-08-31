"""Tests for Capital Path model-risk ensemble aggregation."""

from __future__ import annotations

import pytest

from backtest.capital_path_core import CapitalPathConfig, RiskPolicy
from backtest.capital_path_ensemble import CapitalPathEnsembleError, run_resampling_ensemble
from backtest.capital_path_monte_carlo import MonteCarloSpec


def _config() -> CapitalPathConfig:
    return CapitalPathConfig(
        start_equity=100.0,
        target_equity=160.0,
        milestones=(120.0, 160.0),
        ruin_drawdown=0.35,
    )


def _policy() -> RiskPolicy:
    return RiskPolicy(base_risk_fraction=0.05, drawdown_bands=(), halt_drawdown=None)


def test_requires_at_least_two_models() -> None:
    with pytest.raises(CapitalPathEnsembleError, match="at least two"):
        run_resampling_ensemble(
            [-1.0, 1.0, 2.0],
            model_specs={"iid": MonteCarloSpec(n_paths=10, trades_per_path=20)},
            config=_config(),
            risk_policy=_policy(),
        )


def test_all_winner_sample_collapses_model_risk_to_zero() -> None:
    ensemble = run_resampling_ensemble(
        [1.0, 1.0, 1.0, 1.0],
        model_specs={
            "iid": MonteCarloSpec(
                n_paths=50, trades_per_path=20, seed=1, resampling_method="iid"
            ),
            "moving": MonteCarloSpec(
                n_paths=50,
                trades_per_path=20,
                seed=1,
                resampling_method="moving_block",
                block_size=2,
            ),
            "stationary": MonteCarloSpec(
                n_paths=50,
                trades_per_path=20,
                seed=1,
                resampling_method="stationary",
                expected_block_length=2.0,
            ),
        },
        config=_config(),
        risk_policy=_policy(),
    )
    assert ensemble.success_probability_min == 1.0
    assert ensemble.success_probability_median == 1.0
    assert ensemble.success_probability_max == 1.0
    assert ensemble.success_probability_spread == 0.0
    assert ensemble.ruin_probability_max == 0.0


def test_summary_bounds_match_underlying_model_summaries() -> None:
    ensemble = run_resampling_ensemble(
        [-2.0, -1.0, -0.5, 0.5, 1.0, 2.0, 3.0, -1.0, -1.0, 2.5],
        model_specs={
            "iid": MonteCarloSpec(
                n_paths=250, trades_per_path=50, seed=7, resampling_method="iid"
            ),
            "moving": MonteCarloSpec(
                n_paths=250,
                trades_per_path=50,
                seed=7,
                resampling_method="moving_block",
                block_size=3,
            ),
            "stationary": MonteCarloSpec(
                n_paths=250,
                trades_per_path=50,
                seed=7,
                resampling_method="stationary",
                expected_block_length=3.0,
            ),
        },
        config=_config(),
        risk_policy=_policy(),
    )
    success = {
        name: summary.success_probability
        for name, summary in ensemble.model_summaries.items()
    }
    assert ensemble.success_probability_min == min(success.values())
    assert ensemble.success_probability_max == max(success.values())
    assert ensemble.success_probability_spread == pytest.approx(
        max(success.values()) - min(success.values())
    )
    assert success[ensemble.conservative_model] == ensemble.success_probability_min
    assert success[ensemble.optimistic_model] == ensemble.success_probability_max
    assert ensemble.ruin_probability_max == max(
        summary.ruin_probability for summary in ensemble.model_summaries.values()
    )
    assert ensemble.max_drawdown_p95_max == max(
        summary.max_drawdown.p95 for summary in ensemble.model_summaries.values()
    )


def test_empty_model_name_fails_closed() -> None:
    with pytest.raises(CapitalPathEnsembleError, match="non-empty"):
        run_resampling_ensemble(
            [-1.0, 1.0, 2.0],
            model_specs={
                "": MonteCarloSpec(n_paths=10, trades_per_path=20),
                "iid": MonteCarloSpec(n_paths=10, trades_per_path=20),
            },
            config=_config(),
            risk_policy=_policy(),
        )
