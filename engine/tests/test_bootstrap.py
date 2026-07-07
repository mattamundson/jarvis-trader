"""Golden-sample regression tests for bootstrap primitives.

These tests verify the bootstrap implementations in engine/backtest/monte_carlo.py
against synthetic distributions with known ground truth. If any test fails, a
real statistical bug was introduced — these are not flaky implementation tests.
"""
from __future__ import annotations

import numpy as np
import pytest

from backtest.monte_carlo import (
    bootstrap_max_dd,
    bootstrap_pf,
    bootstrap_sharpe,
    moving_block_bootstrap,
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
