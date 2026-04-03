"""
Offline tests for the /prices/snapshot endpoint.

These are offline counterparts to the 4 tests in test_prices_router.py that
skip when data_manager is None (503 response).  Instead of hitting a live
data_manager we patch main.data_manager with a MagicMock — the same pattern
used by test_get_price_snapshot_caching in test_prices_router.py.

All 4 tests must PASS without any IBKR/Polygon connection.
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from config import settings
from main import app


@pytest.fixture
def client():
    """Create test client with X-API-Key matching app settings."""
    key = os.environ.get("API_KEY") or settings.API_KEY
    return TestClient(app, headers={"X-API-Key": key})


@pytest.fixture
def mock_dm():
    """Return a MagicMock data_manager whose get_batch_prices returns realistic data."""
    dm = MagicMock()
    dm.get_batch_prices = AsyncMock(
        return_value={
            "SPY": {
                "last_price": 500.0,
                "prev_close": 498.0,
                "change_pct": 0.40,
                "source": "polygon",
            },
            "QQQ": {
                "last_price": 430.0,
                "prev_close": 428.0,
                "change_pct": 0.47,
                "source": "polygon",
            },
            "MES": {
                "last_price": 5200.0,
                "prev_close": 5180.0,
                "change_pct": 0.39,
                "source": "ibkr",
            },
            "MNQ": {
                "last_price": 18100.0,
                "prev_close": 18050.0,
                "change_pct": 0.28,
                "source": "ibkr",
            },
        }
    )
    return dm


def test_offline_get_price_snapshot_empty_symbols(client, mock_dm):
    """
    Offline: /prices/snapshot with empty symbols string returns {}.

    The endpoint short-circuits before calling data_manager when symbol_list
    is empty, so the return value of get_batch_prices doesn't matter — but we
    still patch data_manager so the 503 guard passes.
    """
    import main as main_mod

    with patch.object(main_mod, "data_manager", mock_dm):
        response = client.get("/prices/snapshot?symbols=")

    assert response.status_code == 200
    assert response.json() == {}


def test_offline_get_price_snapshot_single_symbol(client, mock_dm):
    """Offline: /prices/snapshot with a single symbol returns that symbol's data."""
    import main as main_mod

    with patch.object(main_mod, "data_manager", mock_dm):
        response = client.get("/prices/snapshot?symbols=SPY")

    assert response.status_code == 200
    data = response.json()
    assert "SPY" in data
    assert "symbol" in data["SPY"]
    assert data["SPY"]["last_price"] == 500.0


def test_offline_get_price_snapshot_multiple_symbols(client, mock_dm):
    """Offline: /prices/snapshot with multiple symbols returns all requested symbols."""
    import main as main_mod

    with patch.object(main_mod, "data_manager", mock_dm):
        response = client.get("/prices/snapshot?symbols=SPY,QQQ")

    assert response.status_code == 200
    data = response.json()
    assert "SPY" in data
    assert "QQQ" in data
    assert data["SPY"]["last_price"] == 500.0
    assert data["QQQ"]["last_price"] == 430.0


def test_offline_get_price_snapshot_futures(client, mock_dm):
    """Offline: /prices/snapshot with futures symbols returns MES and MNQ data."""
    import main as main_mod

    with patch.object(main_mod, "data_manager", mock_dm):
        response = client.get("/prices/snapshot?symbols=MES,MNQ")

    assert response.status_code == 200
    data = response.json()
    assert "MES" in data
    assert "MNQ" in data
    assert data["MES"]["last_price"] == 5200.0
    assert data["MNQ"]["last_price"] == 18100.0
