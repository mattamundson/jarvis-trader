"""Waterfall behavior for MarketDataManager — IBKR Tier 1 when connected."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

from data.market_data import MarketDataManager


class _MinimalConfig:
    """Enough for MarketDataManager construction paths used in tests."""

    IBKR_HOST = "127.0.0.1"
    IBKR_PORT = 4002
    IBKR_CLIENT_ID = 1
    POLYGON_API_KEY = ""
    FINNHUB_API_KEY = ""
    FRED_API_KEY = None


@pytest.mark.asyncio
async def test_get_current_price_uses_ibkr_when_connected() -> None:
    mgr = MarketDataManager(_MinimalConfig())
    mock_ib = MagicMock()
    mock_ib.is_connected = True
    mock_ib.get_snapshot_price = AsyncMock(
        return_value={
            "last_price": 71.5,
            "prev_close": 70.0,
            "change_pct": 2.14,
            "source": "ibkr",
        }
    )
    mgr.ibkr = mock_ib
    mgr.polygon = MagicMock()
    mgr.schwab = None

    out = await mgr.get_current_price("MCL", is_futures=True)

    assert out["source"] == "ibkr"
    assert out["last_price"] == 71.5
    mock_ib.get_snapshot_price.assert_awaited_once()
    mgr.polygon.get_last_price.assert_not_called()


@pytest.mark.asyncio
async def test_get_bars_uses_ibkr_when_connected_non_empty() -> None:
    mgr = MarketDataManager(_MinimalConfig())
    mock_ib = MagicMock()
    mock_ib.is_connected = True
    mock_ib.get_historical_bars = AsyncMock(
        return_value=pd.DataFrame(
            {
                "timestamp": pd.date_range("2025-01-01", periods=3, freq="h"),
                "open": [1.0, 2.0, 3.0],
                "high": [1.1, 2.1, 3.1],
                "low": [0.9, 1.9, 2.9],
                "close": [1.05, 2.05, 3.05],
                "volume": [100.0, 100.0, 100.0],
            }
        )
    )
    mgr.ibkr = mock_ib
    mgr.polygon = MagicMock()

    df = await mgr.get_bars("MCL", lookback_days=7, timeframe="1h", is_futures=True)

    assert not df.empty
    mock_ib.get_historical_bars.assert_awaited_once()
    mgr.polygon.get_historical_bars.assert_not_called()


@pytest.mark.asyncio
async def test_get_current_price_falls_back_to_polygon_when_ibkr_no_price() -> None:
    """
    Polygon is now BLOCKLISTED for futures symbols (MCL, MNQ, MES, etc.)
    since 2026-04-16 incident — Polygon's `CL` is Colgate-Palmolive stock,
    not crude oil. For futures, the waterfall skips Polygon entirely and
    falls through to CSV cache (or unavailable). This test validates the
    blocklist behavior: Polygon should NOT be called for MCL.

    See docs/data-source-audit-2026-04-16.md for the full incident report.
    """
    mgr = MarketDataManager(_MinimalConfig())
    mock_ib = MagicMock()
    mock_ib.is_connected = True
    mock_ib.get_snapshot_price = AsyncMock(
        return_value={"last_price": None, "source": "ibkr_not_connected"}
    )
    mgr.ibkr = mock_ib
    mgr.schwab = None
    mock_poly = MagicMock()
    mock_poly.get_last_price = MagicMock(
        return_value={
            "last_price": 80.0,
            "prev_close": 79.0,
            "change_pct": 1.27,
            "source": "polygon",
        }
    )
    mgr.polygon = mock_poly

    out = await mgr.get_current_price("MCL", is_futures=True)

    # MCL is in POLYGON_FUTURES_BLOCKLIST — Polygon must NOT be called.
    # Waterfall falls through to CSV cache or unavailable.
    mock_poly.get_last_price.assert_not_called()
    assert out["source"] in ("csv_cache", "unavailable")
