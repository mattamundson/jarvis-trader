"""
Contract tests — portfolio paper + safety JSON shapes using real tracker/safety (no mocked main).

Run: pytest engine/tests/test_api_contract_minimal.py -v
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from slowapi.errors import RateLimitExceeded

from middleware.rate_limit import limiter, rate_limit_exception_handler
from portfolio.tracker import PortfolioTracker
from risk.safety_layer import SafetyLayer
from routers import portfolio_router as pr_mod
from routers import safety_router as sr_mod


@pytest.fixture()
def contract_client():
    old_pt, old_db = pr_mod.paper_tracker, pr_mod.db_manager
    old_sl, old_lt = sr_mod._safety_layer, sr_mod._loss_tracker

    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_exception_handler)

    tmp = Path(tempfile.mkdtemp()) / "audit.jsonl"
    tracker = PortfolioTracker(store_path=tmp)
    pr_mod.inject_dependencies(tracker, None)

    cfg = SimpleNamespace(MAX_DAILY_LOSS_PCT=0.02, MAX_DRAWDOWN_PCT=0.10)
    layer = SafetyLayer(cfg)

    class _LT:
        def get_consecutive_losses(self):
            return 0

    sr_mod.inject_dependencies(layer, _LT())

    app.include_router(pr_mod.router, prefix="/portfolio")
    app.include_router(sr_mod.router)

    client = TestClient(app)
    yield client

    pr_mod.inject_dependencies(old_pt, old_db)
    sr_mod.inject_dependencies(old_sl, old_lt)


def test_paper_positions_shape(contract_client: TestClient) -> None:
    r = contract_client.get("/portfolio/paper/positions")
    assert r.status_code == 200
    body = r.json()
    assert "positions" in body and "count" in body
    assert isinstance(body["positions"], list)


def test_history_trades_list(contract_client: TestClient) -> None:
    r = contract_client.get("/portfolio/history/trades")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_safety_status_shape(contract_client: TestClient) -> None:
    r = contract_client.get("/safety/status")
    assert r.status_code == 200
    body = r.json()
    for key in ("kill_switch_active", "daily_pnl", "daily_limit_breached", "drawdown_breached"):
        assert key in body


def test_circuit_breakers_shape(contract_client: TestClient) -> None:
    r = contract_client.get("/safety/circuit-breakers")
    assert r.status_code == 200
    body = r.json()
    assert "all_clear" in body
