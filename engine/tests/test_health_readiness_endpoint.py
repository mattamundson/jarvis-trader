"""Tests for GET /health/readiness — Phase 1 deployment-gate HTTP probe.

Validates:
  - 200 + authorized=True when all blocking checks PASS
  - 503 + authorized=False when at least one blocking check FAILs
  - 500 + error body on infrastructure failure
  - --strict mode promotes advisory checks to blocking
  - Response shape matches CLI --json output
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backtest.live_readiness import CheckResult
from routers import health_router


@pytest.fixture()
def readiness_client():
    app = FastAPI()
    app.include_router(health_router.router)
    return TestClient(app)


def _passing_results() -> list[CheckResult]:
    return [
        CheckResult(name=f"C{i}", passed=True, detail=f"check {i} ok", blocking=True)
        for i in range(1, 8)
    ]


def _failing_results(fail_indices: tuple[int, ...]) -> list[CheckResult]:
    return [
        CheckResult(
            name=f"C{i}",
            passed=(i not in fail_indices),
            detail=f"check {i} {'ok' if i not in fail_indices else 'FAILED'}",
            blocking=True,
            fix=None if i not in fail_indices else f"fix C{i}",
        )
        for i in range(1, 8)
    ]


# -------------------------------------------------------------- #
# 200 path                                                       #
# -------------------------------------------------------------- #


def test_readiness_returns_200_when_all_blocking_pass(readiness_client):
    with patch("routers.health_router.__name__"):  # ensure module is loaded; helps lazy import
        with patch(
            "backtest.live_readiness.run_all_checks",
            return_value=_passing_results(),
        ):
            r = readiness_client.get("/health/readiness")
    assert r.status_code == 200
    body = r.json()
    assert body["authorized"] is True
    assert body["blocking_pass"] == 7
    assert body["blocking_total"] == 7
    assert len(body["results"]) == 7


# -------------------------------------------------------------- #
# 503 path                                                       #
# -------------------------------------------------------------- #


def test_readiness_returns_503_when_any_blocking_fails(readiness_client):
    with patch(
        "backtest.live_readiness.run_all_checks",
        return_value=_failing_results(fail_indices=(1,)),
    ):
        r = readiness_client.get("/health/readiness")
    assert r.status_code == 503
    body = r.json()
    assert body["authorized"] is False
    assert body["blocking_pass"] == 6
    assert body["blocking_total"] == 7


def test_readiness_503_includes_fix_text_for_failed_checks(readiness_client):
    with patch(
        "backtest.live_readiness.run_all_checks",
        return_value=_failing_results(fail_indices=(3,)),
    ):
        r = readiness_client.get("/health/readiness")
    body = r.json()
    failed = [res for res in body["results"] if not res["passed"]]
    assert len(failed) == 1
    assert failed[0]["fix"] == "fix C3"


# -------------------------------------------------------------- #
# Strict mode                                                    #
# -------------------------------------------------------------- #


def test_readiness_strict_promotes_advisory_to_blocking(readiness_client):
    """With strict=true, an advisory FAIL should still produce 503."""
    advisory_fail = [
        CheckResult(name="C3", passed=False, detail="advisory fail", blocking=False),
    ]
    advisory_fail.extend(
        CheckResult(name=f"C{i}", passed=True, detail="ok", blocking=True)
        for i in range(1, 7)
        if i != 3
    )
    with patch(
        "backtest.live_readiness.run_all_checks",
        return_value=advisory_fail,
    ):
        r_default = readiness_client.get("/health/readiness")
        r_strict = readiness_client.get("/health/readiness?strict=true")
    # Default: advisory FAIL doesn't block authorization
    assert r_default.status_code == 200
    assert r_default.json()["authorized"] is True
    # Strict: same advisory FAIL becomes blocking
    assert r_strict.status_code == 503
    assert r_strict.json()["authorized"] is False


# -------------------------------------------------------------- #
# 500 path                                                       #
# -------------------------------------------------------------- #


def test_readiness_returns_500_on_check_infrastructure_error(readiness_client):
    with patch(
        "backtest.live_readiness.run_all_checks",
        side_effect=RuntimeError("simulated infra failure"),
    ):
        r = readiness_client.get("/health/readiness")
    assert r.status_code == 500
    assert "simulated infra failure" in r.json().get("error", "")


# -------------------------------------------------------------- #
# Response shape                                                 #
# -------------------------------------------------------------- #


def test_readiness_response_includes_checked_at_iso8601(readiness_client):
    with patch(
        "backtest.live_readiness.run_all_checks",
        return_value=_passing_results(),
    ):
        r = readiness_client.get("/health/readiness")
    assert "checked_at" in r.json()
    # ISO 8601 with timezone
    assert "T" in r.json()["checked_at"]
    assert r.json()["checked_at"].endswith("+00:00") or r.json()["checked_at"].endswith("Z")


def test_readiness_each_result_has_required_fields(readiness_client):
    with patch(
        "backtest.live_readiness.run_all_checks",
        return_value=_passing_results(),
    ):
        r = readiness_client.get("/health/readiness")
    for res in r.json()["results"]:
        assert {"name", "passed", "detail", "blocking", "fix"} <= set(res.keys())
