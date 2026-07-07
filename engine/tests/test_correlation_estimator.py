"""P2.3: estimate the pairwise return-correlation matrix the portfolio sizer needs.

risk.portfolio_sizer.correlation_scale_factor consumes a sparse {(a,b): rho} map.
This module produces that map from per-symbol return series (derivable from cached
bars). Pure stdlib (no pandas in the hot sizing path), so it is fast and fully
unit-testable. Pairs with too little overlap or a zero-variance leg are omitted —
the sizer then falls back to its conservative default_corr for those pairs.
"""

import math

from risk.correlation_estimator import estimate_correlations, pearson


def test_pearson_perfectly_correlated():
    x = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert math.isclose(pearson(x, x), 1.0, rel_tol=1e-9)


def test_pearson_perfectly_anticorrelated():
    x = [1.0, 2.0, 3.0, 4.0, 5.0]
    y = [5.0, 4.0, 3.0, 2.0, 1.0]
    assert math.isclose(pearson(x, y), -1.0, rel_tol=1e-9)


def test_pearson_uncorrelated_is_near_zero():
    # Symmetric, mean-zero, orthogonal pattern => correlation 0.
    x = [1.0, -1.0, 1.0, -1.0]
    y = [1.0, 1.0, -1.0, -1.0]
    assert math.isclose(pearson(x, y), 0.0, abs_tol=1e-9)


def test_pearson_zero_variance_returns_none():
    x = [3.0, 3.0, 3.0, 3.0]
    y = [1.0, 2.0, 3.0, 4.0]
    assert pearson(x, y) is None


def test_pearson_too_short_returns_none():
    assert pearson([1.0], [2.0]) is None


def test_estimate_emits_pair_keyed_correlations():
    rets = {
        "MES": [0.01, -0.02, 0.03, -0.01, 0.02, -0.03, 0.01, 0.0],
        "MGC": [0.01, -0.02, 0.03, -0.01, 0.02, -0.03, 0.01, 0.0],  # identical => rho 1
    }
    corr = estimate_correlations(rets, min_overlap=5)
    # One unordered pair present, value ~1.0, key is a (a,b) tuple the sizer accepts.
    assert len(corr) == 1
    key = next(iter(corr))
    assert set(key) == {"MES", "MGC"}
    assert math.isclose(corr[key], 1.0, rel_tol=1e-9)


def test_estimate_omits_pairs_below_min_overlap():
    rets = {
        "MES": [0.01, -0.02, 0.03],
        "MGC": [0.01, -0.02, 0.03],
    }
    corr = estimate_correlations(rets, min_overlap=10)
    assert corr == {}


def test_estimate_aligns_unequal_lengths_on_the_overlapping_tail():
    # MGC has a longer history; only the most-recent overlapping window is compared.
    rets = {
        "MES": [0.02, -0.03, 0.01, 0.0, 0.01],
        "MGC": [9.9, 9.9, 0.02, -0.03, 0.01, 0.0, 0.01],  # leading values are pre-overlap
    }
    corr = estimate_correlations(rets, min_overlap=5)
    key = next(iter(corr))
    assert math.isclose(corr[key], 1.0, rel_tol=1e-9)


def test_estimate_omits_zero_variance_leg():
    rets = {
        "MES": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        "MGC": [0.01, -0.02, 0.03, -0.01, 0.02, -0.03],
    }
    corr = estimate_correlations(rets, min_overlap=5)
    assert corr == {}


def test_estimate_three_symbols_three_pairs():
    base = [0.01, -0.02, 0.03, -0.01, 0.02, -0.03]
    rets = {"MES": base, "MGC": base, "MNQ": base}
    corr = estimate_correlations(rets, min_overlap=5)
    assert len(corr) == 3  # MES-MGC, MES-MNQ, MGC-MNQ
