"""
Tests for engine/routers/kairos_router.py

Covered:
  - GET  /kairos/status                — daemon running + daemon not enabled
  - GET  /kairos/observations          — daemon-enabled read (get_recent/read_today,
                                          severity filter) + daemon-not-enabled short-circuit
  - GET  /kairos/observations/{date}   — success + no-results-for-date edge
  - GET  /kairos/watchers              — daemon running + daemon not enabled
  - POST /kairos/tick                  — success + 503 when daemon not enabled
  - GET  /kairos/dream/{date}          — success + no-observations edge
  - POST /kairos/dream                 — success (today, no target_date)

Note: kairos/daemon.py IS implemented in this checkout (contrary to the stale
`kairos_daemon_missing` skip marker in test_kairos.py), but this file does not
exercise daemon internals — it only tests the router's HTTP surface, mocking
`get_kairos()`, `ObservationLog`, and `KairosDreamer` as the router's external
dependencies (matching the task scope: router surface, not daemon internals).

Design:
  - Minimal FastAPI app wrapping only kairos_router (no full main.py import).
  - `routers.kairos_router.get_kairos` is patched directly (module-level import).
  - `kairos.observation_log.ObservationLog` / `kairos.dreaming.KairosDreamer` are
    patched at their source module so the router's function-local `from ... import`
    picks up the mock at call time.
"""

from __future__ import annotations

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

from routers.kairos_router import router as kairos_router  # noqa: E402

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(kairos_router)
    return TestClient(app, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# GET /kairos/status
# ---------------------------------------------------------------------------


def test_status_daemon_not_enabled(client):
    with patch("routers.kairos_router.get_kairos", return_value=None):
        resp = client.get("/kairos/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["running"] is False
    assert data["enabled"] is False
    assert data["message"] == "KAIROS not enabled"


def test_status_daemon_running(client):
    daemon = MagicMock()
    daemon.get_status.return_value = {
        "running": True,
        "tick_count": 12,
        "watcher_count": 3,
        "watchers": ["regime_change", "stc_crossover", "risk_limit"],
    }
    with patch("routers.kairos_router.get_kairos", return_value=daemon):
        resp = client.get("/kairos/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["running"] is True
    assert data["tick_count"] == 12
    assert data["watcher_count"] == 3


# ---------------------------------------------------------------------------
# GET /kairos/observations
# ---------------------------------------------------------------------------


def test_observations_daemon_not_enabled_short_circuits(client):
    """When no daemon is running, the endpoint must not even touch ObservationLog."""
    with patch("routers.kairos_router.get_kairos", return_value=None), patch(
        "kairos.observation_log.ObservationLog"
    ) as mock_log_cls:
        resp = client.get("/kairos/observations")
    assert resp.status_code == 200
    assert resp.json() == {"observations": [], "enabled": False}
    mock_log_cls.assert_not_called()


def test_observations_success_default_minutes(client):
    daemon = MagicMock()
    obs_list = [
        {"watcher": "vix_spike", "severity": "warning", "message": "vix +2.1"},
        {"watcher": "regime_change", "severity": "critical", "message": "regime flip"},
    ]
    mock_log = MagicMock()
    mock_log.get_recent.return_value = obs_list
    mock_log.count_by_severity.return_value = {"info": 0, "warning": 1, "critical": 1}

    with patch("routers.kairos_router.get_kairos", return_value=daemon), patch(
        "kairos.observation_log.ObservationLog", return_value=mock_log
    ):
        resp = client.get("/kairos/observations")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["total"] == 2
    assert data["observations"] == obs_list
    mock_log.get_recent.assert_called_once_with(minutes=60)
    mock_log.read_today.assert_not_called()


def test_observations_minutes_zero_uses_read_today(client):
    daemon = MagicMock()
    mock_log = MagicMock()
    mock_log.read_today.return_value = [{"watcher": "w", "severity": "info", "message": "m"}]
    mock_log.count_by_severity.return_value = {"info": 1, "warning": 0, "critical": 0}

    with patch("routers.kairos_router.get_kairos", return_value=daemon), patch(
        "kairos.observation_log.ObservationLog", return_value=mock_log
    ):
        resp = client.get("/kairos/observations", params={"minutes": 0})
    assert resp.status_code == 200
    mock_log.read_today.assert_called_once()
    mock_log.get_recent.assert_not_called()
    assert resp.json()["total"] == 1


def test_observations_severity_filter(client):
    daemon = MagicMock()
    obs_list = [
        {"watcher": "a", "severity": "info", "message": "1"},
        {"watcher": "b", "severity": "warning", "message": "2"},
        {"watcher": "c", "severity": "warning", "message": "3"},
    ]
    mock_log = MagicMock()
    mock_log.get_recent.return_value = obs_list
    mock_log.count_by_severity.return_value = {"info": 1, "warning": 2, "critical": 0}

    with patch("routers.kairos_router.get_kairos", return_value=daemon), patch(
        "kairos.observation_log.ObservationLog", return_value=mock_log
    ):
        resp = client.get("/kairos/observations", params={"severity": "warning"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert all(o["severity"] == "warning" for o in data["observations"])


# ---------------------------------------------------------------------------
# GET /kairos/observations/{date_str}
# ---------------------------------------------------------------------------


def test_observations_by_date_success(client):
    mock_log = MagicMock()
    mock_log.read_date.return_value = [
        {"watcher": "regime_change", "severity": "warning", "message": "flip"}
    ]
    with patch("kairos.observation_log.ObservationLog", return_value=mock_log):
        resp = client.get("/kairos/observations/2026-07-01")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["date"] == "2026-07-01"
    assert data["total"] == 1
    mock_log.read_date.assert_called_once_with("2026-07-01")


def test_observations_by_date_no_results(client):
    """Nonexistent / malformed date strings degrade to an empty list (per
    ObservationLog.read_date's real behavior), never a 500."""
    mock_log = MagicMock()
    mock_log.read_date.return_value = []
    with patch("kairos.observation_log.ObservationLog", return_value=mock_log):
        resp = client.get("/kairos/observations/not-a-real-date")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["observations"] == []


# ---------------------------------------------------------------------------
# GET /kairos/watchers
# ---------------------------------------------------------------------------


def test_watchers_daemon_not_enabled(client):
    with patch("routers.kairos_router.get_kairos", return_value=None):
        resp = client.get("/kairos/watchers")
    assert resp.status_code == 200
    assert resp.json() == {"watchers": [], "enabled": False}


def test_watchers_daemon_running(client):
    daemon = MagicMock()
    daemon.get_status.return_value = {
        "running": True,
        "watchers": ["vix_spike", "spread_widening"],
    }
    with patch("routers.kairos_router.get_kairos", return_value=daemon):
        resp = client.get("/kairos/watchers")
    assert resp.status_code == 200
    data = resp.json()
    assert data["running"] is True
    assert data["watchers"] == ["vix_spike", "spread_widening"]


# ---------------------------------------------------------------------------
# POST /kairos/tick
# ---------------------------------------------------------------------------


def test_manual_tick_not_enabled_503(client):
    with patch("routers.kairos_router.get_kairos", return_value=None):
        resp = client.post("/kairos/tick")
    assert resp.status_code == 503
    assert "KAIROS not enabled" in resp.json()["detail"]


def test_manual_tick_success(client):
    daemon = MagicMock()
    daemon.tick = AsyncMock()
    daemon._tick_count = 7
    with patch("routers.kairos_router.get_kairos", return_value=daemon):
        resp = client.post("/kairos/tick")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "tick_completed"
    assert data["tick_count"] == 7
    daemon.tick.assert_awaited_once()


# ---------------------------------------------------------------------------
# GET /kairos/dream/{date_str}
# ---------------------------------------------------------------------------


def test_dream_by_date_success(client):
    summary = {
        "date": "2026-07-01",
        "total_observations": 4,
        "severity_counts": {"info": 2, "warning": 1, "critical": 1},
        "patterns": ["High-severity day: 1 CRITICAL observation(s) recorded."],
    }
    mock_dreamer = MagicMock()
    mock_dreamer.dream = AsyncMock(return_value=summary)
    with patch("kairos.dreaming.KairosDreamer", return_value=mock_dreamer):
        resp = client.get("/kairos/dream/2026-07-01")
    assert resp.status_code == 200, resp.text
    assert resp.json() == summary
    mock_dreamer.dream.assert_awaited_once_with(target_date="2026-07-01")


def test_dream_by_date_no_observations(client):
    """Edge case per KairosDreamer.dream(): empty day still returns 200 with a
    'no observations' shaped summary, not an error."""
    empty_summary = {
        "date": "2020-01-01",
        "summary": "No observations to consolidate.",
        "patterns": [],
        "severity_counts": {"info": 0, "warning": 0, "critical": 0},
        "watcher_hits": {},
        "top_watchers": [],
        "llm_insights": None,
    }
    mock_dreamer = MagicMock()
    mock_dreamer.dream = AsyncMock(return_value=empty_summary)
    with patch("kairos.dreaming.KairosDreamer", return_value=mock_dreamer):
        resp = client.get("/kairos/dream/2020-01-01")
    assert resp.status_code == 200
    assert resp.json()["patterns"] == []


# ---------------------------------------------------------------------------
# POST /kairos/dream
# ---------------------------------------------------------------------------


def test_run_dream_default_today(client):
    summary = {"date": "today-placeholder", "total_observations": 0, "patterns": []}
    mock_dreamer = MagicMock()
    mock_dreamer.dream = AsyncMock(return_value=summary)
    with patch("kairos.dreaming.KairosDreamer", return_value=mock_dreamer):
        resp = client.post("/kairos/dream")
    assert resp.status_code == 200, resp.text
    assert resp.json() == summary
    # No target_date supplied — the router calls dream() with defaults.
    mock_dreamer.dream.assert_awaited_once_with()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
