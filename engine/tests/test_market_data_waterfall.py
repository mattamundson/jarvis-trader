"""Waterfall behavior for MarketDataManager — IBKR Tier 1 when connected."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

from data import market_data as market_data_module
from data.market_data import MarketDataManager


@pytest.fixture(autouse=True)
def _disable_tv_tier_0(monkeypatch):
    """Same rationale as test_market_data_fallback._disable_tv_tier_0: these
    waterfall tests assert source attributions for IBKR/Polygon/CSV tiers,
    and TV Tier 0 (live whenever TradingView Desktop is running with CDP)
    intercepts before those tiers can be tested.
    """
    monkeypatch.setattr(market_data_module, "_tv_feed", None)


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


# ── get_tick_price — ticker-only path that skips TV ─────────────────────────


@pytest.mark.asyncio
async def test_get_tick_price_skips_tv_feed(monkeypatch) -> None:
    """get_tick_price must never invoke _tv_feed, even when TV is available.

    Regression guard for P1.9 /portfolio/summary latency fix: ticker reads
    for open positions route through IBKR/Schwab/Polygon but never touch
    TV Desktop (whose chart-switch cost inflates tail latency).
    """
    mgr = MarketDataManager(_MinimalConfig())
    mock_ib = MagicMock()
    mock_ib.is_connected = True
    mock_ib.get_snapshot_price = AsyncMock(
        return_value={"last_price": 71.5, "source": "ibkr"}
    )
    mgr.ibkr = mock_ib
    mgr.schwab = None
    mgr.polygon = MagicMock()

    # Force TV feed to "available" but assert it is NEVER called from get_tick_price.
    mock_tv = MagicMock()
    mock_tv.is_available = MagicMock(return_value=True)
    mock_tv.get_quote = MagicMock(return_value={"close": 999.0})
    mock_tv.get_bars = MagicMock()
    monkeypatch.setattr(market_data_module, "_tv_feed", mock_tv)

    out = await mgr.get_tick_price("MCL", is_futures=True)

    assert out["source"] == "ibkr"
    assert out["last_price"] == 71.5
    mock_ib.get_snapshot_price.assert_awaited_once()
    mock_tv.get_quote.assert_not_called()
    mock_tv.get_bars.assert_not_called()


@pytest.mark.asyncio
async def test_get_tick_price_falls_to_schwab_when_ibkr_empty(monkeypatch) -> None:
    mgr = MarketDataManager(_MinimalConfig())
    mock_ib = MagicMock()
    mock_ib.is_connected = True
    mock_ib.get_snapshot_price = AsyncMock(return_value={"last_price": None})
    mgr.ibkr = mock_ib

    mock_schwab = MagicMock()
    mock_schwab.is_connected = True
    mock_schwab.get_quotes = AsyncMock(
        return_value={"MCL": {"last": 72.1, "mark": 72.15, "change_pct": 1.5}}
    )
    mgr.schwab = mock_schwab
    mgr.polygon = MagicMock()

    mock_tv = MagicMock()
    mock_tv.is_available = MagicMock(return_value=True)
    mock_tv.get_quote = MagicMock(return_value={"close": 999.0})
    monkeypatch.setattr(market_data_module, "_tv_feed", mock_tv)

    out = await mgr.get_tick_price("MCL", is_futures=True)

    assert out["source"] == "schwab"
    assert out["last_price"] == 72.1
    # Still must not touch TV even in Schwab-fallback case.
    mock_tv.get_quote.assert_not_called()


# ── get_tick_price Tier 0 — Redis real-time fabric freshness gate ──────────
#
# GT-17 follow-up (2026-07-27): the original GT-17 fix qualified contracts
# before Tier 1 IBKR ticker snapshots, but an adversarial verifier found that
# unqualified-contract hash collisions actually raise inside reqTickersAsync
# and get caught, falling through to get_snapshot_price's ALREADY-qualified
# historical-bars fallback -- which would produce a non-null change_pct, not
# the reported change_pct=null. Tier 0 (this section) is the mechanism that
# actually matches the report: it hardcodes change_pct=None and, pre-fix,
# trusted whatever was cached under market:latest:{symbol} forever, with no
# staleness check and no TTL on the write side. These tests exercise the
# real Tier-0 code path (a fake redis.Redis client standing in for a real
# Redis server) rather than mocking around it.


class _FakeRedisClient:
    """Minimal stand-in for redis.Redis — enough for get_tick_price's Tier 0
    (two blocking `.get()` calls per symbol key: the cached tick, then its
    freshness marker)."""

    def __init__(self, store: dict) -> None:
        self._store = store

    def get(self, key):
        return self._store.get(key)


def _install_fake_redis(monkeypatch, store: dict) -> None:
    import redis as redis_module

    monkeypatch.setattr(redis_module, "Redis", lambda *a, **kw: _FakeRedisClient(store))


@pytest.mark.asyncio
async def test_get_tick_price_redis_fabric_serves_fresh_data(monkeypatch) -> None:
    """Tier 0 should still serve Redis-cached data when it's genuinely fresh
    -- the freshness gate must not defeat the fabric's whole purpose."""
    import json
    from datetime import datetime, timezone

    store = {
        "market:latest:AAPL": json.dumps({"close": 325.89, "open": 320.0}),
        "datasource:ticks:AAPL:last_update": datetime.now(timezone.utc).isoformat(),
    }
    _install_fake_redis(monkeypatch, store)

    mgr = MarketDataManager(_MinimalConfig())
    mgr.ibkr = MagicMock()
    mgr.ibkr.is_connected = False
    mgr.schwab = None
    mgr.polygon = MagicMock()

    out = await mgr.get_tick_price("AAPL", is_futures=False)

    assert out["source"] == "redis_fabric"
    assert out["last_price"] == 325.89
<<<<<<< HEAD
=======
    # P3-1: as_of must carry the REAL observation time so a downstream
    # build_envelope() can honestly re-derive is_live, not trust this tier
    # forever just because it got past its own internal gate.
    assert out["as_of"] is not None
    import time as _time

    assert abs(_time.time() - out["as_of"]) < 5.0
>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2


@pytest.mark.asyncio
async def test_get_tick_price_redis_fabric_falls_through_when_stale(monkeypatch) -> None:
    """A poisoned/stale market:latest:AAPL entry (e.g. a TV chart pane that
    hadn't finished switching symbols, publishing under the wrong key) must
    NOT be served forever. Once its freshness marker is older than
    DEFAULT_STALE_AFTER_S, Tier 0 must fall through to Tier 1 IBKR -- which
    is now correctly contract-qualified per the original GT-17 fix.

    Values mirror the originally-reported GT-17 symptom (~$7494.10, ~23x
    AAPL's real ~$325 price, with the cached entry never carrying a
    change_pct)."""
    import json
    from datetime import datetime, timedelta, timezone

    stale_ts = (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat()
    store = {
        "market:latest:AAPL": json.dumps({"close": 7494.10, "open": 7400.0}),
        "datasource:ticks:AAPL:last_update": stale_ts,
    }
    _install_fake_redis(monkeypatch, store)

    mgr = MarketDataManager(_MinimalConfig())
    mock_ib = MagicMock()
    mock_ib.is_connected = True
    mock_ib.get_snapshot_price = AsyncMock(
        return_value={
            "last_price": 325.89,
            "prev_close": 324.0,
            "change_pct": 0.58,
            "source": "ibkr",
        }
    )
    mgr.ibkr = mock_ib
    mgr.schwab = None
    mgr.polygon = MagicMock()

    out = await mgr.get_tick_price("AAPL", is_futures=False)

    assert out["source"] == "ibkr"
    assert out["last_price"] == 325.89
    mock_ib.get_snapshot_price.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_tick_price_redis_fabric_falls_through_when_no_freshness_marker(
    monkeypatch,
) -> None:
    """A cached tick with no sibling last_update marker must be treated as
    stale rather than trusted blindly -- e.g. an entry written before the
    freshness marker existed, or one whose marker key expired independently
    of the value key."""
    import json

    store = {
        "market:latest:AAPL": json.dumps({"close": 7494.10, "open": 7400.0}),
    }
    _install_fake_redis(monkeypatch, store)

    mgr = MarketDataManager(_MinimalConfig())
    mock_ib = MagicMock()
    mock_ib.is_connected = True
    mock_ib.get_snapshot_price = AsyncMock(
        return_value={"last_price": 325.89, "source": "ibkr"}
    )
    mgr.ibkr = mock_ib
    mgr.schwab = None
    mgr.polygon = MagicMock()

    out = await mgr.get_tick_price("AAPL", is_futures=False)

    assert out["source"] == "ibkr"
    assert out["last_price"] == 325.89
<<<<<<< HEAD
=======


# ── check_redis_fabric_freshness — P3-1 /health observability path ─────────
#
# Same Redis fabric as get_tick_price's Tier 0 above, but observes freshness
# for a symbol set WITHOUT serving a price -- the mechanism /health uses to
# decide market_data_fresh. Shares _redis_fabric_freshness() with Tier 0 so
# the two can never disagree on what counts as stale.


@pytest.mark.asyncio
async def test_check_redis_fabric_freshness_reports_fresh_entry(monkeypatch) -> None:
    import json
    from datetime import datetime, timezone

    store = {
        "market:latest:MES": json.dumps({"close": 5300.25, "open": 5290.0}),
        "datasource:ticks:MES:last_update": datetime.now(timezone.utc).isoformat(),
    }
    _install_fake_redis(monkeypatch, store)
    mgr = MarketDataManager(_MinimalConfig())

    out = await mgr.check_redis_fabric_freshness(["MES"], stale_after_s=60.0)

    assert out["MES"]["present"] is True
    assert out["MES"]["stale"] is False
    assert out["MES"]["age_s"] is not None and out["MES"]["age_s"] < 5.0


@pytest.mark.asyncio
async def test_check_redis_fabric_freshness_reports_stale_entry(monkeypatch) -> None:
    """The literal P3-1 proof scenario: a market:latest:MES key with a
    30-day-old ts must be reported stale, not silently trusted."""
    import json
    from datetime import datetime, timedelta, timezone

    stale_ts = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    store = {
        "market:latest:MES": json.dumps({"close": 5300.25, "open": 5290.0}),
        "datasource:ticks:MES:last_update": stale_ts,
    }
    _install_fake_redis(monkeypatch, store)
    mgr = MarketDataManager(_MinimalConfig())

    out = await mgr.check_redis_fabric_freshness(["MES"], stale_after_s=900.0)

    assert out["MES"]["present"] is True
    assert out["MES"]["stale"] is True
    assert out["MES"]["age_s"] > 900.0


@pytest.mark.asyncio
async def test_check_redis_fabric_freshness_reports_absent_not_stale(monkeypatch) -> None:
    """No cached entry at all is present=False, stale=False -- distinct from
    a present-but-expired entry. Nothing to be stale about."""
    _install_fake_redis(monkeypatch, {})
    mgr = MarketDataManager(_MinimalConfig())

    out = await mgr.check_redis_fabric_freshness(["MES"], stale_after_s=900.0)

    assert out["MES"] == {"present": False, "age_s": None, "stale": False}


@pytest.mark.asyncio
async def test_check_redis_fabric_freshness_uses_same_threshold_as_get_tick_price(
    monkeypatch,
) -> None:
    """The two must agree on what counts as fresh -- one shared helper, not a
    second, potentially-divergent staleness rule. (Their configured windows
    legitimately differ -- /health uses the longer 900s DATA_INTEGRITY_STALE_
    AFTER_S, get_tick_price's hot path uses the tighter 60s DEFAULT_STALE_
    AFTER_S -- so this uses an age fresh under BOTH to prove shared math, not
    a coincidentally-matching threshold.)"""
    import json
    from datetime import datetime, timedelta, timezone

    ts = (datetime.now(timezone.utc) - timedelta(seconds=15)).isoformat()
    store = {
        "market:latest:MES": json.dumps({"close": 5300.25, "open": 5290.0}),
        "datasource:ticks:MES:last_update": ts,
    }
    _install_fake_redis(monkeypatch, store)
    mgr = MarketDataManager(_MinimalConfig())

    health_view = await mgr.check_redis_fabric_freshness(["MES"], stale_after_s=900.0)
    assert health_view["MES"]["stale"] is False

    mgr.ibkr = MagicMock()
    mgr.ibkr.is_connected = False
    mgr.schwab = None
    mgr.polygon = MagicMock()
    tick = await mgr.get_tick_price("MES", is_futures=True)
    assert tick["source"] == "redis_fabric"  # still fresh under the 60s gate too
>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2
