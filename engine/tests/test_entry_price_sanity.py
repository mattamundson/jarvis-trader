"""
JARVIS TRADER — Entry Price Sanity Check Tests
===============================================
Covers: is_entry_price_sane (pure predicate) + check_entry_price_sanity (async wrapper).

Regression case: 2026-05-09 phantom-trade incident — 6 MES SHORT entries
were inserted at price 7398.5481 (a stop_loss field copied into entry_price).
The real market was ~7385; delta/ATR ~1.35 >> 1.0 threshold.
"""

from __future__ import annotations

import os
from typing import Optional
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

from risk.entry_price_sanity import (
    _compute_atr_from_bars,
    check_entry_price_sanity,
    is_entry_price_sane,
    is_entry_price_sanity_enabled,
)

# ---------------------------------------------------------------------------
# Pure predicate: is_entry_price_sane
# ---------------------------------------------------------------------------


class TestIsEntryPriceSane:
    """Unit tests for the pure is_entry_price_sane function."""

    def test_sane_price_within_atr_passes(self):
        """Entry within 0.5 ATR of market → True."""
        is_sane, reason = is_entry_price_sane(
            symbol="MES",
            entry_price=100.0,
            market_price=100.5,  # delta=0.5, ATR=1.0 → ratio=0.5 <= 1.0
            atr=1.0,
            max_atr_delta=1.0,
        )
        assert is_sane is True
        assert reason == ""

    def test_corrupted_price_far_above_market_rejects(self):
        """2026-05-09 scenario: entry=7398.5481, market=7385, ATR=10 → rejected."""
        is_sane, reason = is_entry_price_sane(
            symbol="MES",
            entry_price=7398.5481,
            market_price=7385.0,
            atr=10.0,
            max_atr_delta=1.0,
        )
        assert is_sane is False
        # delta = 13.5481, ratio = 1.35 > 1.0
        assert "1.35" in reason
        assert "7398.5481" in reason

    def test_atr_unavailable_rejects(self):
        """atr=None → False with 'atr unavailable' reason."""
        is_sane, reason = is_entry_price_sane(
            symbol="MCL",
            entry_price=72.0,
            market_price=71.5,
            atr=None,
            max_atr_delta=1.0,
        )
        assert is_sane is False
        assert "atr unavailable" in reason

    def test_market_price_unavailable_rejects(self):
        """market_price=None → False with 'market price unavailable' reason."""
        is_sane, reason = is_entry_price_sane(
            symbol="MNQ",
            entry_price=17500.0,
            market_price=None,
            atr=15.0,
            max_atr_delta=1.0,
        )
        assert is_sane is False
        assert "market price unavailable" in reason

    def test_zero_atr_rejects(self):
        """atr=0 → False (division-by-zero guard)."""
        is_sane, reason = is_entry_price_sane(
            symbol="MCL",
            entry_price=72.0,
            market_price=72.0,
            atr=0.0,
            max_atr_delta=1.0,
        )
        assert is_sane is False
        assert "zero or negative" in reason or "division guard" in reason

    def test_zero_market_price_rejects(self):
        """market_price=0 → treated as unavailable."""
        is_sane, reason = is_entry_price_sane(
            symbol="MES",
            entry_price=5800.0,
            market_price=0.0,
            atr=10.0,
        )
        assert is_sane is False
        assert "unavailable" in reason

    def test_env_threshold_override(self, monkeypatch):
        """With max_atr_delta=2.0 explicitly, a 1.5-ratio entry now passes."""
        # entry=100, market=85, ATR=10 → delta=15, ratio=1.5
        # Default threshold 1.0 would reject; explicit 2.0 should pass.
        is_sane, reason = is_entry_price_sane(
            symbol="MES",
            entry_price=100.0,
            market_price=85.0,
            atr=10.0,
            max_atr_delta=2.0,
        )
        assert is_sane is True
        assert reason == ""

    def test_exact_boundary_passes(self):
        """Entry exactly at the ATR boundary (ratio==1.0) passes (<= not <)."""
        is_sane, reason = is_entry_price_sane(
            symbol="MES",
            entry_price=110.0,
            market_price=100.0,
            atr=10.0,
            max_atr_delta=1.0,
        )
        assert is_sane is True

    def test_slightly_over_boundary_rejects(self):
        """Entry at ratio 1.01 is rejected."""
        is_sane, reason = is_entry_price_sane(
            symbol="MES",
            entry_price=110.1,
            market_price=100.0,
            atr=10.0,
            max_atr_delta=1.0,
        )
        assert is_sane is False

    def test_2026_05_09_regression(self):
        """Exact 2026-05-09 incident values: entry=7398.5481, market≈7385, ATR≈10.

        On that day the ATR for MES 1h bars was approximately 10-12 points.
        delta = 13.5481 → ratio ≈ 1.35 > 1.0.  Must be rejected.
        """
        # Use ATR=10 as a conservative lower bound (incident ATR was ~10-12)
        is_sane, reason = is_entry_price_sane(
            symbol="MES",
            entry_price=7398.5481,
            market_price=7385.0,
            atr=10.0,
            max_atr_delta=1.0,
        )
        assert is_sane is False, "2026-05-09 corrupted entry must be rejected"
        assert "7398.5481" in reason


# ---------------------------------------------------------------------------
# Feature flag: is_entry_price_sanity_enabled
# ---------------------------------------------------------------------------


class TestIsSanityEnabled:
    """Env-flag tests for is_entry_price_sanity_enabled."""

    def test_default_enabled(self, monkeypatch):
        """Default (no env var) → enabled."""
        monkeypatch.delenv("ENABLE_ENTRY_PRICE_SANITY", raising=False)
        assert is_entry_price_sanity_enabled() is True

    def test_explicit_1_enabled(self, monkeypatch):
        monkeypatch.setenv("ENABLE_ENTRY_PRICE_SANITY", "1")
        assert is_entry_price_sanity_enabled() is True

    def test_explicit_0_disabled(self, monkeypatch):
        monkeypatch.setenv("ENABLE_ENTRY_PRICE_SANITY", "0")
        assert is_entry_price_sanity_enabled() is False

    def test_false_string_disabled(self, monkeypatch):
        monkeypatch.setenv("ENABLE_ENTRY_PRICE_SANITY", "false")
        assert is_entry_price_sanity_enabled() is False

    def test_off_string_disabled(self, monkeypatch):
        monkeypatch.setenv("ENABLE_ENTRY_PRICE_SANITY", "off")
        assert is_entry_price_sanity_enabled() is False


# ---------------------------------------------------------------------------
# Env threshold override via ENTRY_PRICE_SANITY_MAX_ATR_DELTA
# ---------------------------------------------------------------------------


class TestEnvThresholdOverride:
    """Check that ENTRY_PRICE_SANITY_MAX_ATR_DELTA is read at call time."""

    @pytest.mark.asyncio
    async def test_env_threshold_2_passes_1_5_ratio(self, monkeypatch):
        """ENTRY_PRICE_SANITY_MAX_ATR_DELTA=2.0: ratio=1.5 → passes."""
        monkeypatch.setenv("ENTRY_PRICE_SANITY_MAX_ATR_DELTA", "2.0")

        mock_dm = MagicMock()
        mock_dm.get_current_price = AsyncMock(return_value={"last_price": 85.0})

        # Build a DataFrame with enough bars for ATR=10 to be computed
        rows = 30
        df = pd.DataFrame(
            {
                "high": [100.0 + i for i in range(rows)],
                "low": [90.0 + i for i in range(rows)],
                "close": [95.0 + i for i in range(rows)],
            }
        )
        mock_dm.get_bars = AsyncMock(return_value=df)

        is_sane, reason = await check_entry_price_sanity(
            symbol="MES",
            entry_price=100.0,  # delta=15, ATR≈10 → ratio≈1.5
            data_manager=mock_dm,
        )
        assert is_sane is True, f"Expected sane with threshold=2.0 but got: {reason}"


# ---------------------------------------------------------------------------
# Disabled-via-env path skips all checks
# ---------------------------------------------------------------------------


class TestDisabledViaEnv:
    def test_disabled_flag_passes_all(self, monkeypatch):
        """ENABLE_ENTRY_PRICE_SANITY=0: any input passes."""
        monkeypatch.setenv("ENABLE_ENTRY_PRICE_SANITY", "0")
        assert is_entry_price_sanity_enabled() is False
        # With disabled flag, callers skip is_entry_price_sane entirely;
        # but we can also verify the predicate still works independently:
        is_sane, _ = is_entry_price_sane("MES", 9999999.0, 100.0, 1.0)
        assert is_sane is False  # predicate rejects regardless of flag
        # Flag check is what the caller uses to bypass the predicate.


# ---------------------------------------------------------------------------
# Async wrapper: check_entry_price_sanity
# ---------------------------------------------------------------------------


class TestCheckEntryPriceSanity:
    """Tests for the async wrapper that fetches market data from data_manager."""

    @pytest.mark.asyncio
    async def test_sane_price_passes(self, monkeypatch):
        """Reasonable price + working data manager → True."""
        monkeypatch.delenv("ENTRY_PRICE_SANITY_MAX_ATR_DELTA", raising=False)

        mock_dm = MagicMock()
        mock_dm.get_current_price = AsyncMock(return_value={"last_price": 100.0})

        # Build bars where ATR is ~1.0 so entry=100.5 (delta=0.5) passes
        rows = 20
        df = pd.DataFrame(
            {
                "high": [101.0] * rows,
                "low": [99.0] * rows,
                "close": [100.0] * rows,
            }
        )
        mock_dm.get_bars = AsyncMock(return_value=df)

        is_sane, reason = await check_entry_price_sanity(
            symbol="MES",
            entry_price=100.5,
            data_manager=mock_dm,
        )
        assert is_sane is True
        assert reason == ""

    @pytest.mark.asyncio
    async def test_data_manager_price_failure_rejects(self, monkeypatch):
        """When get_current_price raises, market_price=None → rejected."""
        monkeypatch.delenv("ENTRY_PRICE_SANITY_MAX_ATR_DELTA", raising=False)

        mock_dm = MagicMock()
        mock_dm.get_current_price = AsyncMock(side_effect=RuntimeError("no data"))

        rows = 20
        df = pd.DataFrame(
            {
                "high": [101.0] * rows,
                "low": [99.0] * rows,
                "close": [100.0] * rows,
            }
        )
        mock_dm.get_bars = AsyncMock(return_value=df)

        is_sane, reason = await check_entry_price_sanity(
            symbol="MES",
            entry_price=100.5,
            data_manager=mock_dm,
        )
        assert is_sane is False
        assert "market price unavailable" in reason

    @pytest.mark.asyncio
    async def test_corrupted_price_async_rejects(self, monkeypatch):
        """Full async path rejects the 2026-05-09 corrupted price."""
        monkeypatch.delenv("ENTRY_PRICE_SANITY_MAX_ATR_DELTA", raising=False)

        mock_dm = MagicMock()
        mock_dm.get_current_price = AsyncMock(return_value={"last_price": 7385.0})

        rows = 20
        # ATR ~10: high-low spread = 10 per bar
        df = pd.DataFrame(
            {
                "high": [7390.0 + i for i in range(rows)],
                "low": [7380.0 + i for i in range(rows)],
                "close": [7385.0 + i for i in range(rows)],
            }
        )
        mock_dm.get_bars = AsyncMock(return_value=df)

        is_sane, reason = await check_entry_price_sanity(
            symbol="MES",
            entry_price=7398.5481,
            data_manager=mock_dm,
        )
        assert is_sane is False
        assert "7398.5481" in reason


# ---------------------------------------------------------------------------
# ATR computation helper
# ---------------------------------------------------------------------------


class TestComputeAtrFromBars:
    def test_constant_bars_returns_range(self):
        """Constant bars with high-low range 10 → ATR ≈ 10."""
        rows = 20
        df = pd.DataFrame(
            {
                "high": [110.0] * rows,
                "low": [100.0] * rows,
                "close": [105.0] * rows,
            }
        )
        atr = _compute_atr_from_bars(df)
        assert atr is not None
        assert abs(atr - 10.0) < 0.5

    def test_empty_df_returns_none(self):
        assert _compute_atr_from_bars(pd.DataFrame()) is None

    def test_missing_columns_returns_none(self):
        df = pd.DataFrame({"close": [100.0] * 20})
        assert _compute_atr_from_bars(df) is None

    def test_too_few_rows_returns_none(self):
        rows = 5  # < ATR period 14
        df = pd.DataFrame(
            {
                "high": [101.0] * rows,
                "low": [99.0] * rows,
                "close": [100.0] * rows,
            }
        )
        assert _compute_atr_from_bars(df) is None
