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
    _get_max_ref_deviation_pct,
    check_entry_price_sanity,
    is_entry_price_sane,
    is_entry_price_sanity_enabled,
    is_offline_fallback_source,
    is_price_ref_check_enabled,
    is_require_live_source_enabled,
    robust_recent_reference,
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
        # Isolate the ATR-delta path: this fixture's spot (85) sits far from its
        # synthetic bars (~95-124), which the era-aware reference check would
        # (correctly) flag. Disable that check so this test exercises only the
        # ATR threshold it is asserting on.
        monkeypatch.setenv("ENABLE_PRICE_REF_CONTAMINATION_CHECK", "0")

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


# ---------------------------------------------------------------------------
# Min-ATR floor guard (§6.5 — MGC low-vol overnight regime)
# ---------------------------------------------------------------------------


class TestMinAtrFloor:
    """Tests for ENTRY_PRICE_SANITY_MIN_ATR / min_atr_floor parameter (§6.5).

    MGC scenario: 1h ATR drops to 0.5-0.8 pts during the 10pm-2am CT window.
    Without a floor, a valid entry 0.9 pts from market would be flagged
    (delta/ATR = 0.9/0.7 ≈ 1.29 > 1.0).  With min_atr_floor=1.5, effective
    ATR = max(0.7, 1.5) = 1.5, so delta/ATR = 0.9/1.5 = 0.60 ≤ 1.0 → passes.

    The 2026-05-09 corruption case (delta=13.5) is unaffected:
    13.5/max(10, 1.5) = 13.5/10 = 1.35 > 1.0 → still rejected.
    """

    def test_low_vol_entry_fails_without_floor(self):
        """Entry 0.9 pts from market, ATR=0.7 → fails at default threshold."""
        is_sane, reason = is_entry_price_sane(
            symbol="MGC",
            entry_price=3200.9,
            market_price=3200.0,
            atr=0.7,
            max_atr_delta=1.0,
            min_atr_floor=0.0,
        )
        # delta/ATR = 0.9/0.7 ≈ 1.29 > 1.0 → rejected
        assert is_sane is False

    def test_low_vol_entry_passes_with_floor(self):
        """Same entry passes when min_atr_floor lifts effective ATR to 1.5."""
        is_sane, reason = is_entry_price_sane(
            symbol="MGC",
            entry_price=3200.9,
            market_price=3200.0,
            atr=0.7,
            max_atr_delta=1.0,
            min_atr_floor=1.5,
        )
        # effective_ATR = max(0.7, 1.5) = 1.5; delta/ATR = 0.9/1.5 = 0.60 ≤ 1.0
        assert is_sane is True
        assert reason == ""

    def test_floor_does_not_weaken_normal_vol_check(self):
        """When measured ATR > floor, the floor has no effect."""
        # ATR=2.5 >> floor=1.5 → effective_ATR=2.5, threshold unchanged
        is_sane_no_floor, _ = is_entry_price_sane(
            symbol="MGC",
            entry_price=3205.0,
            market_price=3200.0,
            atr=2.5,
            max_atr_delta=1.0,
            min_atr_floor=0.0,
        )
        is_sane_with_floor, _ = is_entry_price_sane(
            symbol="MGC",
            entry_price=3205.0,
            market_price=3200.0,
            atr=2.5,
            max_atr_delta=1.0,
            min_atr_floor=1.5,
        )
        # Both should return identical results
        assert is_sane_no_floor == is_sane_with_floor

    def test_corruption_case_still_rejected_with_floor(self):
        """2026-05-09 corruption (delta=13.5, ATR=10) is rejected even with floor=1.5."""
        is_sane, reason = is_entry_price_sane(
            symbol="MES",
            entry_price=7398.5481,
            market_price=7385.0,
            atr=10.0,
            max_atr_delta=1.0,
            min_atr_floor=1.5,
        )
        # effective_ATR = max(10, 1.5) = 10; delta/ATR = 13.5481/10 = 1.35 > 1.0
        assert is_sane is False
        assert "7398.5481" in reason

    def test_floor_note_in_rejection_reason(self):
        """When the floor lifts effective ATR, the rejection reason says so."""
        is_sane, reason = is_entry_price_sane(
            symbol="MGC",
            entry_price=3202.0,  # delta=2.0; effective_ATR=1.5 → 1.33 > 1.0
            market_price=3200.0,
            atr=0.7,
            max_atr_delta=1.0,
            min_atr_floor=1.5,
        )
        assert is_sane is False
        assert "floored" in reason or "min_atr_floor" in reason

    def test_env_var_min_atr_floor_read(self, monkeypatch):
        """ENTRY_PRICE_SANITY_MIN_ATR env var is read by _get_min_atr_floor."""
        from risk.entry_price_sanity import _get_min_atr_floor

        monkeypatch.setenv("ENTRY_PRICE_SANITY_MIN_ATR", "1.5")
        assert _get_min_atr_floor() == 1.5

        monkeypatch.delenv("ENTRY_PRICE_SANITY_MIN_ATR", raising=False)
        assert _get_min_atr_floor() == 0.0

    @pytest.mark.asyncio
    async def test_async_wrapper_reads_floor_from_env(self, monkeypatch):
        """check_entry_price_sanity passes min_atr_floor from env to predicate."""
        monkeypatch.setenv("ENTRY_PRICE_SANITY_MIN_ATR", "1.5")
        monkeypatch.delenv("ENTRY_PRICE_SANITY_MAX_ATR_DELTA", raising=False)

        mock_dm = MagicMock()
        mock_dm.get_current_price = AsyncMock(return_value={"last_price": 3200.0})

        # Build bars that yield ATR ≈ 0.7 (low-vol MGC overnight)
        rows = 20
        df = pd.DataFrame(
            {
                "high": [3200.5] * rows,
                "low": [3199.8] * rows,
                "close": [3200.0] * rows,
            }
        )
        mock_dm.get_bars = AsyncMock(return_value=df)

        # Entry 0.9 pts from market; ATR ≈ 0.7 → fails without floor, passes with floor=1.5
        is_sane, reason = await check_entry_price_sanity(
            symbol="MGC",
            entry_price=3200.9,
            data_manager=mock_dm,
        )
        assert is_sane is True, f"Expected floor=1.5 to allow MGC low-vol entry but got: {reason}"


# ---------------------------------------------------------------------------
# Era-aware reference contamination check (2026-06-12 MES 5300 incident)
# ---------------------------------------------------------------------------


def _mes_bars(closes):
    """Build a minimal OHLCV frame from a list of closes (high/low padded)."""
    return pd.DataFrame(
        {
            "high": [c + 1.0 for c in closes],
            "low": [c - 1.0 for c in closes],
            "close": list(closes),
        }
    )


class TestRobustRecentReference:
    def test_median_is_outlier_robust(self):
        # mostly-7400 with two contaminated 5300 bars → median stays ~7400
        closes = [7400.0] * 46 + [5300.0, 5300.1]
        ref = robust_recent_reference(_mes_bars(closes))
        assert ref is not None and 7390 <= ref <= 7410

    def test_empty_returns_none(self):
        assert robust_recent_reference(pd.DataFrame()) is None
        assert robust_recent_reference(None) is None


class TestEraAwareReferenceCheck:
    """The ATR check compares entry vs the spot quote; when BOTH come from the
    same contaminated source they agree and it passes. The reference check is
    the second line of defense."""

    def test_wrong_era_entry_rejected_against_reference(self):
        # entry 5300 (band-valid 2024 MES price) vs recent reference 7400
        is_sane, reason = is_entry_price_sane(
            symbol="MES",
            entry_price=5300.375,
            market_price=5300.1,  # contaminated spot agrees with entry → ATR check blind
            atr=12.0,
            recent_ref=7400.0,
        )
        assert is_sane is False
        assert "reference" in reason.lower()

    def test_contaminated_spot_quote_rejected(self):
        # spot quote itself is stale (5300) vs reference 7400 → fail-safe NO_TRADE
        is_sane, reason = is_entry_price_sane(
            symbol="MES",
            entry_price=5300.0,
            market_price=5300.0,
            atr=12.0,
            recent_ref=7400.0,
        )
        assert is_sane is False
        assert "stale" in reason.lower() or "unreliable" in reason.lower()

    def test_clean_current_price_passes_reference(self):
        is_sane, reason = is_entry_price_sane(
            symbol="MES",
            entry_price=7423.75,
            market_price=7423.5,
            atr=12.0,
            recent_ref=7400.0,
        )
        assert is_sane is True, reason

    def test_no_reference_is_backward_compatible(self):
        # recent_ref=None → reference check skipped entirely (old behavior)
        is_sane, _ = is_entry_price_sane(
            symbol="MES",
            entry_price=5300.0,
            market_price=5300.0,
            atr=12.0,
            recent_ref=None,
        )
        assert is_sane is True

    def test_legit_move_within_threshold_passes(self):
        # a real ~5% move from the reference is allowed (not corruption)
        is_sane, _ = is_entry_price_sane(
            symbol="MES",
            entry_price=7770.0,
            market_price=7770.0,
            atr=12.0,
            recent_ref=7400.0,
            max_ref_deviation_pct=0.15,
        )
        assert is_sane is True


class TestPriceRefFlags:
    def test_ref_check_default_enabled(self, monkeypatch):
        monkeypatch.delenv("ENABLE_PRICE_REF_CONTAMINATION_CHECK", raising=False)
        assert is_price_ref_check_enabled() is True

    def test_ref_check_disable(self, monkeypatch):
        monkeypatch.setenv("ENABLE_PRICE_REF_CONTAMINATION_CHECK", "0")
        assert is_price_ref_check_enabled() is False

    def test_ref_deviation_default(self, monkeypatch):
        monkeypatch.delenv("ENTRY_PRICE_SANITY_MAX_REF_DEVIATION_PCT", raising=False)
        assert _get_max_ref_deviation_pct() == 0.15

    def test_ref_deviation_env_override(self, monkeypatch):
        monkeypatch.setenv("ENTRY_PRICE_SANITY_MAX_REF_DEVIATION_PCT", "0.25")
        assert _get_max_ref_deviation_pct() == 0.25


class TestEraAwareAsyncRegression:
    @pytest.mark.asyncio
    async def test_2026_06_12_mes_5300_incident_rejected(self, monkeypatch):
        """Reproduce the live incident end-to-end: a stale 5300 spot quote, but
        the recent bars are mostly 7400 → the reference check must reject."""
        monkeypatch.delenv("ENABLE_PRICE_REF_CONTAMINATION_CHECK", raising=False)
        mock_dm = MagicMock()
        # contaminated spot quote
        mock_dm.get_current_price = AsyncMock(return_value={"last_price": 5300.1})
        # 30d of mostly-clean 7400 bars with the two contaminated tail bars
        closes = [7400.0 + (i % 5) for i in range(60)] + [5300.0, 5300.1]
        mock_dm.get_bars = AsyncMock(return_value=_mes_bars(closes))

        is_sane, reason = await check_entry_price_sanity(
            symbol="MES",
            entry_price=5300.375,
            data_manager=mock_dm,
        )
        assert is_sane is False, "stale-cache 5300 MES trade must be rejected"
        assert "reference" in reason.lower()

    @pytest.mark.asyncio
    async def test_clean_mes_trade_still_passes(self, monkeypatch):
        monkeypatch.delenv("ENABLE_PRICE_REF_CONTAMINATION_CHECK", raising=False)
        mock_dm = MagicMock()
        mock_dm.get_current_price = AsyncMock(return_value={"last_price": 7423.5})
        closes = [7400.0 + (i % 8) for i in range(60)]
        mock_dm.get_bars = AsyncMock(return_value=_mes_bars(closes))
        is_sane, reason = await check_entry_price_sanity(
            symbol="MES",
            entry_price=7423.75,
            data_manager=mock_dm,
        )
        assert is_sane is True, f"clean MES trade should pass: {reason}"


# ---------------------------------------------------------------------------
# Offline-fallback provenance anchor (2026-06-16 MES 5299 short incident)
# ---------------------------------------------------------------------------


class TestOfflineFallbackProvenance:
    """The absolute anchor: when the live feed is fully degraded, get_current_price
    returns source='csv_cache'/'unavailable'. The relative ATR + reference checks
    are blind in that case (entry≈market≈bars all from the same offline cache), so
    the entry MUST be rejected on provenance alone — the failure mode that let the
    MES short @5299 enqueue against a real ~7520 market on 2026-06-16."""

    def test_predicate_flags_offline_sources(self):
        assert is_offline_fallback_source("csv_cache") is True
        assert is_offline_fallback_source("unavailable") is True
        assert is_offline_fallback_source("error") is True
        assert is_offline_fallback_source("CSV_CACHE") is True  # case-insensitive

    def test_predicate_passes_live_and_unknown_sources(self):
        # live feeds — never blocked
        for src in ("ibkr", "schwab", "tradingview", "polygon_stream", "redis_fabric"):
            assert is_offline_fallback_source(src) is False, src
        # unknown / missing → treated as live (don't block a genuine fill)
        assert is_offline_fallback_source(None) is False
        assert is_offline_fallback_source("") is False

    def test_require_live_default_enabled(self, monkeypatch):
        monkeypatch.delenv("ENTRY_PRICE_SANITY_REQUIRE_LIVE_SOURCE", raising=False)
        assert is_require_live_source_enabled() is True

    def test_require_live_can_be_disabled(self, monkeypatch):
        monkeypatch.setenv("ENTRY_PRICE_SANITY_REQUIRE_LIVE_SOURCE", "0")
        assert is_require_live_source_enabled() is False

    @pytest.mark.asyncio
    async def test_offline_sourced_entry_rejected_even_when_plausible(self, monkeypatch):
        """Reproduce 2026-06-16: a plausible-looking number, but it came from the
        offline cache because IB was down → must be refused, not traded."""
        monkeypatch.delenv("ENTRY_PRICE_SANITY_REQUIRE_LIVE_SOURCE", raising=False)
        mock_dm = MagicMock()
        # entry, spot, AND bars all self-consistently wrong-era (5300) — the exact
        # case the relative checks cannot catch. Source admits it's the cache.
        mock_dm.get_current_price = AsyncMock(
            return_value={"last_price": 5299.875, "source": "csv_cache"}
        )
        mock_dm.get_bars = AsyncMock(return_value=_mes_bars([5300.0 + (i % 4) for i in range(60)]))
        is_sane, reason = await check_entry_price_sanity(
            symbol="MES",
            entry_price=5299.875,
            data_manager=mock_dm,
        )
        assert is_sane is False, "offline-sourced entry must be rejected on provenance"
        assert "offline" in reason.lower() or "no_trade" in reason.lower()

    @pytest.mark.asyncio
    async def test_unavailable_source_rejected(self, monkeypatch):
        monkeypatch.delenv("ENTRY_PRICE_SANITY_REQUIRE_LIVE_SOURCE", raising=False)
        mock_dm = MagicMock()
        mock_dm.get_current_price = AsyncMock(
            return_value={"last_price": None, "source": "unavailable"}
        )
        mock_dm.get_bars = AsyncMock(return_value=_mes_bars([7400.0] * 30))
        is_sane, _ = await check_entry_price_sanity(
            symbol="MES", entry_price=7423.0, data_manager=mock_dm
        )
        assert is_sane is False

    @pytest.mark.asyncio
    async def test_offline_source_allowed_when_anchor_disabled(self, monkeypatch):
        """Opt-out: with the anchor disabled, an offline-sourced but otherwise-clean
        price falls through to the relative checks (backward-compatible escape hatch)."""
        monkeypatch.setenv("ENTRY_PRICE_SANITY_REQUIRE_LIVE_SOURCE", "0")
        monkeypatch.delenv("ENABLE_PRICE_REF_CONTAMINATION_CHECK", raising=False)
        mock_dm = MagicMock()
        mock_dm.get_current_price = AsyncMock(
            return_value={"last_price": 7423.5, "source": "csv_cache"}
        )
        mock_dm.get_bars = AsyncMock(return_value=_mes_bars([7400.0 + (i % 8) for i in range(60)]))
        is_sane, reason = await check_entry_price_sanity(
            symbol="MES", entry_price=7423.75, data_manager=mock_dm
        )
        assert is_sane is True, f"anchor disabled → clean numbers should pass: {reason}"

    @pytest.mark.asyncio
    async def test_live_source_passes(self, monkeypatch):
        monkeypatch.delenv("ENTRY_PRICE_SANITY_REQUIRE_LIVE_SOURCE", raising=False)
        monkeypatch.delenv("ENABLE_PRICE_REF_CONTAMINATION_CHECK", raising=False)
        mock_dm = MagicMock()
        mock_dm.get_current_price = AsyncMock(
            return_value={"last_price": 7423.5, "source": "ibkr"}
        )
        mock_dm.get_bars = AsyncMock(return_value=_mes_bars([7400.0 + (i % 8) for i in range(60)]))
        is_sane, reason = await check_entry_price_sanity(
            symbol="MES", entry_price=7423.75, data_manager=mock_dm
        )
        assert is_sane is True, f"live-sourced clean trade should pass: {reason}"
