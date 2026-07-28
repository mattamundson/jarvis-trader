"""
Contract tests — portfolio paper + safety JSON shapes using real tracker/safety (no mocked main).

Run: pytest engine/tests/test_api_contract_minimal.py -v
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
from risk.safety_layer import SafetyLayer
from routers import health_router as hr_mod
from routers import portfolio_router as pr_mod
from routers import safety_router as sr_mod


@pytest.fixture()
def contract_client():
    # Shared singleton limiter — other test modules exhaust buckets before this file runs.
    limiter.reset()

    old_pt, old_db = pr_mod.paper_tracker, pr_mod.db_manager
    old_sl, old_lt = sr_mod._safety_layer, sr_mod._loss_tracker
    old_hr = (
        hr_mod._start_time,
        hr_mod.data_manager,
        hr_mod.safety_layer,
        hr_mod.db_manager,
        hr_mod.paper_tracker,
        hr_mod.pnl_monitor,
        hr_mod.trading_pipeline,
        hr_mod.schwab_connector,
    )

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

    fake_ib = SimpleNamespace(is_connected=False)
    hr_mod.inject_dependencies(
        datetime.now(timezone.utc),
        SimpleNamespace(ibkr=fake_ib),
        layer,
        None,
        tracker,
        None,
        None,
        None,
    )

    app.include_router(pr_mod.router, prefix="/portfolio")
    app.include_router(sr_mod.router)
    app.include_router(hr_mod.router)

    client = TestClient(app)
    yield client

    pr_mod.inject_dependencies(old_pt, old_db)
    sr_mod.inject_dependencies(old_sl, old_lt)
    hr_mod.inject_dependencies(*old_hr)


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


def test_health_contract_shape(contract_client: TestClient) -> None:
    r = contract_client.get("/health")
    assert r.status_code == 200
    body = r.json()
    for key in (
        "status",
        "version",
        "timestamp",
        "live_trading",
        "kill_switch_active",
        "paper_mode",
        "database",
        "ibkr_connected",
        "schwab_connected",
        "uptime_seconds",
    ):
        assert key in body, f"missing contract key: {key}"


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
    for key in ("all_clear", "kill_switch_active", "daily_limit_breached", "drawdown_breached"):
        assert key in body, f"missing contract key: {key}"


def test_paper_phase_summary_shape(contract_client: TestClient) -> None:
    """GET /portfolio/stats/paper-phase-summary matches dashboard PaperPhaseSummary."""
    r = contract_client.get("/portfolio/stats/paper-phase-summary")
    assert r.status_code == 200
    body = r.json()
    for key in (
        "phase",
        "start_date",
        "starting_balance",
        "current_balance",
        "total_return_pct",
        "total_pnl",
        "trading_days",
        "target_trading_days",
        "trades_completed",
        "validation_status",
    ):
        assert key in body
    assert isinstance(body["phase"], str)
    assert isinstance(body["starting_balance"], (int, float))
    assert isinstance(body["current_balance"], (int, float))
    assert isinstance(body["total_return_pct"], (int, float))
    assert isinstance(body["total_pnl"], (int, float))
    assert isinstance(body["trading_days"], int)
    assert isinstance(body["target_trading_days"], int)
    assert isinstance(body["trades_completed"], int)
    assert isinstance(body["validation_status"], str)


def test_trading_days_stats_shape(contract_client: TestClient) -> None:
    """GET /portfolio/stats/trading-days (GT-25): route was dropped in the 2026-05-22
    main.py -> router migration, producing a live 404 on /validation. Verifies every
    field alias TradingDaysCountdownCard and ValidationChecklist consume."""
    r = contract_client.get("/portfolio/stats/trading-days")
    assert r.status_code == 200
    body = r.json()
    for key in (
        "trading_days",
        "trading_days_completed",
        "days_traded",
        "completed_days",
        "threshold",
        "threshold_met",
    ):
        assert key in body, f"missing contract key: {key}"
    assert isinstance(body["trading_days"], int)
    assert body["trading_days"] == body["trading_days_completed"] == body["days_traded"] == body["completed_days"]
    assert isinstance(body["threshold"], int)
    assert isinstance(body["threshold_met"], bool)
    assert body["threshold_met"] == (body["trading_days"] >= body["threshold"])
