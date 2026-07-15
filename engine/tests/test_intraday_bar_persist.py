"""
Tests for engine.scripts.intraday_bar_persist.

Covers:
  - test_skips_outside_trading_hours: weekend → no fetch, exit 0
  - test_fetches_during_trading_hours: Tuesday 11:00 ET → fetch attempted
  - test_force_bypasses_trading_hours_check: weekend + --force → fetch attempted
  - test_handles_unreachable_data_source_gracefully: get_bars raises → exit 0, no crash

is_futures_session_open (formerly is_trading_hours) models the actual CME
Globex MES/MGC session -- nearly 24/5, closed only for the weekend and the
daily 17:00-18:00 ET maintenance halt -- not equities RTH. See
feedback/incident: the old equities-shaped 09:25-16:05 ET gate silently
skipped every futures fetch outside that window.

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
    is_futures_session_open,
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
# is_futures_session_open unit tests
# ---------------------------------------------------------------------------


class TestIsFuturesSessionOpen:
    def test_weekday_mid_session(self):
        # Tuesday 11:00 ET → open (regular weekday session)
        assert is_futures_session_open(_et(1, 11, 0)) is True

    def test_weekday_early_morning(self):
        # Wednesday 03:00 ET → open (this was the exact gap the old equities
        # gate missed -- Globex trades overnight, equities RTH does not)
        assert is_futures_session_open(_et(2, 3, 0)) is True

    def test_daily_maintenance_halt(self):
        # Monday 17:30 ET → closed (daily maintenance halt)
        assert is_futures_session_open(_et(0, 17, 30)) is False

    def test_just_before_maintenance_halt(self):
        # Tuesday 16:59 ET → still open
        assert is_futures_session_open(_et(1, 16, 59)) is True

    def test_just_after_maintenance_halt(self):
        # Tuesday 18:00 ET → reopened
        assert is_futures_session_open(_et(1, 18, 0)) is True

    def test_saturday_mid_day(self):
        # Saturday 12:00 ET → fully closed
        assert is_futures_session_open(_et(5, 12, 0)) is False

    def test_sunday_before_reopen(self):
        # Sunday 12:00 ET → still closed (reopens 18:00 ET)
        assert is_futures_session_open(_et(6, 12, 0)) is False

    def test_sunday_after_reopen(self):
        # Sunday 18:00 ET → open (weekly reopen)
        assert is_futures_session_open(_et(6, 18, 0)) is True

    def test_friday_before_close(self):
        # Friday 16:00 ET → still open
        assert is_futures_session_open(_et(4, 16, 0)) is True

    def test_friday_after_close(self):
        # Friday 17:00 ET → closed for the week
        assert is_futures_session_open(_et(4, 17, 0)) is False


# ---------------------------------------------------------------------------
# test_skips_outside_trading_hours
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_skips_outside_trading_hours():
    """Outside trading hours, _run exits 0 without calling get_bars.

    is_futures_session_open is patched False so the test is deterministic regardless of
    the wall-clock — mirroring the sibling tests below. (Previously this test
    built a Saturday datetime but never injected it, so _run read the real clock
    and the test failed in CI whenever it happened to run during live trading
    hours: "Expected 'MarketDataManager' to not have been called. Called 1 times.")
    """
    with (
        patch("scripts.intraday_bar_persist.is_futures_session_open", return_value=False),
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
    # Patch is_futures_session_open directly to return True so test doesn't depend on clock
    with (
        patch("scripts.intraday_bar_persist.is_futures_session_open", return_value=True),
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
    """--force causes _run to proceed even when is_futures_session_open would return False."""
    with (
        patch("scripts.intraday_bar_persist.is_futures_session_open", return_value=False),
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
    # get_bars must have been called despite is_futures_session_open=False
    mock_mgr.get_bars.assert_awaited_once()


# ---------------------------------------------------------------------------
# test_handles_unreachable_data_source_gracefully
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handles_unreachable_data_source_gracefully():
    """When get_bars raises, _run logs and exits 1 — never propagates the exception."""
    with (
        patch("scripts.intraday_bar_persist.is_futures_session_open", return_value=True),
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
        patch("scripts.intraday_bar_persist.is_futures_session_open", return_value=True),
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
