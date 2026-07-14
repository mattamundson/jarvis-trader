"""Regression tests for Deflated Sharpe Ratio implementation.

Reference values derived from López de Prado (2018) "Advances in Financial
Machine Learning" §8 and Bailey/Borwein/López de Prado/Zhu (2014).
"""
from __future__ import annotations

import numpy as np
import pytest
from scipy import stats

from backtest.deflated_sharpe import (
    _expected_max_sharpe,
    _sharpe_standard_error,
    deflated_sharpe_from_returns,
    deflated_sharpe_ratio,
)


class TestExpectedMaxSharpe:
    def test_n_equals_one_returns_zero(self):
        """With only 1 trial, there's no max bias."""
        assert _expected_max_sharpe(1) == 0.0

    def test_monotonic_increase_with_n(self):
        """E[max SR] grows with number of trials."""
        for n1, n2 in [(10, 100), (100, 1000), (1000, 10000)]:
            assert _expected_max_sharpe(n1) < _expected_max_sharpe(n2)

    def test_known_values(self):
        """Against Gumbel-distribution-based reference values.

        For N=100 (common grid size) the expected max under N(0,1) Sharpe
        samples is roughly 2.5-2.8; the exact value depends on the specific
        Gumbel approximation weights. We test the order of magnitude matches.
        """
        val_100 = _expected_max_sharpe(100)
        assert 2.2 < val_100 < 3.0
        val_1000 = _expected_max_sharpe(1000)
        assert 3.0 < val_1000 < 3.7


class TestSharpeStandardError:
    def test_gaussian_returns_returns_simple_form(self):
        """For Gaussian returns (skew=0, kurt=3) with SR=0, σ_SR = sqrt(1/(T-1))."""
        sigma = _sharpe_standard_error(sharpe=0.0, skew=0.0, kurt=3.0, n_obs=100)
        expected = np.sqrt(1.0 / 99)  # (1 - 0 + (3-1)/4 * 0) / (100-1) = 1/99
        assert abs(sigma - expected) < 1e-6

    def test_negative_skew_inflates_se(self):
        """Negative skew + positive SR → numerator increases → wider SE."""
        sigma_pos = _sharpe_standard_error(sharpe=1.0, skew=0.0, kurt=3.0, n_obs=100)
        sigma_neg = _sharpe_standard_error(sharpe=1.0, skew=-1.0, kurt=3.0, n_obs=100)
        assert sigma_neg > sigma_pos

    def test_small_sample_returns_infinity(self):
        assert _sharpe_standard_error(1.0, 0.0, 3.0, 1) == float("inf")


class TestDeflatedSharpeRatio:
    def test_high_sr_low_n_passes(self):
        """Sharpe 3.0 with only 10 trials and 250 trades → should pass DSR."""
        r = deflated_sharpe_ratio(sharpe=3.0, n_trials=10, n_obs=250)
        assert r["passes_at_10pct"] is True
        assert r["dsr"] > 0.10

    def test_low_sr_high_n_fails(self):
        """Sharpe 0.5 with 1000 grid trials → should fail (noise-level result)."""
        r = deflated_sharpe_ratio(sharpe=0.5, n_trials=1000, n_obs=100)
        assert r["passes_at_10pct"] is False
        assert r["dsr"] < 0.10

    def test_sr_below_expected_max_gives_dsr_below_half(self):
        """When observed SR is below the expected max-of-N, DSR < 0.5."""
        expected_max_100 = _expected_max_sharpe(100)
        r = deflated_sharpe_ratio(
            sharpe=expected_max_100 - 0.5, n_trials=100, n_obs=200
        )
        assert r["dsr"] < 0.5

    def test_sr_above_expected_max_gives_dsr_above_half(self):
        expected_max_100 = _expected_max_sharpe(100)
        r = deflated_sharpe_ratio(
            sharpe=expected_max_100 + 1.0, n_trials=100, n_obs=200
        )
        assert r["dsr"] > 0.5

    def test_output_structure(self):
        r = deflated_sharpe_ratio(sharpe=2.0, n_trials=50, n_obs=100)
        for key in ["raw_sharpe", "expected_max_sharpe", "sharpe_std_error",
                    "dsr", "passes_at_10pct", "n_trials", "n_obs"]:
            assert key in r
        assert r["raw_sharpe"] == 2.0
        assert r["n_trials"] == 50
        assert r["n_obs"] == 100

    def test_degenerate_inputs_handled(self):
        r = deflated_sharpe_ratio(sharpe=2.0, n_trials=0, n_obs=100)
        assert r["dsr"] == 0.0
        r2 = deflated_sharpe_ratio(sharpe=2.0, n_trials=10, n_obs=1)
        assert r2["dsr"] == 0.0

    def test_reference_scenario_sr_2_n_100_t_250(self):
        """Bailey/López de Prado reference-style case.

        SR = 2.0 (annualized), N = 100 trials, T = 250 bars, Gaussian returns.
        Expected max SR for N=100 ≈ 2.5-2.6 — so SR=2.0 is BELOW the max-of-N
        threshold. DSR should be moderate-low (< 0.5) indicating the observed
        SR could be explained by selection bias.
        """
        r = deflated_sharpe_ratio(sharpe=2.0, n_trials=100, n_obs=250,
                                  skew=0.0, kurt=3.0)
        # SR=2.0 is plausibly below E[max SR|N=100], giving a moderate DSR
        assert 0.0 < r["dsr"] < 0.5
        assert r["expected_max_sharpe"] > 2.0


class TestDeflatedSharpeFromReturns:
    def test_gaussian_returns_positive_mean(self):
        rng = np.random.default_rng(0)
        returns = rng.normal(loc=0.001, scale=0.01, size=500)
        r = deflated_sharpe_from_returns(returns, n_trials=10, ann_factor=252.0)
        assert "skew" in r and "kurt" in r
        assert r["n_obs"] == 500
        # Positive drift with reasonable signal → DSR should be meaningful
        assert r["raw_sharpe"] > 0

    def test_zero_variance_returns_degenerate_output(self):
        """Exactly-constant returns give zero std → early exit, DSR = 0.

        Uses zeros to ensure bit-exact std==0 (small constants like 0.001
        accumulate float-precision noise in numpy's reduction, producing a
        non-zero std ~1e-20 and a pathological Sharpe).
        """
        r = deflated_sharpe_from_returns([0.0] * 100, n_trials=10)
        assert r["dsr"] == 0.0
        assert r["raw_sharpe"] == 0.0

    def test_empty_returns(self):
        r = deflated_sharpe_from_returns([], n_trials=10)
        assert r["n_obs"] == 0
        assert r["dsr"] == 0.0

    def test_skew_and_kurt_populated(self):
        rng = np.random.default_rng(42)
        returns = rng.normal(size=300)
        r = deflated_sharpe_from_returns(returns, n_trials=50)
        # Gaussian sample: skew ≈ 0, kurt ≈ 3
        assert abs(r["skew"]) < 0.3
        assert 2.5 < r["kurt"] < 3.5


class TestFromReturnsUsesRawNotAnnualizedSharpe:
    """Regression guard for the 2026-07-10 incident: deflated_sharpe_from_returns
    fed an ANNUALIZED Sharpe into deflated_sharpe_ratio, which is derived for the
    RAW per-observation Sharpe over T=n_obs observations -- annualizing first
    inflated DSR from a true ~0.11 to a false 1.0 on MES's live paper
    authorization (n_trials=3, n_obs=16), and ~0.00 to a false 1.0 on MGC's
    (n_trials=8, n_obs=67).
    """

    def test_wrapper_matches_direct_call_with_raw_sharpe(self):
        rng = np.random.default_rng(7)
        returns = rng.normal(loc=0.002, scale=0.01, size=50)

        wrapped = deflated_sharpe_from_returns(returns, n_trials=5, ann_factor=252.0)

        raw_sharpe = float(returns.mean() / returns.std(ddof=1))
        skew_val = float(stats.skew(returns, bias=False))
        kurt_raw = float(stats.kurtosis(returns, bias=False)) + 3.0
        direct = deflated_sharpe_ratio(
            sharpe=raw_sharpe, n_trials=5, n_obs=len(returns),
            skew=skew_val, kurt=kurt_raw,
        )

        assert wrapped["dsr"] == direct["dsr"]
        assert wrapped["raw_sharpe"] == direct["raw_sharpe"]

    def test_ann_sharpe_reported_but_not_used_for_dsr(self):
        rng = np.random.default_rng(7)
        returns = rng.normal(loc=0.002, scale=0.01, size=50)
        r = deflated_sharpe_from_returns(returns, n_trials=5, ann_factor=252.0)
        assert abs(r["ann_sharpe"] - r["raw_sharpe"] * np.sqrt(252.0)) < 1e-6
        assert r["ann_sharpe"] != r["raw_sharpe"]

    def test_mes_incident_shape_dsr_is_low_not_one(self):
        """2026-05-24 MES live paper authorization: n_trials=3, n_obs=16,
        skew=-0.2531, kurt=3.2072, raw_sharpe=0.4988. Recorded (buggy) DSR was
        1.0; corrected DSR must sit far below the 0.30 ALT floor."""
        r = deflated_sharpe_ratio(
            sharpe=0.4988, n_trials=3, n_obs=16, skew=-0.2531, kurt=3.2072,
        )
        assert r["dsr"] < 0.30
        assert 0.05 < r["dsr"] < 0.20  # pins near the observed ~0.111

    def test_mgc_incident_shape_dsr_is_near_zero_not_one(self):
        """2026-05-24 MGC live paper authorization: n_trials=8, n_obs=67,
        skew=0.7193, kurt=3.3233, raw_sharpe=0.4123. Recorded (buggy) DSR was
        1.0; corrected DSR must fail even the 0.10 CORE floor."""
        r = deflated_sharpe_ratio(
            sharpe=0.4123, n_trials=8, n_obs=67, skew=0.7193, kurt=3.3233,
        )
        assert r["dsr"] < 0.10
