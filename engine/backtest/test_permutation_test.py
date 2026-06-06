"""Tests for the trade-sign permutation significance test.

Covers the Aronson (EBTA ch. 6) sign-shuffle null: under "no directional
edge", each trade's sign is a coin flip. We build the null distribution of
the edge statistic by randomly flipping signs and ask how often the null
matches or beats the observed statistic.
"""
from __future__ import annotations

import math

import pytest

from backtest.permutation_test import permutation_test, permute_and_score


def test_strong_positive_edge_is_significant():
    """An all-winning trade list has the maximum possible mean — no sign
    flip can beat it — so the edge must register as highly significant."""
    pnls = [100.0] * 50
    out = permutation_test(pnls, n_iters=1000, seed=42)
    assert out["p_value"] < 0.05
    assert out["passes_at_5pct"] is True
    assert out["observed"] == pytest.approx(100.0)


def test_no_edge_is_not_significant():
    """A perfectly symmetric P&L stream (equal wins and losses of equal
    magnitude) has zero directional edge — the observed mean sits in the
    middle of the null, so it must NOT pass at 5%."""
    pnls = [100.0, -100.0] * 25
    out = permutation_test(pnls, n_iters=1000, seed=42)
    assert out["p_value"] > 0.05
    assert out["passes_at_5pct"] is False


def test_deterministic_under_fixed_seed():
    """Same seed + same inputs => identical p-value (reproducible gate)."""
    pnls = [12.0, -8.0, 5.0, -3.0, 20.0, -15.0, 7.0]
    a = permutation_test(pnls, n_iters=500, seed=7)
    b = permutation_test(pnls, n_iters=500, seed=7)
    assert a["p_value"] == b["p_value"]


def test_p_value_is_a_valid_probability():
    pnls = [10.0, -2.0, 4.0, -1.0, 6.0]
    out = permutation_test(pnls, n_iters=500, seed=1)
    assert 0.0 <= out["p_value"] <= 1.0


def test_empty_and_singleton_are_safe():
    """Degenerate inputs must not crash and must report 'no detectable
    edge' (p_value = 1.0) rather than a false positive."""
    assert permutation_test([], n_iters=100)["p_value"] == 1.0
    assert permutation_test([42.0], n_iters=100)["p_value"] == 1.0


def test_permute_and_score_accepts_trade_dicts():
    """The thin wrapper named in ml-pitfalls-defense.md accepts trade dicts
    with a 'pnl' field and returns just the float p-value."""
    trades = [{"pnl": 100.0} for _ in range(40)]
    p = permute_and_score(trades, n_iters=1000)
    assert isinstance(p, float)
    assert p < 0.05


def test_permute_and_score_matches_full_result():
    pnls = [9.0, -4.0, 3.0, -2.0, 11.0, -1.0]
    p = permute_and_score(pnls, n_iters=500, seed=99)
    full = permutation_test(pnls, n_iters=500, seed=99)
    assert p == full["p_value"]


def test_all_losses_never_significant():
    """An all-losing strategy must never look like a positive edge."""
    pnls = [-50.0] * 30
    out = permutation_test(pnls, n_iters=1000, seed=42)
    assert out["p_value"] > 0.05
    assert out["passes_at_5pct"] is False


def test_null_stats_reported():
    pnls = [10.0, -2.0, 4.0, -1.0, 6.0, -3.0, 8.0]
    out = permutation_test(pnls, n_iters=1000, seed=3)
    assert "null_mean" in out and "null_std" in out
    assert math.isfinite(out["null_mean"])
    assert out["n_iters"] == 1000
