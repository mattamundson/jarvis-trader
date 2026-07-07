"""Tests for the LLM resilience counters surfaced by GET /health.

vertex_failover_count and google_fallback_count are mirrored from the active
LLM client's instance counters into the module-level _LLM_PATH_STATE so /health
can report cumulative failover/fallback activity without a handle on the client
singleton. They must always be present (default 0) and pass through real values.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import health_router


@pytest.fixture(autouse=True)
def _reset_caches():
    health_router._tv_mcp_health_cache.update(
        checked_at=0.0, healthy=False, details="not yet probed", status="connecting"
    )
    yield


@pytest.fixture
def health_client():
    app = FastAPI()
    app.include_router(health_router.router)
    health_router.inject_dependencies(
        start_time=datetime.now(timezone.utc),
        dm=None,
        sl=None,
        dbm=None,
        pt=None,
        pm=None,
        tp=None,
        schwab=None,
    )
    return TestClient(app)


def test_health_includes_failover_counters_default_zero(health_client):
    """Keys must always be present; cold-start defaults to 0."""
    state = {"healthy": True, "vertex_failover_count": 0, "google_fallback_count": 0}
    with patch("llm.client.get_llm_path_state", return_value=state), \
         patch("routers.health_router._compute_brier_30d_rolling", return_value=None):
        resp = health_client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["vertex_failover_count"] == 0
    assert body["google_fallback_count"] == 0


def test_health_surfaces_failover_counter_values(health_client):
    """Real cumulative counts pass straight through to the payload."""
    state = {"healthy": True, "vertex_failover_count": 3, "google_fallback_count": 7}
    with patch("llm.client.get_llm_path_state", return_value=state), \
         patch("routers.health_router._compute_brier_30d_rolling", return_value=None):
        resp = health_client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["vertex_failover_count"] == 3
    assert body["google_fallback_count"] == 7


def test_health_failover_counters_resilient_to_missing_keys(health_client):
    """An older state dict without the keys must default to 0, never 5xx."""
    state = {"healthy": True}  # no counter keys
    with patch("llm.client.get_llm_path_state", return_value=state), \
         patch("routers.health_router._compute_brier_30d_rolling", return_value=None):
        resp = health_client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["vertex_failover_count"] == 0
    assert body["google_fallback_count"] == 0
