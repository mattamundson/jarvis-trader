"""Test POST /portfolio/paper/admin/close-stale endpoint."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from portfolio.tracker import PortfolioTracker
from routers import portfolio_router as pr_mod


@pytest.fixture()
def stale_positions_client():
    """Set up test client with PortfolioTracker."""
    old_pt, old_db = pr_mod.paper_tracker, pr_mod.db_manager

    app = FastAPI()
    tmp = Path(tempfile.mkdtemp()) / "paper_trade_audit.jsonl"
    tracker = PortfolioTracker(store_path=tmp)
    pr_mod.inject_dependencies(tracker, None)

    app.include_router(pr_mod.router, prefix="/portfolio")
    with TestClient(app) as client:
        yield client

    pr_mod.inject_dependencies(old_pt, old_db)


def test_close_stale_returns_zero_when_no_stale_positions(
    stale_positions_client: TestClient,
) -> None:
    """When no MES @ 5800.0 exists, closed_count should be 0."""
    r = stale_positions_client.post("/portfolio/paper/admin/close-stale")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("status") == "success"
    assert body.get("closed_count") == 0


def test_close_stale_closes_matching_positions(
    stale_positions_client: TestClient,
) -> None:
    """When MES @ 5800.0 exists, close-stale should close it."""
    tracker = pr_mod.paper_tracker
    if not tracker:
        pytest.skip("Tracker not initialized")

    trade_id = tracker.open_trade(
        symbol="MES",
        action="buy",
        quantity=1.0,
        price=5800.0,
        notes="test_stale_position",
    )

    r = stale_positions_client.post("/portfolio/paper/admin/close-stale")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("status") == "success"
    assert body.get("closed_count") == 1

    open_positions = tracker.get_open_positions()
    assert len(open_positions) == 0


def test_close_stale_ignores_different_entry_price(
    stale_positions_client: TestClient,
) -> None:
    """Positions at different entry prices should not be closed."""
    tracker = pr_mod.paper_tracker
    if not tracker:
        pytest.skip("Tracker not initialized")

    trade_id = tracker.open_trade(
        symbol="MES",
        action="buy",
        quantity=1.0,
        price=5810.0,
        notes="test_non_stale_position",
    )

    r = stale_positions_client.post("/portfolio/paper/admin/close-stale")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("closed_count") == 0

    open_positions = tracker.get_open_positions()
    assert len(open_positions) == 1


def test_close_stale_ignores_different_symbol(
    stale_positions_client: TestClient,
) -> None:
    """Non-MES positions should not be closed."""
    tracker = pr_mod.paper_tracker
    if not tracker:
        pytest.skip("Tracker not initialized")

    trade_id = tracker.open_trade(
        symbol="MCL",
        action="buy",
        quantity=1.0,
        price=5800.0,
        notes="test_mcl_position",
    )

    r = stale_positions_client.post("/portfolio/paper/admin/close-stale")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("closed_count") == 0

    open_positions = tracker.get_open_positions()
    assert len(open_positions) == 1
