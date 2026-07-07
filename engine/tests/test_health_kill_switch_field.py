"""Regression: GET /health must reflect the REAL kill-switch state.

SafetyLayer.get_status() exposes the flag as "is_killed". health_router read a
non-existent "kill_switch_active" key, so /health always reported the switch OFF
— every dashboard widget that reads health.kill_switch_active showed green even
when trading was halted. These tests pin the mapping in both directions.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import health_router


class _FakeSafety:
    def __init__(self, is_killed: bool):
        self._is_killed = is_killed

    def get_status(self) -> dict:
        return {
            "is_killed": self._is_killed,
            "kill_switch_reason": "DAILY_LOSS_LIMIT" if self._is_killed else None,
            "daily_realized_pnl": 0.0,
            "equity_peak": 10_000.0,
            "current_equity": 10_000.0,
            "recent_order_count": 0,
        }


@pytest.fixture(autouse=True)
def _reset_caches():
    health_router._tv_mcp_health_cache.update(
        checked_at=0.0, healthy=False, details="not yet probed", status="connecting"
    )
    yield


def _client(sl) -> TestClient:
    app = FastAPI()
    app.include_router(health_router.router)
    health_router.inject_dependencies(
        start_time=datetime.now(timezone.utc),
        dm=None,
        sl=sl,
        dbm=None,
        pt=None,
        pm=None,
        tp=None,
        schwab=None,
    )
    return TestClient(app)


def _get_health(sl):
    with patch("routers.health_router._compute_brier_30d_rolling", return_value=None):
        return _client(sl).get("/health")


def test_health_reports_kill_switch_active_when_killed():
    resp = _get_health(_FakeSafety(is_killed=True))
    assert resp.status_code == 200
    assert resp.json()["kill_switch_active"] is True  # must NOT be silently False


def test_health_reports_kill_switch_inactive_when_not_killed():
    resp = _get_health(_FakeSafety(is_killed=False))
    assert resp.status_code == 200
    assert resp.json()["kill_switch_active"] is False
