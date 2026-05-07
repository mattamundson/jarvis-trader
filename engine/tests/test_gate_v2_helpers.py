"""Tests for engine/backtest/_gate_v2_helpers.py"""
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from backtest._gate_v2_helpers import bootstrap_pf_ci_lower, classify_wfo_consistency


def test_bootstrap_pf_ci_lower_clips_inf():
    result = bootstrap_pf_ci_lower([1.5, 2.0, float("inf"), 3.0])
    assert math.isfinite(result), f"expected finite, got {result}"
    assert result > 0


def test_bootstrap_pf_ci_lower_handles_all_inf():
    result = bootstrap_pf_ci_lower([float("inf"), float("inf"), float("inf")])
    # all capped to 5.0, so mean is 5.0 and 5th percentile must also be 5.0
    assert math.isfinite(result)
    assert result == pytest.approx(5.0)


def test_bootstrap_pf_ci_lower_handles_neg_inf():
    result = bootstrap_pf_ci_lower([1.5, float("-inf"), 2.0])
    assert math.isfinite(result), f"expected finite, got {result}"


def test_bootstrap_pf_ci_lower_too_few_returns_mean():
    # single element: returns mean (the value itself) without bootstrapping
    result = bootstrap_pf_ci_lower([2.5])
    assert result == pytest.approx(2.5)
    # empty: returns 0.0
    assert bootstrap_pf_ci_lower([]) == pytest.approx(0.0)


def test_classify_wfo_consistency_thresholds():
    # 4/4 profitable -> STRONG (100% >= 75%)
    assert classify_wfo_consistency([1.5, 2.0, 1.1, 3.0]) == "STRONG"
    # 3/4 profitable -> STRONG (75% >= 75%)
    assert classify_wfo_consistency([1.5, 2.0, 0.8, 3.0]) == "STRONG"
    # 2/4 profitable -> WEAK (50% < 55%)
    assert classify_wfo_consistency([1.5, 2.0, 0.8, 0.5]) == "WEAK"
    # 3/5 profitable -> MODERATE (60% >= 55%)
    assert classify_wfo_consistency([1.5, 2.0, 0.8, 0.5, 1.2]) == "MODERATE"
    # empty -> WEAK
    assert classify_wfo_consistency([]) == "WEAK"
