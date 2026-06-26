"""Known-answer tests for the PBO (CSCV) estimator."""

from __future__ import annotations

import numpy as np
import pytest

from backtest.factory.pbo import (
    probability_of_backtest_overfitting as pbo_fn,
)


def test_dominant_strategy_has_low_pbo():
    """A strategy that genuinely dominates every period generalises OOS -> PBO ~ 0."""
    rng = np.random.default_rng(42)
    T, N = 200, 8
    M = rng.normal(0.0, 1.0, size=(T, N))
    M[:, 0] = rng.normal(1.0, 0.4, size=T)  # high, stable Sharpe -> real edge
    res = pbo_fn(M, n_partitions=10)
    assert res.pbo < 0.05, f"dominant strategy should give low PBO, got {res.pbo}"
    assert res.median_logit > 0


def test_iid_noise_pbo_near_half():
    """All strategies iid noise -> selection is chance -> PBO ~ 0.5."""
    rng = np.random.default_rng(7)
    T, N = 240, 12
    M = rng.normal(0.0, 1.0, size=(T, N))
    res = pbo_fn(M, n_partitions=10)
    assert 0.3 < res.pbo < 0.7, f"iid noise PBO should be ~0.5, got {res.pbo}"


def test_split_count_is_C_S_half():
    from math import comb

    rng = np.random.default_rng(1)
    M = rng.normal(size=(120, 5))
    res = pbo_fn(M, n_partitions=8)
    assert res.n_splits == comb(8, 4) == 70


def test_validation_errors():
    rng = np.random.default_rng(0)
    with pytest.raises(ValueError):
        pbo_fn(rng.normal(size=(100, 5)), n_partitions=7)  # odd S
    with pytest.raises(ValueError):
        pbo_fn(rng.normal(size=(100, 1)), n_partitions=8)  # N < 2
    with pytest.raises(ValueError):
        pbo_fn(rng.normal(size=(6, 5)), n_partitions=8)  # S > T
    with pytest.raises(ValueError):
        pbo_fn(rng.normal(size=(100,)), n_partitions=8)  # not 2-D
