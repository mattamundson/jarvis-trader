"""POST /portfolio/paper/trade contract (open) — in-memory tracker, no IB."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from slowapi.errors import RateLimitExceeded

from middleware.rate_limit import limiter, rate_limit_exception_handler
from portfolio.tracker import PortfolioTracker
from routers import portfolio_router as pr_mod


@pytest.fixture()
def paper_trade_client():
    old_pt, old_db = pr_mod.paper_tracker, pr_mod.db_manager

    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_exception_handler)

    tmp = Path(tempfile.mkdtemp()) / "paper_trade_audit.jsonl"
    tracker = PortfolioTracker(store_path=tmp)
    pr_mod.inject_dependencies(tracker, None)

    app.include_router(pr_mod.router, prefix="/portfolio")
    client = TestClient(app)
    yield client

    pr_mod.inject_dependencies(old_pt, old_db)


def test_paper_trade_open_returns_trade_id(paper_trade_client: TestClient) -> None:
    r = paper_trade_client.post(
        "/portfolio/paper/trade",
        json={
            "action": "open",
            "symbol": "MCL",
            "side": "long",
            "quantity": 1,
            "entry_price": 72.5,
            "notes": "contract_test",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("status") == "open"
    assert "trade_id" in body and body["trade_id"]
    assert body.get("symbol") == "MCL"
