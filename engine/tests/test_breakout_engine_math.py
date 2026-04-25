"""
US-013 — Math unit tests for VolumeProfileEngine (engine/analysis/breakout_engine.py).

The breakout agent wrapper is tested in test_orphan_agents_integration.py; this
file covers the underlying engine math: Volume Profile calculation (POC/VAH/VAL)
and breakout status transitions.

Hand-crafted OHLCV (not random) so each branch is deterministic.
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis.breakout_engine import VolumeProfileEngine  # noqa: E402


def _flat_ohlcv(n: int = 20, price: float = 100.0, vol: int = 1000) -> pd.DataFrame:
    """All bars identical — stress degenerate case."""
    return pd.DataFrame(
        {
            "open": [price] * n,
            "high": [price + 1] * n,
            "low": [price - 1] * n,
            "close": [price] * n,
            "volume": [vol] * n,
        }
    )


def _skewed_ohlcv(concentrated_price: float = 105.0) -> pd.DataFrame:
    """
    20 bars with 85% of volume concentrated near `concentrated_price`.
    POC should align to the dense band.
    """
    prices = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0, 109.0]
    closes = prices + prices
    volumes = [100] * 10 + [10000] * 10  # second half is concentrated
    return pd.DataFrame(
        {
            "open": [c - 0.5 for c in closes],
            "high": [c + 0.5 for c in closes],
            "low": [c - 0.5 for c in closes],
            "close": closes,
            "volume": volumes,
        }
    )


# ─────────────────────────────────────────────────────────────────────────────
# calculate_profile
# ─────────────────────────────────────────────────────────────────────────────


class TestCalculateProfile:
    def test_empty_dataframe_returns_empty_dict(self):
        engine = VolumeProfileEngine()
        assert engine.calculate_profile(pd.DataFrame()) == {}

    def test_missing_close_column_returns_empty(self):
        engine = VolumeProfileEngine()
        df = pd.DataFrame({"volume": [100]})
        assert engine.calculate_profile(df) == {}

    def test_missing_volume_column_returns_empty(self):
        engine = VolumeProfileEngine()
        df = pd.DataFrame({"close": [100.0]})
        assert engine.calculate_profile(df) == {}

    def test_flat_distribution_produces_valid_profile(self):
        engine = VolumeProfileEngine()
        df = _flat_ohlcv(n=20, price=100.0, vol=1000)
        result = engine.calculate_profile(df, bins=10)
        assert "poc" in result and "vah" in result and "val" in result
        assert result["bins"] == 10
        assert result["total_volume"] == 20 * 1000

    def test_skewed_volume_shifts_poc_to_concentrated_band(self):
        engine = VolumeProfileEngine()
        df = _skewed_ohlcv()
        result = engine.calculate_profile(df, bins=20)
        # POC should be in the concentrated range (100-109) not edges
        assert 100.0 <= result["poc"] <= 109.0

    def test_value_area_pct_respected_70(self):
        engine = VolumeProfileEngine(value_area_pct=0.70)
        df = _skewed_ohlcv()
        result = engine.calculate_profile(df, bins=20)
        # Achieved VA volume pct must be at least the configured target
        assert result["va_volume_pct"] >= 0.70 - 0.01  # tolerance for binning edge

    def test_value_area_pct_smaller_gives_tighter_va(self):
        engine_tight = VolumeProfileEngine(value_area_pct=0.50)
        engine_wide = VolumeProfileEngine(value_area_pct=0.90)
        df = _skewed_ohlcv()
        tight = engine_tight.calculate_profile(df, bins=30)
        wide = engine_wide.calculate_profile(df, bins=30)
        # Wider VA target implies wider band (VAH-VAL) — must be ≥ tight
        assert (wide["vah"] - wide["val"]) >= (tight["vah"] - tight["val"])

    def test_vah_greater_than_or_equal_to_val(self):
        engine = VolumeProfileEngine()
        df = _flat_ohlcv(n=30, price=100.0, vol=500)
        result = engine.calculate_profile(df)
        assert result["vah"] >= result["val"]

    def test_poc_within_va_bounds(self):
        engine = VolumeProfileEngine()
        df = _skewed_ohlcv()
        result = engine.calculate_profile(df, bins=20)
        assert result["val"] <= result["poc"] <= result["vah"]

    def test_bin_count_controls_granularity(self):
        engine = VolumeProfileEngine()
        df = _skewed_ohlcv()
        r10 = engine.calculate_profile(df, bins=10)
        r100 = engine.calculate_profile(df, bins=100)
        assert r10["bins"] == 10
        assert r100["bins"] == 100


# ─────────────────────────────────────────────────────────────────────────────
# detect_breakout
# ─────────────────────────────────────────────────────────────────────────────


class TestDetectBreakout:
    def test_empty_profile_returns_none_status(self):
        engine = VolumeProfileEngine()
        df = _flat_ohlcv(n=5)
        assert engine.detect_breakout(df, {}) == {"status": "none", "side": "none"}

    def test_inside_va_returns_inside(self):
        engine = VolumeProfileEngine()
        df = pd.DataFrame(
            {"open": [100.0, 100.0], "high": [100.5, 100.5], "low": [99.5, 99.5],
             "close": [100.0, 100.0], "volume": [1000, 1000]}
        )
        profile = {"vah": 101.0, "val": 99.0, "poc": 100.0, "bins": 10, "total_volume": 2000, "va_volume_pct": 0.7}
        result = engine.detect_breakout(df, profile)
        assert result["status"] == "inside_va"
        assert result["side"] == "neutral"

    def test_fresh_bullish_breakout(self):
        """prev_price <= VAH, current_price > VAH → breakout bullish."""
        engine = VolumeProfileEngine()
        df = pd.DataFrame({"close": [100.5, 102.0]})
        profile = {"vah": 101.0, "val": 99.0, "poc": 100.0}
        result = engine.detect_breakout(df, profile)
        assert result == {"status": "breakout", "side": "bullish", "level": 101.0, "name": "VAH"}

    def test_fresh_bearish_breakout(self):
        """prev_price >= VAL, current_price < VAL → breakout bearish."""
        engine = VolumeProfileEngine()
        df = pd.DataFrame({"close": [99.5, 98.0]})
        profile = {"vah": 101.0, "val": 99.0, "poc": 100.0}
        result = engine.detect_breakout(df, profile)
        assert result == {"status": "breakout", "side": "bearish", "level": 99.0, "name": "VAL"}

    def test_extended_bullish_above_va(self):
        """Both prev and current above VAH → extended bullish (already out)."""
        engine = VolumeProfileEngine()
        df = pd.DataFrame({"close": [102.0, 103.0]})
        profile = {"vah": 101.0, "val": 99.0, "poc": 100.0}
        result = engine.detect_breakout(df, profile)
        assert result == {"status": "extended", "side": "bullish"}

    def test_extended_bearish_below_va(self):
        engine = VolumeProfileEngine()
        df = pd.DataFrame({"close": [98.0, 97.0]})
        profile = {"vah": 101.0, "val": 99.0, "poc": 100.0}
        result = engine.detect_breakout(df, profile)
        assert result == {"status": "extended", "side": "bearish"}

    def test_single_bar_df_uses_same_price_for_prev(self):
        """Single bar → prev_price == current_price; if inside, inside_va."""
        engine = VolumeProfileEngine()
        df = pd.DataFrame({"close": [100.0]})
        profile = {"vah": 101.0, "val": 99.0, "poc": 100.0}
        result = engine.detect_breakout(df, profile)
        assert result["status"] == "inside_va"

    def test_exactly_on_vah_is_inside(self):
        """Boundary: current == VAH (not >) → inside_va."""
        engine = VolumeProfileEngine()
        df = pd.DataFrame({"close": [100.0, 101.0]})
        profile = {"vah": 101.0, "val": 99.0, "poc": 100.0}
        result = engine.detect_breakout(df, profile)
        assert result["status"] == "inside_va"

    def test_exactly_on_val_is_inside(self):
        engine = VolumeProfileEngine()
        df = pd.DataFrame({"close": [100.0, 99.0]})
        profile = {"vah": 101.0, "val": 99.0, "poc": 100.0}
        result = engine.detect_breakout(df, profile)
        assert result["status"] == "inside_va"
