"""Tests -- /health/assertions single-pane-of-glass endpoint (MR-3.6).

Reshapes the already-computed /health payload into named pass/fail
assertions rather than re-probing anything -- these tests pin that the
reshape is honest (each assertion tracks its source field exactly) and that
absence-of-evidence fails closed (mirrors gates.py's "UNKNOWN == NO-GO").
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import health_router
from routers.health_router import PENDING_APPROVAL_STUCK_AFTER_MIN, _derive_health_assertions


def _all_healthy_payload() -> dict:
    return {
        "timestamp": "2026-08-13T12:00:00+00:00",
        "database": "connected",
        "kill_switch_active": False,
        "ibgateway_alive": True,
        "ib_execution_stale": False,
        "llm_path_healthy": True,
        "tradingview_mcp_healthy": True,
        "pending_approvals": {"count": 0, "oldest_age_min": None},
        "brier_30d_rolling": 0.18,
        "futures_sentiment": {"quality": "fresh", "age_days": 1},
        "execution_connected_verified": True,
    }


def test_all_healthy_payload_passes_every_assertion():
    assertions = _derive_health_assertions(_all_healthy_payload())
    assert all(a["passed"] for a in assertions)
    names = {a["name"] for a in assertions}
    assert names == {
        "database_connected",
        "kill_switch_inactive",
        "ib_gateway_alive",
        "ib_execution_not_stale",
        "llm_path_healthy",
        "tradingview_mcp_healthy",
        "no_stuck_pending_approvals",
        "forecasts_beat_coinflip",
        "futures_sentiment_fresh",
        "execution_path_verified",
    }


@pytest.mark.parametrize(
    "field,bad_value,assertion_name",
    [
        ("database", "error", "database_connected"),
        ("kill_switch_active", True, "kill_switch_inactive"),
        ("ibgateway_alive", False, "ib_gateway_alive"),
        ("ib_execution_stale", True, "ib_execution_not_stale"),
        ("llm_path_healthy", False, "llm_path_healthy"),
        ("tradingview_mcp_healthy", False, "tradingview_mcp_healthy"),
        ("execution_connected_verified", False, "execution_path_verified"),
    ],
)
def test_single_bad_field_fails_only_its_own_assertion(field, bad_value, assertion_name):
    payload = _all_healthy_payload()
    payload[field] = bad_value
    assertions = {a["name"]: a["passed"] for a in _derive_health_assertions(payload)}
    assert assertions[assertion_name] is False
    # Every other assertion must remain unaffected -- no cross-contamination.
    for name, passed in assertions.items():
        if name != assertion_name:
            assert passed is True, f"{name} unexpectedly flipped by {field}={bad_value}"


def test_brier_none_fails_closed_not_open():
    """No rolling Brier data yet must NOT read as passing -- absence of
    evidence is not evidence of health (gates.py's own stated philosophy)."""
    payload = _all_healthy_payload()
    payload["brier_30d_rolling"] = None
    assertions = {a["name"]: a["passed"] for a in _derive_health_assertions(payload)}
    assert assertions["forecasts_beat_coinflip"] is False


def test_brier_at_coinflip_boundary_fails():
    payload = _all_healthy_payload()
    payload["brier_30d_rolling"] = 0.25
    assertions = {a["name"]: a["passed"] for a in _derive_health_assertions(payload)}
    assert assertions["forecasts_beat_coinflip"] is False


def test_pending_approval_stuck_threshold_boundary():
    payload = _all_healthy_payload()
    payload["pending_approvals"] = {
        "count": 1,
        "oldest_age_min": PENDING_APPROVAL_STUCK_AFTER_MIN - 0.01,
    }
    just_under = {a["name"]: a["passed"] for a in _derive_health_assertions(payload)}
    assert just_under["no_stuck_pending_approvals"] is True

    payload["pending_approvals"]["oldest_age_min"] = PENDING_APPROVAL_STUCK_AFTER_MIN + 0.01
    just_over = {a["name"]: a["passed"] for a in _derive_health_assertions(payload)}
    assert just_over["no_stuck_pending_approvals"] is False


def test_missing_fields_fail_closed_not_crash():
    """A payload missing keys entirely (e.g. a partial /health during startup)
    must fail those assertions closed, never raise -- with two deliberate
    exceptions where "absent" is a genuine, distinct healthy state rather
    than "unknown":
      - ib_execution_not_stale: health.get(..., False) -> not False -> True.
        Absence means no stale-hazard signal was raised at all.
      - no_stuck_pending_approvals: pending_approvals defaults to
        {"count": 0, "oldest_age_min": None} when nothing is queued -- None
        here means "confirmed zero pending", not "we don't know", so it
        correctly does not fail closed.
    """
    assertions = _derive_health_assertions({})
    assert len(assertions) == 10
    exceptions = {"ib_execution_not_stale", "no_stuck_pending_approvals"}
    assert all(a["passed"] is False for a in assertions if a["name"] not in exceptions)
    by_name = {a["name"]: a["passed"] for a in assertions}
    assert by_name["ib_execution_not_stale"] is True
    assert by_name["no_stuck_pending_approvals"] is True


# --- endpoint wiring ---------------------------------------------------------


def test_endpoint_reuses_health_cached_not_a_second_probe(monkeypatch):
    """/health/assertions must derive from the same _health_cached() payload
    /health itself returns -- never a second, independently-probed source
    (the exact bug class P3-1 fixed: two signals disagreeing about one
    reality)."""

    async def _fake_health_cached():
        return _all_healthy_payload()

    monkeypatch.setattr(health_router, "_health_cached", _fake_health_cached)

    app = FastAPI()
    app.include_router(health_router.router)
    client = TestClient(app)

    body = client.get("/health/assertions").json()
    assert body["all_passed"] is True
    assert body["failed"] == []
    assert len(body["assertions"]) == 10
    assert body["timestamp"] == "2026-08-13T12:00:00+00:00"


def test_endpoint_reports_failed_list(monkeypatch):
    payload = _all_healthy_payload()
    payload["ibgateway_alive"] = False
    payload["llm_path_healthy"] = False

    async def _fake_health_cached():
        return payload

    monkeypatch.setattr(health_router, "_health_cached", _fake_health_cached)

    app = FastAPI()
    app.include_router(health_router.router)
    client = TestClient(app)

    body = client.get("/health/assertions").json()
    assert body["all_passed"] is False
    assert set(body["failed"]) == {"ib_gateway_alive", "llm_path_healthy"}
