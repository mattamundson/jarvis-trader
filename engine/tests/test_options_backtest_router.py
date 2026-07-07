"""
Tests for engine/routers/options_backtest_router.py.

Goal
----
Verify the WIRING — endpoint shapes, job lifecycle, persistence, auth.
The backtest math itself is covered by tests/test_options_backtester.py
(29 tests); this file mocks the runner so we don't depend on it.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ENGINE_DIR = Path(__file__).parent.parent
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))

from routers import options_backtest_router as ob_router_mod  # noqa: E402

# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def tmp_output_dir(tmp_path, monkeypatch):
    """Redirect the router output to a tmp dir and reset state for each test."""
    out_dir = tmp_path / "options_backtests"
    out_dir.mkdir(parents=True, exist_ok=True)
    ob_router_mod.reset_state()
    ob_router_mod.set_output_dir(out_dir)
    yield out_dir
    ob_router_mod.reset_state()
    ob_router_mod.set_output_dir(ob_router_mod._DEFAULT_OUTPUT_DIR)


@pytest.fixture
def app_no_auth(tmp_output_dir):
    """Minimal FastAPI app with only the router — no auth middleware."""
    app = FastAPI()
    app.include_router(ob_router_mod.router)
    return app


@pytest.fixture
def client_no_auth(app_no_auth):
    return TestClient(app_no_auth)


@pytest.fixture
def fast_runner(monkeypatch):
    """Replace the default runner with a deterministic, fast stub."""

    def _runner(job):
        return {
            "summary": {
                "n_trades": 3,
                "total_pnl": 42.0,
                "win_rate": 0.667,
                "profit_factor": 2.0,
            },
            "metrics": {
                "profit_factor": 2.0,
                "win_rate": 0.667,
                "total_pnl": 42.0,
                "n_trades": 3,
            },
            "trades": [
                {"signal_ts": "2025-01-02T15:30:00Z", "pnl": 10.0},
                {"signal_ts": "2025-01-09T15:30:00Z", "pnl": 22.0},
                {"signal_ts": "2025-01-16T15:30:00Z", "pnl": 10.0},
            ],
            "notes": "fast stub runner",
        }

    ob_router_mod.set_runner_override(_runner)
    yield _runner
    ob_router_mod.set_runner_override(None)


def _wait_for_status(client, job_id, target="done", timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        resp = client.get(f"/backtest/options/jobs/{job_id}")
        if resp.status_code == 200 and resp.json().get("status") in (target, "error"):
            return resp.json()
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} never reached status={target} within {timeout}s")


# ── Tests ────────────────────────────────────────────────────────────────────


def test_post_run_returns_job_id_and_queued_status(client_no_auth, fast_runner):
    payload = {
        "symbol": "SPY",
        "strategy": "vertical_spread",
        "start_date": "2025-01-01",
        "end_date": "2025-03-31",
        "params": {"target_dte": 30, "target_delta": 0.30},
    }
    resp = client_no_auth.post("/backtest/options/run", json=payload)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "job_id" in body
    assert body["status"] in ("queued", "running", "done")
    # uuid4 string has 36 chars with hyphens
    assert len(body["job_id"]) == 36


def test_get_jobs_after_completion_returns_done_status(client_no_auth, fast_runner, tmp_output_dir):
    resp = client_no_auth.post(
        "/backtest/options/run",
        json={
            "symbol": "SPY",
            "strategy": "vertical_spread",
            "start_date": "2025-01-01",
            "end_date": "2025-03-31",
        },
    )
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]

    final = _wait_for_status(client_no_auth, job_id, target="done")
    assert final["status"] == "done", final
    assert final["job_id"] == job_id
    assert final["symbol"] == "SPY"
    assert final["strategy"] == "vertical_spread"
    assert final["started_at"] is not None
    assert final["finished_at"] is not None
    assert final["result_path"] is not None
    # The result file actually exists with the expected schema
    result_path = Path(final["result_path"])
    assert result_path.exists()
    written = json.loads(result_path.read_text(encoding="utf-8"))
    assert written["job_id"] == job_id
    assert written["input"]["symbol"] == "SPY"
    assert written["summary"]["n_trades"] == 3
    assert written["metrics"]["profit_factor"] == 2.0
    assert isinstance(written["trades"], list) and len(written["trades"]) == 3


def test_get_jobs_unknown_id_returns_404(client_no_auth):
    resp = client_no_auth.get("/backtest/options/jobs/does-not-exist")
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


def test_get_results_paginates(client_no_auth, tmp_output_dir):
    # Seed 25 mock result files across two date directories.
    date_a = tmp_output_dir / "2025-01-15"
    date_b = tmp_output_dir / "2025-02-15"
    date_a.mkdir(parents=True, exist_ok=True)
    date_b.mkdir(parents=True, exist_ok=True)
    for i in range(12):
        (date_a / f"SPY_vertical_spread_aaaa{i:04d}.json").write_text(
            json.dumps({"job_id": f"a{i}", "summary": {}}),
            encoding="utf-8",
        )
    for i in range(13):
        (date_b / f"SPY_vertical_spread_bbbb{i:04d}.json").write_text(
            json.dumps({"job_id": f"b{i}", "summary": {}}),
            encoding="utf-8",
        )

    # Default page size = 20.
    resp = client_no_auth.get("/backtest/options/results")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 25
    assert body["limit"] == 20
    assert body["offset"] == 0
    assert len(body["items"]) == 20

    # Newest first — date_b ("2025-02-15") comes before date_a.
    assert body["items"][0]["date"] == "2025-02-15"
    assert body["items"][0]["symbol"] == "SPY"
    assert body["items"][0]["strategy"] == "vertical"
    # Note: filename splits on "_" so "vertical_spread" maps to "vertical" / "spread".
    # That's fine for the listing — the on-disk file contains the canonical input.

    # Offset+limit pagination.
    resp2 = client_no_auth.get("/backtest/options/results?limit=10&offset=20")
    assert resp2.status_code == 200
    body2 = resp2.json()
    assert body2["total"] == 25
    assert body2["limit"] == 10
    assert body2["offset"] == 20
    assert len(body2["items"]) == 5  # only 5 left after offset=20


def test_endpoints_require_api_key(tmp_output_dir):
    """When mounted under the engine's APIKeyMiddleware, calls without
    X-API-Key must be rejected."""
    import os

    os.environ.setdefault("API_KEY", "test-key-for-options-router")

    from middleware.api_key_middleware import APIKeyMiddleware

    app = FastAPI()
    app.add_middleware(APIKeyMiddleware)
    app.include_router(ob_router_mod.router)
    client = TestClient(app)

    # No header -> 401
    resp = client.post(
        "/backtest/options/run",
        json={
            "symbol": "SPY",
            "strategy": "vertical_spread",
            "start_date": "2025-01-01",
            "end_date": "2025-03-31",
        },
    )
    assert resp.status_code == 401

    resp = client.get("/backtest/options/jobs/anything")
    assert resp.status_code == 401

    resp = client.get("/backtest/options/results")
    assert resp.status_code == 401


def test_job_state_persists_across_restart(client_no_auth, fast_runner, tmp_output_dir):
    """Submit a job, wait for completion, simulate restart by resetting
    in-memory state, then verify the on-disk _jobs.json is reloaded."""
    resp = client_no_auth.post(
        "/backtest/options/run",
        json={
            "symbol": "SPY",
            "strategy": "vertical_spread",
            "start_date": "2025-01-01",
            "end_date": "2025-03-31",
        },
    )
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]
    final = _wait_for_status(client_no_auth, job_id, target="done")
    assert final["status"] == "done"

    # Confirm _jobs.json exists
    jobs_file = tmp_output_dir / "_jobs.json"
    assert jobs_file.exists()
    jobs_disk = json.loads(jobs_file.read_text(encoding="utf-8"))
    assert any(j["job_id"] == job_id for j in jobs_disk)

    # Simulate restart — clear in-memory but keep on-disk
    with ob_router_mod._jobs_lock:
        ob_router_mod._jobs.clear()
    assert len(ob_router_mod._jobs) == 0

    # Reload from disk
    ob_router_mod.load_jobs_from_disk()
    assert job_id in ob_router_mod._jobs
    reloaded = ob_router_mod._jobs[job_id]
    assert reloaded["status"] == "done"
    assert reloaded["symbol"] == "SPY"

    # And the endpoint also sees it
    resp2 = client_no_auth.get(f"/backtest/options/jobs/{job_id}")
    assert resp2.status_code == 200
    assert resp2.json()["status"] == "done"


def test_invalid_date_format_returns_400(client_no_auth, fast_runner):
    resp = client_no_auth.post(
        "/backtest/options/run",
        json={
            "symbol": "SPY",
            "strategy": "vertical_spread",
            "start_date": "not-a-date",
            "end_date": "2025-03-31",
        },
    )
    assert resp.status_code == 400
    assert "date" in resp.json()["detail"].lower()
