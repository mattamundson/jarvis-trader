"""
Offline tests for the /prices/snapshot endpoint.

These tests patch routers.prices_router._data_manager directly (the module-
level reference that get_price_snapshot reads) and mock get_current_price so
no live IBKR/Polygon connection is needed.

Note: the router uses get_current_price() per symbol, not get_batch_prices().
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from config import settings
from main import app

_PRICE_DATA = {
    "SPY": {"last_price": 500.0, "prev_close": 498.0, "change_pct": 0.40, "source": "polygon"},
    "QQQ": {"last_price": 430.0, "prev_close": 428.0, "change_pct": 0.47, "source": "polygon"},
    "MES": {"last_price": 5200.0, "prev_close": 5180.0, "change_pct": 0.39, "source": "ibkr"},
    "MNQ": {"last_price": 18100.0, "prev_close": 18050.0, "change_pct": 0.28, "source": "ibkr"},
}


@pytest.fixture
def client():
    """Create test client with X-API-Key matching app settings."""
    key = os.environ.get("API_KEY") or settings.API_KEY
    return TestClient(app, headers={"X-API-Key": key})


@pytest.fixture(autouse=True)
def _clear_price_cache():
    """Clear the module-level PriceCache between tests to prevent cross-test contamination."""
    import routers.prices_router as _pr

    _pr._price_cache._cache.clear()
    yield
    _pr._price_cache._cache.clear()


@pytest.fixture
def mock_dm():
    """Return a MagicMock data_manager whose get_current_price returns per-symbol data."""
    dm = MagicMock()

    async def _get_current_price(sym, **_kw):
        return _PRICE_DATA.get(sym.upper(), {"last_price": None})

    dm.get_current_price = AsyncMock(side_effect=_get_current_price)
    return dm


def _patch_dm(mock_dm):
    """Context manager: inject mock_dm into the prices router's module-level ref."""
    return patch("routers.prices_router._data_manager", mock_dm)


def test_offline_get_price_snapshot_empty_symbols(client, mock_dm):
    """
    Offline: /prices/snapshot with empty symbols string returns {}.

    The endpoint short-circuits before calling data_manager when symbol_list
    is empty, so get_current_price is never called.
    """
    with _patch_dm(mock_dm):
        response = client.get("/prices/snapshot?symbols=")

    assert response.status_code == 200
    assert response.json() == {}


def test_offline_get_price_snapshot_single_symbol(client, mock_dm):
    """Offline: /prices/snapshot with a single symbol returns that symbol's data."""
    with _patch_dm(mock_dm):
        response = client.get("/prices/snapshot?symbols=SPY")

    assert response.status_code == 200
    data = response.json()
    assert "SPY" in data
    assert "symbol" in data["SPY"]
    assert data["SPY"]["last_price"] == 500.0


def test_offline_get_price_snapshot_multiple_symbols(client, mock_dm):
    """Offline: /prices/snapshot with multiple symbols returns all requested symbols."""
    with _patch_dm(mock_dm):
        response = client.get("/prices/snapshot?symbols=SPY,QQQ")

    assert response.status_code == 200
    data = response.json()
    assert "SPY" in data
    assert "QQQ" in data
    assert data["SPY"]["last_price"] == 500.0
    assert data["QQQ"]["last_price"] == 430.0


def test_offline_get_price_snapshot_futures(client, mock_dm):
    """Offline: /prices/snapshot with futures symbols returns MES and MNQ data."""
    with _patch_dm(mock_dm):
        response = client.get("/prices/snapshot?symbols=MES,MNQ")

    assert response.status_code == 200
    data = response.json()
    assert "MES" in data
    assert "MNQ" in data
    assert data["MES"]["last_price"] == 5200.0
    assert data["MNQ"]["last_price"] == 18100.0
