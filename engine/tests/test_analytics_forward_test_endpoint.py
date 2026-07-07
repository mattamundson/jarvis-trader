"""Tests for GET /analytics/forward-test (read-only forward-test cockpit surface).

The endpoint exposes run_forward_test() over the locked candidate registry so the
north-star liveness pane can show whether any held candidate is graduating on its
forward (paper) record. It must:
  - return 200 with the report payload when the DB is wired,
  - degrade gracefully to INSUFFICIENT_DATA (200) when the DB is not initialised
    (never 503 -- the cockpit always wants a renderable body),
  - return 500 when the underlying loop raises,
  - and pass persist=False so the read path never writes report files.

Run with:
    cd engine
    .venv\\Scripts\\python.exe -m pytest tests/test_analytics_forward_test_endpoint.py -v
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

test_env_vars = {
    "API_KEY": "test-key",
    "POSTGRES_URL": "postgresql://test:test@localhost/test",
    "REDIS_URL": "redis://localhost",
    "POLYGON_API_KEY": "test-key",
    "ANTHROPIC_API_KEY": "test-key",
}
for key, value in test_env_vars.items():
    os.environ.setdefault(key, value)

_ENGINE_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if _ENGINE_ROOT not in sys.path:
    sys.path.insert(0, _ENGINE_ROOT)


@pytest.fixture
def client():
    """TestClient wrapping analytics router with rate limiting disabled."""
    from slowapi import Limiter

    for key in list(sys.modules.keys()):
        if "analytics_router" in key:
            del sys.modules[key]

    with patch.object(Limiter, "limit", return_value=lambda f: f):
        from routers.analytics_router import router as analytics_router

    app = FastAPI()
    app.include_router(analytics_router)
    return TestClient(app, raise_server_exceptions=True)


_SAMPLE_REPORT = {
    "generated_at": "2026-06-12T21:00:00+00:00",
    "window_days": 30,
    "graduation_rule": {"min_forward_oos_windows": 6},
    "n_active_candidates": 5,
    "n_graduated": 0,
    "candidates": [
        {
            "id": "MGC_trend_rv_filter_rank1",
            "symbol": "MGC",
            "attribution_level": "symbol",
            "precise_attribution": False,
            "forward": {"n_oos_windows": 1, "p_edge": 0.5},
            "survives_family_fdr": False,
            "graduated": False,
            "reason": "attribution is 'symbol' -- tag trades with candidate_id",
        }
    ],
    "symbol_context": {"MGC": {"n_oos_windows": 1}},
    "note": "Live paper trades are currently scanner-sourced and untagged.",
}


class TestForwardTestEndpoint:
    @patch("routers.analytics_router._get_db")
    @patch("backtest.forward_test.run_forward_test")
    def test_returns_200_with_report(self, mock_run, mock_get_db, client):
        mock_get_db.return_value = MagicMock()
        mock_run.return_value = _SAMPLE_REPORT

        resp = client.get("/analytics/forward-test")
        assert resp.status_code == 200
        data = resp.json()
        assert data["n_active_candidates"] == 5
        assert data["n_graduated"] == 0
        assert data["candidates"][0]["id"] == "MGC_trend_rv_filter_rank1"

    @patch("routers.analytics_router._get_db")
    @patch("backtest.forward_test.run_forward_test")
    def test_passes_persist_false(self, mock_run, mock_get_db, client):
        """The read path must never write report files: persist=False."""
        mock_get_db.return_value = MagicMock()
        mock_run.return_value = _SAMPLE_REPORT

        client.get("/analytics/forward-test")
        assert mock_run.called
        assert mock_run.call_args.kwargs.get("persist") is False

    @patch("routers.analytics_router._get_db")
    def test_db_uninitialised_returns_insufficient_data(self, mock_get_db, client):
        """No 503 -- the cockpit wants a renderable INSUFFICIENT_DATA body."""
        mock_get_db.side_effect = HTTPException(status_code=503, detail="no db")

        resp = client.get("/analytics/forward-test")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "INSUFFICIENT_DATA"
        assert data["n_active_candidates"] == 0
        assert data["candidates"] == []

    @patch("routers.analytics_router._get_db")
    @patch("backtest.forward_test.run_forward_test")
    def test_loop_error_returns_500(self, mock_run, mock_get_db, client):
        mock_get_db.return_value = MagicMock()
        mock_run.side_effect = RuntimeError("boom")

        resp = client.get("/analytics/forward-test")
        assert resp.status_code == 500
