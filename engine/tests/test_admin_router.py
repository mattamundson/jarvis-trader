"""
Tests for engine/routers/admin_router.py

Covered:
  - GET /admin/feature-flags returns current flag state (both False by default)
  - POST /admin/feature-flags enables ENABLE_KRONOS; subsequent GET reflects change
  - POST /admin/feature-flags with only enable_research_agent does NOT touch ENABLE_KRONOS
  - POST /admin/feature-flags without X-API-Key returns 401
  - is_kronos_enabled() / is_research_agent_enabled() see the updated env vars

Design:
  - Uses a minimal FastAPI app wrapping only admin_router (no full main.py import).
  - APIKeyMiddleware is added manually so auth tests are realistic.
  - Fixture cleans os.environ ENABLE_KRONOS + ENABLE_RESEARCH_AGENT before/after each test.
  - Never touches engine/.env or any live endpoint.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Path bootstrap — add engine root so routers, agents, config, middleware
# are all importable without a full main.py import.
# ---------------------------------------------------------------------------

_ENGINE_ROOT = str(Path(__file__).parent.parent)
if _ENGINE_ROOT not in sys.path:
    sys.path.insert(0, _ENGINE_ROOT)

# ---------------------------------------------------------------------------
# Load .env so config.settings (used by APIKeyMiddleware) has API_KEY
# ---------------------------------------------------------------------------


def _load_env() -> None:
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and "=" in line and not line.startswith("#"):
                key, value = line.split("=", 1)
                os.environ.setdefault(key, value)


_load_env()

# ---------------------------------------------------------------------------
# Build a minimal FastAPI app with auth middleware + admin_router
# ---------------------------------------------------------------------------

from config import settings  # noqa: E402 — must follow _load_env()
from middleware.api_key_middleware import APIKeyMiddleware  # noqa: E402
from routers.admin_router import router as admin_router  # noqa: E402

_app = FastAPI()
_app.add_middleware(APIKeyMiddleware)
_app.include_router(admin_router)

client = TestClient(_app, raise_server_exceptions=True)

_VALID_HEADERS = {"X-API-Key": settings.API_KEY}
_BAD_HEADERS = {"X-API-Key": "wrong-key"}

# ---------------------------------------------------------------------------
# Fixture — clean env before/after every test
# ---------------------------------------------------------------------------

_MANAGED_FLAGS = ("ENABLE_KRONOS", "ENABLE_RESEARCH_AGENT")


@pytest.fixture(autouse=True)
def clean_env_flags():
    """Remove both managed env vars before the test; restore original state after."""
    # Capture originals (may be absent)
    originals = {k: os.environ.pop(k, None) for k in _MANAGED_FLAGS}
    yield
    # Restore: re-set if they existed, delete if they didn't
    for k, v in originals.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


# ---------------------------------------------------------------------------
# GET tests
# ---------------------------------------------------------------------------


def test_get_feature_flags_default() -> None:
    """GET /admin/feature-flags returns both flags as False when env vars are absent."""
    resp = client.get("/admin/feature-flags", headers=_VALID_HEADERS)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data == {"enable_kronos": False, "enable_research_agent": False}


def test_get_feature_flags_reflects_env() -> None:
    """GET /admin/feature-flags reflects a flag pre-set in os.environ."""
    os.environ["ENABLE_KRONOS"] = "1"
    resp = client.get("/admin/feature-flags", headers=_VALID_HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data["enable_kronos"] is True
    assert data["enable_research_agent"] is False


# ---------------------------------------------------------------------------
# POST tests
# ---------------------------------------------------------------------------


def test_post_enable_kronos() -> None:
    """POST enable_kronos=True; GET reflects True; is_kronos_enabled() returns True."""
    from agents.kronos_classifier import is_kronos_enabled

    resp = client.post(
        "/admin/feature-flags",
        json={"enable_kronos": True},
        headers=_VALID_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["enable_kronos"] is True
    assert data["enable_research_agent"] is False

    # Verify GET reflects the change
    get_resp = client.get("/admin/feature-flags", headers=_VALID_HEADERS)
    assert get_resp.json()["enable_kronos"] is True

    # Verify helper reads os.environ fresh
    assert is_kronos_enabled() is True


def test_post_enable_research_agent() -> None:
    """POST enable_research_agent=True; is_research_agent_enabled() returns True."""
    from agents.research_agent import is_research_agent_enabled

    resp = client.post(
        "/admin/feature-flags",
        json={"enable_research_agent": True},
        headers=_VALID_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["enable_research_agent"] is True
    assert is_research_agent_enabled() is True


def test_post_partial_update() -> None:
    """POST with only enable_research_agent does NOT change ENABLE_KRONOS."""
    # Pre-set Kronos to 1 explicitly
    os.environ["ENABLE_KRONOS"] = "1"

    resp = client.post(
        "/admin/feature-flags",
        json={"enable_research_agent": True},
        headers=_VALID_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    # Kronos must be unchanged (True, from pre-set env)
    assert data["enable_kronos"] is True, "Partial update must not change ENABLE_KRONOS"
    assert data["enable_research_agent"] is True


def test_post_disable_flag() -> None:
    """POST enable_kronos=False after it was enabled sets it back to False."""
    from agents.kronos_classifier import is_kronos_enabled

    # Enable first
    os.environ["ENABLE_KRONOS"] = "1"
    assert is_kronos_enabled() is True

    resp = client.post(
        "/admin/feature-flags",
        json={"enable_kronos": False},
        headers=_VALID_HEADERS,
    )
    assert resp.status_code == 200
    assert resp.json()["enable_kronos"] is False
    assert is_kronos_enabled() is False


def test_post_empty_body_is_noop() -> None:
    """POST with an empty body (no fields) returns current state unchanged."""
    os.environ["ENABLE_KRONOS"] = "1"

    resp = client.post(
        "/admin/feature-flags",
        json={},
        headers=_VALID_HEADERS,
    )
    assert resp.status_code == 200
    data = resp.json()
    # Both should be what they were before the empty POST
    assert data["enable_kronos"] is True
    assert data["enable_research_agent"] is False


# ---------------------------------------------------------------------------
# Auth tests
# ---------------------------------------------------------------------------


def test_get_auth_required() -> None:
    """GET /admin/feature-flags without X-API-Key returns 401."""
    resp = client.get("/admin/feature-flags")
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}"


def test_post_auth_required() -> None:
    """POST /admin/feature-flags without X-API-Key returns 401."""
    resp = client.post("/admin/feature-flags", json={"enable_kronos": True})
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}"


def test_post_invalid_key_returns_401() -> None:
    """POST /admin/feature-flags with wrong X-API-Key returns 401."""
    resp = client.post(
        "/admin/feature-flags",
        json={"enable_kronos": True},
        headers=_BAD_HEADERS,
    )
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}"


def test_get_invalid_key_returns_401() -> None:
    """GET /admin/feature-flags with wrong X-API-Key returns 401."""
    resp = client.get("/admin/feature-flags", headers=_BAD_HEADERS)
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}"
