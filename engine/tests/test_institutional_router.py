"""Tests for the institutional router (Volume Profile + Harmonics + Regime).

TestClient mounts the real router standalone (no main.py auth middleware,
matching this repo's other standalone router tests e.g.
test_hidden_pivots_router.py). Only the injected MarketDataManager is
mocked -- the volume-profile, harmonics, and regime engines run for real
against synthetic OHLCV bars, same pattern as test_hidden_pivots_router.py's
`_fake_bars` fixture.
"""

from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import institutional_router
from routers.institutional_router import router as institutional_api_router


def _fake_bars(n: int = 150) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    dates = pd.date_range("2025-01-01", periods=n, freq="15min")
    close = 100.0 + np.cumsum(rng.normal(0.05, 0.5, n))
    close = np.clip(close, 1.0, None)
    spread = np.abs(rng.normal(0.4, 0.1, n))
    return pd.DataFrame(
        {
            "open": close,
            "high": close + spread,
            "low": close - spread,
            "close": close,
            "volume": rng.integers(500, 5000, n).astype(float),
        },
        index=dates,
    )


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(institutional_api_router)
    # raise_server_exceptions=False so an unhandled exception in the handler
    # (e.g. a data-manager failure the router doesn't catch) surfaces as a
    # real 500 response instead of propagating out of client.get().
    return TestClient(app, raise_server_exceptions=False)


class TestProfileEndpoint:
    def test_503_when_data_manager_not_injected(self, client, monkeypatch):
        monkeypatch.setattr(institutional_router, "_data_manager", None)
        resp = client.get("/institutional/profile/MCL")
        assert resp.status_code == 503

    def test_404_when_no_bars_returned(self, client, monkeypatch):
        mock_dm = MagicMock()
        mock_dm.get_bars = AsyncMock(return_value=pd.DataFrame())
        monkeypatch.setattr(institutional_router, "_data_manager", mock_dm)

        resp = client.get("/institutional/profile/MCL")
        assert resp.status_code == 404

    def test_returns_full_shape_on_success(self, client, monkeypatch):
        mock_dm = MagicMock()
        mock_dm.get_bars = AsyncMock(return_value=_fake_bars())
        monkeypatch.setattr(institutional_router, "_data_manager", mock_dm)

        resp = client.get("/institutional/profile/mcl", params={"timeframe": "15m"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["symbol"] == "MCL"  # symbol is upper-cased
        assert isinstance(data["current_price"], (int, float))
        assert "volume_profile" in data and isinstance(data["volume_profile"], dict)
        assert isinstance(data["harmonics"], list)
        for pattern in data["harmonics"]:
            assert {"name", "type", "confidence", "points", "ratios"} <= set(pattern)
        regime = data["regime"]
        assert {"value", "description", "adx", "atr_ratio"} <= set(regime)
        assert data["timeframe"] == "15m"

    def test_futures_symbol_flag_passed_to_data_manager(self, client, monkeypatch):
        mock_dm = MagicMock()
        mock_dm.get_bars = AsyncMock(return_value=_fake_bars())
        monkeypatch.setattr(institutional_router, "_data_manager", mock_dm)

        resp = client.get("/institutional/profile/MCL")
        assert resp.status_code == 200
        mock_dm.get_bars.assert_awaited_once_with(
            "MCL", lookback_days=10, timeframe="15m", is_futures=True
        )

    def test_equity_symbol_not_treated_as_futures(self, client, monkeypatch):
        mock_dm = MagicMock()
        mock_dm.get_bars = AsyncMock(return_value=_fake_bars())
        monkeypatch.setattr(institutional_router, "_data_manager", mock_dm)

        resp = client.get("/institutional/profile/SPY")
        assert resp.status_code == 200
        mock_dm.get_bars.assert_awaited_once_with(
            "SPY", lookback_days=10, timeframe="15m", is_futures=False
        )

    def test_get_bars_exception_propagates_as_server_error(self, client, monkeypatch):
        # The router does not catch exceptions from get_bars itself (unlike
        # market_router's /data-source-status) -- a broker/data failure here
        # surfaces as an unhandled 500 rather than a graceful error payload.
        mock_dm = MagicMock()
        mock_dm.get_bars = AsyncMock(side_effect=RuntimeError("data source down"))
        monkeypatch.setattr(institutional_router, "_data_manager", mock_dm)

        resp = client.get("/institutional/profile/MCL")
        assert resp.status_code == 500
