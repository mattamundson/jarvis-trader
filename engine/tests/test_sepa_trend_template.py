"""Tests for engine/analytics/sepa_trend_template.py.

Covers:

1. Pure Stage 2 uptrend (synthetic steady uptrend) → score = 1.0 with
   benchmark supplied, and every criterion True.
2. Pure downtrend → score = 0.0, every criterion False.
3. Range-bound series → mixed score with explicit reason strings.
4. Short series insufficient for SMA-200 → evaluates only what it can.
5. ``is_stage_2_uptrend`` threshold behavior.
6. Optional benchmark: when None, criterion 8 is skipped (not failed).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from analytics.sepa_trend_template import (
    SEPAResult,
    _relative_strength_percentile,
    evaluate_sepa,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _uptrend(n: int = 400, start: float = 50.0, slope: float = 0.25) -> pd.Series:
    """Steady linear uptrend with tiny noise."""
    rng = np.random.default_rng(42)
    trend = np.arange(n) * slope + start
    noise = rng.normal(0, 0.1, size=n)
    return pd.Series(trend + noise)


def _downtrend(n: int = 400, start: float = 150.0, slope: float = -0.25) -> pd.Series:
    rng = np.random.default_rng(7)
    trend = np.arange(n) * slope + start
    noise = rng.normal(0, 0.1, size=n)
    return pd.Series(trend + noise).clip(lower=1.0)


def _rangebound(n: int = 400, center: float = 100.0, amp: float = 2.0) -> pd.Series:
    idx = np.arange(n)
    return pd.Series(center + amp * np.sin(idx / 10.0))


# ---------------------------------------------------------------------------
# Happy path: uptrend
# ---------------------------------------------------------------------------


def test_pure_uptrend_hits_all_criteria_with_benchmark():
    close = _uptrend()
    # Benchmark flat → close dramatically outperforms → RS ≫ 70
    benchmark = pd.Series(np.full(len(close), 100.0))
    result = evaluate_sepa(close, benchmark_close=benchmark)

    # All 8 criteria should be True on a clean uptrend vs. flat benchmark
    assert result.c1_price_above_long_smas is True
    assert result.c2_sma150_above_sma200 is True
    assert result.c3_sma200_uptrending is True
    assert result.c4_sma50_above_long_smas is True
    assert result.c5_price_above_sma50 is True
    assert result.c6_above_52wk_low_by_pct is True
    assert result.c7_within_52wk_high_pct is True
    assert result.c8_relative_strength_ge_70 is True

    assert result.evaluated_count == 8
    assert result.passed_count == 8
    assert result.score == pytest.approx(1.0)
    assert result.is_stage_2_uptrend() is True
    assert result.reasons_failed == []


def test_pure_uptrend_without_benchmark_skips_c8():
    close = _uptrend()
    result = evaluate_sepa(close)
    assert result.c8_relative_strength_ge_70 is None
    assert result.evaluated_count == 7
    assert result.score == pytest.approx(1.0)
    assert any("c8" in r for r in result.reasons_skipped)


# ---------------------------------------------------------------------------
# Downtrend
# ---------------------------------------------------------------------------


def test_pure_downtrend_fails_everything():
    close = _downtrend()
    result = evaluate_sepa(close)
    # Criteria 1,2,3,4,5,7 must be False on a clean downtrend.
    assert result.c1_price_above_long_smas is False
    assert result.c2_sma150_above_sma200 is False
    assert result.c3_sma200_uptrending is False
    assert result.c4_sma50_above_long_smas is False
    assert result.c5_price_above_sma50 is False
    # c6 (pct above 52wk low) is False — price is at/near the 52wk low
    assert result.c6_above_52wk_low_by_pct is False
    # c7 (within 25% of 52wk high) is False — price is far below the high
    assert result.c7_within_52wk_high_pct is False
    assert result.score == pytest.approx(0.0)
    assert result.is_stage_2_uptrend() is False
    assert len(result.reasons_failed) >= 5


# ---------------------------------------------------------------------------
# Range-bound
# ---------------------------------------------------------------------------


def test_rangebound_series_has_mixed_outcomes():
    close = _rangebound()
    result = evaluate_sepa(close)
    # Range-bound: price roughly tracks all SMAs; ≥ some criteria pass,
    # some fail — the key assertion is that the result is NOT saturated.
    assert 0.0 < result.score < 1.0


# ---------------------------------------------------------------------------
# Short-series behavior
# ---------------------------------------------------------------------------


def test_short_series_skips_long_sma_criteria():
    # 60 bars — enough for SMA50, too few for SMA150/SMA200.
    short = _uptrend(n=60)
    result = evaluate_sepa(short)
    assert result.c1_price_above_long_smas is None  # needs SMA150+200
    assert result.c2_sma150_above_sma200 is None
    assert result.c3_sma200_uptrending is None
    assert result.c4_sma50_above_long_smas is None
    assert result.c5_price_above_sma50 is True
    # Score is computed over whatever was evaluated.
    assert result.evaluated_count >= 1
    assert any("needs" in r for r in result.reasons_skipped)


def test_empty_series_returns_zero_score():
    result = evaluate_sepa(pd.Series(dtype=float))
    assert result.score == 0.0
    assert result.evaluated_count == 0


# ---------------------------------------------------------------------------
# Threshold helper
# ---------------------------------------------------------------------------


def test_is_stage_2_uptrend_threshold():
    # Synthesize a result with score exactly 0.75
    result = SEPAResult(score=0.75)
    assert result.is_stage_2_uptrend(threshold=0.75) is True
    assert result.is_stage_2_uptrend(threshold=0.80) is False


# ---------------------------------------------------------------------------
# Relative strength helper
# ---------------------------------------------------------------------------


def test_rs_percentile_outperformance_above_70():
    close = _uptrend()  # strong uptrend
    benchmark = pd.Series(np.full(len(close), 100.0))  # flat
    rs = _relative_strength_percentile(close, benchmark)
    assert rs is not None
    assert rs >= 70.0


def test_rs_percentile_underperformance_below_30():
    close = _downtrend()
    benchmark = pd.Series(np.full(len(close), 100.0))
    rs = _relative_strength_percentile(close, benchmark)
    assert rs is not None
    assert rs <= 30.0


def test_rs_percentile_clamps_to_100():
    # Extreme outperformance: benchmark slow-grind down, close moonshot.
    n = 300
    close = pd.Series(np.arange(n) * 5.0 + 50.0)
    benchmark = pd.Series(np.arange(n) * -0.1 + 200.0)
    rs = _relative_strength_percentile(close, benchmark)
    assert rs is not None
    assert 0.0 <= rs <= 100.0


def test_rs_percentile_insufficient_history_returns_none():
    rs = _relative_strength_percentile(pd.Series([1.0, 2.0]), pd.Series([1.0, 2.0]))
    assert rs is None


# ---------------------------------------------------------------------------
# Tunable thresholds
# ---------------------------------------------------------------------------


def test_evaluate_sepa_respects_custom_sma_periods():
    close = _uptrend(n=100)
    # With shorter SMAs, the slow MA (30) can be computed — all criteria that
    # depend on it become evaluable on a 100-bar series.
    result = evaluate_sepa(close, sma_fast=5, sma_mid=10, sma_slow=30)
    assert result.c1_price_above_long_smas is True
    assert result.c3_sma200_uptrending is True  # renamed internally, still uses sma_slow


def test_evaluate_sepa_respects_custom_pct_thresholds():
    close = _uptrend()
    # Impossibly tight high threshold → c7 should fail
    result = evaluate_sepa(close, within_high_pct=0.001)
    # On a monotonic uptrend the last bar IS the 52wk high, so pct_below = 0,
    # which satisfies even the tight threshold. Use an impossibly LARGE
    # above-low threshold instead to force a failure.
    result2 = evaluate_sepa(close, above_low_pct=10.0)
    assert result2.c6_above_52wk_low_by_pct is False
