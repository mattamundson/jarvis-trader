"""Integration tests for Capital Path dependence-preserving resampling modes."""

from __future__ import annotations

from backtest.capital_path_core import CapitalPathConfig, RiskPolicy
from backtest.capital_path_monte_carlo import MonteCarloSpec, run_empirical_bootstrap


CONFIG = CapitalPathConfig(
    start_equity=100,
    target_equity=200,
    milestones=(150.0, 200.0),
    ruin_drawdown=0.40,
)
POLICY = RiskPolicy(base_risk_fraction=0.05, drawdown_bands=(), halt_drawdown=None)
EMPIRICAL = [-1.0, -1.0, -0.5, 0.25, 1.0, 2.0, 3.0, -0.75]


def test_moving_block_mode_is_reproducible_and_reported() -> None:
    spec = MonteCarloSpec(
        n_paths=100,
        trades_per_path=40,
        seed=99,
        resampling_method="moving_block",
        block_size=3,
    )
    first = run_empirical_bootstrap(EMPIRICAL, config=CONFIG, risk_policy=POLICY, spec=spec)
    second = run_empirical_bootstrap(EMPIRICAL, config=CONFIG, risk_policy=POLICY, spec=spec)
    assert first == second
    assert first.summary.resampling_method == "moving_block"
    assert first.summary.block_size == 3


def test_stationary_mode_is_reproducible_and_reported() -> None:
    spec = MonteCarloSpec(
        n_paths=100,
        trades_per_path=40,
        seed=77,
        resampling_method="stationary",
        expected_block_length=3.5,
    )
    first = run_empirical_bootstrap(EMPIRICAL, config=CONFIG, risk_policy=POLICY, spec=spec)
    second = run_empirical_bootstrap(EMPIRICAL, config=CONFIG, risk_policy=POLICY, spec=spec)
    assert first == second
    assert first.summary.resampling_method == "stationary"
    assert first.summary.expected_block_length == 3.5


def test_different_resampling_assumptions_can_produce_different_forecasts() -> None:
    iid = run_empirical_bootstrap(
        EMPIRICAL,
        config=CONFIG,
        risk_policy=POLICY,
        spec=MonteCarloSpec(n_paths=500, trades_per_path=50, seed=21),
    ).summary
    block = run_empirical_bootstrap(
        EMPIRICAL,
        config=CONFIG,
        risk_policy=POLICY,
        spec=MonteCarloSpec(
            n_paths=500,
            trades_per_path=50,
            seed=21,
            resampling_method="moving_block",
            block_size=4,
        ),
    ).summary
    # We do not prescribe which model is optimistic. We require only that the
    # model identity is explicit and at least one path statistic can differ.
    assert iid.resampling_method != block.resampling_method
    assert (
        iid.success_probability != block.success_probability
        or iid.max_drawdown != block.max_drawdown
        or iid.terminal_equity != block.terminal_equity
    )
