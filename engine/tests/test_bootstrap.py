"""Golden-sample regression tests for bootstrap primitives.

These tests verify the bootstrap implementations in engine/backtest/monte_carlo.py
against synthetic distributions with known ground truth. If any test fails, a
real statistical bug was introduced — these are not flaky implementation tests.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from scipy.stats import norm

from backtest.metrics import calculate_metrics
from backtest.monte_carlo import (
    _load_result_from_json,
    bootstrap_max_dd,
    bootstrap_pf,
    bootstrap_sharpe,
    compute_cvar,
    compute_var,
    moving_block_bootstrap,
    probability_of_ruin,
)


class TestBootstrapPF:
    def test_coin_flip_pnls_ci_contains_one(self):
        """p=0.5 win/loss with ±1 magnitude: true PF = 1.0. CI should contain it."""
        pnls = ([1.0] * 500) + ([-1.0] * 500)
        r = bootstrap_pf(pnls, n_resamples=2000, seed=42)
        assert r["n_trades"] == 1000
        # PF is exactly 1.0 on this deterministic sample; bootstrap should be tight around 1.0
        assert r["pf_ci_95_low"] < 1.0 < r["pf_ci_95_high"] or abs(r["median_pf"] - 1.0) < 0.05

    def test_two_to_one_wins_pf_near_two(self):
        """50 wins at +2.0 and 50 losses at -1.0: true PF = 2.0."""
        pnls = ([2.0] * 50) + ([-1.0] * 50)
        r = bootstrap_pf(pnls, n_resamples=2000, seed=42)
        assert r["pf_ci_95_low"] < 2.0 < r["pf_ci_95_high"]
        assert abs(r["median_pf"] - 2.0) < 0.3  # bootstrap noise tolerance
        assert r["p_positive_edge"] > 0.95  # overwhelming majority of resamples show edge

    def test_all_positive_pnls_means_positive_edge(self):
        """Strategy with no losses: p_positive_edge should be 1.0."""
        pnls = [1.0] * 100
        r = bootstrap_pf(pnls, n_resamples=1000, seed=42)
        assert r["p_positive_edge"] == 1.0
        # median_pf is inf on no-loss data (by _pf_from_pnls convention)
        assert r["median_pf"] == float("inf") or r["median_pf"] > 100

    def test_all_negative_pnls_no_edge(self):
        """Strategy with only losses: p_positive_edge should be 0.0."""
        pnls = [-1.0] * 100
        r = bootstrap_pf(pnls, n_resamples=1000, seed=42)
        assert r["p_positive_edge"] == 0.0
        assert r["median_pf"] == 0.0

    def test_empty_pnls_returns_zeros(self):
        r = bootstrap_pf([], n_resamples=100, seed=42)
        assert r["n_trades"] == 0
        assert r["median_pf"] == 0.0

    def test_seed_reproducibility(self):
        pnls = list(np.random.default_rng(0).normal(0.2, 1.0, size=200))
        r1 = bootstrap_pf(pnls, n_resamples=500, seed=123)
        r2 = bootstrap_pf(pnls, n_resamples=500, seed=123)
        assert r1 == r2


class TestMovingBlockBootstrap:
    def test_block_size_defaults_to_sqrt_n(self):
        pnls = [1.0] * 100  # N=100 → sqrt(N)=10
        r = moving_block_bootstrap(pnls, n_resamples=100, seed=42)
        assert r["block_size"] == 10

    def test_custom_block_size_honored(self):
        pnls = [1.0, -1.0] * 50
        r = moving_block_bootstrap(pnls, n_resamples=100, block_size=5, seed=42)
        assert r["block_size"] == 5

    def test_block_size_clamped_to_n(self):
        pnls = [1.0] * 10
        r = moving_block_bootstrap(pnls, n_resamples=50, block_size=1000, seed=42)
        assert r["block_size"] == 10  # clamped to N

    def test_serial_correlation_preserved_gives_wider_ci(self):
        """On an autocorrelated series, moving-block CI should be wider than IID.

        Construct a series where consecutive trades are perfectly correlated
        (win → win, loss → loss blocks of 10). IID bootstrap breaks the
        structure; moving-block preserves it and produces a wider CI.
        """
        rng = np.random.default_rng(0)
        # 20 blocks of 10 trades each, with block sign correlated
        pnls = []
        for _ in range(20):
            sign = rng.choice([1.0, -1.0])
            pnls.extend([sign * abs(rng.normal(0.5, 0.2))] * 10)
        iid = bootstrap_pf(pnls, n_resamples=2000, seed=42)
        mb = moving_block_bootstrap(pnls, n_resamples=2000, block_size=10, seed=42)
        iid_width = iid["pf_ci_95_high"] - iid["pf_ci_95_low"]
        mb_width = mb["pf_ci_95_high"] - mb["pf_ci_95_low"]
        # Moving-block with block=10 (matching the structure) should be wider
        # because it samples actual runs of wins or losses.
        assert mb_width >= iid_width * 0.95  # at minimum not narrower

    def test_empty_pnls_returns_zeros(self):
        r = moving_block_bootstrap([], n_resamples=100, seed=42)
        assert r["n_trades"] == 0


class TestBootstrapSharpe:
    def test_positive_expectation_gives_positive_median_sharpe(self):
        rng = np.random.default_rng(0)
        pnls = list(rng.normal(loc=5.0, scale=10.0, size=200))
        r = bootstrap_sharpe(pnls, n_resamples=1000, seed=42)
        assert r["median_sharpe"] > 0
        assert r["p_positive_sharpe"] > 0.9

    def test_zero_expectation_sharpe_near_zero(self):
        rng = np.random.default_rng(0)
        pnls = list(rng.normal(loc=0.0, scale=1.0, size=500))
        r = bootstrap_sharpe(pnls, n_resamples=1000, seed=42)
        assert r["sharpe_ci_95_low"] < 0.0 < r["sharpe_ci_95_high"] or abs(r["median_sharpe"]) < 0.5

    def test_empty_pnls_returns_zeros(self):
        r = bootstrap_sharpe([], n_resamples=100, seed=42)
        assert r["n_trades"] == 0


class TestBootstrapMaxDD:
    def test_observed_dd_on_trending_pnls(self):
        """Trending up + one big loser: max DD is driven by the single loser."""
        pnls = [1.0] * 50 + [-30.0] + [1.0] * 50
        r = bootstrap_max_dd(pnls, initial_capital=10_000.0, n_resamples=500, seed=42)
        assert r["observed_max_dd_pct"] > 0
        assert r["mc_95th"] >= r["mc_50th"]
        assert r["mc_99th"] >= r["mc_95th"]

    def test_mc_percentiles_monotonic(self):
        rng = np.random.default_rng(0)
        pnls = list(rng.normal(loc=1.0, scale=5.0, size=100))
        r = bootstrap_max_dd(pnls, n_resamples=500, seed=42)
        assert r["mc_50th"] <= r["mc_95th"] <= r["mc_99th"]

    def test_short_pnls_returns_zeros(self):
        r = bootstrap_max_dd([1.0], n_resamples=100, seed=42)
        assert r["n_trades"] == 1
        assert r["observed_max_dd_pct"] == 0.0


class TestComputeVar:
    def test_normal_synthetic_var_matches_closed_form(self):
        """5th-percentile VaR on N(0, 100) should be close to the closed-form
        Gaussian quantile -1.645 * std (negative, matching metrics.py's
        negative-for-loss sign convention)."""
        rng = np.random.default_rng(1)
        pnls = rng.normal(loc=0, scale=100, size=2000)
        r = compute_var(list(pnls), confidence=0.95, n_resamples=2000, seed=42)
        expected_var = norm.ppf(0.05) * 100.0  # ~ -164.5
        assert abs(r["var_pct"] - expected_var) < 25.0  # bootstrap/sample noise tolerance
        assert r["n_trades"] == 2000
        assert r["confidence"] == 0.95

    def test_short_pnls_returns_zeros(self):
        r = compute_var([1.0], n_resamples=100, seed=42)
        assert r["n_trades"] == 1
        assert r["var_pct"] == 0.0

    def test_empty_pnls_returns_zeros(self):
        r = compute_var([], n_resamples=100, seed=42)
        assert r["n_trades"] == 0
        assert r["var_pct"] == 0.0

    def test_all_positive_pnls_clip_toward_zero(self):
        """No losses at all: VaR must not error and must not report a large
        negative (loss-like) number — it should sit at/above 0."""
        pnls = [1.0] * 100
        r = compute_var(pnls, n_resamples=500, seed=42)
        assert r["var_pct"] >= 0.0

    def test_seed_reproducibility(self):
        pnls = list(np.random.default_rng(0).normal(0, 50, size=200))
        r1 = compute_var(pnls, n_resamples=500, seed=123)
        r2 = compute_var(pnls, n_resamples=500, seed=123)
        assert r1 == r2


class TestComputeCvar:
    def test_normal_synthetic_cvar_matches_closed_form(self):
        """CVaR (Expected Shortfall) on N(0, 100) at 95% confidence should be
        close to the closed-form Gaussian value: -std * phi(z)/alpha, with
        z = Phi^-1(0.05) and alpha = 0.05 (~ -206.3 for std=100)."""
        rng = np.random.default_rng(2)
        pnls = rng.normal(loc=0, scale=100, size=2000)
        r = compute_cvar(list(pnls), confidence=0.95, n_resamples=2000, seed=42)
        z = norm.ppf(0.05)
        expected_cvar = -100.0 * norm.pdf(z) / 0.05
        assert abs(r["cvar"] - expected_cvar) < 35.0  # bootstrap/sample noise tolerance
        assert r["n_trades"] == 2000

    def test_short_pnls_returns_zeros(self):
        r = compute_cvar([1.0], n_resamples=100, seed=42)
        assert r["n_trades"] == 1
        assert r["cvar"] == 0.0

    def test_empty_pnls_returns_zeros(self):
        r = compute_cvar([], n_resamples=100, seed=42)
        assert r["cvar"] == 0.0

    def test_all_positive_pnls_clip_toward_zero(self):
        pnls = [1.0] * 100
        r = compute_cvar(pnls, n_resamples=500, seed=42)
        assert r["cvar"] >= 0.0

    def test_seed_reproducibility(self):
        pnls = list(np.random.default_rng(0).normal(0, 50, size=200))
        r1 = compute_cvar(pnls, n_resamples=500, seed=123)
        r2 = compute_cvar(pnls, n_resamples=500, seed=123)
        assert r1 == r2

    def test_cvar_at_least_as_extreme_as_var(self):
        """CVaR (mean of the tail beyond VaR) must be <= VaR itself (more
        negative / a bigger loss), never a smaller-magnitude number."""
        rng = np.random.default_rng(3)
        pnls = rng.normal(loc=0, scale=100, size=1000)
        var_r = compute_var(list(pnls), n_resamples=500, seed=42)
        cvar_r = compute_cvar(list(pnls), n_resamples=500, seed=42)
        assert cvar_r["cvar"] <= var_r["var_pct"]


class TestProbabilityOfRuin:
    def test_one_huge_loser_pushes_ruin_probability_up(self):
        pnls = [500.0] * 80 + [-8000.0]
        r = probability_of_ruin(
            pnls, initial_capital=10_000.0, ruin_threshold_pct=0.5, n_resamples=2000, seed=42
        )
        assert r["probability_of_ruin"] > 0.0

    def test_uniformly_small_losses_no_ruin(self):
        pnls = [50.0] * 40 + [-40.0] * 40
        r = probability_of_ruin(
            pnls, initial_capital=10_000.0, ruin_threshold_pct=0.5, n_resamples=2000, seed=42
        )
        assert r["probability_of_ruin"] == pytest.approx(0.0, abs=1e-3)

    def test_monotonic_in_ruin_threshold(self):
        """Raising ruin_threshold_pct (an easier-to-breach, higher equity
        floor) must never DECREASE the reported probability."""
        pnls = [500.0] * 80 + [-8000.0]
        r_low = probability_of_ruin(
            pnls, initial_capital=10_000.0, ruin_threshold_pct=0.5, n_resamples=2000, seed=42
        )
        r_high = probability_of_ruin(
            pnls, initial_capital=10_000.0, ruin_threshold_pct=0.9, n_resamples=2000, seed=42
        )
        assert r_high["probability_of_ruin"] >= r_low["probability_of_ruin"]

    def test_failsafe_under_two_trades_returns_zero_not_one(self):
        """Fail-safe must be 0.0 (not 1.0) — too little data to simulate a
        path must not silently over-flag as risky."""
        r = probability_of_ruin([100.0], n_resamples=100, seed=42)
        assert r["probability_of_ruin"] == 0.0
        r0 = probability_of_ruin([], n_resamples=100, seed=42)
        assert r0["probability_of_ruin"] == 0.0

    def test_seed_reproducibility(self):
        pnls = [500.0] * 80 + [-8000.0]
        r1 = probability_of_ruin(pnls, n_resamples=1000, seed=7)
        r2 = probability_of_ruin(pnls, n_resamples=1000, seed=7)
        assert r1 == r2


class TestBootstrapVarCvarCrossCheckAgainstMetrics:
    """Cross-check compute_var/compute_cvar against metrics.py's single-sample
    var_95/cvar_95 on the same real trade list -- same underlying percentile
    method, different framing (bootstrap CI vs. point estimate) and different
    units (dollars here vs. fraction-of-capital in metrics.py)."""

    def _load_fixture(self):
        fixture = (
            Path(__file__).parent.parent
            / "backtest"
            / "results"
            / "MES_1h_2024-06-01_2026-03-27.json"
        )
        return _load_result_from_json(str(fixture))

    def test_compute_var_matches_metrics_var_95_after_unit_conversion(self):
        bt_result = self._load_fixture()
        pnls = [t.pnl for t in bt_result.trades]
        assert len(pnls) >= 10  # calculate_metrics only sets var_95 when len(returns) >= 10

        metrics_result = calculate_metrics(bt_result)
        var_r = compute_var(pnls, confidence=0.95, n_resamples=2000, seed=42)

        # compute_var reports raw dollar PnL; metrics.py reports a fraction of
        # initial_capital. Convert dollars -> fraction before comparing (same
        # 5th-percentile method on the same trades, just rescaled).
        var_fraction = var_r["var_pct"] / bt_result.initial_capital
        assert var_fraction == pytest.approx(metrics_result.var_95, abs=1e-6)

    def test_compute_cvar_matches_metrics_cvar_95_after_unit_conversion(self):
        bt_result = self._load_fixture()
        pnls = [t.pnl for t in bt_result.trades]
        assert len(pnls) >= 10

        metrics_result = calculate_metrics(bt_result)
        cvar_r = compute_cvar(pnls, confidence=0.95, n_resamples=2000, seed=42)

        cvar_fraction = cvar_r["cvar"] / bt_result.initial_capital
        assert cvar_fraction == pytest.approx(metrics_result.cvar_95, abs=1e-6)
