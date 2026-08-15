"""Tests for routers/macro_router.py — /macro/snapshot, /macro/series/{id}, /macro/regime.

Design:
  - FastAPI TestClient (sync) mounted with only macro_router — no full app, no
    real network, no real .env secrets.
  - The router does its imports (`data.fred_data`, `options.strategy_executor`,
    `backtest.macro_regime`) *inside* each endpoint function, so we patch the
    functions at their source-module location (`patch("data.fred_data...")`)
    rather than at the router's import site — the local `from x import y`
    re-binds at call time and picks up the patched attribute.
  - Each test resets the router's module-level `_macro_cache` / `_data_manager`
    state so the 5-minute in-memory cache from one test can't leak into the next.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import macro_router


@pytest.fixture(autouse=True)
def _reset_macro_router_state():
    """Clear the in-memory snapshot/regime cache and injected data_manager."""
    macro_router._macro_cache.clear()
    macro_router.inject_dependencies(data_manager=None)
    yield
    macro_router._macro_cache.clear()
    macro_router.inject_dependencies(data_manager=None)


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(macro_router.router)
    return TestClient(app)


# ---------------------------------------------------------------------------
# GET /macro/snapshot
# ---------------------------------------------------------------------------


def test_snapshot_success_flattens_fred_payload(client):
    """Normal FRED payload is flattened + VIX classified into a regime band."""
    raw = {
        "timestamp": "2026-07-09T10:00:00",
        "fed_funds_rate": {"value": 5.25, "unit": "%", "description": "Federal Funds Rate"},
        "ten_year_yield": {"value": 4.10, "unit": "%", "description": "10-Year Treasury Yield"},
        "vix": {"value": 12.0, "unit": "index", "description": "CBOE Volatility Index"},
        "unemployment": {"value": 3.9, "unit": "%", "description": "Unemployment Rate"},
    }
    mock_service = MagicMock()
    mock_service.get_macro_snapshot.return_value = raw

    with patch("data.fred_data.get_fred_service", return_value=mock_service):
        response = client.get("/macro/snapshot")

    assert response.status_code == 200
    body = response.json()
    assert body["vix"] == 12.0
    assert body["fed_funds_rate"] == 5.25
    assert body["ten_year_yield"] == 4.10
    assert body["unemployment"] == 3.9
    assert body["timestamp"] == "2026-07-09T10:00:00"
    assert body["vix_regime"] == "LOW"  # vix < 15


def test_snapshot_fred_failure_falls_back_to_data_manager_vix(client):
    """When FRED raises, the endpoint still returns 200 and enriches VIX from data_manager."""
    mock_service = MagicMock()
    mock_service.get_macro_snapshot.side_effect = RuntimeError("FRED API down")

    mock_dm = MagicMock()
    mock_dm.get_vix = AsyncMock(return_value={"value": 25.5, "source": "ibkr"})
    macro_router.inject_dependencies(data_manager=mock_dm)

    with patch("data.fred_data.get_fred_service", return_value=mock_service):
        response = client.get("/macro/snapshot")

    assert response.status_code == 200
    body = response.json()
    assert body["vix"] == 25.5
    assert body["vix_regime"] == "HIGH"  # 20 <= 25.5 < 30
    # Everything else genuinely unavailable from FRED
    assert body["fed_funds_rate"] is None
    assert body["ten_year_yield"] is None
    assert body["unemployment"] is None


def test_snapshot_total_failure_degrades_gracefully(client):
    """FRED raises AND no data_manager registered -> all-None payload, still 200."""
    mock_service = MagicMock()
    mock_service.get_macro_snapshot.side_effect = RuntimeError("FRED API down")

    with patch("data.fred_data.get_fred_service", return_value=mock_service):
        response = client.get("/macro/snapshot")

    assert response.status_code == 200
    body = response.json()
    assert body["vix"] is None
    assert body["fed_funds_rate"] is None
    assert body["ten_year_yield"] is None
    assert body["unemployment"] is None
    assert body["vix_regime"] is None


def test_snapshot_uses_5min_cache_on_second_call(client):
    """Second call within the 5-minute TTL should not re-hit the FRED service."""
    raw = {
        "timestamp": "2026-07-09T10:00:00",
        "fed_funds_rate": {"value": 5.25},
        "ten_year_yield": {"value": 4.10},
        "vix": {"value": 18.0},
        "unemployment": {"value": 3.9},
    }
    mock_service = MagicMock()
    mock_service.get_macro_snapshot.return_value = raw

    with patch("data.fred_data.get_fred_service", return_value=mock_service) as get_service:
        r1 = client.get("/macro/snapshot")
        r2 = client.get("/macro/snapshot")

    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json() == r2.json()
    # get_fred_service() is called once per request that misses cache; the second
    # request should be served from _macro_cache without calling get_macro_snapshot again.
    assert mock_service.get_macro_snapshot.call_count == 1


# ---------------------------------------------------------------------------
# GET /macro/series/{series_id}
# ---------------------------------------------------------------------------


def test_series_success_returns_history(client):
    mock_service = MagicMock()
    mock_service.get_series_history.return_value = [
        {"date": "2026-06-01", "value": 5.25},
        {"date": "2026-07-01", "value": 5.33},
    ]

    with patch("data.fred_data.get_fred_service", return_value=mock_service):
        response = client.get("/macro/series/fedfunds?periods=12")

    assert response.status_code == 200
    body = response.json()
    assert body["series_id"] == "FEDFUNDS"  # upper-cased
    assert body["count"] == 2
    assert body["data"][1]["value"] == 5.33
    mock_service.get_series_history.assert_called_once_with("FEDFUNDS", 12)


def test_series_not_found_returns_404(client):
    mock_service = MagicMock()
    mock_service.get_series_history.return_value = []

    with patch("data.fred_data.get_fred_service", return_value=mock_service):
        response = client.get("/macro/series/BOGUSSERIES")

    assert response.status_code == 404
    assert "BOGUSSERIES" in response.json()["detail"]


# ---------------------------------------------------------------------------
# GET /macro/regime
# ---------------------------------------------------------------------------


def test_regime_success_returns_computed_result(client):
    result = {
        "state": "RISK_ON",
        "weekly_trend": "UP",
        "monthly_momentum": "ABOVE",
        "asof": "2026-07-03",
        "spy_close": 560.12,
        "bias_line": "MACRO TREND: RISK_ON ...",
        "stale_days": 4,
        "components": {"weekly_supertrend_atr10x3": True, "monthly_sma12_momentum": True},
    }

    with patch("backtest.macro_regime.compute_macro_regime", return_value=result):
        response = client.get("/macro/regime")

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "RISK_ON"
    assert body["spy_close"] == 560.12


def test_regime_computation_failure_returns_500(client):
    with patch(
        "backtest.macro_regime.compute_macro_regime",
        side_effect=RuntimeError("SPY bar load failed"),
    ):
        response = client.get("/macro/regime")

    assert response.status_code == 500
    assert "macro regime computation failed" in response.json()["detail"]
