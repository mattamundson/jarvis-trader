"""GT-01: GET /portfolio must surface SafetyLayer's real equity/PnL keys.

Regression coverage for a dict-key mismatch: the router used to read
``status.get("portfolio_equity", ...)`` / ``status.get("daily_pnl", ...)``
against SafetyLayer.get_status(), which never emits those names — it emits
``current_equity`` / ``daily_realized_pnl`` instead — so the response always
fell through to the 0.0 default regardless of the real account state.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from slowapi.errors import RateLimitExceeded

from middleware.rate_limit import limiter, rate_limit_exception_handler
from routers import portfolio_router as pr_mod


@pytest.fixture()
def portfolio_client():
    old_pt, old_db, old_dm, old_safety = (
        pr_mod.paper_tracker,
        pr_mod.db_manager,
        pr_mod._data_manager,
        pr_mod._safety_layer,
    )

    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_exception_handler)

    safety = MagicMock()
    # Real SafetyLayer.get_status() return shape (engine/risk/safety_layer.py) —
    # no "portfolio_equity" or "daily_pnl" keys exist on this dict.
    safety.get_status.return_value = {
        "is_killed": False,
        "kill_switch_active": False,
        "kill_switch_reason": None,
        "daily_realized_pnl": -212.75,
        "equity_peak": 16000.0,
        "current_equity": 15537.51,
        "recent_order_count": 3,
    }
    pr_mod.inject_dependencies(None, None, None, safety)

    app.include_router(pr_mod.router, prefix="/portfolio")
    client = TestClient(app)
    yield client

    pr_mod.inject_dependencies(old_pt, old_db, old_dm, old_safety)


def test_portfolio_surfaces_real_equity_and_daily_pnl(portfolio_client: TestClient) -> None:
    r = portfolio_client.get("/portfolio")
    assert r.status_code == 200, r.text
    body = r.json()

    # Root bug: these used to always be 0.0 because the router read keys
    # SafetyLayer never emits.
    assert body["total_equity"] == 15537.51
    assert body["daily_pnl"] == -212.75

    # cash_balance is the historical field; cash is the alias the
    # dashboard's command-center page actually reads (page.tsx ~:641).
    assert body["cash_balance"] == 15537.51
    assert body["cash"] == 15537.51
    assert body["margin_available"] == 15537.51


def test_portfolio_defaults_are_zero_when_safety_layer_omits_keys(
    portfolio_client: TestClient,
) -> None:
    """A SafetyLayer status dict missing the keys entirely should still 200
    with an honest 0.0 default — never raise, never fabricate a value."""
    pr_mod._safety_layer.get_status.return_value = {"is_killed": False}

    r = portfolio_client.get("/portfolio")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total_equity"] == 0.0
    assert body["daily_pnl"] == 0.0
    assert body["cash"] == 0.0
