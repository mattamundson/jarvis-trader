"""Tests for the MES Sprint Gate aggregation endpoint."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def gate_client() -> TestClient:
    """Bare FastAPI app mounting only phase3_readiness_router (auth-free)."""
    from routers.phase3_readiness_router import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_mes_sprint_gate_returns_structure(gate_client: TestClient):
    resp = gate_client.get("/system/mes-sprint-gate")
    assert resp.status_code == 200
    data = resp.json()
    assert "overall" in data
    assert data["overall"] in ("PASS", "FAIL", "PENDING")
    assert "checks" in data
    assert isinstance(data["checks"], list)
    assert "ready_for_live" in data
    assert isinstance(data["ready_for_live"], bool)


def test_mes_sprint_gate_check_names(gate_client: TestClient):
    resp = gate_client.get("/system/mes-sprint-gate")
    data = resp.json()
    names = [c["name"] for c in data["checks"]]
    assert "smoke_test" in names
    assert "bracket_trades" in names
    assert "kill_switch_clean" in names
    assert "pm2_restarts" in names
    assert "loss_streak" in names
    assert "drawdown" in names


def test_mes_sprint_gate_each_check_shape(gate_client: TestClient):
    resp = gate_client.get("/system/mes-sprint-gate")
    data = resp.json()
    for check in data["checks"]:
        assert "name" in check
        assert "pass" in check
        assert isinstance(check["pass"], bool)
