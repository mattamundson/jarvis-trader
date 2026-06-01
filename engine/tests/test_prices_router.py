"""
Test prices router with caching.

Note: These tests call the live /prices/snapshot endpoint in main.py.
When running without a live data_manager (CI / unit test mode), the endpoint
returns 503 "Data manager not initialized". Tests that hit live data skip in
that case so the suite stays green without requiring a running IBKR/Polygon
connection.
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from config import settings
from main import app


@pytest.fixture
def client():
    """Create test client with X-API-Key matching running app settings."""
    key = os.environ.get("API_KEY") or settings.API_KEY
    return TestClient(app, headers={"X-API-Key": key})


def _skip_if_no_data_manager(response):
    """Skip the test if the data manager isn't initialised (CI / no-creds env)."""
    if response.status_code == 503:
        pytest.skip("data_manager not initialized — no IBKR/Polygon connection in test env")


def test_get_price_snapshot_empty_symbols(client):
    """Test /prices/snapshot with empty symbols."""
    response = client.get("/prices/snapshot?symbols=")
    _skip_if_no_data_manager(response)
    assert response.status_code == 200
    assert response.json() == {}


def test_get_price_snapshot_single_symbol(client):
    """Test /prices/snapshot with single symbol."""
    response = client.get("/prices/snapshot?symbols=SPY")
    _skip_if_no_data_manager(response)
    assert response.status_code == 200
    data = response.json()
    assert "SPY" in data
    assert "symbol" in data["SPY"]


def test_get_price_snapshot_multiple_symbols(client):
    """Test /prices/snapshot with multiple symbols."""
    response = client.get("/prices/snapshot?symbols=SPY,QQQ")
    _skip_if_no_data_manager(response)
    assert response.status_code == 200
    data = response.json()
    assert "SPY" in data
    assert "QQQ" in data


def test_get_price_snapshot_futures(client):
    """Test /prices/snapshot with futures symbols."""
    response = client.get("/prices/snapshot?symbols=MES,MNQ")
    _skip_if_no_data_manager(response)
    assert response.status_code == 200
    data = response.json()
    if "MES" not in data or "MNQ" not in data:
        pytest.skip("Data manager did not return both MES and MNQ (no connection or market closed)")


def test_get_price_snapshot_caching(client):
    """Test that /prices/snapshot returns consistent data (mocked data_manager).

    The router calls get_current_price(symbol) per symbol — not get_batch_prices.
    Patch routers.prices_router._data_manager (the module-level reference the
    endpoint actually reads) instead of main.data_manager.
    """
    import routers.prices_router as _pr

    spy_data = {
        "last_price": 654.53,
        "prev_close": 654.0,
        "change_pct": 0.08,
        "source": "polygon",
    }

    mock_dm = MagicMock()

    async def _get_current_price(sym, **_kw):
        return spy_data if sym.upper() == "SPY" else {"last_price": None}

    mock_dm.get_current_price = AsyncMock(side_effect=_get_current_price)

    with patch.object(_pr, "_data_manager", mock_dm):
        response1 = client.get("/prices/snapshot?symbols=SPY")
        assert response1.status_code == 200
        data1 = response1.json()

        response2 = client.get("/prices/snapshot?symbols=SPY")
        assert response2.status_code == 200
        data2 = response2.json()

    assert data1["SPY"]["last_price"] == data2["SPY"]["last_price"]
    assert data1["SPY"]["last_price"] == 654.53
