"""
Tests for engine/routers/scheduler_router.py

Covered:
  - GET  /scheduler/jobs                  — list scheduled jobs (success);
                                              empty when no scheduler injected;
                                              500 when scheduler.get_jobs() raises
  - POST /scheduler/morning-brief/trigger — always returns "triggered" immediately
                                              (background task); 401 without auth
  - POST /scheduler/discord-import/trigger — success; 404 job-not-found;
                                              500 when scheduler not initialised
  - GET  /scheduler/status                — success with jobs + decision count;
                                              degraded shape when scheduler is None
  - POST /scheduler/scan-now              — success (mocked pipeline/safety layer);
                                              503 pipeline unavailable;
                                              503 safety layer unavailable;
                                              kill-switch-active short-circuit;
                                              per-symbol exception is caught and
                                              surfaced in results (not a 500)

Design:
  - Uses a minimal FastAPI app wrapping only scheduler_router (no full main.py
    import), mirroring tests/test_admin_router.py.
  - APIKeyMiddleware is added manually so auth tests are realistic.
  - The router's external dependencies (_scheduler, _trading_pipeline,
    _safety_layer, _log_decision_fn, _deliver_whatsapp_fn) are plain module
    globals normally set via inject_scheduler(). Tests set/clear them directly
    via monkeypatch.setattr on the routers.scheduler_router module so state
    never leaks between tests.
  - notifications.morning_brief.assemble_morning_brief / openclaw_notifier.
    send_raw / discord_notifier.discord_morning_brief are patched so the
    morning-brief background task never touches a real subprocess or network
    call (conftest.py also disables OpenClaw via OPENCLAW_ENABLED=false, but
    the patches make the test deterministic regardless of env state).
  - Never touches engine/.env or any live endpoint.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------

_ENGINE_ROOT = str(Path(__file__).parent.parent)
if _ENGINE_ROOT not in sys.path:
    sys.path.insert(0, _ENGINE_ROOT)


def _load_env() -> None:
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and "=" in line and not line.startswith("#"):
                key, value = line.split("=", 1)
                os.environ.setdefault(key, value)


_load_env()

from config import settings  # noqa: E402 — must follow _load_env()
from middleware.api_key_middleware import APIKeyMiddleware  # noqa: E402
from routers import scheduler_router  # noqa: E402
from routers.scheduler_router import router as scheduler_api_router  # noqa: E402

_VALID_HEADERS = {"X-API-Key": settings.API_KEY}
_BAD_HEADERS = {"X-API-Key": "wrong-key"}


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeJob:
    def __init__(self, id, name, next_run_time=None, func=None):
        self.id = id
        self.name = name
        self.next_run_time = next_run_time
        self.func = func or AsyncMock(return_value=None)


class _FakeScheduler:
    def __init__(self, jobs=None, running=True):
        self._jobs = jobs or []
        self.running = running

    def get_jobs(self):
        return self._jobs

    def get_job(self, job_id):
        for j in self._jobs:
            if j.id == job_id:
                return j
        return None


# ---------------------------------------------------------------------------
# App / client fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def app() -> FastAPI:
    _app = FastAPI()
    _app.add_middleware(APIKeyMiddleware)
    _app.include_router(scheduler_api_router)
    return _app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture(autouse=True)
def _reset_globals(monkeypatch):
    """Ensure every scheduler_router global starts each test as None/empty."""
    monkeypatch.setattr(scheduler_router, "_scheduler", None)
    monkeypatch.setattr(scheduler_router, "_trading_pipeline", None)
    monkeypatch.setattr(scheduler_router, "_safety_layer", None)
    monkeypatch.setattr(scheduler_router, "_decision_log_ref", [])
    monkeypatch.setattr(scheduler_router, "_log_decision_fn", None)
    monkeypatch.setattr(scheduler_router, "_deliver_whatsapp_fn", None)
    yield


# ---------------------------------------------------------------------------
# GET /scheduler/jobs
# ---------------------------------------------------------------------------


def test_get_jobs_success(client: TestClient, monkeypatch) -> None:
    job = _FakeJob(id="nightly_discord_import", name="Nightly Discord Import")
    monkeypatch.setattr(scheduler_router, "_scheduler", _FakeScheduler(jobs=[job]))

    resp = client.get("/scheduler/jobs", headers=_VALID_HEADERS)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["total_jobs"] == 1
    assert data["jobs"][0]["id"] == "nightly_discord_import"
    assert data["jobs"][0]["next_run_time"] is None


def test_get_jobs_no_scheduler_returns_empty(client: TestClient) -> None:
    resp = client.get("/scheduler/jobs", headers=_VALID_HEADERS)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"total_jobs": 0, "jobs": []}


def test_get_jobs_scheduler_error_returns_500(client: TestClient, monkeypatch) -> None:
    bad_scheduler = MagicMock()
    bad_scheduler.get_jobs.side_effect = RuntimeError("scheduler backend down")
    monkeypatch.setattr(scheduler_router, "_scheduler", bad_scheduler)

    resp = client.get("/scheduler/jobs", headers=_VALID_HEADERS)
    assert resp.status_code == 500, resp.text
    assert "scheduler backend down" in resp.json()["detail"]


def test_get_jobs_auth_required(client: TestClient) -> None:
    resp = client.get("/scheduler/jobs")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /scheduler/morning-brief/trigger
# ---------------------------------------------------------------------------


def test_trigger_morning_brief_success(client: TestClient) -> None:
    with (
        patch(
            "notifications.morning_brief.assemble_morning_brief",
            new=AsyncMock(return_value="brief text"),
        ),
        patch("notifications.openclaw_notifier.send_raw", new=AsyncMock(return_value=True)),
        patch(
            "notifications.discord_notifier.discord_morning_brief",
            new=AsyncMock(return_value=True),
        ),
    ):
        resp = client.post("/scheduler/morning-brief/trigger", headers=_VALID_HEADERS)

    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "status": "triggered",
        "message": "Morning brief sending in background",
    }


def test_trigger_morning_brief_auth_required(client: TestClient) -> None:
    resp = client.post("/scheduler/morning-brief/trigger")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /scheduler/discord-import/trigger
# ---------------------------------------------------------------------------


def test_trigger_discord_import_success(client: TestClient, monkeypatch) -> None:
    job_func = AsyncMock(return_value=None)
    job = _FakeJob(id="nightly_discord_import", name="Nightly Discord Import", func=job_func)
    monkeypatch.setattr(scheduler_router, "_scheduler", _FakeScheduler(jobs=[job]))

    resp = client.post("/scheduler/discord-import/trigger", headers=_VALID_HEADERS)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["triggered"] is True
    assert "timestamp" in data
    job_func.assert_awaited_once()


def test_trigger_discord_import_job_not_found_returns_404(
    client: TestClient, monkeypatch
) -> None:
    monkeypatch.setattr(scheduler_router, "_scheduler", _FakeScheduler(jobs=[]))

    resp = client.post("/scheduler/discord-import/trigger", headers=_VALID_HEADERS)
    assert resp.status_code == 404, resp.text
    assert "not found" in resp.json()["detail"]


def test_trigger_discord_import_no_scheduler_returns_500(client: TestClient) -> None:
    resp = client.post("/scheduler/discord-import/trigger", headers=_VALID_HEADERS)
    assert resp.status_code == 500, resp.text
    assert "not initialized" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# GET /scheduler/status
# ---------------------------------------------------------------------------


def test_scheduler_status_success(client: TestClient, monkeypatch) -> None:
    job = _FakeJob(id="job1", name="Job One")
    monkeypatch.setattr(scheduler_router, "_scheduler", _FakeScheduler(jobs=[job], running=True))
    monkeypatch.setattr(scheduler_router, "_decision_log_ref", [{"symbol": "MES"}])

    resp = client.get("/scheduler/status", headers=_VALID_HEADERS)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["running"] is True
    assert data["jobs"][0]["id"] == "job1"
    assert data["total_decisions_logged"] == 1


def test_scheduler_status_no_scheduler(client: TestClient) -> None:
    """No scheduler injected — status endpoint returns a degraded, minimal shape."""
    resp = client.get("/scheduler/status", headers=_VALID_HEADERS)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"running": False, "jobs": []}


# ---------------------------------------------------------------------------
# POST /scheduler/scan-now
# ---------------------------------------------------------------------------


def _wire_scan_dependencies(monkeypatch, pipeline=None, safety=None, log_fn=None, whatsapp_fn=None):
    if pipeline is not None:
        monkeypatch.setattr(scheduler_router, "_trading_pipeline", pipeline)
    if safety is not None:
        monkeypatch.setattr(scheduler_router, "_safety_layer", safety)
    if log_fn is not None:
        monkeypatch.setattr(scheduler_router, "_log_decision_fn", log_fn)
    if whatsapp_fn is not None:
        monkeypatch.setattr(scheduler_router, "_deliver_whatsapp_fn", whatsapp_fn)


def test_scan_now_pipeline_unavailable_returns_503(client: TestClient, monkeypatch) -> None:
    safety = MagicMock()
    safety.get_status.return_value = {"kill_switch_active": False}
    _wire_scan_dependencies(monkeypatch, safety=safety)

    resp = client.post("/scheduler/scan-now", headers=_VALID_HEADERS)
    assert resp.status_code == 503, resp.text
    assert "Pipeline not available" in resp.json()["detail"]


def test_scan_now_safety_layer_unavailable_returns_503(client: TestClient, monkeypatch) -> None:
    pipeline = MagicMock()
    _wire_scan_dependencies(monkeypatch, pipeline=pipeline)

    resp = client.post("/scheduler/scan-now", headers=_VALID_HEADERS)
    assert resp.status_code == 503, resp.text
    assert "Safety layer not initialized" in resp.json()["detail"]


def test_scan_now_kill_switch_active_skips(client: TestClient, monkeypatch) -> None:
    pipeline = MagicMock()
    safety = MagicMock()
    safety.get_status.return_value = {"kill_switch_active": True}
    _wire_scan_dependencies(monkeypatch, pipeline=pipeline, safety=safety)

    resp = client.post("/scheduler/scan-now", headers=_VALID_HEADERS)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"status": "skipped", "reason": "kill_switch_active"}
    pipeline.analyze_and_decide.assert_not_called()


def test_scan_now_success_hold_action(client: TestClient, monkeypatch) -> None:
    """Success path: pipeline returns a HOLD decision for every scanned symbol."""
    monkeypatch.setattr(settings, "FUTURES_WATCHLIST", ["MES"])
    monkeypatch.setattr(settings, "OPTIONS_WATCHLIST", [])

    pipeline = MagicMock()
    pipeline.analyze_and_decide = AsyncMock(
        return_value={
            "final_action": "hold",
            "fund_decision": {"final_conviction": 0.2},
            "trade_decision": {},
            "final_quantity": 0,
            "summary": "no edge",
            "errors": [],
        }
    )
    safety = MagicMock()
    safety.get_status.return_value = {"kill_switch_active": False}
    log_fn = MagicMock()
    whatsapp_fn = AsyncMock(return_value=(True, None))
    _wire_scan_dependencies(
        monkeypatch, pipeline=pipeline, safety=safety, log_fn=log_fn, whatsapp_fn=whatsapp_fn
    )

    resp = client.post("/scheduler/scan-now", headers=_VALID_HEADERS)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "complete"
    assert data["symbols_scanned"] == 1
    assert data["results"][0]["symbol"] == "MES"
    assert data["results"][0]["action"] == "hold"
    assert data["results"][0]["alert_sent"] is False  # HOLD never alerts
    log_fn.assert_called_once()
    whatsapp_fn.assert_not_awaited()


def test_scan_now_non_hold_action_sends_alert(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(settings, "FUTURES_WATCHLIST", ["MES"])
    monkeypatch.setattr(settings, "OPTIONS_WATCHLIST", [])

    pipeline = MagicMock()
    pipeline.analyze_and_decide = AsyncMock(
        return_value={
            "final_action": "buy",
            "fund_decision": {"final_conviction": 0.81},
            "trade_decision": {"limit_price": 5900.0, "reasoning": "breakout"},
            "final_quantity": 2,
            "summary": "breakout long",
            "errors": [],
        }
    )
    safety = MagicMock()
    safety.get_status.return_value = {"kill_switch_active": False}
    log_fn = MagicMock()
    whatsapp_fn = AsyncMock(return_value=(True, None))
    _wire_scan_dependencies(
        monkeypatch, pipeline=pipeline, safety=safety, log_fn=log_fn, whatsapp_fn=whatsapp_fn
    )

    resp = client.post("/scheduler/scan-now", headers=_VALID_HEADERS)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["results"][0]["action"] == "buy"
    assert data["results"][0]["alert_sent"] is True
    whatsapp_fn.assert_awaited_once()


def test_scan_now_per_symbol_exception_is_captured_not_500(
    client: TestClient, monkeypatch
) -> None:
    """Mocked-dependency-failure path: pipeline raises for a symbol; endpoint
    still returns 200 with the error captured per-symbol (does not 500)."""
    monkeypatch.setattr(settings, "FUTURES_WATCHLIST", ["MES"])
    monkeypatch.setattr(settings, "OPTIONS_WATCHLIST", [])

    pipeline = MagicMock()
    pipeline.analyze_and_decide = AsyncMock(side_effect=RuntimeError("LLM timeout"))
    safety = MagicMock()
    safety.get_status.return_value = {"kill_switch_active": False}
    _wire_scan_dependencies(monkeypatch, pipeline=pipeline, safety=safety)

    resp = client.post("/scheduler/scan-now", headers=_VALID_HEADERS)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["results"][0]["symbol"] == "MES"
    assert "LLM timeout" in data["results"][0]["error"]


def test_scan_now_auth_required(client: TestClient) -> None:
    resp = client.post("/scheduler/scan-now")
    assert resp.status_code == 401
