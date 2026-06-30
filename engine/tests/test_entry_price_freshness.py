"""
JARVIS TRADER — Entry-Price Bar-Freshness Anchor Tests
======================================================
Covers the bar-timestamp freshness anchor added to risk/entry_price_sanity.py.

Motivating incident: 2026-06-29 autonomous-auto-approve contamination — MES paper
fills booked at a months-old cached ~5300 while the real market was ~7497. The IB
paper-account market-data subscription was down (Error 10168), so get_bars fell
through to a stale CSV cache. The cache was internally self-consistent
(entry ≈ market ≈ recent-median, all from the same wrong era) and the spot quote
did NOT tag itself 'csv_cache', so the provenance, ATR and era anchors all passed.
The ONE orthogonal signal they cannot see is the bar's own AGE — that is what this
anchor adds.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

from risk.entry_price_sanity import (
    _DEFAULT_MAX_BAR_AGE_SECONDS,
    _get_max_bar_age_seconds,
    check_entry_price_sanity,
    is_bar_freshness_check_enabled,
    latest_bar_age_seconds,
)

# ---------------------------------------------------------------------------
# Flag + env-threshold helpers
# ---------------------------------------------------------------------------


class TestFreshnessFlag:
    def test_enabled_by_default(self, monkeypatch):
        monkeypatch.delenv("ENABLE_ENTRY_PRICE_FRESHNESS", raising=False)
        assert is_bar_freshness_check_enabled() is True

    @pytest.mark.parametrize("val", ["0", "false", "no", "off", "OFF"])
    def test_disabled_via_env(self, monkeypatch, val):
        monkeypatch.setenv("ENABLE_ENTRY_PRICE_FRESHNESS", val)
        assert is_bar_freshness_check_enabled() is False


class TestMaxBarAgeEnv:
    def test_default_when_unset(self, monkeypatch):
        monkeypatch.delenv("ENTRY_PRICE_MAX_BAR_AGE_SECONDS", raising=False)
        assert _get_max_bar_age_seconds() == _DEFAULT_MAX_BAR_AGE_SECONDS == 7200

    def test_honors_valid_override(self, monkeypatch):
        monkeypatch.setenv("ENTRY_PRICE_MAX_BAR_AGE_SECONDS", "300")
        assert _get_max_bar_age_seconds() == 300

    def test_floors_below_60_to_default(self, monkeypatch):
        # values below the 60s floor are rejected -> fall back to default
        monkeypatch.setenv("ENTRY_PRICE_MAX_BAR_AGE_SECONDS", "30")
        assert _get_max_bar_age_seconds() == _DEFAULT_MAX_BAR_AGE_SECONDS

    def test_garbage_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("ENTRY_PRICE_MAX_BAR_AGE_SECONDS", "not-a-number")
        assert _get_max_bar_age_seconds() == _DEFAULT_MAX_BAR_AGE_SECONDS


# ---------------------------------------------------------------------------
# Pure helper: latest_bar_age_seconds
# ---------------------------------------------------------------------------


def _bars_with_index(end: pd.Timestamp, periods: int = 30) -> pd.DataFrame:
    idx = pd.date_range(end=end, periods=periods, freq="1h")
    return pd.DataFrame(
        {
            "high": [7402.0] * periods,
            "low": [7398.0] * periods,
            "close": [7400.0] * periods,
        },
        index=idx,
    )


class TestLatestBarAgeSeconds:
    def test_datetimeindex_age(self):
        now = pd.Timestamp("2026-06-29T12:00:00", tz="UTC")
        df = _bars_with_index(now - pd.Timedelta(seconds=1800))
        age = latest_bar_age_seconds(df, now=now)
        assert age == pytest.approx(1800.0, abs=1.0)

    def test_naive_index_assumed_utc(self):
        now = pd.Timestamp("2026-06-29T12:00:00", tz="UTC")
        idx = pd.date_range(end="2026-06-29T11:00:00", periods=5, freq="1h")  # tz-naive
        df = pd.DataFrame({"close": [7400.0] * 5}, index=idx)
        age = latest_bar_age_seconds(df, now=now)
        assert age == pytest.approx(3600.0, abs=1.0)

    def test_timestamp_column_fallback(self):
        now = pd.Timestamp("2026-06-29T12:00:00", tz="UTC")
        df = pd.DataFrame(
            {
                "timestamp": pd.date_range(end=now - pd.Timedelta(hours=2), periods=3, freq="1h"),
                "close": [7400.0, 7401.0, 7402.0],
            }
        )  # plain RangeIndex; timestamp carried in a column
        age = latest_bar_age_seconds(df, now=now)
        assert age == pytest.approx(7200.0, abs=1.0)

    def test_rangeindex_no_timestamp_returns_none(self):
        df = pd.DataFrame({"close": [7400.0] * 5})  # no DatetimeIndex, no ts column
        assert latest_bar_age_seconds(df) is None

    def test_empty_df_returns_none(self):
        assert latest_bar_age_seconds(pd.DataFrame()) is None

    def test_none_returns_none(self):
        assert latest_bar_age_seconds(None) is None


# ---------------------------------------------------------------------------
# Integration: check_entry_price_sanity gated on freshness
# ---------------------------------------------------------------------------


def _mock_dm(bars: pd.DataFrame, last_price: float = 7400.0, source: str = "ibkr"):
    dm = MagicMock()
    dm.get_current_price = AsyncMock(return_value={"last_price": last_price, "source": source})
    dm.get_bars = AsyncMock(return_value=bars)
    return dm


class TestFreshnessIntegration:
    @pytest.mark.asyncio
    async def test_stale_bars_rejected_even_when_price_plausible(self, monkeypatch):
        """The 2026-06-29 case: every relative check passes (entry≈market≈median,
        live-looking source) but the latest bar is 5h old -> rejected on age."""
        monkeypatch.delenv("ENABLE_ENTRY_PRICE_FRESHNESS", raising=False)
        monkeypatch.delenv("ENTRY_PRICE_MAX_BAR_AGE_SECONDS", raising=False)
        stale = _bars_with_index(pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=5))
        dm = _mock_dm(stale)

        is_sane, reason = await check_entry_price_sanity(
            symbol="MES", entry_price=7400.0, data_manager=dm
        )
        assert is_sane is False
        assert "STALE bar" in reason

    @pytest.mark.asyncio
    async def test_fresh_bars_pass(self, monkeypatch):
        monkeypatch.delenv("ENABLE_ENTRY_PRICE_FRESHNESS", raising=False)
        monkeypatch.delenv("ENTRY_PRICE_MAX_BAR_AGE_SECONDS", raising=False)
        monkeypatch.delenv("ENTRY_PRICE_SANITY_MAX_ATR_DELTA", raising=False)
        fresh = _bars_with_index(pd.Timestamp.now(tz="UTC") - pd.Timedelta(minutes=30))
        dm = _mock_dm(fresh)

        is_sane, reason = await check_entry_price_sanity(
            symbol="MES", entry_price=7400.0, data_manager=dm
        )
        assert is_sane is True, f"expected fresh+plausible to pass, got: {reason}"

    @pytest.mark.asyncio
    async def test_freshness_disabled_does_not_block_stale(self, monkeypatch):
        """With the anchor disabled, stale-but-self-consistent bars pass the
        relative checks (proves the gate is isolated to the freshness flag)."""
        monkeypatch.setenv("ENABLE_ENTRY_PRICE_FRESHNESS", "0")
        monkeypatch.delenv("ENTRY_PRICE_SANITY_MAX_ATR_DELTA", raising=False)
        stale = _bars_with_index(pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=5))
        dm = _mock_dm(stale)

        is_sane, reason = await check_entry_price_sanity(
            symbol="MES", entry_price=7400.0, data_manager=dm
        )
        assert is_sane is True, f"freshness disabled should not reject on age, got: {reason}"

    @pytest.mark.asyncio
    async def test_untimestamped_bars_skip_freshness(self, monkeypatch):
        """Timestamp-less synthetic frames (no DatetimeIndex/ts column) must not
        false-trip — the anchor skips and the relative anchors decide."""
        monkeypatch.delenv("ENABLE_ENTRY_PRICE_FRESHNESS", raising=False)
        monkeypatch.delenv("ENTRY_PRICE_SANITY_MAX_ATR_DELTA", raising=False)
        rows = 30
        df = pd.DataFrame(
            {"high": [7402.0] * rows, "low": [7398.0] * rows, "close": [7400.0] * rows}
        )  # RangeIndex, no timestamp
        dm = _mock_dm(df)

        is_sane, reason = await check_entry_price_sanity(
            symbol="MES", entry_price=7400.0, data_manager=dm
        )
        assert is_sane is True, f"untimestamped bars should skip freshness, got: {reason}"
