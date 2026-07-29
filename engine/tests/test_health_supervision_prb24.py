"""PRB-24 — pm2-vs-reality process-supervision cross-check.

Nothing structurally cross-checked pm2's belief about process state against
actual reality (pm2 jlist vs a live TCP port probe vs the real port-owner
PID). A WinError 10048 port-bind race left a healthy-but-pm2-unsupervised
orphan process serving :8010 for a stretch (2026-07-28/29), and a separate
audit found pm2 believed jarvis-dashboard/jarvis-engine were errored/stopped
while orphan processes actually served both ports — nothing surfaced that as
a finding.

These tests exercise `_compute_supervision_status()` (the core cross-check),
the pure `_parse_netstat_listening_pid()` parser, and the two endpoints that
expose it (`/health/supervision`, and the `process_supervision` subsystem
folded into `/health/full`) against four scenarios:

  (a) all-agree-healthy
  (b) pm2 says online but the port is dead
  (c) pm2 says stopped but the port is alive under a different pid (the
      actual incident shape — an orphan process pm2 doesn't know about)
  (d) pm2 command unavailable — must degrade gracefully, never 500

Run with the engine venv:
    engine/.venv/Scripts/python.exe -m pytest engine/tests/test_health_supervision_prb24.py -q
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import health_router


@pytest.fixture(autouse=True)
def _reset_supervision_caches():
    """Every test gets a cold cache — TTL must never leak a mock from a prior test."""
    health_router._supervision_cache.update(checked_at=0.0, payload=None)
    health_router._supervision_port_cache.clear()
    yield
    health_router._supervision_cache.update(checked_at=0.0, payload=None)
    health_router._supervision_port_cache.clear()


def _health_client():
    app = FastAPI()
    app.include_router(health_router.router)
    health_router.inject_dependencies(
        start_time=datetime.now(timezone.utc),
        dm=None, sl=None, dbm=None, pt=None, pm=None, tp=None, schwab=None,
    )
    return TestClient(app)


class _FakeHealthySafetyLayer:
    """Minimal safety_layer double that makes _full_health_inner's safety_layer
    and circuit_breakers blocks both report clean, so overall isn't escalated
    for reasons unrelated to the supervision cross-check under test."""

    _kill_switch_active = False
    _kill_switch_reason = None

    def check_circuit_breakers(self):
        return {"daily_limit_breached": False, "drawdown_breached": False}


def _healthy_full_health_client():
    """A /health/full client whose non-supervision subsystems are all clean,
    so `overall` reflects ONLY what the process_supervision subsystem does to
    it. Without this, db_manager=None/safety_layer=None alone already push
    overall to 'degraded' via their own 'not_initialized' branches — that's
    real _full_health_inner behavior unrelated to PRB-24, but it would make a
    bare overall=="healthy"/"degraded" assertion here meaningless."""
    app = FastAPI()
    app.include_router(health_router.router)

    db_manager = MagicMock()
    db_manager.health_check.return_value = {"ok": True}

    paper_tracker = MagicMock()
    paper_tracker.get_open_positions.return_value = []

    pnl_state = MagicMock(source="paper", current_balance=10000.0, starting_balance=10000.0)
    pnl_monitor = MagicMock()
    pnl_monitor.get_current_pnl_state.return_value = pnl_state
    pnl_monitor.get_daily_pnl.return_value = 0.0
    pnl_monitor.get_drawdown_pct.return_value = 0.0

    health_router.inject_dependencies(
        start_time=datetime.now(timezone.utc),
        dm=None,
        sl=_FakeHealthySafetyLayer(),
        dbm=db_manager,
        pt=paper_tracker,
        pm=pnl_monitor,
        tp=None,
        schwab=None,
    )
    return TestClient(app)


def _pm2_entry(name: str, status: str, pid: int) -> dict:
    return {"name": name, "pid": pid, "pm2_env": {"status": status}}


# ---------------------------------------------------------------------------
# _parse_netstat_listening_pid — pure function, no subprocess needed
# ---------------------------------------------------------------------------

_NETSTAT_SAMPLE = """
Active Connections

  Proto  Local Address          Foreign Address        State           PID
  TCP    0.0.0.0:135            0.0.0.0:0              LISTENING       812
  TCP    127.0.0.1:8010         0.0.0.0:0              LISTENING       12345
  TCP    127.0.0.1:3010         0.0.0.0:0              LISTENING       999
  TCP    127.0.0.1:54321        127.0.0.1:8010         ESTABLISHED     4444
  TCP    [::]:8020              [::]:0                 LISTENING       555
""".strip()


def test_parse_netstat_finds_listening_pid():
    assert health_router._parse_netstat_listening_pid(_NETSTAT_SAMPLE, 8010) == 12345


def test_parse_netstat_finds_ipv6_listening_pid():
    assert health_router._parse_netstat_listening_pid(_NETSTAT_SAMPLE, 8020) == 555


def test_parse_netstat_ignores_non_listening_rows():
    # Port 8010 also appears as the foreign address of an ESTABLISHED row
    # (pid 4444) — only the LISTENING row's pid must be returned.
    assert health_router._parse_netstat_listening_pid(_NETSTAT_SAMPLE, 8010) != 4444


def test_parse_netstat_no_numeric_suffix_false_match():
    # Port 10 must never match the ':8010' row via a naive suffix check.
    assert health_router._parse_netstat_listening_pid(_NETSTAT_SAMPLE, 10) is None


def test_parse_netstat_returns_none_when_port_absent():
    assert health_router._parse_netstat_listening_pid(_NETSTAT_SAMPLE, 65000) is None


def test_parse_netstat_handles_garbage_input():
    assert health_router._parse_netstat_listening_pid("not netstat output at all\n", 8010) is None


# ---------------------------------------------------------------------------
# (a) all-agree-healthy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_agree_healthy():
    processes = [
        _pm2_entry("jarvis-engine", "online", 100),
        _pm2_entry("jarvis-dashboard", "online", 200),
        _pm2_entry("jarvis-bridge-api", "online", 300),
    ]
    pid_by_port = {8010: 100, 3010: 200, 8020: 300}

    with patch.object(health_router, "_run_pm2_jlist", new=AsyncMock(return_value=(processes, None))), \
         patch.object(health_router, "_check_port_alive", return_value=True), \
         patch.object(health_router, "_get_port_owner_pid", new=AsyncMock(side_effect=lambda p: pid_by_port[p])):
        result = await health_router._compute_supervision_status()

    assert result["available"] is True
    assert result["supervision_ok"] is True
    for app_name, entry in result["apps"].items():
        assert entry["mismatch_reason"] is None, f"{app_name}: {entry['mismatch_reason']}"
        assert entry["pm2_status"] == "online"
        assert entry["port_alive"] is True


# ---------------------------------------------------------------------------
# (b) pm2 says online but the port is dead
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pm2_online_but_port_dead():
    processes = [
        _pm2_entry("jarvis-engine", "online", 100),
        _pm2_entry("jarvis-dashboard", "online", 200),
        _pm2_entry("jarvis-bridge-api", "online", 300),
    ]

    def port_alive(port: int) -> bool:
        return port != 8010  # jarvis-engine's port is dead despite pm2 believing it's up

    with patch.object(health_router, "_run_pm2_jlist", new=AsyncMock(return_value=(processes, None))), \
         patch.object(health_router, "_check_port_alive", side_effect=port_alive), \
         patch.object(health_router, "_get_port_owner_pid", new=AsyncMock(return_value=None)):
        result = await health_router._compute_supervision_status()

    assert result["supervision_ok"] is False
    engine_entry = result["apps"]["jarvis-engine"]
    assert engine_entry["port_alive"] is False
    assert engine_entry["mismatch_reason"] is not None
    assert "online" in engine_entry["mismatch_reason"]
    # Unaffected apps still agree.
    assert result["apps"]["jarvis-dashboard"]["mismatch_reason"] is None


# ---------------------------------------------------------------------------
# (c) pm2 says stopped but the port is alive under a different pid — the
# actual 2026-07-28/29 incident shape (orphan process serving the port).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pm2_stopped_but_port_alive_different_pid_orphan_shape():
    processes = [
        _pm2_entry("jarvis-engine", "online", 100),
        _pm2_entry("jarvis-dashboard", "stopped", 0),  # pm2 believes this is dead
        _pm2_entry("jarvis-bridge-api", "online", 300),
    ]
    pid_by_port = {8010: 100, 3010: 987654, 8020: 300}  # 987654 = the orphan

    with patch.object(health_router, "_run_pm2_jlist", new=AsyncMock(return_value=(processes, None))), \
         patch.object(health_router, "_check_port_alive", return_value=True), \
         patch.object(health_router, "_get_port_owner_pid", new=AsyncMock(side_effect=lambda p: pid_by_port[p])):
        result = await health_router._compute_supervision_status()

    assert result["supervision_ok"] is False
    dash_entry = result["apps"]["jarvis-dashboard"]
    assert dash_entry["pm2_status"] == "stopped"
    assert dash_entry["pm2_pid"] is None  # pm2's 0 normalizes to None
    assert dash_entry["port_alive"] is True
    assert dash_entry["actual_pid"] == 987654
    assert dash_entry["mismatch_reason"] is not None
    assert "orphan" in dash_entry["mismatch_reason"]


@pytest.mark.asyncio
async def test_pm2_pid_mismatch_when_both_believe_online():
    """A subtler variant of (c): pm2 says online with pid X, port IS alive,
    but the process actually answering the port has a different pid — pm2's
    tracked process died and something else (or a stale pm2 record) grabbed
    the port without pm2 noticing."""
    processes = [_pm2_entry("jarvis-engine", "online", 100)]
    pid_by_port = {8010: 999, 3010: None, 8020: None}

    with patch.object(health_router, "_run_pm2_jlist", new=AsyncMock(return_value=(processes, None))), \
         patch.object(health_router, "_check_port_alive", return_value=True), \
         patch.object(health_router, "_get_port_owner_pid", new=AsyncMock(side_effect=lambda p: pid_by_port[p])):
        result = await health_router._compute_supervision_status()

    engine_entry = result["apps"]["jarvis-engine"]
    assert engine_entry["mismatch_reason"] is not None
    assert "pid mismatch" in engine_entry["mismatch_reason"]


@pytest.mark.asyncio
async def test_no_pm2_entry_but_port_alive_is_a_mismatch():
    """pm2 doesn't even track the app (never registered / config drift), but
    something is answering its port — unsupervised process, first-class flag."""
    processes = []  # nothing tracked at all

    with patch.object(health_router, "_run_pm2_jlist", new=AsyncMock(return_value=(processes, None))), \
         patch.object(health_router, "_check_port_alive", return_value=True), \
         patch.object(health_router, "_get_port_owner_pid", new=AsyncMock(return_value=555)):
        result = await health_router._compute_supervision_status()

    assert result["supervision_ok"] is False
    for entry in result["apps"].values():
        assert entry["pm2_found"] is False
        assert entry["mismatch_reason"] is not None
        assert "no" in entry["mismatch_reason"]


# ---------------------------------------------------------------------------
# (d) pm2 command unavailable — must degrade gracefully, never crash /health
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pm2_unavailable_degrades_gracefully():
    with patch.object(
        health_router, "_run_pm2_jlist",
        new=AsyncMock(return_value=(None, "pm2 not found on PATH")),
    ):
        result = await health_router._compute_supervision_status()

    assert result["available"] is False
    assert result["supervision_ok"] is None
    assert result["error"] == "pm2 not found on PATH"
    assert result["apps"] == {}


@pytest.mark.asyncio
async def test_run_pm2_jlist_handles_missing_executable():
    """Exercise the real _run_pm2_jlist plumbing (not just the mocked
    higher-level function) — a FileNotFoundError from the subprocess shell-out
    (pm2 truly absent from PATH) must resolve to (None, <reason>), never raise."""
    with patch("asyncio.create_subprocess_shell", new=AsyncMock(side_effect=FileNotFoundError())):
        processes, error = await health_router._run_pm2_jlist()

    assert processes is None
    assert error is not None
    assert "not found" in error.lower()


@pytest.mark.asyncio
async def test_run_pm2_jlist_handles_timeout():
    import asyncio as _asyncio

    class _NeverCompletes:
        def communicate(self):
            # asyncio.wait_for is mocked below and never actually awaits this,
            # so returning a bare (non-coroutine) value avoids an "unawaited
            # coroutine" warning while still matching proc.communicate()'s
            # call shape used by _run_pm2_jlist.
            return object()

    async def _fake_create_subprocess_shell(*_a, **_kw):
        return _NeverCompletes()

    with patch("asyncio.create_subprocess_shell", side_effect=_fake_create_subprocess_shell), \
         patch("asyncio.wait_for", new=AsyncMock(side_effect=_asyncio.TimeoutError())):
        processes, error = await health_router._run_pm2_jlist()

    assert processes is None
    assert "timed out" in error


# ---------------------------------------------------------------------------
# Endpoint-level: GET /health/supervision
# ---------------------------------------------------------------------------


def test_endpoint_health_supervision_returns_mismatch():
    processes = [_pm2_entry("jarvis-engine", "online", 100)]

    with patch.object(health_router, "_run_pm2_jlist", new=AsyncMock(return_value=(processes, None))), \
         patch.object(health_router, "_check_port_alive", return_value=False), \
         patch.object(health_router, "_get_port_owner_pid", new=AsyncMock(return_value=None)):
        resp = _health_client().get("/health/supervision")

    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is True
    assert body["supervision_ok"] is False
    assert body["apps"]["jarvis-engine"]["mismatch_reason"] is not None


def test_endpoint_health_supervision_never_500s_on_unavailable():
    with patch.object(
        health_router, "_run_pm2_jlist",
        new=AsyncMock(return_value=(None, "pm2 not found on PATH")),
    ):
        resp = _health_client().get("/health/supervision")

    assert resp.status_code == 200  # never a 500 — degrade, don't crash
    body = resp.json()
    assert body["available"] is False
    assert body["supervision_ok"] is None


def test_endpoint_health_supervision_never_500s_on_internal_exception():
    """Even if the cached compute somehow raises, the endpoint's own try/except
    must still return a 200 degraded payload, not surface a 500 to callers."""
    with patch.object(health_router, "_supervision_cached", new=AsyncMock(side_effect=RuntimeError("boom"))):
        resp = _health_client().get("/health/supervision")

    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is False
    assert body["supervision_ok"] is None
    assert "boom" in body["error"]


# ---------------------------------------------------------------------------
# Endpoint-level: process_supervision subsystem inside GET /health/full
# ---------------------------------------------------------------------------


_LLM_HEALTHY_STATE = {"healthy": True, "google_fallback_count": 0, "vertex_failover_count": 0}
_LLM_HEALTHY_SUMMARY = {
    "active_provider": "anthropic",
    "primary_provider": "anthropic",
    "providers_configured": ["anthropic"],
    "providers_available": 1,
    "primary_healthy": True,
    "single_leg_warning": False,
}


def test_full_health_escalates_overall_on_supervision_mismatch():
    processes = [_pm2_entry("jarvis-engine", "online", 100)]

    with patch.object(health_router, "_run_pm2_jlist", new=AsyncMock(return_value=(processes, None))), \
         patch.object(health_router, "_check_port_alive", return_value=False), \
         patch.object(health_router, "_get_port_owner_pid", new=AsyncMock(return_value=None)), \
         patch("llm.client.get_llm_path_state", return_value=_LLM_HEALTHY_STATE), \
         patch("llm.client.get_llm_provider_summary", return_value=_LLM_HEALTHY_SUMMARY):
        resp = _healthy_full_health_client().get("/health/full")

    assert resp.status_code == 200
    body = resp.json()
    sup = body["subsystems"]["process_supervision"]
    assert sup["status"] == "mismatch"
    assert sup["details"]["supervision_ok"] is False
    assert body["overall"] == "degraded"


def test_full_health_does_not_escalate_when_supervision_unavailable():
    """pm2 not being on PATH is an environment fact, not a live incident —
    must not by itself flip an otherwise-healthy engine to 'degraded'."""
    with patch.object(
        health_router, "_run_pm2_jlist",
        new=AsyncMock(return_value=(None, "pm2 not found on PATH")),
    ), \
         patch("llm.client.get_llm_path_state", return_value=_LLM_HEALTHY_STATE), \
         patch("llm.client.get_llm_provider_summary", return_value=_LLM_HEALTHY_SUMMARY):
        resp = _healthy_full_health_client().get("/health/full")

    assert resp.status_code == 200
    body = resp.json()
    sup = body["subsystems"]["process_supervision"]
    assert sup["status"] == "unavailable"
    assert body["overall"] == "healthy"


def test_full_health_ok_when_supervision_agrees():
    processes = [
        _pm2_entry("jarvis-engine", "online", 100),
        _pm2_entry("jarvis-dashboard", "online", 200),
        _pm2_entry("jarvis-bridge-api", "online", 300),
    ]
    pid_by_port = {8010: 100, 3010: 200, 8020: 300}

    with patch.object(health_router, "_run_pm2_jlist", new=AsyncMock(return_value=(processes, None))), \
         patch.object(health_router, "_check_port_alive", return_value=True), \
         patch.object(health_router, "_get_port_owner_pid", new=AsyncMock(side_effect=lambda p: pid_by_port[p])), \
         patch("llm.client.get_llm_path_state", return_value=_LLM_HEALTHY_STATE), \
         patch("llm.client.get_llm_provider_summary", return_value=_LLM_HEALTHY_SUMMARY):
        resp = _healthy_full_health_client().get("/health/full")

    assert resp.status_code == 200
    body = resp.json()
    assert body["subsystems"]["process_supervision"]["status"] == "ok"
    assert body["overall"] == "healthy"


def test_full_health_process_supervision_survives_internal_exception():
    with patch.object(health_router, "_supervision_cached", new=AsyncMock(side_effect=RuntimeError("boom"))):
        resp = _health_client().get("/health/full")

    assert resp.status_code == 200  # never 5xx on a supervision read failure
    sup = resp.json()["subsystems"]["process_supervision"]
    assert sup["status"] == "error"
    assert "boom" in sup["error"]


# ---------------------------------------------------------------------------
# Caching: _supervision_cached must not re-shell-out within the TTL window
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_supervision_cache_serves_within_ttl():
    call_count = {"n": 0}

    async def _counting_pm2_jlist():
        call_count["n"] += 1
        return [_pm2_entry("jarvis-engine", "online", 100)], None

    with patch.object(health_router, "_run_pm2_jlist", side_effect=_counting_pm2_jlist), \
         patch.object(health_router, "_check_port_alive", return_value=True), \
         patch.object(health_router, "_get_port_owner_pid", new=AsyncMock(return_value=100)):
        first = await health_router._supervision_cached()
        second = await health_router._supervision_cached()

    assert call_count["n"] == 1  # second call served from cache, no re-shell-out
    assert first == second
