"""Regression (T2-19): GET /system/data-integrity must surface a hard backend
failure (e.g. Redis unreachable) as a genuine failure, distinguishable from
"Redis answered and there are honestly zero sources reported".

Before this fix, `get_data_integrity()` caught ANY exception and returned
HTTP 200 with `{"error": str(e), "sources": [], "count": 0}`. The dashboard's
`DataIntegrityResponse` type has no `error` field and `fetchEngine()` only
throws on a non-2xx status, so the diagnostic information was silently
dropped — the /data-integrity page read the response as a true empty state
("No data sources reported by the engine.") instead of a failure. These
tests pin that a hard failure now returns 503 (matching the /health
endpoint's existing failure contract), while a genuinely empty Redis
(reachable, zero matching keys) still returns 200 with count=0.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import health_router


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(health_router.router)
    return TestClient(app)


def test_redis_unreachable_returns_503_not_a_fake_empty_state():
    """A hard Redis failure must not look like an honest empty state."""
    fake_redis = AsyncMock()
    fake_redis.keys.side_effect = ConnectionError("Redis unreachable at localhost:6379")

    with patch("redis.asyncio.from_url", return_value=fake_redis):
        resp = _client().get("/system/data-integrity")

    assert resp.status_code == 503
    body = resp.json()
    # Distinguishable from the true-empty-state shape: no bare count=0/
    # sources=[] pretending to be a clean read. FastAPI's HTTPException body
    # carries `detail`, which the dashboard's error path already renders.
    assert "detail" in body
    assert "Redis unreachable" in body["detail"] or "unreachable" in body["detail"].lower()


def test_redis_reachable_with_zero_sources_is_a_real_200_empty_state():
    """A genuinely empty Redis (no datasource keys) is NOT a failure."""
    fake_redis = AsyncMock()
    fake_redis.keys.return_value = []
    fake_redis.close.return_value = None

    with patch("redis.asyncio.from_url", return_value=fake_redis):
        resp = _client().get("/system/data-integrity")

    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 0
    assert body["sources"] == []
    assert "error" not in body


def test_from_url_raising_is_also_a_hard_failure():
    """Connection setup itself failing (not just .keys()) must also 503."""
    with patch("redis.asyncio.from_url", side_effect=ConnectionError("no connection")):
        resp = _client().get("/system/data-integrity")

    assert resp.status_code == 503
    assert "detail" in resp.json()


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
