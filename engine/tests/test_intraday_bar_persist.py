"""
Tests for engine.scripts.intraday_bar_persist.

Covers:
  - test_skips_outside_trading_hours: weekend → no fetch, exit 0
  - test_fetches_during_trading_hours: Tuesday 11:00 ET → fetch attempted
  - test_force_bypasses_trading_hours_check: weekend + --force → fetch attempted
  - test_handles_unreachable_data_source_gracefully: get_bars raises → exit 0, no crash

All tests mock MarketDataManager to keep these fully offline.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

# Make engine root importable when pytest runs from the engine directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.intraday_bar_persist import (
    DEFAULT_SYMBOLS,
    INTERVAL,
    _run,
    fetch_symbol,
    is_trading_hours,
)

_ET = ZoneInfo("America/New_York")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _et(weekday: int, hour: int, minute: int = 0) -> datetime:
    """Build a tz-aware datetime at the given Eastern weekday/hour/minute.

    weekday: 0=Mon … 6=Sun.  Uses 2026-05-04 (Monday) as the epoch.
    """
    monday = datetime(2026, 5, 4, tzinfo=_ET)
    dt = monday + timedelta(days=weekday, hours=hour, minutes=minute)
    return dt.astimezone(timezone.utc)


def _make_bars(n: int = 5, symbol: str = "MES") -> pd.DataFrame:
    df = pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-05-07 09:00", periods=n, freq="h", tz="UTC"),
            "open": [5300.0 + i for i in range(n)],
            "high": [5310.0 + i for i in range(n)],
            "low": [5290.0 + i for i in range(n)],
            "close": [5305.0 + i for i in range(n)],
            "volume": [1000.0 + i * 10 for i in range(n)],
        }
    )
    df.attrs["source"] = "ibkr"
    df.attrs["symbol"] = symbol
    return df


# ---------------------------------------------------------------------------
# is_trading_hours unit tests
# ---------------------------------------------------------------------------


class TestIsTradingHours:
    def test_weekday_inside_window(self):
        # Tuesday 11:00 ET → inside
        assert is_trading_hours(_et(1, 11, 0)) is True

    def test_weekday_at_open_boundary(self):
        # Monday 09:25 ET → open boundary
        assert is_trading_hours(_et(0, 9, 25)) is True

    def test_weekday_at_close_boundary(self):
        # Friday 16:05 ET → close boundary
        assert is_trading_hours(_et(4, 16, 5)) is True

    def test_weekday_before_open(self):
        # Wednesday 08:00 ET → before gate open
        assert is_trading_hours(_et(2, 8, 0)) is False

    def test_weekday_after_close(self):
        # Thursday 16:30 ET → after gate close
        assert is_trading_hours(_et(3, 16, 30)) is False

    def test_saturday_mid_day(self):
        # Saturday 12:00 ET → weekend
        assert is_trading_hours(_et(5, 12, 0)) is False

    def test_sunday_mid_day(self):
        # Sunday 12:00 ET → weekend
        assert is_trading_hours(_et(6, 12, 0)) is False


# ---------------------------------------------------------------------------
# test_skips_outside_trading_hours
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_skips_outside_trading_hours():
    """Outside trading hours, _run exits 0 without calling get_bars.

    is_trading_hours is patched False so the test is deterministic regardless of
    the wall-clock — mirroring the sibling tests below. (Previously this test
    built a Saturday datetime but never injected it, so _run read the real clock
    and the test failed in CI whenever it happened to run during live trading
    hours: "Expected 'MarketDataManager' to not have been called. Called 1 times.")
    """
    with (
        patch("scripts.intraday_bar_persist.is_trading_hours", return_value=False),
        patch("scripts.intraday_bar_persist.MarketDataManager") as mock_cls,
    ):
        mock_mgr = MagicMock()
        mock_mgr.initialize = AsyncMock()
        mock_mgr.get_bars = AsyncMock()
        mock_cls.return_value = mock_mgr

        exit_code = await _run(
            symbols=["MES"],
            force=False,
            no_fetch=False,
        )

    # Should return 0 (skip)
    assert exit_code == 0
    # MarketDataManager should never have been constructed
    mock_cls.assert_not_called()


# ---------------------------------------------------------------------------
# test_fetches_during_trading_hours
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetches_during_trading_hours():
    """During trading hours, _run calls get_bars for each symbol and exits 0."""
    # Patch is_trading_hours directly to return True so test doesn't depend on clock
    with (
        patch("scripts.intraday_bar_persist.is_trading_hours", return_value=True),
        patch("scripts.intraday_bar_persist.MarketDataManager") as mock_cls,
    ):
        mock_mgr = MagicMock()
        mock_mgr.initialize = AsyncMock()
        mock_mgr.ibkr = MagicMock()
        mock_mgr.ibkr.disconnect = AsyncMock()
        mock_mgr.get_bars = AsyncMock(return_value=_make_bars(10, "MES"))
        mock_cls.return_value = mock_mgr

        exit_code = await _run(
            symbols=["MES"],
            force=False,
            no_fetch=False,
        )

    assert exit_code == 0
    mock_mgr.get_bars.assert_awaited_once_with(
        symbol="MES",
        lookback_days=14,
        timeframe="1h",
        is_futures=True,
    )


# ---------------------------------------------------------------------------
# test_force_bypasses_trading_hours_check
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_force_bypasses_trading_hours_check():
    """--force causes _run to proceed even when is_trading_hours would return False."""
    with (
        patch("scripts.intraday_bar_persist.is_trading_hours", return_value=False),
        patch("scripts.intraday_bar_persist.MarketDataManager") as mock_cls,
    ):
        mock_mgr = MagicMock()
        mock_mgr.initialize = AsyncMock()
        mock_mgr.ibkr = MagicMock()
        mock_mgr.ibkr.disconnect = AsyncMock()
        mock_mgr.get_bars = AsyncMock(return_value=_make_bars(5, "MGC"))
        mock_cls.return_value = mock_mgr

        exit_code = await _run(
            symbols=["MGC"],
            force=True,
            no_fetch=False,
        )

    assert exit_code == 0
    # get_bars must have been called despite is_trading_hours=False
    mock_mgr.get_bars.assert_awaited_once()


# ---------------------------------------------------------------------------
# test_handles_unreachable_data_source_gracefully
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handles_unreachable_data_source_gracefully():
    """When get_bars raises, _run logs and exits 1 — never propagates the exception."""
    with (
        patch("scripts.intraday_bar_persist.is_trading_hours", return_value=True),
        patch("scripts.intraday_bar_persist.MarketDataManager") as mock_cls,
    ):
        mock_mgr = MagicMock()
        mock_mgr.initialize = AsyncMock()
        mock_mgr.ibkr = MagicMock()
        mock_mgr.ibkr.disconnect = AsyncMock()
        mock_mgr.get_bars = AsyncMock(
            side_effect=ConnectionError("IBKR Gateway not reachable")
        )
        mock_cls.return_value = mock_mgr

        # Should NOT raise — must handle gracefully
        exit_code = await _run(
            symbols=["MES"],
            force=False,
            no_fetch=False,
        )

    # Unexpected exception → exit 1, but no crash/exception propagated
    assert exit_code == 1


# ---------------------------------------------------------------------------
# test_no_fetch_dry_run
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_fetch_dry_run():
    """--no-fetch skips the actual get_bars call entirely."""
    with (
        patch("scripts.intraday_bar_persist.is_trading_hours", return_value=True),
        patch("scripts.intraday_bar_persist.MarketDataManager") as mock_cls,
    ):
        mock_mgr = MagicMock()
        mock_mgr.initialize = AsyncMock()
        mock_mgr.ibkr = MagicMock()
        mock_mgr.ibkr.disconnect = AsyncMock()
        mock_mgr.get_bars = AsyncMock()
        mock_cls.return_value = mock_mgr

        exit_code = await _run(
            symbols=["MES", "MGC"],
            force=False,
            no_fetch=True,
        )

    assert exit_code == 0
    mock_mgr.get_bars.assert_not_called()


# ---------------------------------------------------------------------------
# fetch_symbol unit tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_symbol_returns_row_count():
    """fetch_symbol propagates the row count from get_bars."""
    mock_mgr = MagicMock()
    mock_mgr.get_bars = AsyncMock(return_value=_make_bars(7, "MES"))

    result = await fetch_symbol(mock_mgr, "MES", no_fetch=False)

    assert result["error"] is None
    assert result["rows_returned"] == 7
    assert result["persisted"] is True
    assert result["source"] == "ibkr"


@pytest.mark.asyncio
async def test_fetch_symbol_no_fetch_skips_get_bars():
    """no_fetch=True → get_bars never called."""
    mock_mgr = MagicMock()
    mock_mgr.get_bars = AsyncMock()

    result = await fetch_symbol(mock_mgr, "MES", no_fetch=True)

    mock_mgr.get_bars.assert_not_called()
    assert result["source"] == "dry_run"
    assert result["error"] is None


@pytest.mark.asyncio
async def test_fetch_symbol_empty_df_not_persisted():
    """Empty DataFrame returned → persisted=False, no error."""
    empty = pd.DataFrame()
    empty.attrs["source"] = "none"
    mock_mgr = MagicMock()
    mock_mgr.get_bars = AsyncMock(return_value=empty)

    result = await fetch_symbol(mock_mgr, "MES", no_fetch=False)

    assert result["error"] is None
    assert result["persisted"] is False
    assert result["rows_returned"] == 0
