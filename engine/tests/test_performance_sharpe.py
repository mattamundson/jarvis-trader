"""Tests for PerformanceCalculator.calculate_sharpe flat-curve handling.

A flat P&L series should yield Sharpe 0.0. The old `std == 0.0` guard missed
float-dust std (~1e-18) from cancellation in the sum-of-squares, returning a
Sharpe of ~1e17 — which would falsely clear the SHARPE_TARGET validation gate.
"""

from __future__ import annotations

import math

from analytics.performance import PerformanceCalculator

calc = PerformanceCalculator.calculate_sharpe


def test_flat_nonzero_series_returns_zero():
    # The regression: [0.1, 0.1, 0.1] left std ~3e-18, bypassing == 0.0.
    assert calc([0.1, 0.1, 0.1]) == 0.0


def test_flat_zero_series_returns_zero():
    assert calc([0.0, 0.0, 0.0]) == 0.0


def test_flat_negative_series_returns_zero():
    assert calc([-2.5, -2.5, -2.5, -2.5]) == 0.0


def test_fewer_than_two_points_returns_zero():
    assert calc([]) == 0.0
    assert calc([1.23]) == 0.0


def test_real_series_is_finite_and_signed():
    up = calc([10.0, -2.0, 8.0, -1.0, 12.0])
    assert math.isfinite(up)
    assert up > 0  # positive mean -> positive Sharpe

    down = calc([-10.0, 2.0, -8.0, 1.0, -12.0])
    assert math.isfinite(down)
    assert down < 0


def test_no_blowup_across_flat_magnitudes():
    # None of these flat curves should escape to a huge Sharpe.
    for v in (0.1, 0.3, 1.7, 99.99, -0.1, 1e-3):
        assert calc([v, v, v, v]) == 0.0
