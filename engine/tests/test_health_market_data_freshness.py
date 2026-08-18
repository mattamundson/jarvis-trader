"""P3-1 (roadmap-drain): a `market:latest:{symbol}` Redis fabric entry that
goes stale (or the whole fabric dying) used to have zero effect on /health --
this endpoint would read "ok" indefinitely while the badge fed from the same
source silently served an old price. These tests pin GET /health's new
market_data_fresh/market_data_stale_symbols fields and the status downgrade.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import health_router


class _FakeSafety:
    def get_status(self) -> dict:
        return {
            "is_killed": False,
            "kill_switch_reason": None,
            "daily_realized_pnl": 0.0,
            "equity_peak": 10_000.0,
            "current_equity": 10_000.0,
            "recent_order_count": 0,
        }


class _FakeDataManager:
    """Stands in for MarketDataManager -- only the one method /health calls."""

    def __init__(self, freshness: dict):
        self._freshness = freshness
        self.ibkr = None
        self.received_symbols = None
        self.received_stale_after_s = None

    async def check_redis_fabric_freshness(self, symbols, stale_after_s=None):
        self.received_symbols = list(symbols)
        self.received_stale_after_s = stale_after_s
        return self._freshness


class _RaisingDataManager:
    """Simulates the check itself blowing up -- must fail OPEN, not 500."""

    def __init__(self):
        self.ibkr = None

    async def check_redis_fabric_freshness(self, symbols, stale_after_s=None):
        raise RuntimeError("redis exploded")


@pytest.fixture(autouse=True)
def _reset_caches():
    health_router._tv_mcp_health_cache.update(
        checked_at=0.0, healthy=False, details="not yet probed", status="connecting"
    )
    yield


def _client(dm) -> TestClient:
    app = FastAPI()
    app.include_router(health_router.router)
    health_router.inject_dependencies(
        start_time=datetime.now(timezone.utc),
        dm=dm,
        sl=_FakeSafety(),
        dbm=None,
        pt=None,
        pm=None,
        tp=None,
        schwab=None,
    )
    return TestClient(app)


def _get_health(dm):
    with patch("routers.health_router._compute_brier_30d_rolling", return_value=None):
        return _client(dm).get("/health")


def test_health_ok_and_fresh_when_all_active_symbols_fresh():
    dm = _FakeDataManager({"MES": {"present": True, "age_s": 4.2, "stale": False}})
    resp = _get_health(dm)
    assert resp.status_code == 200
    body = resp.json()
    assert body["market_data_fresh"] is True
    assert body["market_data_stale_symbols"] == []
    # db_ok is False in this harness (dbm=None) so overall status is still
    # "degraded" for an unrelated reason -- market_data_fresh itself must be
    # independently correct regardless of the other inputs to `status`.


def test_health_degrades_when_active_symbol_is_stale():
    dm = _FakeDataManager({"MES": {"present": True, "age_s": 2_600_000.0, "stale": True}})
    resp = _get_health(dm)
    assert resp.status_code == 200
    body = resp.json()
    assert body["market_data_fresh"] is False
    assert body["market_data_stale_symbols"] == ["MES"]
    assert body["status"] == "degraded"


def test_health_fresh_when_symbol_has_no_cached_entry_at_all():
    """No entry yet (cold start, or this symbol simply isn't on the TV-stream
    fabric right now) is NOT proof of staleness -- distinct from a present-
    but-expired entry. Must not spuriously degrade /health."""
    dm = _FakeDataManager({"MES": {"present": False, "age_s": None, "stale": False}})
    resp = _get_health(dm)
    body = resp.json()
    assert body["market_data_fresh"] is True
    assert body["market_data_stale_symbols"] == []


def test_health_checks_only_authorized_tradeable_symbols():
    """A halted instrument's dead feed must never page anyone -- the checked
    set derives from the single canonical backtest.signals authority."""
    from backtest.signals import DO_NOT_TRADE_SYMBOLS, TREND_INSTRUMENTS

    dm = _FakeDataManager({})
    _get_health(dm)
    expected = sorted(TREND_INSTRUMENTS - DO_NOT_TRADE_SYMBOLS)
    assert dm.received_symbols == expected
    for halted in DO_NOT_TRADE_SYMBOLS:
        assert halted not in dm.received_symbols


def test_health_reuses_the_data_integrity_threshold_not_a_third_number():
    dm = _FakeDataManager({})
    _get_health(dm)
    assert dm.received_stale_after_s == health_router.DATA_INTEGRITY_STALE_AFTER_S


def test_health_fails_open_not_500_when_freshness_check_raises():
    resp = _get_health(_RaisingDataManager())
    assert resp.status_code == 200
    body = resp.json()
    assert body["market_data_fresh"] is True
    assert body["market_data_stale_symbols"] == []


def test_health_fresh_when_no_data_manager_injected():
    resp = _get_health(None)
    assert resp.status_code == 200
    body = resp.json()
    assert body["market_data_fresh"] is True
    assert body["market_data_stale_symbols"] == []
