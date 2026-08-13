"""
Tests for engine/routers/flags_router.py

Covered:
  - GET  /flags/           — list all flags (success); 503 when FeatureFlags not injected
  - GET  /flags/{name}     — single flag lookup (success); 404 for unknown flag name
  - PUT  /flags/{name}     — set runtime override (success + requires_restart branch);
                              404 for unknown flag; 422 when the injected FeatureFlags
                              rejects the value (mocked-dependency-failure path)
  - DELETE /flags/{name}   — reset to config default (success); 404 for unknown flag;
                              422 when the injected FeatureFlags raises on reset
  - auth-missing / bad-key returns 401 (enforced by APIKeyMiddleware, global)

Design:
  - Uses a minimal FastAPI app wrapping only flags_router (no full main.py import),
    mirroring tests/test_admin_router.py.
  - APIKeyMiddleware is added manually so auth tests are realistic.
  - The router's only external dependency is the injected FeatureFlags instance
    (set via routers.flags_router.set_flags). Tests use a small in-memory fake
    that mirrors flags.registry.FeatureFlags's public contract (list_flags/
    set_flag/reset_flag) instead of a real SQLite-backed instance — this mocks
    the external dependency without re-implementing router logic.
  - Never touches engine/.env or any live endpoint.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

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
from flags.registry import FLAG_DEFINITIONS  # noqa: E402
from middleware.api_key_middleware import APIKeyMiddleware  # noqa: E402
from routers import flags_router  # noqa: E402
from routers.flags_router import router as flags_api_router  # noqa: E402

_VALID_HEADERS = {"X-API-Key": settings.API_KEY}
_BAD_HEADERS = {"X-API-Key": "wrong-key"}

_KNOWN_FLAG = FLAG_DEFINITIONS[0]["name"]  # "ENABLE_KAIROS" — deterministic pick
_RESTART_FLAG = next(f["name"] for f in FLAG_DEFINITIONS if f["requires_restart"])
_NO_RESTART_FLAG = next(f["name"] for f in FLAG_DEFINITIONS if not f["requires_restart"])


# ---------------------------------------------------------------------------
# Fake FeatureFlags — mocks the router's one external dependency
# ---------------------------------------------------------------------------


class _FakeFeatureFlags:
    """In-memory double matching flags.registry.FeatureFlags's public contract."""

    def __init__(
        self,
        overrides: Optional[Dict[str, bool]] = None,
        raise_on_set: Optional[Exception] = None,
        raise_on_reset: Optional[Exception] = None,
    ) -> None:
        self._overrides: Dict[str, bool] = dict(overrides or {})
        self._raise_on_set = raise_on_set
        self._raise_on_reset = raise_on_reset

    def list_flags(self) -> List[Dict[str, Any]]:
        result = []
        for defn in FLAG_DEFINITIONS:
            name = defn["name"]
            if name in self._overrides:
                enabled = self._overrides[name]
                source = "runtime"
            else:
                enabled = bool(defn["default"])
                source = "config"
            result.append(
                {
                    "name": name,
                    "enabled": enabled,
                    "description": defn["description"],
                    "category": defn["category"],
                    "requires_restart": defn["requires_restart"],
                    "source": source,
                }
            )
        return result

    def set_flag(self, name: str, enabled: bool, updated_by: str = "api") -> None:
        if self._raise_on_set is not None:
            raise self._raise_on_set
        self._overrides[name] = enabled

    def reset_flag(self, name: str) -> None:
        if self._raise_on_reset is not None:
            raise self._raise_on_reset
        self._overrides.pop(name, None)


# ---------------------------------------------------------------------------
# App / client fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def app() -> FastAPI:
    _app = FastAPI()
    _app.add_middleware(APIKeyMiddleware)
    _app.include_router(flags_api_router, prefix="/flags", tags=["feature-flags"])
    return _app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture(autouse=True)
def _reset_flags_singleton():
    """Ensure routers.flags_router._flags starts/ends as None (mirrors real boot state)."""
    original = flags_router._flags
    flags_router.set_flags(None)  # type: ignore[arg-type]
    yield
    flags_router._flags = original


def _inject(fake: _FakeFeatureFlags) -> None:
    flags_router.set_flags(fake)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# GET /flags/ — list all flags
# ---------------------------------------------------------------------------


def test_list_flags_success(client: TestClient) -> None:
    _inject(_FakeFeatureFlags())
    resp = client.get("/flags/", headers=_VALID_HEADERS)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == len(FLAG_DEFINITIONS)
    names = {f["name"] for f in data}
    assert _KNOWN_FLAG in names
    for flag in data:
        assert flag["source"] in ("config", "runtime")


def test_list_flags_reflects_runtime_override(client: TestClient) -> None:
    _inject(_FakeFeatureFlags(overrides={_KNOWN_FLAG: True}))
    resp = client.get("/flags/", headers=_VALID_HEADERS)
    assert resp.status_code == 200
    data = {f["name"]: f for f in resp.json()}
    assert data[_KNOWN_FLAG]["enabled"] is True
    assert data[_KNOWN_FLAG]["source"] == "runtime"


def test_list_flags_not_initialised_returns_503(client: TestClient) -> None:
    """FeatureFlags singleton not injected — _get_flags() must raise 503."""
    resp = client.get("/flags/", headers=_VALID_HEADERS)
    assert resp.status_code == 503, resp.text
    assert "not initialised" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# GET /flags/{name} — single flag
# ---------------------------------------------------------------------------


def test_get_flag_success(client: TestClient) -> None:
    _inject(_FakeFeatureFlags())
    resp = client.get(f"/flags/{_KNOWN_FLAG}", headers=_VALID_HEADERS)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["name"] == _KNOWN_FLAG


def test_get_flag_case_insensitive(client: TestClient) -> None:
    """Lower-case flag name in URL must still resolve (router upper()s it)."""
    _inject(_FakeFeatureFlags())
    resp = client.get(f"/flags/{_KNOWN_FLAG.lower()}", headers=_VALID_HEADERS)
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == _KNOWN_FLAG


def test_get_flag_unknown_name_returns_404(client: TestClient) -> None:
    _inject(_FakeFeatureFlags())
    resp = client.get("/flags/NOT_A_REAL_FLAG", headers=_VALID_HEADERS)
    assert resp.status_code == 404, resp.text
    assert "Unknown feature flag" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# PUT /flags/{name} — set runtime override
# ---------------------------------------------------------------------------


def test_set_flag_success_no_restart(client: TestClient) -> None:
    _inject(_FakeFeatureFlags())
    resp = client.put(
        f"/flags/{_NO_RESTART_FLAG}", json={"enabled": True}, headers=_VALID_HEADERS
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["name"] == _NO_RESTART_FLAG
    assert data["enabled"] is True
    assert data["source"] == "runtime"
    assert data["restart_required"] is False
    assert "active immediately" in data["message"]


def test_set_flag_success_requires_restart_warns(client: TestClient) -> None:
    _inject(_FakeFeatureFlags())
    resp = client.put(f"/flags/{_RESTART_FLAG}", json={"enabled": True}, headers=_VALID_HEADERS)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["restart_required"] is True
    assert "restart the engine" in data["message"]


def test_set_flag_unknown_name_returns_404(client: TestClient) -> None:
    _inject(_FakeFeatureFlags())
    resp = client.put("/flags/NOT_A_REAL_FLAG", json={"enabled": True}, headers=_VALID_HEADERS)
    assert resp.status_code == 404, resp.text


def test_set_flag_missing_body_field_returns_422(client: TestClient) -> None:
    """Bad input: PUT body without the required 'enabled' field."""
    _inject(_FakeFeatureFlags())
    resp = client.put(f"/flags/{_KNOWN_FLAG}", json={}, headers=_VALID_HEADERS)
    assert resp.status_code == 422, resp.text


def test_set_flag_dependency_value_error_returns_422(client: TestClient) -> None:
    """Mocked-dependency-failure path: FeatureFlags.set_flag() raises ValueError."""
    _inject(_FakeFeatureFlags(raise_on_set=ValueError("boom from db layer")))
    resp = client.put(f"/flags/{_KNOWN_FLAG}", json={"enabled": True}, headers=_VALID_HEADERS)
    assert resp.status_code == 422, resp.text
    assert "boom from db layer" in resp.json()["detail"]


def test_set_flag_not_initialised_returns_503(client: TestClient) -> None:
    resp = client.put(f"/flags/{_KNOWN_FLAG}", json={"enabled": True}, headers=_VALID_HEADERS)
    assert resp.status_code == 503, resp.text


# ---------------------------------------------------------------------------
# DELETE /flags/{name} — reset to config default
# ---------------------------------------------------------------------------


def test_reset_flag_success(client: TestClient) -> None:
    _inject(_FakeFeatureFlags(overrides={_KNOWN_FLAG: True}))
    resp = client.delete(f"/flags/{_KNOWN_FLAG}", headers=_VALID_HEADERS)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["name"] == _KNOWN_FLAG
    assert data["source"] == "config"


def test_reset_flag_unknown_name_returns_404(client: TestClient) -> None:
    _inject(_FakeFeatureFlags())
    resp = client.delete("/flags/NOT_A_REAL_FLAG", headers=_VALID_HEADERS)
    assert resp.status_code == 404, resp.text


def test_reset_flag_dependency_value_error_returns_422(client: TestClient) -> None:
    """Mocked-dependency-failure path: FeatureFlags.reset_flag() raises ValueError."""
    _inject(_FakeFeatureFlags(raise_on_reset=ValueError("boom from db layer")))
    resp = client.delete(f"/flags/{_KNOWN_FLAG}", headers=_VALID_HEADERS)
    assert resp.status_code == 422, resp.text


# ---------------------------------------------------------------------------
# Auth tests
# ---------------------------------------------------------------------------


def test_list_flags_auth_required(client: TestClient) -> None:
    _inject(_FakeFeatureFlags())
    resp = client.get("/flags/")
    assert resp.status_code == 401


def test_get_flag_auth_required(client: TestClient) -> None:
    _inject(_FakeFeatureFlags())
    resp = client.get(f"/flags/{_KNOWN_FLAG}")
    assert resp.status_code == 401


def test_set_flag_bad_key_returns_401(client: TestClient) -> None:
    _inject(_FakeFeatureFlags())
    resp = client.put(f"/flags/{_KNOWN_FLAG}", json={"enabled": True}, headers=_BAD_HEADERS)
    assert resp.status_code == 401


def test_reset_flag_auth_required(client: TestClient) -> None:
    _inject(_FakeFeatureFlags())
    resp = client.delete(f"/flags/{_KNOWN_FLAG}")
    assert resp.status_code == 401
