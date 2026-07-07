"""POST /portfolio/paper/trade contract (open) — in-memory tracker, no IB."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from slowapi.errors import RateLimitExceeded

from middleware.rate_limit import limiter, rate_limit_exception_handler
from portfolio.tracker import PortfolioTracker
from routers import portfolio_router as pr_mod


@pytest.fixture()
def paper_trade_client():
    old_pt, old_db, old_safety = pr_mod.paper_tracker, pr_mod.db_manager, pr_mod._safety_layer

    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_exception_handler)

    tmp = Path(tempfile.mkdtemp()) / "paper_trade_audit.jsonl"
    tracker = PortfolioTracker(store_path=tmp)
    safety = MagicMock()
    safety.get_status.return_value = {"kill_switch_active": False}
    pr_mod.inject_dependencies(tracker, None, None, safety)

    app.include_router(pr_mod.router, prefix="/portfolio")
    client = TestClient(app)
    yield client

    pr_mod.inject_dependencies(old_pt, old_db, None, old_safety)


def test_paper_trade_open_returns_trade_id(paper_trade_client: TestClient) -> None:
    r = paper_trade_client.post(
        "/portfolio/paper/trade",
        json={
            "action": "open",
            "symbol": "MES",
            "side": "long",
            "quantity": 1,
            "entry_price": 5823.50,
            "notes": "contract_test",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("status") == "open"
    assert "trade_id" in body and body["trade_id"]
    assert body.get("symbol") == "MES"


def test_paper_trade_open_blocked_by_kill_switch() -> None:
    old_pt, old_db, old_safety = pr_mod.paper_tracker, pr_mod.db_manager, pr_mod._safety_layer

    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_exception_handler)

    tmp = Path(tempfile.mkdtemp()) / "paper_trade_blocked.jsonl"
    tracker = PortfolioTracker(store_path=tmp)
    safety = MagicMock()
    # router reads is_killed (safety_layer dual-key contract); keep kill_switch_active too
    safety.get_status.return_value = {"is_killed": True, "kill_switch_active": True}
    pr_mod.inject_dependencies(tracker, None, None, safety)

    app.include_router(pr_mod.router, prefix="/portfolio")
    client = TestClient(app)
    try:
        r = client.post(
            "/portfolio/paper/trade",
            json={
                "action": "open",
                "symbol": "MCL",
                "side": "long",
                "quantity": 1,
                "entry_price": 72.5,
            },
        )
    finally:
        pr_mod.inject_dependencies(old_pt, old_db, None, old_safety)

    assert r.status_code == 409, r.text
