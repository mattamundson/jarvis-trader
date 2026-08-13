"""
Regression tests for the 2026-07-30 port_guardian crash-loop fix.

Root cause: _looks_like_orphan_uvicorn() matches on process name only
("python"/"uvicorn"), so it can't distinguish a genuinely abandoned orphan
(the 2026-04-14 case this script was built for) from the CURRENT live-serving
engine that PM2 just decided to restart for an unrelated reason. Before this
fix, main() killed any name-matching port holder unconditionally, which
produced a daisy-chain: each freshly spawned guardian killed its own
just-booted, healthy predecessor, restarted, and was killed by the next spawn
— observed as an "orphan-kill" restart-loop climbing ~145 restarts/hour with
no external crash involved. These tests pin the two required behaviors: skip
the kill when /health says the holder is alive, still kill when it doesn't.
"""

from scripts import port_guardian


class TestSkipsKillingHealthyOrphan:
    def test_refuses_to_kill_and_returns_3_when_health_check_passes(self, monkeypatch):
        killed = {"called": False}

        monkeypatch.setattr(port_guardian, "_check_venv_python", lambda: None)
        monkeypatch.setattr(port_guardian, "_port_holders", lambda port: [4242])
        monkeypatch.setattr(port_guardian, "_process_name", lambda pid: "python")
        monkeypatch.setattr(port_guardian, "_is_healthy", lambda port: True)

        def _kill(pid):
            killed["called"] = True
            return True

        monkeypatch.setattr(port_guardian, "_kill_pid", _kill)
        monkeypatch.setattr(port_guardian.time, "sleep", lambda s: None)

        events = []
        monkeypatch.setattr(
            port_guardian,
            "_record_restart_event",
            lambda reason, details, log_path: events.append((reason, details)),
        )

        rc = port_guardian.main()

        assert rc == 3
        assert killed["called"] is False, "a healthy port holder must never be killed"
        assert events == [("healthy-orphan-skip", {"pid": 4242, "name": "python", "port": port_guardian.PORT})]

    def test_still_kills_when_orphan_is_not_healthy(self, monkeypatch):
        killed = {"called": False}

        monkeypatch.setattr(port_guardian, "_check_venv_python", lambda: None)
        monkeypatch.setattr(port_guardian, "_port_holders", lambda port: [4242])
        monkeypatch.setattr(port_guardian, "_process_name", lambda pid: "python")
        monkeypatch.setattr(port_guardian, "_is_healthy", lambda port: False)

        def _kill(pid):
            killed["called"] = True
            return True

        monkeypatch.setattr(port_guardian, "_kill_pid", _kill)
        # Short-circuit before the uvicorn launch (out of scope for this unit test) by
        # reporting the port never actually released -- main() returns 2 immediately
        # after the kill attempt without importing/running uvicorn.
        monkeypatch.setattr(port_guardian, "_wait_port_free", lambda port, timeout=None: False)
        monkeypatch.setattr(port_guardian, "_record_restart_event", lambda *a, **k: None)

        rc = port_guardian.main()

        assert killed["called"] is True, "a genuinely unhealthy orphan must still be killed"
        assert rc == 2

    def test_health_check_is_probed_before_any_kill_attempt(self, monkeypatch):
        # Order matters: _is_healthy must be consulted before _kill_pid is ever
        # invoked, not just before deciding what to do on kill failure.
        call_order = []

        monkeypatch.setattr(port_guardian, "_check_venv_python", lambda: None)
        monkeypatch.setattr(port_guardian, "_port_holders", lambda port: [4242])
        monkeypatch.setattr(port_guardian, "_process_name", lambda pid: "uvicorn")

        def _is_healthy(port):
            call_order.append("is_healthy")
            return True

        def _kill(pid):
            call_order.append("kill_pid")
            return True

        monkeypatch.setattr(port_guardian, "_is_healthy", _is_healthy)
        monkeypatch.setattr(port_guardian, "_kill_pid", _kill)
        monkeypatch.setattr(port_guardian.time, "sleep", lambda s: None)
        monkeypatch.setattr(port_guardian, "_record_restart_event", lambda *a, **k: None)

        port_guardian.main()

        assert call_order == ["is_healthy"], "kill_pid must not run once health check short-circuits"
