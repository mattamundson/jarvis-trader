"""
JARVIS TRADER — Pipeline Funnel Tests
=====================================
Unit tests for /analytics/pipeline-funnel: the funnel stage math (runs →
signals → approved → executed → filled), the 30/90d window parameter, and
the TTL cache.

Run with:
    cd engine
    .venv\\Scripts\\python.exe -m pytest tests/test_pipeline_funnel.py -v
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Set test environment variables BEFORE any imports
test_env_vars = {
    "API_KEY": "test-key",
    "POSTGRES_URL": "postgresql://test:***@localhost/test",
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
    "TWILIO_WHATSAPP_FROM": "+123****7890",
    "WHATSAPP_TO": "+0987654321",
    "TRADINGVIEW_WEBHOOK_SECRET": "jarvis_test_secret_12345",
}
for key, value in test_env_vars.items():
    os.environ.setdefault(key, value)

_ENGINE_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if _ENGINE_ROOT not in sys.path:
    sys.path.insert(0, _ENGINE_ROOT)

from routers import analytics_router  # noqa: E402


class _FakeDb:
    """Minimal fake DatabaseManager: fetch_one returns configured counts.

    The funnel endpoint only uses fetch_one with COUNT(*) queries; the exact
    SQL text is irrelevant for the math, so we return a canned row per call
    by cycling through a list in the order the endpoint issues queries.
    """

    def __init__(self, counts: list[int]):
        self._counts = list(counts)
        self.calls: list[str] = []

    def fetch_one(self, sql: str, params: tuple = ()) -> dict:
        self.calls.append(sql)
        if not self._counts:
            return {"n": 0}
        return {"n": self._counts.pop(0)}


@pytest.fixture
def client():
    """TestClient wrapping analytics router with rate limiting disabled."""
    with patch.object(type(analytics_router.limiter), "limit", return_value=lambda f: f):
        app = FastAPI()
        app.include_router(analytics_router.router)
    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture(autouse=True)
def _clear_funnel_cache():
    analytics_router._funnel_cache.clear()
    yield
    analytics_router._funnel_cache.clear()


def _set_db(fake: _FakeDb):
    analytics_router.set_db_manager(fake)  # type: ignore[arg-type]


# ── _compute_pipeline_funnel: stage math ────────────────────────────────────


def test_funnel_math_happy_path():
    fake = _FakeDb([1000, 200, 150, 40, 38, 5, 2, 3])  # runs, signals, approved,
    # executed, filled, human_approved(paq), human_approved(pta), human_rejected
    result = analytics_router._compute_pipeline_funnel(fake, days=30)

    assert result["period"] == "30d"
    assert result["days"] == 30
    assert result["funnel"] == {
        "runs": 1000,
        "signals": 200,
        "approved": 150,
        "executed": 40,
        "filled": 38,
    }
    assert result["conversion_rates"] == {
        "runs_to_signals": 20.0,  # 200/1000
        "signals_to_approved": 75.0,  # 150/200
        "approved_to_executed": 26.7,  # 40/150
        "executed_to_filled": 95.0,  # 38/40
        "overall_conversion": 3.8,  # 38/1000
    }
    # Human-review lanes land in details, not the monotone chain.
    assert result["details"]["human_approved"] == 7
    assert result["details"]["human_rejected"] == 3


def test_funnel_math_zero_denominators_do_not_crash():
    fake = _FakeDb([0, 0, 0, 0, 0, 0, 0, 0])
    result = analytics_router._compute_pipeline_funnel(fake, days=90)
    assert result["funnel"] == {
        "runs": 0,
        "signals": 0,
        "approved": 0,
        "executed": 0,
        "filled": 0,
    }
    assert result["conversion_rates"] == {
        "runs_to_signals": 0.0,
        "signals_to_approved": 0.0,
        "approved_to_executed": 0.0,
        "executed_to_filled": 0.0,
        "overall_conversion": 0.0,
    }


def test_funnel_cutoff_format():
    cutoff = analytics_router._funnel_cutoff(30)
    # Naive UTC "YYYY-MM-DDTHH:MM:SS" — must lexicographically compare against
    # both naive pipeline_runs timestamps and tz-aware "+00:00" paper rows.
    assert len(cutoff) == 19
    assert cutoff[10] == "T"
    assert "+" not in cutoff and "Z" not in cutoff


# ── Endpoint: query param + cache ───────────────────────────────────────────


def test_endpoint_defaults_to_30d(client):
    fake = _FakeDb([100, 20, 15, 5, 5, 1, 0, 0])
    _set_db(fake)
    resp = client.get("/analytics/pipeline-funnel")
    assert resp.status_code == 200
    data = resp.json()
    assert data["period"] == "30d"
    assert data["days"] == 30
    assert data["funnel"]["runs"] == 100


def test_endpoint_accepts_90d(client):
    fake = _FakeDb([1000, 300, 250, 80, 75, 10, 0, 5])
    _set_db(fake)
    resp = client.get("/analytics/pipeline-funnel?days=90")
    assert resp.status_code == 200
    data = resp.json()
    assert data["period"] == "90d"
    assert data["days"] == 90
    assert data["conversion_rates"]["runs_to_signals"] == 30.0


def test_endpoint_rejects_out_of_range_days(client):
    _set_db(_FakeDb([0] * 8))
    resp = client.get("/analytics/pipeline-funnel?days=180")
    assert resp.status_code == 422


def test_endpoint_caches_second_call(client):
    fake = _FakeDb([100, 20, 15, 5, 5, 1, 0, 0])
    _set_db(fake)

    resp1 = client.get("/analytics/pipeline-funnel?days=30")
    assert resp1.status_code == 200
    assert resp1.json()["details"]["cache_hit"] is False
    first_calls = list(fake.calls)
    assert len(first_calls) == 8  # 5 funnel + 3 human-lane queries

    resp2 = client.get("/analytics/pipeline-funnel?days=30")
    assert resp2.status_code == 200
    assert resp2.json()["details"]["cache_hit"] is True
    # No additional DB queries issued on cache hit.
    assert fake.calls == first_calls


def test_endpoint_distinct_windows_do_not_share_cache(client):
    fake = _FakeDb([100, 20, 15, 5, 5, 1, 0, 0] * 2)
    _set_db(fake)

    r30 = client.get("/analytics/pipeline-funnel?days=30")
    r90 = client.get("/analytics/pipeline-funnel?days=90")
    assert r30.json()["details"]["cache_hit"] is False
    assert r90.json()["details"]["cache_hit"] is False
    assert len(fake.calls) == 16  # both windows hit the DB exactly once each


def test_endpoint_missing_db_returns_503(client):
    analytics_router.set_db_manager(None)  # type: ignore[arg-type]
    resp = client.get("/analytics/pipeline-funnel")
    assert resp.status_code == 503
