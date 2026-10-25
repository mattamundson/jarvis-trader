"""Contract coverage for the canonical /safety/status response."""

from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from slowapi.errors import RateLimitExceeded

from api.models import SafetyStatusResponse
from middleware.rate_limit import limiter
from routers import safety_router


class _FakeSafetyLayer:
    _current_equity = 50000.0
    _equity_peak = 52500.0

    def __init__(self) -> None:
        self._pnl_monitor = SimpleNamespace(
            get_current_pnl_state=lambda: SimpleNamespace(
                source="sqlite",
                current_balance=50000.0,
                starting_balance=51000.0,
            )
        )

    def get_status(self) -> dict[str, object]:
        return {
            "is_killed": False,
            "kill_switch_reason": None,
            "current_equity": 50000.0,
            "equity_peak": 52500.0,
            "daily_realized_pnl": -250.0,
            "last_kill_switch_ts": "2026-09-02T12:00:00+00:00",
            "last_kill_switch_reason_value": "MANUAL",
        }

    def check_circuit_breakers(self) -> dict[str, object]:
        return {
            "daily_pnl": -500.0,
            "daily_limit": -2500.0,
            "daily_limit_pct": -0.05,
            "daily_limit_breached": False,
            "drawdown_pct": -0.02,
            "drawdown_limit_pct": -0.10,
            "drawdown_breached": False,
            "orders_per_minute_limit": 5,
        }

    def orders_in_last_minute(self) -> int:
        return 2


class _FakeLossTracker:
    def get_consecutive_losses(self) -> int:
        return 3


def _client() -> TestClient:
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, lambda request, exc: None)  # type: ignore[arg-type]
    app.include_router(safety_router.router)
    return TestClient(app)


def test_safety_status_exposes_full_typed_contract() -> None:
    """The route must return every field declared by SafetyStatusResponse."""
    limiter.reset()
    old_safety_layer = safety_router._safety_layer
    old_loss_tracker = safety_router._loss_tracker
    safety_router.inject_dependencies(_FakeSafetyLayer(), _FakeLossTracker())

    try:
        response = _client().get("/safety/status")
    finally:
        safety_router.inject_dependencies(old_safety_layer, old_loss_tracker)

    assert response.status_code == 200
    body = response.json()
    missing = sorted(set(SafetyStatusResponse.model_fields) - set(body))

    assert missing == []
    assert body["kill_switch_active"] is False
    assert body["daily_pnl"] == -500.0
    assert body["daily_limit"] == -2500.0
    assert body["daily_pnl_pct"] == -0.01
    assert body["drawdown_pct"] == -0.02
    assert body["portfolio_equity"] == 50000.0
    assert body["starting_balance"] == 51000.0
    assert body["pnl_source"] == "sqlite"
    assert body["orders_last_minute"] == 2
    assert body["consecutive_losses"] == 3
    assert body["orders_per_minute_limit"] == 5
    assert body["last_kill_switch_reason_value"] == "MANUAL"
    assert isinstance(body["time_since_kill_switch_sec"], (int, float))
