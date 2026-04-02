"""
Cold / degraded startup: routers should return explicit 503 (or structured stubs),
not opaque 500s, when optional subsystems are not injected.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from slowapi.errors import RateLimitExceeded

from middleware.rate_limit import limiter, rate_limit_exception_handler
from routers import safety_router as sr_mod


def test_safety_status_without_dependencies_returns_503() -> None:
    """Before lifespan injects SafetyLayer, /safety/status must be 503 — not 500."""
    # Shared in-memory limiter: earlier tests may exhaust /safety/status (10/min).
    limiter.reset()
    old_sl, old_lt = sr_mod._safety_layer, sr_mod._loss_tracker
    sr_mod.inject_dependencies(None, None)
    try:
        app = FastAPI()
        app.state.limiter = limiter
        app.add_exception_handler(RateLimitExceeded, rate_limit_exception_handler)
        app.include_router(sr_mod.router)
        client = TestClient(app)
        r = client.get("/safety/status")
        assert r.status_code == 503
        body = r.json()
        assert "detail" in body
    finally:
        sr_mod.inject_dependencies(old_sl, old_lt)
