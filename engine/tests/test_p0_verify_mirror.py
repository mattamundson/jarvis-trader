"""
Mirror the HTTP paths exercised by scripts/verify_p0_paper_ib.py using an in-process app.

Keeps P0 checks honest in CI without a live engine or httpx to a remote host.
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from slowapi.errors import RateLimitExceeded

from middleware.rate_limit import limiter, rate_limit_exception_handler
from portfolio.tracker import PortfolioTracker
from routers import health_router as hr_mod
from routers import portfolio_router as pr_mod
from routers import safety_router as sr_mod


@pytest.fixture()
def p0_mirror_client() -> TestClient:
    limiter.reset()
    old_pt, old_db = pr_mod.paper_tracker, pr_mod.db_manager
    old_sl, old_lt = sr_mod._safety_layer, sr_mod._loss_tracker
    hr_snap = (
        hr_mod._start_time,
        hr_mod.data_manager,
        hr_mod.safety_layer,
        hr_mod.db_manager,
        hr_mod.paper_tracker,
        hr_mod.pnl_monitor,
        hr_mod.trading_pipeline,
    )

    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_exception_handler)

    tmp = Path(tempfile.mkdtemp()) / "p0_mirror.jsonl"
    tracker = PortfolioTracker(store_path=tmp)
    pr_mod.inject_dependencies(tracker, None)

    cfg = SimpleNamespace(MAX_DAILY_LOSS_PCT=0.02, MAX_DRAWDOWN_PCT=0.10)
    from risk.safety_layer import SafetyLayer

    layer = SafetyLayer(cfg)

    class _LT:
        def get_consecutive_losses(self):
            return 0

    sr_mod.inject_dependencies(layer, _LT())
    hr_mod.inject_dependencies(
        datetime.now(timezone.utc),
        None,
        layer,
        None,
        tracker,
        None,
        None,
    )

    app.include_router(hr_mod.router)
    app.include_router(pr_mod.router, prefix="/portfolio")
    app.include_router(sr_mod.router)

    client = TestClient(app)
    yield client

    pr_mod.inject_dependencies(old_pt, old_db)
    sr_mod.inject_dependencies(old_sl, old_lt)
    hr_mod.inject_dependencies(*hr_snap)


def test_public_health(p0_mirror_client: TestClient) -> None:
    r = p0_mirror_client.get("/health")
    assert r.status_code == 200


def test_full_health_p0_tolerance(p0_mirror_client: TestClient) -> None:
    r = p0_mirror_client.get("/health/full")
    assert r.status_code in (200, 503)


def test_authenticated_style_routes_match_p0_script(p0_mirror_client: TestClient) -> None:
    for path in (
        "/health/full",
        "/safety/status",
        "/safety/circuit-breakers",
        "/portfolio/paper/positions",
    ):
        r = p0_mirror_client.get(path)
        assert r.status_code in (200, 503), f"{path} -> {r.status_code} {r.text}"
