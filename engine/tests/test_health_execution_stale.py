"""Tests — /health execution-connector honesty (execution_connected_verified + ib_execution_stale).

The execution connector's `is_connected` is a *cached* boolean that in paper mode
stays True after IB Gateway logs out, so the raw `ibkr_execution_connected` field
can report execution-ready while `ibgateway_alive=false` (the 2026-06-01
stop-enforcement-believed-connected hazard). /health now also surfaces a reconciled
truth (raw AND the live port probe) and an explicit stale flag. These pin the full
truth table without a running engine or a real Gateway.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import health_router


def _client(monkeypatch, *, exec_connected: bool, gateway_alive: bool) -> TestClient:
    async def _fake_ib_health():
        return {
            "status": "connected" if exec_connected else "disconnected",
            "execution_connected": exec_connected,
            "data_connected": False,
        }

    monkeypatch.setattr(health_router, "_get_ib_gateway_health", _fake_ib_health)
    monkeypatch.setattr(
        health_router, "_check_ibgateway_alive", lambda: (gateway_alive, 4002)
    )
    # Always recompute (bypass the 1s single-flight snapshot) so each case is live.
    monkeypatch.setattr(health_router, "_HEALTH_SNAPSHOT_TTL_SEC", 0.0)

    app = FastAPI()
    app.include_router(health_router.router)
    return TestClient(app)


@pytest.mark.parametrize(
    "exec_connected,gateway_alive,expect_verified,expect_stale",
    [
        (True, True, True, False),    # genuinely connected
        (True, False, False, True),   # THE HAZARD: cached-connected but Gateway logged out
        (False, True, False, False),  # disconnected, Gateway up
        (False, False, False, False), # disconnected, Gateway down
    ],
)
def test_execution_reconciliation_truth_table(
    monkeypatch, exec_connected, gateway_alive, expect_verified, expect_stale
):
    client = _client(monkeypatch, exec_connected=exec_connected, gateway_alive=gateway_alive)
    body = client.get("/health").json()

    # Raw cached belief is preserved for back-compat.
    assert body["ibkr_execution_connected"] is exec_connected
    # Reconciled truth = raw AND live port probe.
    assert body["execution_connected_verified"] is expect_verified
    # Stale = believes connected but the port is dead.
    assert body["ib_execution_stale"] is expect_stale


def test_stale_flag_is_the_hazard_case_only(monkeypatch):
    """ib_execution_stale must be True in exactly one quadrant — the silent hazard."""
    stale_true = 0
    for ec in (True, False):
        for ga in (True, False):
            client = _client(monkeypatch, exec_connected=ec, gateway_alive=ga)
            if client.get("/health").json()["ib_execution_stale"]:
                stale_true += 1
                assert ec is True and ga is False
    assert stale_true == 1
