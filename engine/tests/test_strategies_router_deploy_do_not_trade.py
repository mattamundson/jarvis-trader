"""POST /strategies/rl/deploy — DO_NOT_TRADE_SYMBOLS gating (PRB-03).

2026-07-29 prod-readiness audit: this endpoint (informally "rl/activate"
per its `active=True` field, which starts an RLExecutor for live hourly
execution) had zero DO_NOT_TRADE_SYMBOLS gating, and neither did
SafetyLayer.check_order() -- the RLExecutor's own pre-order gate. A
documented, callable API could start real paper order routing on a symbol
the platform's own halt policy says must never trade.

This file covers the fast, endpoint-level 4xx added alongside the
authoritative check_order() fix (see test_safety_layer.py::
TestDoNotTradeSymbols for the check_order()-level coverage, which is the
fix that actually closes the gap for every current and future caller).

No IB Gateway, no real model file, no background task execution -- the
DO_NOT_TRADE_SYMBOLS check short-circuits before any of that is touched.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from slowapi.errors import RateLimitExceeded

_ENGINE_ROOT = str(Path(__file__).parent.parent)
if _ENGINE_ROOT not in sys.path:
    sys.path.insert(0, _ENGINE_ROOT)

from middleware.rate_limit import limiter, rate_limit_exception_handler  # noqa: E402
from routers import strategies_router as sr_mod  # noqa: E402
from strategies.rl_executor import _executor_registry  # noqa: E402


@pytest.fixture()
def deploy_client():
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_exception_handler)
    app.include_router(sr_mod.router)
    return TestClient(app)


def test_deploy_rejects_do_not_trade_symbol(deploy_client: TestClient) -> None:
    """symbol=MCL (a current DO_NOT_TRADE_SYMBOLS member) with active=True
    must be rejected with a 4xx before any executor is constructed."""
    r = deploy_client.post(
        "/strategies/rl/deploy",
        json={"symbol": "MCL", "model_path": "models/does_not_matter", "active": True},
    )
    assert 400 <= r.status_code < 500, r.text
    assert "MCL" in r.text
    assert "MCL" not in _executor_registry


def test_deploy_rejects_do_not_trade_symbol_case_insensitive(deploy_client: TestClient) -> None:
    r = deploy_client.post(
        "/strategies/rl/deploy",
        json={"symbol": "mnq", "model_path": "models/does_not_matter", "active": True},
    )
    assert 400 <= r.status_code < 500, r.text
    assert "MNQ" not in _executor_registry


def test_deploy_deactivate_of_do_not_trade_symbol_is_not_blocked(
    deploy_client: TestClient,
) -> None:
    """active=False (deactivation) must NOT be blocked by the new check --
    stopping an executor for a halted symbol should always be allowed. No
    executor is registered, so this hits the existing 404 "nothing to
    deactivate" path, not the do-not-trade 4xx."""
    r = deploy_client.post(
        "/strategies/rl/deploy",
        json={"symbol": "MCL", "model_path": "models/does_not_matter", "active": False},
    )
    assert r.status_code == 404, r.text
    assert "MCL" in r.text
