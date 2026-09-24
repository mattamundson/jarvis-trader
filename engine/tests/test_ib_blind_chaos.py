"""
IB-blind chaos drill (Phase 3, P3.1).

Paper-only, offline simulation of IBKR data going blind mid-session (the data
leg drops while the process stays up). Asserts three honesty invariants:

  (a) FAILOVER   — the market-data waterfall falls through to the next
                    available tier (never crashes, never silently serves
                    stale/wrong data attributed as "ibkr").
  (b) NO-NaN      — canonical metrics (analytics.metrics) never emit NaN/inf
                    under degenerate/blind inputs — only a well-typed None.
  (c) HONEST-UI   — the provenance layer (and the /prices/snapshot consumer
                    of it) reports is_live=False / a non-ibkr source when the
                    IB data leg is down, so the dashboard cannot render a
                    misleading LIVE badge.

Mirrors the mocking patterns already established in
test_market_data_fallback.py (waterfall), test_provenance.py (derive_is_live),
test_metrics_module.py (metrics guards), and test_prices_router_offline.py
(TestClient against a patched _data_manager). No live IB Gateway connection
is ever made.
"""

from __future__ import annotations

import asyncio
import math
import os
import time
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from analytics.metrics import calmar, max_drawdown_pct, sharpe, total_return_pct
from config import settings
from data import market_data as market_data_module
from data.market_data import IBKRDataConnector, MarketDataManager
from data.provenance import derive_is_live
from main import app


@pytest.fixture(autouse=True)
def _disable_tv_tier_0(monkeypatch):
    """Disable TV Tier 0 / SQLite Tier 1.5 so the IBKR-blind scenario actually
    exercises the Polygon/CSV fallback tiers instead of being intercepted
    upstream. Same rationale as test_market_data_fallback.py."""
    monkeypatch.setattr(market_data_module, "_tv_feed", None)
    monkeypatch.setattr(market_data_module, "_load_bars", None)


def _fresh_bars(n: int = 50) -> pd.DataFrame:
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


# ── (a) Failover: bars waterfall survives IB going blind ────────────────────


class TestBarsFailoverOnIBBlind:
    @pytest.mark.asyncio
    async def test_ib_blind_falls_over_to_csv_cache(self):
        """IBKR data leg drops mid-session -> get_bars falls through to CSV cache,
        never raises, never attributes the result to 'ibkr'."""
        mgr = MarketDataManager.__new__(MarketDataManager)
        mgr.ibkr = MagicMock()
        mgr.ibkr.is_connected = False  # <-- the chaos injection
        mgr.polygon = None
        mgr._load_csv_cache = MagicMock(return_value=_fresh_bars())

        df = await mgr.get_bars(symbol="MES", timeframe="1h", lookback_days=30)

        assert not df.empty
        assert df.attrs.get("source") == "csv_cache"
        assert df.attrs.get("source") != "ibkr"

    @pytest.mark.asyncio
    async def test_ib_blind_and_polygon_blocklisted_falls_over_to_csv_cache(self):
        """Futures symbol (Polygon-blocklisted) + IB blind -> CSV is the only
        remaining tier; must still resolve without an exception."""
        mgr = MarketDataManager.__new__(MarketDataManager)
        mgr.ibkr = MagicMock()
        mgr.ibkr.is_connected = False
        mgr.polygon = MagicMock()
        mgr.polygon.get_historical_bars = MagicMock(return_value=_fresh_bars())
        mgr._load_csv_cache = MagicMock(return_value=_fresh_bars())

        df = await mgr.get_bars(symbol="MCL", timeframe="1h", lookback_days=30)

        mgr.polygon.get_historical_bars.assert_not_called()
        assert not df.empty
        assert df.attrs.get("source") == "csv_cache"

    @pytest.mark.asyncio
    async def test_fully_blind_all_tiers_down_returns_empty_none_source_no_crash(self):
        """Total outage: IB blind, no Polygon, empty CSV cache -> honest empty
        DataFrame attributed 'none'. Must not raise and must not fabricate data."""
        mgr = MarketDataManager.__new__(MarketDataManager)
        mgr.ibkr = None
        mgr.polygon = None
        mgr._load_csv_cache = MagicMock(return_value=pd.DataFrame())

        df = await mgr.get_bars(symbol="MES", timeframe="1h", lookback_days=30)

        assert df.empty
        assert df.attrs.get("source") == "none"


class TestCurrentPriceFailoverOnIBBlind:
    @pytest.mark.asyncio
    async def test_ib_blind_falls_over_to_csv_cache_last_close(self):
        """get_current_price waterfall: IB blind + no Schwab/Polygon-stream/Polygon
        -> CSV last-close tier serves an honest, non-'ibkr' price."""
        mgr = MarketDataManager.__new__(MarketDataManager)
        mgr.ibkr = MagicMock()
        mgr.ibkr.is_connected = False
        mgr.schwab = None
        mgr.polygon_streamer = None
        mgr.polygon = None
        mgr._load_csv_cache = MagicMock(return_value=_fresh_bars())
        mgr._symbol_last_ts = {}
        mgr._mark_symbol_fresh = MagicMock()

        result = await mgr.get_current_price("MES")

        assert result["source"] == "csv_cache"
        assert result["last_price"] is not None
        assert result["source"] != "ibkr"

    @pytest.mark.asyncio
    async def test_fully_blind_returns_none_price_not_zero_no_crash(self):
        """Total outage on the price leg -> None (never a silent 0.0), no exception."""
        mgr = MarketDataManager.__new__(MarketDataManager)
        mgr.ibkr = None
        mgr.schwab = None
        mgr.polygon_streamer = None
        mgr.polygon = None
        mgr._load_csv_cache = MagicMock(return_value=pd.DataFrame())
        mgr._symbol_last_ts = {}
        mgr._mark_symbol_fresh = MagicMock()

        result = await mgr.get_current_price("MES")

        assert result["last_price"] is None
        assert result["last_price"] != 0.0
        assert result["source"] == "unavailable"


# ── (b) No metric returns NaN/impossible values under a blind/degenerate feed ─


class TestMetricsNeverNanUnderOutage:
    """A blind data leg starves these functions of real observations. They
    must degrade to a well-typed None, never NaN/inf (the -1.46e14 / NaN-badge
    class of bug PR #272 fixed)."""

    def test_max_drawdown_pct_empty_curve_under_outage(self):
        result = max_drawdown_pct([], 10000)
        assert result == 0.0
        assert math.isfinite(result)

    def test_max_drawdown_pct_all_none_curve_under_outage(self):
        # Every observation blind (IB down for the whole window) -> no data,
        # not a fabricated drawdown.
        result = max_drawdown_pct([None, None, None], 10000)
        assert result == 0.0
        assert math.isfinite(result)

    def test_calmar_undefined_when_dd_unmeasurable_under_outage(self):
        result = calmar(1000.0, None)
        assert result is None

    def test_sharpe_insufficient_observations_under_outage(self):
        # Only one tick made it through before the feed went blind.
        result = sharpe([42.0])
        assert result is None

    def test_sharpe_never_nan_or_inf_on_degenerate_blind_series(self):
        for series in ([], [0.0], [0.0, 0.0, 0.0], [None, None]):
            filtered = [x for x in series if x is not None]
            result = sharpe(filtered)
            assert result is None or math.isfinite(result)

    def test_total_return_pct_unmeasurable_under_outage(self):
        # starting_capital unknown/zero (no live snapshot ever landed)
        result = total_return_pct(11206, 0)
        assert result is None


# ── (c) Honest degraded UI signal: is_live=False, non-ibkr source ───────────


class TestProvenanceHonestOnIBBlind:
    def test_derive_is_live_false_when_ibkr_data_leg_down(self):
        assert (
            derive_is_live("ibkr", as_of=1_000_000.0, now=1_000_000.0, ibkr_data_connected=False)
            is False
        )

    def test_derive_is_live_false_for_fallback_tier_even_if_fresh(self):
        # Fallback tiers (csv_cache) are static — the dashboard must never
        # promote them to LIVE just because the outage is recent.
        assert derive_is_live("csv_cache", as_of=1_000_000.0, now=1_000_000.0) is False


@pytest.fixture
def client():
    key = os.environ.get("API_KEY") or settings.API_KEY
    return TestClient(app, headers={"X-API-Key": key})


@pytest.fixture(autouse=True)
def _clear_price_cache():
    import routers.prices_router as _pr

    _pr._price_cache._cache.clear()
    yield
    _pr._price_cache._cache.clear()


class TestPricesSnapshotHonestUnderIBBlind:
    def test_snapshot_reports_not_live_and_non_ibkr_source_when_ib_blind(self, client):
        """/prices/snapshot must render an honest degraded signal — never a
        500, never is_live=True — when the IB data leg is down and a fallback
        tier serves the price."""
        dm = MagicMock()
        dm.ibkr = MagicMock()
        dm.ibkr.is_connected = False  # <-- chaos injection

        async def _get_current_price(sym, **_kw):
            return {"last_price": 5200.0, "prev_close": 5180.0, "change_pct": 0.39, "source": "csv_cache"}

        dm.get_current_price = AsyncMock(side_effect=_get_current_price)

        with patch("routers.prices_router._data_manager", dm):
            response = client.get("/prices/snapshot?symbols=MES")

        assert response.status_code == 200
        data = response.json()["MES"]
        assert data["source"] != "ibkr"
        assert data["is_live"] is False

    def test_snapshot_never_500s_on_total_outage(self, client):
        """Total outage (get_current_price raises) -> honest 'unavailable'
        payload, not a 500 — the router's existing except-branch contract."""
        dm = MagicMock()
        dm.ibkr = None
        dm.get_current_price = AsyncMock(side_effect=ConnectionError("IB gateway unreachable"))

        with patch("routers.prices_router._data_manager", dm):
            response = client.get("/prices/snapshot?symbols=MES")

        assert response.status_code == 200
        data = response.json()["MES"]
        assert data["source"] == "unavailable"
        assert data["is_live"] is False
        assert data["last_price"] is None


# ── (d) Wedged, not blind: socket alive but the API never answers ───────────


def _never_returns():
    """A coroutine function that never completes — models a wedged Gateway."""

    async def _inner(*_args, **_kwargs):
        await asyncio.sleep(3600)

    return _inner


class TestIBWedgedNotBlind:
    """The 2026-08-15 outage mode, which every test above misses.

    All the 'blind' cases set ``is_connected = False`` — IB failing *loudly*.
    The real incident failed by *silence*: the Gateway socket stayed open (so
    ``is_connected``, which is only a local ``ib_async.IB.isConnected()`` socket
    check, kept returning True and ``/health`` kept reporting
    ``ibkr_data_connected: true``) while every data request simply never came
    back. Nothing raises, so no ``except`` branch ever runs and Tiers 2-5 of the
    waterfall — including the CSV cache built for exactly this — are
    unreachable. Every price-serving endpoint hung indefinitely.

    ``services/ib_freshness_heartbeat.py`` already guards this call with
    ``asyncio.wait_for(..., timeout=8.0)``; the three price-serving call sites
    in ``market_data.py`` did not.
    """

    @pytest.mark.asyncio
    async def test_wedged_snapshot_returns_bounded_instead_of_hanging(self, monkeypatch):
        """get_snapshot_price must bound its IB awaits. Un-fixed, this hangs
        forever and the outer wait_for raises TimeoutError."""
        monkeypatch.setattr(market_data_module, "_IBKR_DATA_REQUEST_TIMEOUT_S", 0.2)

        conn = IBKRDataConnector.__new__(IBKRDataConnector)
        conn._connected = True
        conn._ib = MagicMock()
        conn._ib.isConnected.return_value = True
        conn._qualified_contract = _never_returns()
        conn.get_historical_bars = _never_returns()

        started = time.monotonic()
        result = await asyncio.wait_for(
            conn.get_snapshot_price("MES", is_futures=True), timeout=10
        )
        elapsed = time.monotonic() - started

        # Bounded by the two guarded awaits, not by the 3600s sleep.
        assert elapsed < 5, f"get_snapshot_price took {elapsed:.1f}s — not bounded"
        assert result["last_price"] is None
        assert result["source"] != "ibkr"

    @pytest.mark.asyncio
    async def test_wedged_ib_tick_price_still_reaches_csv_cache(self, monkeypatch):
        """The trader-facing invariant: a wedged Gateway must degrade to a
        lower tier, not hang the request. This is what zeroed the 'did it trade
        today, did it profit' surface."""
        monkeypatch.setattr(market_data_module, "_IBKR_DATA_REQUEST_TIMEOUT_S", 0.2)

        conn = IBKRDataConnector.__new__(IBKRDataConnector)
        conn._connected = True
        conn._ib = MagicMock()
        conn._ib.isConnected.return_value = True
        conn._qualified_contract = _never_returns()
        conn.get_historical_bars = _never_returns()

        mgr = MarketDataManager.__new__(MarketDataManager)
        mgr.ibkr = conn
        mgr.schwab = None
        mgr.polygon_streamer = None
        mgr.polygon = None
        mgr._load_csv_cache = MagicMock(return_value=_fresh_bars())
        mgr._last_price_source = None
        mgr._record_ibkr_freshness = MagicMock()

        result = await asyncio.wait_for(
            mgr.get_tick_price("MES", is_futures=True), timeout=10
        )

        assert result["source"] == "csv_cache"
        assert result["last_price"] is not None
        assert result["source"] != "ibkr"


class TestDataLegHealthCheckVerifiesRoundTrip:
    """health_check()'s own `_connected` read had the exact same blind spot as
    get_snapshot_price -- it trusted the shallow socket flag with no round-trip
    probe at all, so /health's `ibkr_data_connected` could never observe a
    wedge (only a full disconnect). Mirrors the execution connector's
    reqCurrentTimeAsync probe pattern."""

    @pytest.mark.asyncio
    async def test_reports_wedged_when_shallow_connected_but_roundtrip_fails(
        self, monkeypatch
    ):
        monkeypatch.setattr(market_data_module, "_IBKR_DATA_REQUEST_TIMEOUT_S", 0.2)
        conn = IBKRDataConnector.__new__(IBKRDataConnector)
        conn._connected = True
        conn._port = 4002
        conn._host = "127.0.0.1"
        conn._client_id = 226
        conn._ib = MagicMock()
        conn._ib.reqCurrentTimeAsync = _never_returns()

        result = await asyncio.wait_for(conn.health_check(), timeout=5)

        assert result["connected"] is False
        assert result["status"] == "wedged"

    @pytest.mark.asyncio
    async def test_reports_connected_when_roundtrip_succeeds(self, monkeypatch):
        conn = IBKRDataConnector.__new__(IBKRDataConnector)
        conn._connected = True
        conn._port = 4002
        conn._host = "127.0.0.1"
        conn._client_id = 226
        conn._ib = MagicMock()
        conn._ib.reqCurrentTimeAsync = AsyncMock(return_value=None)

        result = await conn.health_check()

        assert result["connected"] is True
        assert result["status"] == "connected"
        assert result["latency_ms"] is not None

    @pytest.mark.asyncio
    async def test_reports_disconnected_without_probing_when_shallow_false(self):
        conn = IBKRDataConnector.__new__(IBKRDataConnector)
        conn._connected = False
        conn._port = 4002
        conn._host = "127.0.0.1"
        conn._client_id = 226
        conn._ib = MagicMock()
        conn._ib.reqCurrentTimeAsync = AsyncMock(return_value=None)

        result = await conn.health_check()

        assert result["connected"] is False
        assert result["status"] == "disconnected"
        conn._ib.reqCurrentTimeAsync.assert_not_called()
