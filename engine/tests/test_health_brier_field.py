"""Tests for the brier_30d_rolling field surfaced by GET /health.

Wires Novel #2 (Brier calibration) from analytics → /health payload, so
operators can read the calibration metric without hitting the deeper
/calibration endpoint. None = no agent has enough closed signals yet.
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
    """Reset the Brier and TV caches so cross-test state doesn't leak."""
    health_router._brier_cache.update(checked_at=0.0, value=None)
    health_router._tv_mcp_health_cache.update(
        checked_at=0.0,
        healthy=False,
        details="not yet probed",
        status="connecting",
    )
    yield
    health_router._brier_cache.update(checked_at=0.0, value=None)


@pytest.fixture
def health_client():
    app = FastAPI()
    app.include_router(health_router.router)
    # Inject the bare minimum so _health_inner doesn't blow up.
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


def test_health_response_includes_brier_field(health_client):
    """The /health JSON must always contain the brier_30d_rolling key,
    even when the value is None (cold-start: no closed signals yet)."""
    with patch("routers.health_router._compute_brier_30d_rolling", return_value=None):
        resp = health_client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert "brier_30d_rolling" in body
    assert body["brier_30d_rolling"] is None


def test_health_response_surfaces_brier_value(health_client):
    """When the tracker returns a real Brier (data available),
    /health passes the float straight through."""
    with patch("routers.health_router._compute_brier_30d_rolling", return_value=0.142857):
        resp = health_client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["brier_30d_rolling"] == pytest.approx(0.142857, abs=1e-6)


def test_compute_brier_30d_rolling_caches_value():
    """Two calls within the cache TTL should only hit the tracker once."""
    call_count = {"n": 0}

    class _StubTracker:
        def compute_rolling_brier(self):
            call_count["n"] += 1
            return 0.10

    # Patch the tracker class wherever the helper imports it from.
    # Health router tries both 'engine.analytics' and 'analytics' paths.
    with patch("analytics.ic_ensemble.BrierCalibrationTracker", return_value=_StubTracker()), \
         patch("engine.analytics.ic_ensemble.BrierCalibrationTracker", return_value=_StubTracker(), create=True):
        first = health_router._compute_brier_30d_rolling()
        second = health_router._compute_brier_30d_rolling()
    assert first == pytest.approx(0.10)
    assert second == pytest.approx(0.10)
    assert call_count["n"] == 1, "Second call must hit cache, not re-query tracker"


def test_compute_brier_30d_rolling_returns_none_on_tracker_error():
    """If BrierCalibrationTracker raises (DB locked, import failure, etc.),
    the helper must return None — never 5xx /health."""

    class _BrokenTracker:
        def compute_rolling_brier(self):
            raise RuntimeError("DB locked")

    with patch("analytics.ic_ensemble.BrierCalibrationTracker", return_value=_BrokenTracker()), \
         patch("engine.analytics.ic_ensemble.BrierCalibrationTracker", return_value=_BrokenTracker(), create=True):
        assert health_router._compute_brier_30d_rolling() is None
