"""Tests for MCPT small-sample power analysis (analytics/mcpt_power.py).

Fast (small n_sims/n_perm); asserts qualitative invariants: power rises with
both sample size and effect size, and tiny samples are underpowered.
"""

from __future__ import annotations

from analytics.mcpt_power import estimate_power, power_grid


def test_power_rises_with_sample_size():
    """Same edge, more trades -> more power."""
    small = estimate_power(16, 0.30, n_sims=150, n_perm=200, seed=1).power
    large = estimate_power(250, 0.30, n_sims=150, n_perm=200, seed=1).power
    assert large > small


def test_power_rises_with_effect_size():
    """Same N, bigger edge -> more power."""
    weak = estimate_power(67, 0.05, n_sims=150, n_perm=200, seed=2).power
    strong = estimate_power(67, 0.50, n_sims=150, n_perm=200, seed=2).power
    assert strong > weak


def test_tiny_sample_weak_edge_is_underpowered():
    """The core finding: N=16 with a realistic small edge cannot reliably reject."""
    res = estimate_power(16, 0.10, n_sims=200, n_perm=200, seed=3)
    assert res.power < 0.80


def test_power_in_unit_interval():
    res = estimate_power(67, 0.20, n_sims=100, n_perm=200, seed=4)
    assert 0.0 <= res.power <= 1.0
    assert res.n_trades == 67
    assert res.alpha == 0.05


def test_grid_shape():
    grid = power_grid(sample_sizes=(16, 67), effect_sizes=(0.1, 0.3), n_sims=60)
    assert len(grid) == 4
