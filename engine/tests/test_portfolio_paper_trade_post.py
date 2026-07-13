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
from risk.safety_layer import RiskCheckResult
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


def test_paper_trade_open_blocked_by_aggregated_contract_limit() -> None:
    """2026-07-13 risk-aggregation fix: the direct-open sync path previously
    never called safety_layer's contract-limit check at all. Prove it now
    does, and that a rejection from check_contract_limits() actually blocks
    the open (409), not just gets computed and ignored."""
    old_pt, old_db, old_safety = pr_mod.paper_tracker, pr_mod.db_manager, pr_mod._safety_layer

    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_exception_handler)

    tmp = Path(tempfile.mkdtemp()) / "paper_trade_contract_limit.jsonl"
    tracker = PortfolioTracker(store_path=tmp)
    safety = MagicMock()
    safety.get_status.return_value = {"is_killed": False, "kill_switch_active": False}
    safety.check_contract_limits.return_value = RiskCheckResult(
        approved=False,
        rejection_reason="Requested 2 contracts exceeds max 2 (combined with 1 already open on MES)",
    )
    pr_mod.inject_dependencies(tracker, None, None, safety)

    app.include_router(pr_mod.router, prefix="/portfolio")
    client = TestClient(app)
    try:
        r = client.post(
            "/portfolio/paper/trade",
            json={
                "action": "open",
                "symbol": "MES",
                "side": "long",
                "quantity": 2,
                "entry_price": 5823.50,
            },
        )
    finally:
        pr_mod.inject_dependencies(old_pt, old_db, None, old_safety)

    assert r.status_code == 409, r.text
    assert "combined with 1 already open" in r.text
    safety.check_contract_limits.assert_called_once()


def test_paper_trade_close_not_gated_by_contract_limit() -> None:
    """Close operations pass quantity=0 through _guard_direct_paper_open and
    must never be blocked by the contract-limit check (only open orders
    represent new exposure). check_contract_limits is configured to always
    reject here -- if the close path consulted it, this would 409."""
    old_pt, old_db, old_safety = pr_mod.paper_tracker, pr_mod.db_manager, pr_mod._safety_layer

    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_exception_handler)

    tmp = Path(tempfile.mkdtemp()) / "paper_trade_close_contract_limit.jsonl"
    tracker = PortfolioTracker(store_path=tmp)
    safety = MagicMock()
    safety.get_status.return_value = {"is_killed": False, "kill_switch_active": False}
    safety.check_contract_limits.return_value = RiskCheckResult(
        approved=False, rejection_reason="should never be consulted for a close"
    )
    pr_mod.inject_dependencies(tracker, None, None, safety)

    app.include_router(pr_mod.router, prefix="/portfolio")
    client = TestClient(app)
    try:
        close_r = client.post(
            "/portfolio/paper/trade",
            json={"action": "close", "symbol": "MCL", "exit_price": 73.0},
        )
    finally:
        pr_mod.inject_dependencies(old_pt, old_db, None, old_safety)

    # No open position exists for MCL, so this may 400/404 for "no position
    # to close" reasons -- the point is it must NOT be a 409 carrying the
    # always-reject contract-limit message, and the mock must never be hit.
    assert "should never be consulted" not in close_r.text
    safety.check_contract_limits.assert_not_called()
