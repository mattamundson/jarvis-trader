"""Tests for market data endpoints: earnings stub, session clock, data-source probe.

TestClient mounts the real router standalone (no main.py auth middleware).
The injected MarketDataManager is mocked via monkeypatch on the router module.
The `/market/session` clock reads `datetime.now()` via a function-local
`from datetime import datetime`, so tests freeze time by swapping the
`datetime` class attribute on the shared `datetime` module -- the router
re-resolves that attribute on every call, so the swap is picked up without
touching the router's import statement.
"""

import datetime as datetime_module
import zoneinfo
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import market_router
from routers.market_router import router as market_api_router

_EASTERN = zoneinfo.ZoneInfo("America/New_York")


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(market_api_router)
    return TestClient(app)


def _freeze_now(monkeypatch, iso: str) -> None:
    """Freeze `datetime.datetime.now()` (as seen by market_router) to `iso`, ET."""
    frozen = datetime_module.datetime.fromisoformat(iso).replace(tzinfo=_EASTERN)

    class _FrozenDatetime(datetime_module.datetime):
        @classmethod
        def now(cls, tz=None):
            return frozen

    monkeypatch.setattr(datetime_module, "datetime", _FrozenDatetime)


def _fake_bars(n: int = 10, source: str = "ibkr") -> pd.DataFrame:
    idx = pd.date_range("2026-07-01", periods=n, freq="1h")
    df = pd.DataFrame(
        {
            "open": [100.0] * n,
            "high": [101.0] * n,
            "low": [99.0] * n,
            "close": [100.5] * n,
            "volume": [1000.0] * n,
        },
        index=idx,
    )
    df.attrs["source"] = source
    return df


# ─── GET /market/earnings ─────────────────────────────────────────────────


class TestEarningsEndpoint:
    def test_default_days_lookahead(self, client):
        resp = client.get("/market/earnings")
        assert resp.status_code == 200
        data = resp.json()
        assert data["upcoming_earnings"] == []
        assert data["count"] == 0
        assert data["days_lookahead"] == 7
        assert data["source"] == "unavailable"

    def test_custom_days_lookahead(self, client):
        resp = client.get("/market/earnings", params={"days": 14})
        assert resp.status_code == 200
        assert resp.json()["days_lookahead"] == 14

    def test_non_integer_days_returns_422(self, client):
        resp = client.get("/market/earnings", params={"days": "not-a-number"})
        assert resp.status_code == 422


# ─── GET /market/session ──────────────────────────────────────────────────


class TestSessionEndpoint:
    def test_regular_session_on_a_weekday_noon(self, client, monkeypatch):
        _freeze_now(monkeypatch, "2026-07-07T12:00:00")  # Tuesday, 12:00 ET
        resp = client.get("/market/session")
        assert resp.status_code == 200
        data = resp.json()
        assert data["session"] == "regular"
        assert data["is_open"] is True

    def test_weekend_is_closed(self, client, monkeypatch):
        _freeze_now(monkeypatch, "2026-07-11T12:00:00")  # Saturday
        resp = client.get("/market/session")
        data = resp.json()
        assert data["session"] == "closed"
        assert "weekend" in data["description"].lower()
        assert data["is_open"] is False

    def test_pre_market_window(self, client, monkeypatch):
        _freeze_now(monkeypatch, "2026-07-07T07:00:00")  # Tuesday, 7:00 ET
        resp = client.get("/market/session")
        data = resp.json()
        assert data["session"] == "pre_market"
        assert data["is_open"] is False

    def test_after_hours_window(self, client, monkeypatch):
        _freeze_now(monkeypatch, "2026-07-07T17:00:00")  # Tuesday, 17:00 ET
        resp = client.get("/market/session")
        data = resp.json()
        assert data["session"] == "after_hours"
        assert data["is_open"] is False

    def test_session_response_is_self_consistent(self, client):
        # No freeze -- sanity-check invariants against whatever "now" actually is.
        resp = client.get("/market/session")
        assert resp.status_code == 200
        data = resp.json()
        assert data["session"] in {"closed", "pre_market", "regular", "after_hours"}
        assert data["is_open"] == (data["session"] == "regular")


# ─── GET /market/data-source-status ───────────────────────────────────────


class TestDataSourceStatusEndpoint:
    def test_503_when_data_manager_not_injected(self, client, monkeypatch):
        monkeypatch.setattr(market_router, "_data_manager", None)
        resp = client.get("/market/data-source-status")
        assert resp.status_code == 503

    def test_returns_source_and_bar_count_on_success(self, client, monkeypatch):
        mock_dm = MagicMock()
        mock_dm.get_bars = AsyncMock(return_value=_fake_bars(n=42, source="polygon"))
        monkeypatch.setattr(market_router, "_data_manager", mock_dm)

        resp = client.get(
            "/market/data-source-status",
            params={"symbol": "MCL", "timeframe": "1h", "lookback_days": 5},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["symbol"] == "MCL"
        assert data["timeframe"] == "1h"
        assert data["source"] == "polygon"
        assert data["bars"] == 42
        assert "latency_ms" in data
        mock_dm.get_bars.assert_awaited_once_with(symbol="MCL", timeframe="1h", lookback_days=5)

    def test_empty_bars_reports_none_source(self, client, monkeypatch):
        empty = pd.DataFrame()
        empty.attrs["source"] = "none"
        mock_dm = MagicMock()
        mock_dm.get_bars = AsyncMock(return_value=empty)
        monkeypatch.setattr(market_router, "_data_manager", mock_dm)

        resp = client.get("/market/data-source-status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["source"] == "none"
        assert data["bars"] == 0

    def test_get_bars_exception_returns_error_payload_not_500(self, client, monkeypatch):
        mock_dm = MagicMock()
        mock_dm.get_bars = AsyncMock(side_effect=RuntimeError("polygon unreachable"))
        monkeypatch.setattr(market_router, "_data_manager", mock_dm)

        resp = client.get("/market/data-source-status")
        # The handler catches the exception itself and returns 200 with an
        # "error" source rather than letting FastAPI turn it into a 500.
        assert resp.status_code == 200
        data = resp.json()
        assert data["source"] == "error"
        assert data["bars"] == 0
        assert "polygon unreachable" in data["error"]
