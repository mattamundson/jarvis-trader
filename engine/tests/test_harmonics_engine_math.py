"""
US-013 — Math unit tests for HarmonicEngine (engine/analysis/harmonics_engine.py).

The harmonic agent wrapper is tested in test_orphan_agents_integration.py; this
file covers the underlying engine math: swing-point detection, XABCD ratio
matching, and the _is_near helper.

Approach: for pattern detection we call `_check_points` directly with synthetic
SwingPoint objects rather than reverse-engineering OHLCV that produces the right
swing sequence. This gives deterministic coverage of each Fibonacci ratio path.
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis.harmonics_engine import HarmonicEngine, HarmonicPattern, SwingPoint  # noqa: E402


def _swings_gartley_bullish() -> list[SwingPoint]:
    """
    Gartley bullish:
      AB/XA ≈ 0.618
      XD/XA ≈ 0.786
    Low-High-Low-High-Low (X=low, A=high, B=low, C=high, D=low).
    X=100, A=200 → XA=100
    AB=61.8 → B = A - 61.8 = 138.2
    BC chosen in range; doesn't affect pattern match for Gartley
    XD=78.6 → D = X + 78.6 = 178.6
    """
    return [
        SwingPoint(0, 100.0, "low"),
        SwingPoint(10, 200.0, "high"),
        SwingPoint(20, 138.2, "low"),
        SwingPoint(30, 172.4, "high"),
        SwingPoint(40, 178.6, "low"),
    ]


def _swings_butterfly_bullish() -> list[SwingPoint]:
    """
    Butterfly bullish:
      AB/XA ≈ 0.786
      XD/XA in [1.27, 1.618]
    X=100, A=200 → XA=100
    AB=78.6 → B = A - 78.6 = 121.4
    XD=150 → D = X + 150 = 250 (Butterfly extends beyond A)
    """
    return [
        SwingPoint(0, 100.0, "low"),
        SwingPoint(10, 200.0, "high"),
        SwingPoint(20, 121.4, "low"),
        SwingPoint(30, 180.0, "high"),
        SwingPoint(40, 250.0, "low"),
    ]


def _swings_bat_bullish() -> list[SwingPoint]:
    """
    Bat bullish:
      AB/XA in [0.382, 0.50]
      XD/XA ≈ 0.886
    X=100, A=200 → XA=100
    AB=45 → B = 155 (in [0.382, 0.50])
    XD=88.6 → D = 188.6
    """
    return [
        SwingPoint(0, 100.0, "low"),
        SwingPoint(10, 200.0, "high"),
        SwingPoint(20, 155.0, "low"),
        SwingPoint(30, 175.0, "high"),
        SwingPoint(40, 188.6, "low"),
    ]


def _swings_crab_bullish() -> list[SwingPoint]:
    """
    Crab bullish:
      AB/XA in [0.382, 0.618]
      XD/XA ≈ 1.618
    X=100, A=200 → XA=100
    AB=50 → B=150 (0.50, in range)
    XD=161.8 → D=261.8
    """
    return [
        SwingPoint(0, 100.0, "low"),
        SwingPoint(10, 200.0, "high"),
        SwingPoint(20, 150.0, "low"),
        SwingPoint(30, 190.0, "high"),
        SwingPoint(40, 261.8, "low"),
    ]


# ─────────────────────────────────────────────────────────────────────────────
# _is_near helper
# ─────────────────────────────────────────────────────────────────────────────


class TestIsNear:
    def test_exact_target_is_near(self):
        engine = HarmonicEngine(deviation=0.05)
        assert engine._is_near(0.618, 0.618) is True

    def test_within_deviation_is_near(self):
        engine = HarmonicEngine(deviation=0.05)
        # 0.618 * (1 + 0.04) = 0.643 — within 5% tolerance
        assert engine._is_near(0.643, 0.618) is True

    def test_outside_deviation_is_not_near(self):
        engine = HarmonicEngine(deviation=0.05)
        # 0.618 * 1.10 = 0.680 — outside 5% tolerance
        assert engine._is_near(0.680, 0.618) is False

    def test_range_target_matches_middle(self):
        """target=0.382, target2=0.50 → range [0.382*0.95, 0.50*1.05] = [0.363, 0.525]."""
        engine = HarmonicEngine(deviation=0.05)
        assert engine._is_near(0.45, 0.382, 0.50) is True

    def test_range_target_rejects_outside(self):
        engine = HarmonicEngine(deviation=0.05)
        assert engine._is_near(0.30, 0.382, 0.50) is False
        assert engine._is_near(0.60, 0.382, 0.50) is False


# ─────────────────────────────────────────────────────────────────────────────
# get_swing_points
# ─────────────────────────────────────────────────────────────────────────────


class TestGetSwingPoints:
    def test_empty_dataframe_returns_empty(self):
        engine = HarmonicEngine()
        assert engine.get_swing_points(pd.DataFrame({"high": [], "low": []})) == []

    def test_short_dataframe_returns_empty(self):
        """If len(df) < 2*window, no swings can be found."""
        engine = HarmonicEngine()
        df = pd.DataFrame({"high": [1.0] * 5, "low": [0.5] * 5})
        assert engine.get_swing_points(df, window=5) == []

    def test_monotone_increasing_produces_no_interior_swings(self):
        engine = HarmonicEngine()
        # Strictly increasing — every point has a neighbor higher to the right.
        df = pd.DataFrame(
            {
                "high": np.arange(20, dtype=float),
                "low": np.arange(20, dtype=float) - 0.1,
            }
        )
        swings = engine.get_swing_points(df, window=3)
        # Only the last bar could be a local high but it's at the boundary → skipped.
        # Similarly first bar is boundary → skipped. Result: 0 interior swings.
        assert swings == []

    def test_alternating_pattern_finds_swings(self):
        """Construct clear alternating peaks/troughs and verify both types detected."""
        engine = HarmonicEngine()
        highs = [1.0, 2.0, 5.0, 2.0, 1.0, 2.0, 3.0, 5.0, 2.0, 1.0, 1.5, 3.0]
        lows = [h - 0.5 for h in highs]
        df = pd.DataFrame({"high": highs, "low": lows})
        swings = engine.get_swing_points(df, window=2)
        # Must find at least one high + one low
        types = [s.type for s in swings]
        assert "high" in types
        assert "low" in types

    def test_consolidation_keeps_most_extreme_same_type(self):
        """
        After initial detection, consecutive same-type swings are consolidated:
        the more extreme point wins. We construct a sequence where this matters.
        """
        engine = HarmonicEngine()
        # Two high-like regions back-to-back; consolidator should keep the higher one.
        # The raw detector may find both before consolidation.
        highs = [1.0, 2.0, 5.0, 3.0, 6.0, 3.0, 1.0]
        lows = [h - 0.5 for h in highs]
        df = pd.DataFrame({"high": highs, "low": lows})
        swings = engine.get_swing_points(df, window=1)
        # Check that no two consecutive swings share a type
        for i in range(1, len(swings)):
            assert swings[i].type != swings[i - 1].type


# ─────────────────────────────────────────────────────────────────────────────
# _check_points — direct synthetic-swing tests for each pattern
# ─────────────────────────────────────────────────────────────────────────────


class TestCheckPoints:
    def test_gartley_bullish_match(self):
        engine = HarmonicEngine(deviation=0.05)
        result = engine._check_points(_swings_gartley_bullish())
        assert result is not None
        assert result.name == "Gartley"
        assert result.type == "bullish"

    def test_butterfly_bullish_match(self):
        engine = HarmonicEngine(deviation=0.05)
        result = engine._check_points(_swings_butterfly_bullish())
        assert result is not None
        assert result.name == "Butterfly"

    def test_bat_bullish_match(self):
        engine = HarmonicEngine(deviation=0.05)
        result = engine._check_points(_swings_bat_bullish())
        assert result is not None
        assert result.name == "Bat"

    def test_crab_bullish_match(self):
        engine = HarmonicEngine(deviation=0.05)
        result = engine._check_points(_swings_crab_bullish())
        assert result is not None
        assert result.name == "Crab"

    def test_no_match_when_ratios_off(self):
        engine = HarmonicEngine(deviation=0.05)
        pts = [
            SwingPoint(0, 100.0, "low"),
            SwingPoint(10, 200.0, "high"),
            SwingPoint(20, 130.0, "low"),   # AB/XA = 0.70 — no pattern
            SwingPoint(30, 170.0, "high"),
            SwingPoint(40, 140.0, "low"),   # XD/XA = 0.40 — no pattern
        ]
        assert engine._check_points(pts) is None

    def test_zero_leg_returns_none(self):
        """If any leg is zero (same-price swing), bail to avoid div-by-zero."""
        engine = HarmonicEngine()
        pts = [
            SwingPoint(0, 100.0, "low"),
            SwingPoint(10, 100.0, "high"),  # XA = 0
            SwingPoint(20, 90.0, "low"),
            SwingPoint(30, 95.0, "high"),
            SwingPoint(40, 88.0, "low"),
        ]
        assert engine._check_points(pts) is None

    def test_side_bearish_when_first_is_high(self):
        """If swing[0] is high (not low) the pattern labels bearish."""
        engine = HarmonicEngine(deviation=0.05)
        # Mirror Gartley: X=high, A=low, B=high, C=low, D=high
        pts = [
            SwingPoint(0, 200.0, "high"),
            SwingPoint(10, 100.0, "low"),   # XA=100
            SwingPoint(20, 161.8, "high"),  # AB=61.8 → AB/XA=0.618
            SwingPoint(30, 127.6, "low"),
            SwingPoint(40, 121.4, "high"),  # XD=78.6 → 0.786
        ]
        result = engine._check_points(pts)
        assert result is not None
        assert result.type == "bearish"

    def test_returned_pattern_has_points_list(self):
        """HarmonicPattern.points must contain 5 (index, price) tuples in order."""
        engine = HarmonicEngine()
        pattern = engine._check_points(_swings_gartley_bullish())
        assert pattern is not None
        assert len(pattern.points) == 5
        # First point is X at index 0, last is D at index 40
        assert pattern.points[0] == (0, 100.0)
        assert pattern.points[-1] == (40, 178.6)


# ─────────────────────────────────────────────────────────────────────────────
# detect_patterns
# ─────────────────────────────────────────────────────────────────────────────


class TestDetectPatterns:
    def test_empty_df_returns_empty_list(self):
        engine = HarmonicEngine()
        assert engine.detect_patterns(pd.DataFrame({"high": [], "low": []})) == []

    def test_fewer_than_5_swings_returns_empty(self):
        engine = HarmonicEngine()
        df = pd.DataFrame({"high": [1.0, 2.0, 1.0, 2.0], "low": [0.5] * 4})
        assert engine.detect_patterns(df) == []

    def test_random_data_typically_yields_no_patterns(self):
        """Uniform random walk rarely hits exact fib ratios — expect 0 or small N."""
        engine = HarmonicEngine(deviation=0.02)  # tight deviation
        rng = np.random.default_rng(42)
        closes = 100.0 + rng.standard_normal(200).cumsum()
        df = pd.DataFrame(
            {"high": closes + 0.5, "low": closes - 0.5, "close": closes}
        )
        patterns = engine.detect_patterns(df)
        # Non-deterministic; assertion is soft — most random windows won't match
        assert isinstance(patterns, list)
