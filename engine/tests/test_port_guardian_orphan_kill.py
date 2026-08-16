"""Regression tests for port_guardian ownership-aware orphan handling."""

from __future__ import annotations

import http.client
import sys
import types

from scripts import port_guardian


def _base_main_mocks(monkeypatch, holders=None, command_line="python scripts/port_guardian.py"):
    monkeypatch.setattr(port_guardian, "_check_venv_python", lambda: None)
    monkeypatch.setattr(port_guardian, "_port_holders", lambda port: list(holders or [4242]))
    monkeypatch.setattr(port_guardian, "_process_name", lambda pid: "python")
    monkeypatch.setattr(port_guardian, "_process_command_line", lambda pid: command_line)
    monkeypatch.setattr(port_guardian, "_record_restart_event", lambda *a, **k: None)
    monkeypatch.setattr(port_guardian.time, "sleep", lambda seconds: None)


def test_healthy_managed_predecessor_is_not_killed(monkeypatch):
    _base_main_mocks(monkeypatch)
    monkeypatch.setattr(port_guardian, "_is_healthy", lambda port: True)

    killed = []
    monkeypatch.setattr(port_guardian, "_kill_pid", lambda pid: killed.append(pid) or True)

    assert port_guardian.main() == 3
    assert killed == []


def test_healthy_direct_uvicorn_remains_takeover_candidate(monkeypatch):
    _base_main_mocks(monkeypatch, command_line="python -m uvicorn main:app --port 8010")
    monkeypatch.setattr(port_guardian, "_is_healthy", lambda port: True)

    killed = []
    monkeypatch.setattr(port_guardian, "_kill_pid", lambda pid: killed.append(pid) or True)
    monkeypatch.setattr(port_guardian, "_wait_port_free", lambda port, timeout=None: False)

    assert port_guardian.main() == 2
    assert killed == [4242]


def test_transient_health_timeout_is_retried_before_kill(monkeypatch):
    _base_main_mocks(monkeypatch)
    responses = iter([False, True, True])
    monkeypatch.setattr(port_guardian, "_is_healthy", lambda port: next(responses))

    killed = []
    monkeypatch.setattr(port_guardian, "_kill_pid", lambda pid: killed.append(pid) or True)

    assert port_guardian.main() == 3
    assert killed == []


def test_malformed_http_reply_is_unhealthy(monkeypatch):
    def malformed(*args, **kwargs):
        raise http.client.BadStatusLine("not-http")

    monkeypatch.setattr(port_guardian.urllib.request, "urlopen", malformed)

    assert port_guardian._is_healthy(port_guardian.PORT) is False


def test_port_released_during_backoff_continues_startup(monkeypatch):
    calls = iter([[4242], []])
    _base_main_mocks(monkeypatch)
    monkeypatch.setattr(port_guardian, "_port_holders", lambda port: next(calls))
    monkeypatch.setattr(port_guardian, "_is_healthy", lambda port: True)
    monkeypatch.setattr(port_guardian, "_wait_port_free", lambda port, timeout=None: True)
    monkeypatch.setattr(port_guardian, "_start_readiness_watchdog", lambda: None)

    run_calls = []
    monkeypatch.setitem(
        sys.modules,
        "uvicorn",
        types.SimpleNamespace(run=lambda *args, **kwargs: run_calls.append((args, kwargs))),
    )

    assert port_guardian.main() == 0
    assert len(run_calls) == 1


def test_multiple_holders_are_all_inspected_and_fail_closed(monkeypatch):
    _base_main_mocks(monkeypatch, holders=[4242, 4343])
    inspected = []
    monkeypatch.setattr(
        port_guardian,
        "_process_command_line",
        lambda pid: inspected.append(pid) or f"python scripts/port_guardian.py --pid {pid}",
    )

    killed = []
    monkeypatch.setattr(port_guardian, "_kill_pid", lambda pid: killed.append(pid) or True)

    assert port_guardian.main() == 1
    assert inspected == [4242, 4343]
    assert killed == []


def test_holder_change_after_backoff_fails_closed(monkeypatch):
    calls = iter([[4242], [4343]])
    _base_main_mocks(monkeypatch)
    monkeypatch.setattr(port_guardian, "_port_holders", lambda port: next(calls))
    monkeypatch.setattr(port_guardian, "_is_healthy", lambda port: True)

    killed = []
    monkeypatch.setattr(port_guardian, "_kill_pid", lambda pid: killed.append(pid) or True)

    assert port_guardian.main() == 1
    assert killed == []


def test_unhealthy_orphan_is_still_killed(monkeypatch):
    _base_main_mocks(monkeypatch)
    monkeypatch.setattr(port_guardian, "_is_healthy", lambda port: False)

    killed = []
    monkeypatch.setattr(port_guardian, "_kill_pid", lambda pid: killed.append(pid) or True)
    monkeypatch.setattr(port_guardian, "_wait_port_free", lambda port, timeout=None: False)

    assert port_guardian.main() == 2
    assert killed == [4242]
