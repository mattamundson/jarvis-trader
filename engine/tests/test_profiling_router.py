"""
JARVIS TRADER — Profiling Router Tests
======================================
Tests for GET /pipeline/profiling/summary, /averages, /history endpoints.

Run with:
    cd engine
    .venv\\Scripts\\python.exe -m pytest tests/test_profiling_router.py -v --tb=short
"""

from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Set test environment variables BEFORE any imports
test_env_vars = {
    "API_KEY": "test-key",
    "POSTGRES_URL": "postgresql://test:test@localhost/test",
    "REDIS_URL": "redis://localhost",
    "POLYGON_API_KEY": "test-key",
    "ANTHROPIC_API_KEY": "test-key",
    "SCHWAB_APP_KEY": "test",
    "SCHWAB_APP_SECRET": "test",
    "FINNHUB_API_KEY": "test",
    "ALPACA_API_KEY": "test",
    "ALPACA_SECRET_KEY": "test",
    "TWILIO_ACCOUNT_SID": "test",
    "TWILIO_AUTH_TOKEN": "test",
    "TWILIO_WHATSAPP_FROM": "+1234567890",
    "WHATSAPP_TO": "+0987654321",
    "TRADINGVIEW_WEBHOOK_SECRET": "jarvis_test_secret_12345",
}
for key, value in test_env_vars.items():
    os.environ.setdefault(key, value)

# Add engine to path
_ENGINE_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if _ENGINE_ROOT not in sys.path:
    sys.path.insert(0, _ENGINE_ROOT)


@pytest.fixture
def mock_profiler_instance():
    """Create a mocked profiler instance."""
    p = AsyncMock()
    p.get_report = AsyncMock(
        return_value={
            "stage_1_technical": 0.125,
            "stage_2_debate": 0.245,
            "stage_3_trader": 0.180,
            "stage_4_risk": 0.090,
            "stage_5_fund": 0.075,
            "total": 1.050,
        }
    )
    p.get_average_times = AsyncMock(return_value={"stage_1_technical": 0.122, "total": 1.048})
    p.get_history = AsyncMock(
        return_value=[
            {
                "run_id": 1,
                "timestamp": "2026-03-29T10:00:00",
                "total": 1.050,
                "stages": {"stage_1_technical": 0.125, "total": 1.050},
            }
        ]
    )
    p.get_history_size = AsyncMock(return_value=2)
    p.get_max_history = AsyncMock(return_value=1000)
    return p


@pytest.fixture
def client(mock_profiler_instance):
    """FastAPI TestClient wrapping profiling router."""
    from routers import profiling_router as profiling_module
    from routers.profiling_router import router as profiling_router

    app = FastAPI()
    app.include_router(profiling_router)
    profiling_module.set_profiler_instance(mock_profiler_instance)
    return TestClient(app, raise_server_exceptions=True)


class TestProfilingRouter:
    """Profiling router integration tests."""

    def test_summary_returns_200(self, client):
        """GET /pipeline/profiling/summary returns HTTP 200."""
        resp = client.get("/pipeline/profiling/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "current_run" in data
        assert data["current_run"]["total"] == 1.050

    def test_summary_includes_stages(self, client):
        """summary includes stage timings."""
        data = client.get("/pipeline/profiling/summary").json()
        assert "stage_1_technical" in data["current_run"]

    def test_summary_returns_503_if_no_profiler(self):
        """Returns 503 if profiler not available."""
        from routers import profiling_router as profiling_module
        from routers.profiling_router import router as profiling_router

        app = FastAPI()
        app.include_router(profiling_router)
        profiling_module.set_profiler_instance(None)

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/pipeline/profiling/summary")
        assert resp.status_code == 503

    def test_averages_returns_200(self, client):
        """GET /pipeline/profiling/averages returns HTTP 200."""
        resp = client.get("/pipeline/profiling/averages")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "rolling_averages" in data
        assert "period" in data
        assert data["rolling_averages"]["total"] == 1.048

    def test_averages_respects_last_n(self, client):
        """averages respects last_n parameter."""
        resp = client.get("/pipeline/profiling/averages?last_n=50")
        assert resp.status_code == 200
        assert "rolling_averages" in resp.json()

    def test_history_returns_200(self, client):
        """GET /pipeline/profiling/history returns HTTP 200."""
        resp = client.get("/pipeline/profiling/history")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "history" in data
        assert isinstance(data["history"], list)
        assert len(data["history"]) > 0

    def test_history_includes_capacity_fields(self, client):
        """history response includes capacity tracking fields."""
        data = client.get("/pipeline/profiling/history").json()
        assert "retrieved_count" in data
        assert "total_stored" in data
        assert "max_capacity" in data
        assert data["total_stored"] == 2
        assert data["max_capacity"] == 1000

    def test_history_respects_last_n(self, client):
        """history respects last_n parameter."""
        resp = client.get("/pipeline/profiling/history?last_n=5")
        assert resp.status_code == 200
