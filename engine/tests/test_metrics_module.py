"""Golden tests for the canonical metrics module (analytics.metrics).

Locks the floor + guard invariants from PR #272: known inputs -> known outputs,
plus the pathological cases that previously produced NaN / -1e14 nonsense.
"""

import math

import pytest

from analytics.metrics import (
    calmar,
    max_drawdown_pct,
    sharpe,
    total_return_pct,
)

# ── max_drawdown_pct ────────────────────────────────────────────────────────


def test_max_drawdown_pct_known_curve():
    # peak reaches 11000 at index 1, trough 9900 -> (11000-9900)/11000 = 10.0%
    assert max_drawdown_pct([10000, 11000, 9900, 10500], 10000) == 10.0


def test_max_drawdown_pct_no_drawdown_is_zero():
    assert max_drawdown_pct([10000, 10500, 11000], 10000) == 0.0


def test_max_drawdown_pct_floors_denominator_against_starting_capital():
    # Curve never rises above starting capital. Seeding the peak at 10000 means
    # the trough of 8000 measures a real 20% dd instead of exploding on a ~0 peak
    # (the -1.46e14 blowup PR #272 fixed on the all-negative cumulative curve).
    dd = max_drawdown_pct([9000, 8000, 8500], 10000)
    assert dd == 20.0
    assert math.isfinite(dd)


def test_max_drawdown_pct_nonpositive_capital_is_none():
    assert max_drawdown_pct([10000, 9000], 0) is None
    assert max_drawdown_pct([10000, 9000], -5) is None


def test_max_drawdown_pct_empty_curve_is_zero():
    assert max_drawdown_pct([], 10000) == 0.0


def test_max_drawdown_pct_skips_none_entries():
    assert max_drawdown_pct([10000, None, 9000, None], 10000) == 10.0


# ── calmar ──────────────────────────────────────────────────────────────────


def test_calmar_known():
    # 1000 / 0.10 = 10000.0
    assert calmar(1000.0, 0.10) == 10000.0


def test_calmar_sign_agnostic_on_max_dd():
    # magnitude only — a negative max_dd fraction gives the same ratio
    assert calmar(1000.0, -0.10) == 10000.0


def test_calmar_tiny_max_dd_is_none_not_blowup():
    # denominator below the floor -> undefined, never return/~0 = 1e14 nonsense
    assert calmar(5000.0, 1e-9) is None
    assert calmar(5000.0, 0.0) is None


def test_calmar_missing_inputs_are_none():
    assert calmar(None, 0.10) is None
    assert calmar(1000.0, None) is None


def test_calmar_1206pct_drawdown_case():
    # 12.06% drawdown that previously fed the display blowup — now well-defined
    result = calmar(0.30, 0.1206)
    assert result == pytest.approx(2.4876, abs=1e-4)
    assert math.isfinite(result)


# ── sharpe ──────────────────────────────────────────────────────────────────


def test_sharpe_known_series():
    # returns [1,2,3,4,5]: mean=3, sample var=2.5, std=1.5811
    # ann_return=756, ann_std=1.5811*sqrt(252)=25.1000 -> 30.1195
    result = sharpe([1, 2, 3, 4, 5])
    assert result == pytest.approx(30.1195, abs=1e-3)


def test_sharpe_zero_variance_is_none():
    # flat series has no defined risk-adjusted return (near-zero denominator)
    assert sharpe([10, 10, 10]) is None


def test_sharpe_too_few_observations_is_none():
    assert sharpe([42]) is None
    assert sharpe([]) is None


def test_sharpe_never_nan_or_inf():
    for series in ([1, 2, 3, 4, 5], [-100, 50, -30, 80], [0.1, 0.2, 0.15]):
        result = sharpe(series)
        assert result is None or math.isfinite(result)


# ── total_return_pct ────────────────────────────────────────────────────────


def test_total_return_pct_1206_case():
    # 10000 -> 11206 = the 12.06% case named in the checklist
    assert total_return_pct(11206, 10000) == 12.06


def test_total_return_pct_negative():
    assert total_return_pct(9000, 10000) == -10.0


def test_total_return_pct_nonpositive_capital_is_none():
    assert total_return_pct(11206, 0) is None
    assert total_return_pct(11206, -100) is None
