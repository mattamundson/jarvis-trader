"""Regression test for dashboard audit finding "Bug F" (2026-07-11, shared
watchlist/regime/hidden-pivots hang, half 2 of 2).

Bug: MarketDataManager.get_bars()'s Tier-2 Polygon fallback called
PolygonDataConnector.get_historical_bars() -- a synchronous, blocking method
(the Polygon SDK's list_aggs() iterator does blocking network I/O) -- directly
inside the async def _get_bars_impl(), with no await/asyncio.to_thread. This
blocked FastAPI's single event loop for the call's full duration. Concretely,
hidden_pivots_router.py's asyncio.gather() over ~33 symbols got NO real
concurrency on a cold cache: each symbol's Polygon call serialized on the
event loop despite being "gathered," and while blocked the process couldn't
service any other request either (including the client's own abort/retry
traffic), compounding the pile-up documented in the sibling proxy-layer fix.

This test proves the fix (asyncio.to_thread wrap) actually restores
concurrency: a slow, blocking mock Polygon call must NOT prevent an
unrelated concurrent coroutine from completing first.
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pandas as pd
import pytest

from data import market_data as market_data_module
from data.market_data import MarketDataManager


@pytest.fixture(autouse=True)
def _disable_other_tiers(monkeypatch):
    """Force the Polygon tier to actually be reached (see
    test_market_data_fallback.py's _disable_tv_tier_0 for why TV/SQLite
    tiers must be disabled for these lower-tier tests)."""
    monkeypatch.setattr(market_data_module, "_tv_feed", None)
    monkeypatch.setattr(market_data_module, "_load_bars", None)


def _fresh_bars(n: int = 10) -> pd.DataFrame:
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


def _blocking_get_historical_bars(*args, **kwargs) -> pd.DataFrame:
    """Simulates the real Polygon SDK's blocking network I/O with a plain
    time.sleep() -- NOT asyncio.sleep(), which would yield to the event loop
    and defeat the point of this test."""
    time.sleep(0.3)
    return _fresh_bars()


@pytest.mark.asyncio
async def test_slow_polygon_call_does_not_block_event_loop():
    mgr = MarketDataManager.__new__(MarketDataManager)
    mgr.ibkr = MagicMock()
    mgr.ibkr.is_connected = True
    from unittest.mock import AsyncMock
    mgr.ibkr.get_historical_bars = AsyncMock(return_value=pd.DataFrame())
    mgr.polygon = MagicMock()
    mgr.polygon.get_historical_bars = MagicMock(side_effect=_blocking_get_historical_bars)

    fast_completed_first = asyncio.Event()

    async def fast_coroutine():
        # Yields immediately; if the event loop were blocked by the
        # synchronous Polygon call, this would NOT complete until after it.
        await asyncio.sleep(0.01)
        fast_completed_first.set()

    slow_task = asyncio.create_task(
        mgr.get_bars(symbol="SPY", timeframe="1h", lookback_days=30)
    )
    fast_task = asyncio.create_task(fast_coroutine())

    # The fast coroutine (10ms) must finish well before the slow Polygon
    # call (300ms) if the event loop is actually free to run it concurrently.
    await asyncio.wait_for(fast_task, timeout=0.2)
    assert fast_completed_first.is_set(), (
        "Event loop was blocked by the synchronous Polygon call -- "
        "the fast coroutine should have completed first via asyncio.to_thread"
    )

    df = await slow_task
    assert not df.empty
    assert df.attrs.get("source") == "polygon"
