"""Tests for GET /portfolio/paper/positions/unrealized endpoint."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


class FakePaperTracker:
    def __init__(self, positions=None):
        self._positions = positions or []

    def get_open_positions(self):
        return self._positions


class FakeDataManager:
    async def get_current_price(self, symbol: str):
        prices = {"MCL": 73.0, "MNQ": 17480.0}
        return prices.get(symbol)


def _make_client(tracker, data_manager):
    """Create a TestClient with the portfolio router mounted under /portfolio."""
    import routers.portfolio_router as pr

    pr.paper_tracker = tracker
    pr._data_manager = data_manager

    app = FastAPI()
    app.include_router(pr.router, prefix="/portfolio")
    return TestClient(app)


@pytest.fixture
def client_with_positions():
    """TestClient with one open MCL long position."""
    import routers.portfolio_router as pr

    original_pt = pr.paper_tracker
    original_dm = pr._data_manager

    tc = _make_client(
        FakePaperTracker(
            [
                {
                    "trade_id": "test-001",
                    "symbol": "MCL",
                    "action": "buy",
                    "quantity": 1,
                    "entry_price": 72.0,
                    "stop_loss": None,
                    "take_profit": None,
                    "entry_time": "2026-04-04T09:00:00",
                }
            ]
        ),
        FakeDataManager(),
    )
    yield tc

    pr.paper_tracker = original_pt
    pr._data_manager = original_dm


@pytest.fixture
def client_empty():
    """TestClient with no positions."""
    import routers.portfolio_router as pr

    original_pt = pr.paper_tracker
    original_dm = pr._data_manager

    tc = _make_client(FakePaperTracker([]), None)
    yield tc

    pr.paper_tracker = original_pt
    pr._data_manager = original_dm


def test_unrealized_empty_positions(client_empty):
    """Returns 200 with empty list when no positions."""
    resp = client_empty.get("/portfolio/paper/positions/unrealized")
    assert resp.status_code == 200
    assert resp.json() == []


def test_unrealized_long_mcl(client_with_positions):
    """LONG MCL: current=73, entry=72, qty=1 -> unrealized_pnl=100.0"""
    resp = client_with_positions.get("/portfolio/paper/positions/unrealized")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["unrealized_pnl"] == pytest.approx(100.0, abs=0.01)
    assert data[0]["direction"] == "LONG"


def test_unrealized_short_mnq():
    """SHORT MNQ: current=17480, entry=17500, qty=1 -> unrealized_pnl=40.0"""
    import routers.portfolio_router as pr

    original_pt = pr.paper_tracker
    original_dm = pr._data_manager

    tc = _make_client(
        FakePaperTracker(
            [
                {
                    "trade_id": "test-002",
                    "symbol": "MNQ",
                    "action": "sell",
                    "quantity": 1,
                    "entry_price": 17500.0,
                    "stop_loss": None,
                    "take_profit": None,
                    "entry_time": "2026-04-04T09:00:00",
                }
            ]
        ),
        FakeDataManager(),
    )

    resp = tc.get("/portfolio/paper/positions/unrealized")
    assert resp.status_code == 200
    data = resp.json()
    # (17500 - 17480) * 2.0 * 1 = 40.0
    assert data[0]["unrealized_pnl"] == pytest.approx(40.0, abs=0.01)
    assert data[0]["direction"] == "SHORT"

    pr.paper_tracker = original_pt
    pr._data_manager = original_dm


def test_unrealized_pnl_none_when_no_data_manager():
    """Returns None unrealized_pnl when data_manager not injected."""
    import routers.portfolio_router as pr

    original_pt = pr.paper_tracker
    original_dm = pr._data_manager

    tc = _make_client(
        FakePaperTracker(
            [
                {
                    "trade_id": "test-003",
                    "symbol": "MCL",
                    "action": "buy",
                    "quantity": 1,
                    "entry_price": 72.0,
                    "stop_loss": None,
                    "take_profit": None,
                    "entry_time": "2026-04-04T09:00:00",
                }
            ]
        ),
        None,  # no data manager
    )

    resp = tc.get("/portfolio/paper/positions/unrealized")
    assert resp.status_code == 200
    data = resp.json()
    assert data[0]["unrealized_pnl"] is None
    assert data[0]["current_price"] is None

    pr.paper_tracker = original_pt
    pr._data_manager = original_dm


def test_stop_distance_computed():
    """stop_distance and target_distance computed correctly."""
    import routers.portfolio_router as pr

    original_pt = pr.paper_tracker
    original_dm = pr._data_manager

    tc = _make_client(
        FakePaperTracker(
            [
                {
                    "trade_id": "test-004",
                    "symbol": "MCL",
                    "action": "buy",
                    "quantity": 1,
                    "entry_price": 72.0,
                    "stop_loss": 70.0,
                    "take_profit": 75.0,
                    "entry_time": "2026-04-04T09:00:00",
                }
            ]
        ),
        FakeDataManager(),  # MCL -> 73.0
    )

    resp = tc.get("/portfolio/paper/positions/unrealized")
    assert resp.status_code == 200
    data = resp.json()
    assert data[0]["stop_distance"] == pytest.approx(3.0, abs=0.01)  # |73-70|
    assert data[0]["target_distance"] == pytest.approx(2.0, abs=0.01)  # |75-73|

    pr.paper_tracker = original_pt
    pr._data_manager = original_dm
