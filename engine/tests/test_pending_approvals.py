"""Pending trade approval DB + API router."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from config import TradingConfig
from database.manager import DatabaseManager
from risk.safety_layer import SafetyLayer
from routers.approval_router import inject_dependencies
from routers.approval_router import router as approval_router


@pytest.fixture
def tmp_db():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d) / "t.db"


@pytest.fixture
def dbm(tmp_db: Path):
    m = DatabaseManager(str(tmp_db))
    m.initialize()
    return m


def test_insert_list_get_pending(dbm: DatabaseManager):
    snap = {"final_action": "buy", "summary": "test"}
    aid = dbm.insert_pending_approval(
        symbol="MCL",
        action="buy",
        quantity=1.0,
        entry_price=70.5,
        pipeline_snapshot=snap,
    )
    assert len(aid) == 36
    rows = dbm.list_pending_approvals()
    assert len(rows) == 1
    assert rows[0]["approval_id"] == aid
    assert rows[0]["pipeline_snapshot"]["summary"] == "test"
    one = dbm.get_pending_approval(aid)
    assert one is not None
    assert one["status"] == "pending"


def test_resolve_double_approve_fails(dbm: DatabaseManager):
    aid = dbm.insert_pending_approval(
        symbol="MCL",
        action="buy",
        quantity=1,
        entry_price=1.0,
        pipeline_snapshot={},
    )
    assert dbm.resolve_pending_approval(
        aid, new_status="approved", resolved_by="t", paper_trade_id="tid"
    )
    assert not dbm.resolve_pending_approval(
        aid, new_status="approved", resolved_by="t2", paper_trade_id="x"
    )


def test_approval_router_approve_flow(tmp_db: Path):
    dbm = DatabaseManager(str(tmp_db))
    dbm.initialize()
    mock_pt = MagicMock()
    mock_pt.open_trade.return_value = "paper-uuid-123"
    cfg = TradingConfig()
    cfg.FUTURES_WATCHLIST = ["MES", "MGC"]
    cfg.ALLOW_PAPER_SIMULATED_ORDERS = True
    # Bypass the overnight contract cap so this approval-flow test is wall-clock-
    # independent (default MAX_OVERNIGHT_CONTRACTS=1 rejects the MES qty=2 below
    # after 15:00 CT). Same idiom as test_safety_layer.py.
    cfg.MAX_OVERNIGHT_CONTRACTS = 5
    safety = SafetyLayer(cfg)

    inject_dependencies(safety, mock_pt, dbm)

    app = FastAPI()
    app.include_router(approval_router)
    client = TestClient(app, headers={"X-API-Key": "test-key"})

    aid = dbm.insert_pending_approval(
        symbol="MES",
        action="buy",
        quantity=2.0,
        entry_price=None,
        pipeline_snapshot={"trade_decision": {"limit_price": 5823.50}},
    )

    # Patch is_strategy_authorized so MES's VALIDATION_ONLY_INSTRUMENTS gate
    # doesn't block the approval-flow mechanics test. The gate itself is covered
    # separately in test_validation_only_instruments.py.
    with patch("backtest.gate_v2_policy.is_strategy_authorized", return_value=(True, "")):
        r = client.post(f"/pipeline/pending-approvals/{aid}/approve", json={})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["paper_trade_id"] == "paper-uuid-123"
    mock_pt.open_trade.assert_called_once()

    r2 = client.post(f"/pipeline/pending-approvals/{aid}/approve", json={})
    assert r2.status_code == 409


def test_approval_router_reject(tmp_db: Path):
    dbm = DatabaseManager(str(tmp_db))
    dbm.initialize()
    inject_dependencies(SafetyLayer(TradingConfig()), MagicMock(), dbm)
    app = FastAPI()
    app.include_router(approval_router)
    client = TestClient(app, headers={"X-API-Key": "test-key"})
    aid = dbm.insert_pending_approval(
        symbol="MCL",
        action="sell",
        quantity=1,
        entry_price=1.0,
        pipeline_snapshot={},
    )
    r = client.post(
        f"/pipeline/pending-approvals/{aid}/reject",
        json={"reason": "no thanks"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "rejected"
