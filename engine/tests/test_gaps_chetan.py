"""Tests for engine/backtest/gaps_chetan.py."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from backtest.gaps_chetan import compute_chetan_gaps


def _make_df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _base_row(open_=100.0, high=101.0, low=99.0, close=100.5, volume=1000):
    return {"open": open_, "high": high, "low": low, "close": close, "volume": volume}


# ---------------------------------------------------------------------------
# 1. Gap DOWN detection
# ---------------------------------------------------------------------------

class TestGapDown:
    def test_gap_down_detected(self):
        """Prior low (98.0) minus current high (97.0) = 1.0 > 0.10 → DOWN."""
        df = _make_df([
            {"open": 100, "high": 101, "low": 98, "close": 100, "volume": 500},
            {"open": 96,  "high": 97,  "low": 95, "close": 96,  "volume": 500},
        ])
        result = compute_chetan_gaps(df)
        assert result.loc[1, "chetan_gap_detected"] is True or result.loc[1, "chetan_gap_detected"]
        assert result.loc[1, "chetan_gap_direction"] == "DOWN"

    def test_gap_down_zone_bounds(self):
        """gap_top = prior low, gap_bottom = current high."""
        df = _make_df([
            {"open": 100, "high": 101, "low": 98, "close": 100, "volume": 500},
            {"open": 96,  "high": 97,  "low": 95, "close": 96,  "volume": 500},
        ])
        result = compute_chetan_gaps(df)
        assert result.loc[1, "chetan_gap_top"] == pytest.approx(98.0)
        assert result.loc[1, "chetan_gap_bottom"] == pytest.approx(97.0)

    def test_gap_down_exactly_at_threshold(self):
        """Prior low 100.20, current high 100.10 → diff 0.10 → detected (uses int-friendly values)."""
        df = _make_df([
            {"open": 101, "high": 102, "low": 100.20, "close": 101, "volume": 500},
            {"open": 99,  "high": 100.10, "low": 99,  "close": 99,  "volume": 500},
        ])
        result = compute_chetan_gaps(df)
        assert result.loc[1, "chetan_gap_detected"]
        assert result.loc[1, "chetan_gap_direction"] == "DOWN"


# ---------------------------------------------------------------------------
# 2. Gap UP detection
# ---------------------------------------------------------------------------

class TestGapUp:
    def test_gap_up_detected(self):
        """Current low (102.5) minus prior high (102.0) = 0.5 > 0.10 → UP."""
        df = _make_df([
            {"open": 100, "high": 102, "low": 100, "close": 101, "volume": 500},
            {"open": 103, "high": 104, "low": 102.5, "close": 103, "volume": 500},
        ])
        result = compute_chetan_gaps(df)
        assert result.loc[1, "chetan_gap_detected"]
        assert result.loc[1, "chetan_gap_direction"] == "UP"

    def test_gap_up_zone_bounds(self):
        """gap_top = current low, gap_bottom = prior high."""
        df = _make_df([
            {"open": 100, "high": 102, "low": 100, "close": 101, "volume": 500},
            {"open": 103, "high": 104, "low": 102.5, "close": 103, "volume": 500},
        ])
        result = compute_chetan_gaps(df)
        assert result.loc[1, "chetan_gap_top"] == pytest.approx(102.5)
        assert result.loc[1, "chetan_gap_bottom"] == pytest.approx(102.0)


# ---------------------------------------------------------------------------
# 3. No-gap (overlapping bars)
# ---------------------------------------------------------------------------

class TestNoGap:
    def test_overlapping_bars_no_gap(self):
        """Normal overlapping bars → no gap detected."""
        df = _make_df([
            {"open": 100, "high": 102, "low": 99, "close": 101, "volume": 500},
            {"open": 101, "high": 103, "low": 100, "close": 102, "volume": 500},
        ])
        result = compute_chetan_gaps(df)
        assert not result.loc[1, "chetan_gap_detected"]
        assert result.loc[1, "chetan_gap_direction"] == "NONE"

    def test_no_gap_zone_bounds_are_nan(self):
        df = _make_df([
            {"open": 100, "high": 102, "low": 99, "close": 101, "volume": 500},
            {"open": 101, "high": 103, "low": 100, "close": 102, "volume": 500},
        ])
        result = compute_chetan_gaps(df)
        assert math.isnan(result.loc[1, "chetan_gap_top"])
        assert math.isnan(result.loc[1, "chetan_gap_bottom"])

    def test_first_row_always_no_gap(self):
        """First bar has no prior bar → always NONE."""
        df = _make_df([_base_row()])
        result = compute_chetan_gaps(df)
        assert not result.loc[0, "chetan_gap_detected"]
        assert result.loc[0, "chetan_gap_direction"] == "NONE"


# ---------------------------------------------------------------------------
# 4. min_gap_points filter
# ---------------------------------------------------------------------------

class TestMinGapFilter:
    def test_sub_threshold_gap_not_detected(self):
        """Gap of 0.08 below default threshold 0.10 → not detected."""
        df = _make_df([
            {"open": 100, "high": 101, "low": 99.08, "close": 100, "volume": 500},
            {"open": 98,  "high": 99.00, "low": 97,  "close": 98,  "volume": 500},
        ])
        result = compute_chetan_gaps(df)
        assert not result.loc[1, "chetan_gap_detected"]

    def test_custom_threshold_respected(self):
        """Gap of 0.08 (below 0.10 but above 0.05) detected when min_gap_points=0.05."""
        df = _make_df([
            {"open": 100, "high": 101, "low": 99.08, "close": 100, "volume": 500},
            {"open": 98,  "high": 99.00, "low": 97,  "close": 98,  "volume": 500},
        ])
        result = compute_chetan_gaps(df, min_gap_points=0.05)
        assert result.loc[1, "chetan_gap_detected"]
        assert result.loc[1, "chetan_gap_direction"] == "DOWN"

    def test_zero_threshold_catches_any_separation(self):
        """min_gap_points=0 detects even a 0.01-point gap."""
        df = _make_df([
            {"open": 100, "high": 101, "low": 100.01, "close": 100.5, "volume": 500},
            {"open": 99,  "high": 100.00, "low": 99, "close": 99.5, "volume": 500},
        ])
        result = compute_chetan_gaps(df, min_gap_points=0.0)
        assert result.loc[1, "chetan_gap_detected"]


# ---------------------------------------------------------------------------
# 5. Direction classification — multi-row series
# ---------------------------------------------------------------------------

class TestDirectionClassification:
    def test_multi_row_directions(self):
        """Verify direction column across a 4-row series."""
        df = _make_df([
            {"open": 100, "high": 102, "low": 98,    "close": 100, "volume": 500},  # row 0: seed
            {"open": 96,  "high": 97,  "low": 95,    "close": 96,  "volume": 500},  # row 1: DOWN (98-97=1)
            {"open": 96,  "high": 97,  "low": 95,    "close": 96,  "volume": 500},  # row 2: no gap (97-95 overlap)
            {"open": 99,  "high": 100, "low": 97.20, "close": 99,  "volume": 500},  # row 3: UP (97.20-97=0.20)
        ])
        result = compute_chetan_gaps(df)
        assert result.loc[0, "chetan_gap_direction"] == "NONE"
        assert result.loc[1, "chetan_gap_direction"] == "DOWN"
        assert result.loc[2, "chetan_gap_direction"] == "NONE"
        assert result.loc[3, "chetan_gap_direction"] == "UP"

    def test_output_columns_present(self):
        """All four expected columns exist in output."""
        df = _make_df([_base_row(), _base_row()])
        result = compute_chetan_gaps(df)
        for col in ("chetan_gap_detected", "chetan_gap_direction",
                    "chetan_gap_top", "chetan_gap_bottom"):
            assert col in result.columns

    def test_original_columns_preserved(self):
        """Original OHLCV columns are untouched."""
        df = _make_df([_base_row(), _base_row()])
        result = compute_chetan_gaps(df)
        for col in ("open", "high", "low", "close", "volume"):
            assert col in result.columns
        assert len(result) == 2
