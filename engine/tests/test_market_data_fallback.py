"""
MarketDataManager fallback chain regression tests.

Guards the contract that `df.attrs["source"]` always identifies which tier
served the request. Without this attribution, silent source-failure bugs
(e.g. Polygon 2026-04-16 futures-blocklist incident) become invisible
downstream in signal generation and backtests.

Tiers:
  1. IBKR (paper connector)   → attrs["source"] == "ibkr"
  2. Polygon                  → attrs["source"] == "polygon" (equities only)
  3. CSV backtest cache       → attrs["source"] == "csv_cache"
  Empty DataFrame (all failed) → attrs["source"] == "none"
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from data.market_data import MarketDataManager


def _fresh_bars(n: int = 50) -> pd.DataFrame:
    """Build a valid OHLCV frame with recent timestamps (won't trip the 2-day stale guard)."""
    end = datetime.now()
    ts = pd.date_range(end=end, periods=n, freq="1h")
    return pd.DataFrame({
        "timestamp": ts,
        "open": [100.0] * n,
        "high": [101.0] * n,
        "low": [99.0] * n,
        "close": [100.5] * n,
        "volume": [1000] * n,
    })


@pytest.mark.asyncio
async def test_ibkr_tier_wins_and_attrs_source_set():
    """When IBKR is connected and returns data, attrs['source'] = 'ibkr'."""
    mgr = MarketDataManager.__new__(MarketDataManager)
    mgr.ibkr = MagicMock()
    mgr.ibkr.is_connected = True
    mgr.ibkr.get_historical_bars = AsyncMock(return_value=_fresh_bars())
    mgr.polygon = None

    df = await mgr.get_bars(symbol="MCL", timeframe="1h", lookback_days=30)

    assert not df.empty
    assert df.attrs.get("source") == "ibkr"
    assert df.attrs.get("symbol") == "MCL"
    mgr.ibkr.get_historical_bars.assert_awaited_once()


@pytest.mark.asyncio
async def test_polygon_tier_used_for_equities_when_ibkr_returns_empty():
    """IBKR empty → Polygon called for equities → attrs['source'] = 'polygon'."""
    mgr = MarketDataManager.__new__(MarketDataManager)
    mgr.ibkr = MagicMock()
    mgr.ibkr.is_connected = True
    mgr.ibkr.get_historical_bars = AsyncMock(return_value=pd.DataFrame())
    mgr.polygon = MagicMock()
    mgr.polygon.get_historical_bars = MagicMock(return_value=_fresh_bars())

    df = await mgr.get_bars(symbol="SPY", timeframe="1h", lookback_days=30)

    assert not df.empty
    assert df.attrs.get("source") == "polygon"
    assert df.attrs.get("symbol") == "SPY"


@pytest.mark.asyncio
async def test_polygon_skipped_for_futures_blocklist():
    """MCL is in POLYGON_FUTURES_BLOCKLIST → Polygon must not be called."""
    mgr = MarketDataManager.__new__(MarketDataManager)
    mgr.ibkr = MagicMock()
    mgr.ibkr.is_connected = True
    mgr.ibkr.get_historical_bars = AsyncMock(return_value=pd.DataFrame())
    mgr.polygon = MagicMock()
    mgr.polygon.get_historical_bars = MagicMock(return_value=_fresh_bars())

    # _load_csv_cache lives on the class, stub it on the instance
    mgr._load_csv_cache = MagicMock(return_value=pd.DataFrame())

    df = await mgr.get_bars(symbol="MCL", timeframe="1h", lookback_days=30)

    # Polygon MUST NOT be called for MCL
    mgr.polygon.get_historical_bars.assert_not_called()
    # With IBKR empty and Polygon skipped and CSV empty, result is empty but attributed
    assert df.empty
    assert df.attrs.get("source") == "none"
    assert df.attrs.get("symbol") == "MCL"


@pytest.mark.asyncio
async def test_csv_cache_serves_when_live_sources_down():
    """IBKR offline + Polygon skipped → CSV cache → attrs['source'] = 'csv_cache'."""
    mgr = MarketDataManager.__new__(MarketDataManager)
    mgr.ibkr = MagicMock()
    mgr.ibkr.is_connected = False
    mgr.polygon = None
    mgr._load_csv_cache = MagicMock(return_value=_fresh_bars())

    df = await mgr.get_bars(symbol="MCL", timeframe="1h", lookback_days=30)

    assert not df.empty
    assert df.attrs.get("source") == "csv_cache"
    assert df.attrs.get("symbol") == "MCL"


@pytest.mark.asyncio
async def test_stale_csv_cache_rejected_and_source_is_none():
    """CSV cache last-bar >2 days old → rejected → attrs['source'] = 'none'."""
    stale = _fresh_bars()
    # Shift all timestamps to 5 days ago (past the 2-day staleness threshold)
    stale["timestamp"] = pd.date_range(
        end=datetime.now() - timedelta(days=5), periods=len(stale), freq="1h"
    )

    mgr = MarketDataManager.__new__(MarketDataManager)
    mgr.ibkr = MagicMock()
    mgr.ibkr.is_connected = False
    mgr.polygon = None
    mgr._load_csv_cache = MagicMock(return_value=stale)

    df = await mgr.get_bars(symbol="MCL", timeframe="1h", lookback_days=30)

    assert df.empty
    assert df.attrs.get("source") == "none"
