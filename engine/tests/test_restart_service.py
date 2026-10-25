from __future__ import annotations

import importlib.util
import json
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "restart_service.py"
SPEC = importlib.util.spec_from_file_location("restart_service", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
RESTART = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RESTART)


class FakeResponse:
    status = 200

    def __init__(self, payload: dict):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode()


def test_engine_application_readiness_accepts_lowercase_ok_in_paper_mode(monkeypatch):
    monkeypatch.setattr(RESTART, "_read_api_key", lambda: "redacted")
    monkeypatch.setattr(
        RESTART.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: FakeResponse({"status": "ok", "live_trading": False}),
    )

    assert RESTART.application_ready(RESTART.TARGETS["engine"]) is True


def test_engine_restart_refuses_unsafe_listener_kill_when_pm2_fails(monkeypatch):
    killed: list[int] = []
    monkeypatch.setattr(RESTART.sys, "argv", ["restart_service.py", "engine"])
    monkeypatch.setattr(RESTART, "listening_pid", lambda _port: 1234)
    monkeypatch.setattr(RESTART, "restart_with_pm2", lambda _name: False)
    monkeypatch.setattr(RESTART, "kill", lambda pid: killed.append(pid) or True)

    assert RESTART.main() == 1
    assert killed == []
