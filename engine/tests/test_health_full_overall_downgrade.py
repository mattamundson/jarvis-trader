"""GT-51 regression — /health/full must downgrade `overall` when
ib_gateway / portfolio / pnl_monitor subsystem checks raise.

Prior to this fix, the ib_gateway, portfolio, and pnl_monitor except
blocks in `_full_health_inner` set only that subsystem's own status to
"error" without ever reassigning `overall`, so a thrown exception in one
of those three checks could leave `overall` at "healthy" while a
subsystem silently sat in "error". The database and safety_layer except
blocks already did this correctly; this test locks the same behavior in
for the other three.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import health_router


def _client_with(pt=None, pm=None):
    app = FastAPI()
    app.include_router(health_router.router)
    health_router.inject_dependencies(
        start_time=datetime.now(timezone.utc),
        dm=None, sl=None, dbm=None, pt=pt, pm=pm, tp=None, schwab=None,
    )
    return TestClient(app)


def test_ib_gateway_exception_downgrades_overall():
    client = _client_with()
    with patch.object(
        health_router, "_get_ib_gateway_health", side_effect=RuntimeError("boom")
    ):
        resp = client.get("/health/full")
    assert resp.status_code == 200
    body = resp.json()
    assert body["subsystems"]["ib_gateway"]["status"] == "error"
    assert body["overall"] == "degraded"


def test_portfolio_exception_downgrades_overall():
    bad_tracker = MagicMock()
    bad_tracker.get_open_positions.side_effect = RuntimeError("boom")
    client = _client_with(pt=bad_tracker)
    resp = client.get("/health/full")
    assert resp.status_code == 200
    body = resp.json()
    assert body["subsystems"]["portfolio"]["status"] == "error"
    assert body["overall"] == "degraded"


def test_pnl_monitor_exception_downgrades_overall():
    bad_pnl = MagicMock()
    bad_pnl.get_current_pnl_state.side_effect = RuntimeError("boom")
    client = _client_with(pm=bad_pnl)
    resp = client.get("/health/full")
    assert resp.status_code == 200
    body = resp.json()
    assert body["subsystems"]["pnl_monitor"]["status"] == "error"
    assert body["overall"] == "degraded"


def test_ib_gateway_exception_then_circuit_breaker_trip_still_escalates():
    """Ordering regression: an earlier subsystem exception must never block a
    later, more-severe escalation.

    `ib_gateway` (step 3) runs before `circuit_breakers` (step 4). Before this
    fix, `circuit_breakers`'s escalation guard was `if overall == "healthy"`:
    if `ib_gateway` threw first and downgraded `overall` to "degraded", that
    guard was false by the time `circuit_breakers` tripped, so `overall` got
    stuck at "degraded" instead of correctly escalating to the more severe
    "circuit_breaker_tripped" — silently masking a real trading-safety state.
    """
    class _FakeSafetyLayer:
        _kill_switch_active = False
        _kill_switch_reason = None

        def check_circuit_breakers(self):
            return {"daily_limit_breached": True, "drawdown_breached": False}

    safety_layer = _FakeSafetyLayer()

    app = FastAPI()
    app.include_router(health_router.router)
    health_router.inject_dependencies(
        start_time=datetime.now(timezone.utc),
        dm=None, sl=safety_layer, dbm=None, pt=None, pm=None, tp=None, schwab=None,
    )
    client = TestClient(app)

    with patch.object(
        health_router, "_get_ib_gateway_health", side_effect=RuntimeError("boom")
    ):
        resp = client.get("/health/full")
    assert resp.status_code == 200
    body = resp.json()
    assert body["subsystems"]["ib_gateway"]["status"] == "error"
    assert body["subsystems"]["circuit_breakers"]["status"] == "tripped"
    assert body["overall"] == "circuit_breaker_tripped"


def test_ib_gateway_exception_does_not_downgrade_kill_switch_active():
    """Severity ordering: a subsystem error must never *reduce* severity.

    If safety_layer already escalated `overall` to "kill_switch_active"
    (more severe than "degraded"), a later ib_gateway exception should
    leave `overall` at "kill_switch_active", not stomp it down to
    "degraded".
    """
    class _FakeSafetyLayer:
        """Deliberately has no check_circuit_breakers — hasattr() must be
        False so the circuit_breakers block takes its "not_available"
        branch instead of calling a mock and breaking response validation.
        """

        _kill_switch_active = True
        _kill_switch_reason = None

    safety_layer = _FakeSafetyLayer()

    app = FastAPI()
    app.include_router(health_router.router)
    health_router.inject_dependencies(
        start_time=datetime.now(timezone.utc),
        dm=None, sl=safety_layer, dbm=None, pt=None, pm=None, tp=None, schwab=None,
    )
    client = TestClient(app)

    with patch.object(
        health_router, "_get_ib_gateway_health", side_effect=RuntimeError("boom")
    ):
        resp = client.get("/health/full")
    assert resp.status_code == 200
    body = resp.json()
    assert body["subsystems"]["ib_gateway"]["status"] == "error"
    assert body["overall"] == "kill_switch_active"
