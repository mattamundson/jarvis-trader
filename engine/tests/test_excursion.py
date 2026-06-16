"""
Unit tests for engine/analytics/excursion.py

Tests compute_excursion() for both LONG and SHORT with a known synthetic
bars_df, including edge cases (empty bars, non-positive entry, unknown side).
"""

from __future__ import annotations

import pandas as pd
import pytest

from analytics.excursion import compute_excursion, mfe_capture_ratio

# ── Synthetic bar fixtures ────────────────────────────────────────────────────

# LONG trade: entry at 100.0
# bars range: low=[95, 97, 98], high=[102, 105, 103]
#   => min_low = 95  => MAE = (100 - 95) / 100 = 0.05
#   => max_high = 105 => MFE = (105 - 100) / 100 = 0.05
_LONG_BARS = pd.DataFrame(
    {
        "high": [102.0, 105.0, 103.0],
        "low": [98.0, 97.0, 95.0],
        "close": [100.5, 103.0, 98.0],
    }
)

# SHORT trade: entry at 100.0
# bars range: low=[97, 96, 95], high=[101, 104, 102]
#   => max_high = 104 => MAE = (104 - 100) / 100 = 0.04
#   => min_low  =  95 => MFE = (100 -  95) / 100 = 0.05
_SHORT_BARS = pd.DataFrame(
    {
        "high": [101.0, 104.0, 102.0],
        "low": [97.0, 96.0, 95.0],
        "close": [99.0, 98.0, 96.0],
    }
)


# ── compute_excursion tests ───────────────────────────────────────────────────


class TestLong:
    """LONG trade excursion — entry at 100.0, multiplier=5.0, qty=2."""

    def test_mae_pct(self):
        result = compute_excursion("buy", 100.0, _LONG_BARS, multiplier=5.0, qty=2.0)
        assert result["mae_pct"] == pytest.approx(0.05, rel=1e-6)

    def test_mfe_pct(self):
        result = compute_excursion("buy", 100.0, _LONG_BARS, multiplier=5.0, qty=2.0)
        assert result["mfe_pct"] == pytest.approx(0.05, rel=1e-6)

    def test_mae_usd(self):
        # mae_pct * entry_price * multiplier * qty = 0.05 * 100 * 5 * 2 = 50.0
        result = compute_excursion("buy", 100.0, _LONG_BARS, multiplier=5.0, qty=2.0)
        assert result["mae_usd"] == pytest.approx(50.0, rel=1e-6)

    def test_mfe_usd(self):
        result = compute_excursion("buy", 100.0, _LONG_BARS, multiplier=5.0, qty=2.0)
        assert result["mfe_usd"] == pytest.approx(50.0, rel=1e-6)

    def test_bar_count(self):
        result = compute_excursion("buy", 100.0, _LONG_BARS)
        assert result["bar_count"] == 3

    def test_long_aliases(self):
        """All recognized long-side labels should compute identically."""
        for side in ("buy", "long", "buy_to_open", "buy to open", "BUY", "LONG"):
            result = compute_excursion(side, 100.0, _LONG_BARS)
            assert result["mae_pct"] == pytest.approx(0.05, rel=1e-6), f"failed for side={side!r}"

    def test_non_negative(self):
        result = compute_excursion("buy", 100.0, _LONG_BARS)
        assert result["mae_pct"] >= 0.0
        assert result["mfe_pct"] >= 0.0


class TestShort:
    """SHORT trade excursion — entry at 100.0, multiplier=1.0, qty=1."""

    def test_mae_pct(self):
        # short MAE = (max_high - entry) / entry = (104 - 100) / 100 = 0.04
        result = compute_excursion("sell", 100.0, _SHORT_BARS)
        assert result["mae_pct"] == pytest.approx(0.04, rel=1e-6)

    def test_mfe_pct(self):
        # short MFE = (entry - min_low) / entry = (100 - 95) / 100 = 0.05
        result = compute_excursion("sell", 100.0, _SHORT_BARS)
        assert result["mfe_pct"] == pytest.approx(0.05, rel=1e-6)

    def test_mae_usd_unit_multiplier(self):
        # mae_pct * entry_price * 1.0 * 1.0 = 0.04 * 100 = 4.0
        result = compute_excursion("sell", 100.0, _SHORT_BARS, multiplier=1.0, qty=1.0)
        assert result["mae_usd"] == pytest.approx(4.0, rel=1e-6)

    def test_mfe_usd_unit_multiplier(self):
        result = compute_excursion("sell", 100.0, _SHORT_BARS, multiplier=1.0, qty=1.0)
        assert result["mfe_usd"] == pytest.approx(5.0, rel=1e-6)

    def test_short_aliases(self):
        for side in ("sell", "short", "sell_to_open"):
            result = compute_excursion(side, 100.0, _SHORT_BARS)
            assert result["mae_pct"] == pytest.approx(0.04, rel=1e-6), f"failed for side={side!r}"


class TestEdgeCases:
    def test_empty_dataframe(self):
        empty = pd.DataFrame(columns=["high", "low"])
        result = compute_excursion("buy", 100.0, empty)
        assert result["mae_pct"] is None
        assert result["bar_count"] == 0

    def test_none_bars(self):
        result = compute_excursion("buy", 100.0, None)
        assert result["mae_pct"] is None

    def test_missing_columns(self):
        bad = pd.DataFrame({"close": [100.0, 101.0]})
        result = compute_excursion("buy", 100.0, bad)
        assert result["mae_pct"] is None

    def test_zero_entry_price(self):
        result = compute_excursion("buy", 0.0, _LONG_BARS)
        assert result["mae_pct"] is None

    def test_negative_entry_price(self):
        result = compute_excursion("buy", -5.0, _LONG_BARS)
        assert result["mae_pct"] is None

    def test_default_multiplier_qty(self):
        """With multiplier=1, qty=1, usd == pct * entry_price."""
        result = compute_excursion("buy", 100.0, _LONG_BARS, multiplier=1.0, qty=1.0)
        assert result["mae_usd"] == pytest.approx(result["mae_pct"] * 100.0, rel=1e-6)


# ── mfe_capture_ratio tests ───────────────────────────────────────────────────


class TestMfeCaptureRatio:
    def test_equal_mae_mfe(self):
        # If mae == mfe, capture = (mfe - mae) / mfe = 0
        assert mfe_capture_ratio(0.05, 0.05) == pytest.approx(0.0, abs=1e-6)

    def test_zero_mae(self):
        # Perfect exit — no adverse, all favorable
        assert mfe_capture_ratio(0.0, 0.05) == pytest.approx(1.0, rel=1e-6)

    def test_typical_case(self):
        # mae=0.02, mfe=0.05 -> (0.05-0.02)/0.05 = 0.6
        assert mfe_capture_ratio(0.02, 0.05) == pytest.approx(0.6, rel=1e-6)

    def test_zero_mfe_returns_none(self):
        assert mfe_capture_ratio(0.01, 0.0) is None

    def test_none_inputs_return_none(self):
        assert mfe_capture_ratio(None, 0.05) is None
        assert mfe_capture_ratio(0.02, None) is None
        assert mfe_capture_ratio(None, None) is None
