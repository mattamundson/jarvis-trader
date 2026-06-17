"""US-002 tests — per-symbol data freshness tracking + /health/full exposure.

MarketDataManager records a wall-clock timestamp on every successful bar/price
serve, keyed by (upper-cased) symbol. `symbol_freshness()` turns that into a
{symbol: seconds_since_last_serve} map, surfaced under
/health/full -> subsystems.ib_gateway.per_symbol_freshness so an operator can
see per-instrument staleness, not just the global last source.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pandas as pd
import pytest

from data.market_data import MarketDataManager
from routers import health_router


def _run(coro):
    return asyncio.run(coro)


def _bare_mgr() -> MarketDataManager:
    """A MarketDataManager with just the freshness state wired — skips the heavy
    __init__ (connectors, Reddit, locks) which is irrelevant to this unit."""
    mgr = MarketDataManager.__new__(MarketDataManager)
    mgr._symbol_last_ts = {}
    return mgr


# --- tracking + reader -----------------------------------------------------

def test_freshness_empty_initially():
    assert _bare_mgr().symbol_freshness() == {}


def test_mark_and_read_freshness():
    mgr = _bare_mgr()
    mgr._mark_symbol_fresh("MES")
    mgr._mark_symbol_fresh("MGC")
    fresh = mgr.symbol_freshness()
    assert set(fresh) == {"MES", "MGC"}
    # Just-marked → tiny, non-negative age in seconds.
    for age in fresh.values():
        assert isinstance(age, float)
        assert 0.0 <= age < 5.0


def test_mark_is_case_insensitive():
    mgr = _bare_mgr()
    mgr._mark_symbol_fresh("mes")
    assert "MES" in mgr.symbol_freshness()
    assert "mes" not in mgr.symbol_freshness()


def test_mark_never_raises_on_bad_symbol():
    mgr = _bare_mgr()
    # None has no .upper() — must be swallowed, not propagated into the hot path.
    mgr._mark_symbol_fresh(None)  # type: ignore[arg-type]
    assert mgr.symbol_freshness() == {}


# --- get_bars wrapper ------------------------------------------------------

def test_get_bars_marks_on_nonempty_serve():
    mgr = _bare_mgr()
    mgr._get_bars_impl = AsyncMock(return_value=pd.DataFrame({"close": [1.0, 2.0]}))
    df = _run(mgr.get_bars("mes"))
    assert not df.empty
    assert "MES" in mgr._symbol_last_ts


def test_get_bars_no_mark_on_empty_serve():
    mgr = _bare_mgr()
    mgr._get_bars_impl = AsyncMock(return_value=pd.DataFrame())
    df = _run(mgr.get_bars("mes"))
    assert df.empty
    assert mgr._symbol_last_ts == {}


def test_get_bars_forwards_args():
    mgr = _bare_mgr()
    impl = AsyncMock(return_value=pd.DataFrame({"close": [1.0]}))
    mgr._get_bars_impl = impl
    _run(mgr.get_bars("MGC", lookback_days=7, timeframe="1h", is_futures=True))
    impl.assert_awaited_once_with("MGC", 7, "1h", True)


# --- get_current_price wrapper ---------------------------------------------

def test_get_current_price_marks_on_real_price():
    mgr = _bare_mgr()
    mgr._get_current_price_impl = AsyncMock(
        return_value={"last_price": 5123.5, "source": "ibkr"}
    )
    out = _run(mgr.get_current_price("mnq"))
    assert out["last_price"] == 5123.5
    assert "MNQ" in mgr._symbol_last_ts


def test_get_current_price_no_mark_when_unavailable():
    mgr = _bare_mgr()
    mgr._get_current_price_impl = AsyncMock(
        return_value={"last_price": None, "source": "unavailable"}
    )
    out = _run(mgr.get_current_price("mnq"))
    assert out["last_price"] is None
    assert mgr._symbol_last_ts == {}


# --- /health/full exposure -------------------------------------------------

class _FakeIB:
    is_connected = True

    async def health_check(self):
        return {"status": "connected"}


class _FakeDataMgr:
    def __init__(self, freshness):
        self.ibkr = _FakeIB()
        self._last_bar_source = "ibkr"
        self._last_ibkr_data_ts = 123.0
        self._watchdog = None
        self._freshness = freshness

    def symbol_freshness(self):
        return self._freshness


def test_health_full_exposes_per_symbol_freshness(monkeypatch):
    monkeypatch.setattr(health_router, "safety_layer", None)
    monkeypatch.setattr(
        health_router, "data_manager", _FakeDataMgr({"MES": 4.2, "MGC": 61.0})
    )
    health = _run(health_router._get_ib_gateway_health())
    assert health["data_source"] == "ibkr"
    assert health["per_symbol_freshness"] == {"MES": 4.2, "MGC": 61.0}


def test_health_full_defensive_when_method_absent(monkeypatch):
    class _OldDataMgr:
        ibkr = _FakeIB()
        _last_bar_source = "ibkr"
        _last_ibkr_data_ts = 1.0
        _watchdog = None
        # no symbol_freshness()

    monkeypatch.setattr(health_router, "safety_layer", None)
    monkeypatch.setattr(health_router, "data_manager", _OldDataMgr())
    health = _run(health_router._get_ib_gateway_health())
    # Older engine build (no method) → key simply absent, no crash.
    assert "per_symbol_freshness" not in health
