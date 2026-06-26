"""Tests for the Phase-4 combinations / ensemble layer."""

from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.factory.combos import (
    CORR_THRESHOLD,
    align_sleeves,
    inverse_vol_weights,
    max_dd_frac,
    pair_correlation,
    sharpe,
)


def _idx(n):
    return pd.date_range("2025-06-18", periods=n, freq="h")


def test_uncorrelated_positive_streams_diversify():
    """Two independent positive-mean return streams blended equal-weight must
    raise Sharpe above the better sleeve -- the core free-lunch this layer exists
    to find. (Diversification of i.i.d. streams scales Sharpe by ~sqrt(2).)"""
    rng = np.random.default_rng(7)
    n = 4000
    a = pd.Series(rng.normal(0.0004, 0.01, n), index=_idx(n))
    b = pd.Series(rng.normal(0.0004, 0.01, n), index=_idx(n))
    rho = pair_correlation(a, b)
    assert abs(rho) < CORR_THRESHOLD
    blended = 0.5 * a + 0.5 * b
    assert sharpe(blended) > max(sharpe(a), sharpe(b))


def test_perfectly_correlated_streams_do_not_diversify():
    """Identical sleeves: correlation ~1, so the layer must refuse to combine
    them (blending adds gross exposure with no risk reduction)."""
    rng = np.random.default_rng(11)
    n = 3000
    a = pd.Series(rng.normal(0.0003, 0.008, n), index=_idx(n))
    b = a.copy()
    rho = pair_correlation(a, b)
    assert rho > 0.99
    assert not (abs(rho) < CORR_THRESHOLD)
    # blending an identical stream cannot raise Sharpe
    blended = 0.5 * a + 0.5 * b
    assert abs(sharpe(blended) - sharpe(a)) < 1e-6


def test_align_sleeves_restricts_to_shared_window_and_zero_fills():
    a = pd.Series(np.ones(100), index=_idx(100))
    b = pd.Series(np.ones(100), index=pd.date_range("2025-06-20", periods=100, freq="h"))
    aa, bb = align_sleeves(a, b)
    # shared window starts at the later start, ends at the earlier end
    assert aa.index[0] == max(a.index[0], b.index[0])
    assert aa.index[-1] == min(a.index[-1], b.index[-1])
    assert not aa.isna().any() and not bb.isna().any()


def test_correlation_ignores_both_flat_bars():
    """Bars where both sleeves are flat (0) must not be counted -- otherwise a
    sleeve that is mostly flat looks artificially uncorrelated with everything."""
    idx = _idx(10)
    a = pd.Series([0, 0, 1.0, -1.0, 0, 0, 2.0, -2.0, 0, 0], index=idx)
    b = pd.Series([0, 0, 1.0, -1.0, 0, 0, 2.0, -2.0, 0, 0], index=idx)
    # identical on the live bars -> correlation 1, NOT diluted by the 6 flat bars
    assert pair_correlation(a, b) > 0.99


def test_inverse_vol_weights_favor_the_calmer_sleeve():
    n = 2000
    calm = pd.Series(np.tile([0.005, -0.005], n // 2), index=_idx(n))  # low vol
    wild = pd.Series(np.tile([0.05, -0.05], n // 2), index=_idx(n))  # 10x vol
    wc, ww = inverse_vol_weights(calm, wild)
    assert wc > ww  # calmer sleeve gets more capital under equal-risk
    assert abs(wc + ww - 1.0) < 1e-9


def test_max_dd_fraction_is_bounded():
    rng = np.random.default_rng(3)
    r = pd.Series(rng.normal(0, 0.01, 1000), index=_idx(1000))
    dd = max_dd_frac(r)
    assert 0.0 <= dd <= 1.0
