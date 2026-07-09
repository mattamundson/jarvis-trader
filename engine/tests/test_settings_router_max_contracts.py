"""
JARVIS TRADER — Settings Router: max_contracts bound regression test
======================================================================
T0-07 (dashboard-integrity audit, 2026-07-09): the DB-backed risk-limit
override channel (POST /settings/risk) validated max_contracts with
``1 <= int(v) <= 10``, five times the documented hardcoded safety
invariant in .claude/rules/safety.md ("Max contracts per instrument: 2
micro contracts"). A user could click Save in the dashboard's Risk
Limits editor (dashboard/app/settings/page.tsx) and silently raise the
runtime-effective contract cap past the invariant with no
[safety-review] gate on the DB write path.

This test pins the corrected bound directly against the API (bypassing
the dashboard UI entirely) so a future edit can't silently widen it
again without failing CI.

Run with:
    cd engine
    .venv\\Scripts\\python.exe -m pytest tests/test_settings_router_max_contracts.py -v --tb=short
"""

from __future__ import annotations

import os
import sys

import pytest

# ---------------------------------------------------------------------------
# Environment bootstrap — mirrors tests/test_config_router.py
# ---------------------------------------------------------------------------


def _load_env() -> None:
    """Load .env into os.environ (mirrors conftest pattern used in other tests)."""
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    if os.path.exists(env_path):
        with open(env_path) as fh:
            for line in fh:
                line = line.strip()
                if line and "=" in line and not line.startswith("#"):
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key, value)


_load_env()

_ENGINE_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if _ENGINE_ROOT not in sys.path:
    sys.path.insert(0, _ENGINE_ROOT)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeDbManager:
    """Minimal in-memory stand-in for DatabaseManager's settings mixin."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    def get_setting(self, key: str, default=None):
        return self._store.get(key, default)

    def set_setting(self, key: str, value) -> None:
        self._store[key] = str(value)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def client():
    """FastAPI TestClient wrapping just settings_router, with a fake DB manager."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from routers.settings_router import inject_dependencies
    from routers.settings_router import router as settings_router

    fake_db = FakeDbManager()
    inject_dependencies(None, fake_db, None)

    app = FastAPI()
    app.include_router(settings_router)
    return TestClient(app, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# max_contracts bound tests
# ---------------------------------------------------------------------------


def test_max_contracts_10_rejected(client):
    """
    T0-07 regression: POSTing max_contracts=10 directly to the API must be
    rejected. Prior bound (1 <= v <= 10) allowed this — 5x the documented
    invariant ("Max contracts per instrument: 2 micro contracts",
    .claude/rules/safety.md).
    """
    resp = client.post("/settings/risk", json={"max_contracts": 10})
    assert resp.status_code == 200, f"Unexpected transport error: {resp.status_code}: {resp.text}"
    body = resp.json()

    assert "max_contracts" in body["errors"], (
        f"max_contracts=10 was NOT rejected — errors={body['errors']!r}, "
        f"updated={body['updated']!r}"
    )
    assert "max_contracts" not in body["updated"], (
        "max_contracts=10 was persisted despite exceeding the safety invariant"
    )
    assert body["count"] == 0


def test_max_contracts_3_rejected(client):
    """One above the invariant ceiling must also be rejected (boundary check)."""
    resp = client.post("/settings/risk", json={"max_contracts": 3})
    assert resp.status_code == 200
    body = resp.json()

    assert "max_contracts" in body["errors"], (
        f"max_contracts=3 was NOT rejected — errors={body['errors']!r}"
    )
    assert "max_contracts" not in body["updated"]


def test_max_contracts_2_accepted(client):
    """
    The documented ceiling itself (2) must still be accepted — the fix must
    not over-tighten below the actual invariant.
    """
    resp = client.post("/settings/risk", json={"max_contracts": 2})
    assert resp.status_code == 200
    body = resp.json()

    assert "max_contracts" not in body["errors"], (
        f"max_contracts=2 was wrongly rejected — errors={body['errors']!r}"
    )
    assert body["updated"].get("max_contracts") == 2
    assert body["count"] == 1


def test_max_contracts_1_accepted(client):
    """Lower boundary (1) must still be accepted."""
    resp = client.post("/settings/risk", json={"max_contracts": 1})
    assert resp.status_code == 200
    body = resp.json()

    assert "max_contracts" not in body["errors"]
    assert body["updated"].get("max_contracts") == 1


def test_max_contracts_0_rejected(client):
    """Lower boundary violation (0) must be rejected too."""
    resp = client.post("/settings/risk", json={"max_contracts": 0})
    assert resp.status_code == 200
    body = resp.json()

    assert "max_contracts" in body["errors"]
    assert "max_contracts" not in body["updated"]
