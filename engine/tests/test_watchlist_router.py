"""Unit tests for routers/watchlist_router.py.

Covers GET /watchlist, POST /watchlist, GET /watchlist/scan, and
DELETE /watchlist/{symbol}. The router mutates the process-global
``config.settings`` watchlists directly, so every test snapshots and
restores FUTURES_WATCHLIST/OPTIONS_WATCHLIST to avoid cross-test leakage.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routers.watchlist_router as watchlist_router
from analytics.mtf_analyzer import MTFState, TFSignal
from config import settings
from routers.watchlist_router import inject_dependencies
from routers.watchlist_router import router as watchlist_api_router


@pytest.fixture
def app_with_router():
    app = FastAPI()
    app.include_router(watchlist_api_router)
    return app


@pytest.fixture
def client(app_with_router):
    return TestClient(app_with_router)


@pytest.fixture(autouse=True)
def _restore_watchlists():
    """Snapshot/restore the global watchlists mutated by add/remove endpoints."""
    prior_futures = list(settings.FUTURES_WATCHLIST)
    prior_options = list(settings.OPTIONS_WATCHLIST)
    yield
    settings.FUTURES_WATCHLIST = prior_futures
    settings.OPTIONS_WATCHLIST = prior_options


@pytest.fixture(autouse=True)
def _restore_data_manager():
    """Snapshot/restore the module-global _data_manager injected via inject_dependencies."""
    prior = watchlist_router._data_manager
    yield
    watchlist_router._data_manager = prior


# ─────────────────────────────────────────────────────────────────────────────
# GET /watchlist
# ─────────────────────────────────────────────────────────────────────────────
def test_get_watchlist_with_data_manager_returns_prices(client):
    settings.FUTURES_WATCHLIST = ["MES", "MNQ"]
    settings.OPTIONS_WATCHLIST = ["SPY"]

    mock_dm = AsyncMock()
    mock_dm.get_batch_prices.return_value = {
        "MES": {"last_price": 5800.0, "change_pct": 0.5},
        "MNQ": {"last_price": 20100.0, "change_pct": -0.2},
        "SPY": {"last_price": 550.0, "change_pct": 0.1},
    }
    inject_dependencies(None, data_manager=mock_dm)

    resp = client.get("/watchlist")
    assert resp.status_code == 200
    items = resp.json()
    by_symbol = {i["symbol"]: i for i in items}
    assert by_symbol["MES"]["type"] == "futures"
    assert by_symbol["MES"]["last_price"] == 5800.0
    assert by_symbol["MES"]["name"] == "Micro E-mini S&P 500"
    assert by_symbol["SPY"]["type"] == "options"
    assert by_symbol["SPY"]["last_price"] == 550.0
    mock_dm.get_batch_prices.assert_awaited_once()


def test_get_watchlist_price_fetch_failure_falls_back_to_none(client):
    """When get_batch_prices raises, every item still returns with null prices (no 500)."""
    settings.FUTURES_WATCHLIST = ["MES"]
    settings.OPTIONS_WATCHLIST = ["SPY"]

    mock_dm = AsyncMock()
    mock_dm.get_batch_prices.side_effect = RuntimeError("upstream data feed down")
    inject_dependencies(None, data_manager=mock_dm)

    resp = client.get("/watchlist")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 2
    for item in items:
        assert item["last_price"] is None
        assert item["change_pct"] is None


def test_get_watchlist_no_data_manager_returns_null_prices(client):
    settings.FUTURES_WATCHLIST = ["MCL"]
    settings.OPTIONS_WATCHLIST = []
    watchlist_router._data_manager = None

    resp = client.get("/watchlist")
    assert resp.status_code == 200
    items = resp.json()
    assert items == [
        {
            "symbol": "MCL",
            "name": "Micro Crude Oil",
            "type": "futures",
            "last_price": None,
            "change_pct": None,
        }
    ]


# ─────────────────────────────────────────────────────────────────────────────
# POST /watchlist
# ─────────────────────────────────────────────────────────────────────────────
def test_add_futures_symbol_success(client):
    settings.FUTURES_WATCHLIST = ["MES"]
    resp = client.post("/watchlist", json={"symbol": "mcl"})
    assert resp.status_code == 200
    data = resp.json()
    assert data == {"status": "added", "symbol": "MCL", "type": "futures"}
    assert "MCL" in settings.FUTURES_WATCHLIST


def test_add_options_symbol_success(client):
    settings.OPTIONS_WATCHLIST = []
    resp = client.post("/watchlist", json={"symbol": "nvda"})
    assert resp.status_code == 200
    data = resp.json()
    assert data == {"status": "added", "symbol": "NVDA", "type": "options"}
    assert "NVDA" in settings.OPTIONS_WATCHLIST


def test_add_empty_symbol_returns_400(client):
    resp = client.post("/watchlist", json={"symbol": "   "})
    assert resp.status_code == 400
    assert "symbol must not be empty" in resp.json()["detail"]


# ─────────────────────────────────────────────────────────────────────────────
# GET /watchlist/scan
# ─────────────────────────────────────────────────────────────────────────────
def test_scan_watchlist_success(client):
    async def fake_analyze_mtf(symbol, data_manager=None):
        return MTFState(
            symbol=symbol,
            signals=[TFSignal("1h", 60.0, "BULLISH", 100.0, "live")],
            alignment="BULLISH",
            confidence=1.0,
            aligned_timeframes=3,
            total_timeframes=3,
            recommendation="BUY",
            source="live",
        )

    with patch("analytics.mtf_analyzer.analyze_mtf", side_effect=fake_analyze_mtf):
        resp = client.get("/watchlist/scan", params={"symbols": "MES,MNQ"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["market_bias"] == "BULLISH"
    assert data["buy_count"] == 2
    assert data["sell_count"] == 0
    assert len(data["symbols"]) == 2
    assert data["symbols"][0]["recommendation"] == "BUY"
    assert data["symbols"][0]["timeframes"]["1h"]["stc_signal"] == "BULLISH"


def test_scan_watchlist_empty_symbols_returns_400(client):
    resp = client.get("/watchlist/scan", params={"symbols": "  ,  "})
    assert resp.status_code == 400
    assert "No symbols provided" in resp.json()["detail"]


def test_scan_watchlist_per_symbol_error_does_not_fail_whole_request(client):
    """A single symbol's analyze_mtf failure degrades to WAIT/error, not a 500."""

    async def flaky_analyze_mtf(symbol, data_manager=None):
        if symbol == "MES":
            raise ValueError("bad bars")
        return MTFState(symbol=symbol, recommendation="SELL", alignment="BEARISH")

    with patch("analytics.mtf_analyzer.analyze_mtf", side_effect=flaky_analyze_mtf):
        resp = client.get("/watchlist/scan", params={"symbols": "MES,MNQ"})

    assert resp.status_code == 200
    data = resp.json()
    results_by_symbol = {r["symbol"]: r for r in data["symbols"]}
    assert results_by_symbol["MES"]["recommendation"] == "WAIT"
    assert results_by_symbol["MES"]["error"] == "bad bars"
    assert results_by_symbol["MNQ"]["recommendation"] == "SELL"
    assert data["sell_count"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# DELETE /watchlist/{symbol}
# ─────────────────────────────────────────────────────────────────────────────
def test_remove_futures_symbol_success(client):
    settings.FUTURES_WATCHLIST = ["MES", "MNQ"]
    resp = client.delete("/watchlist/mes")
    assert resp.status_code == 200
    assert resp.json() == {"status": "removed", "symbol": "MES"}
    assert "MES" not in settings.FUTURES_WATCHLIST
    assert "MNQ" in settings.FUTURES_WATCHLIST


def test_remove_symbol_not_found_returns_404(client):
    settings.FUTURES_WATCHLIST = ["MES"]
    settings.OPTIONS_WATCHLIST = ["SPY"]
    resp = client.delete("/watchlist/ZZZZ")
    assert resp.status_code == 404
    assert "ZZZZ" in resp.json()["detail"]
