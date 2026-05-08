"""End-to-end check: SafetyLayer.submit_entry_with_stop → sidecar → gate count."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def gate_client_isolated(tmp_path, monkeypatch):
    """Mount the gate router with the data dir redirected to tmp_path.

    Both the writer (SafetyLayer) and the reader (gate router) resolve their
    sidecar paths via __file__-relative paths, so we patch __file__ on each.
    """
    from routers import phase3_readiness_router as gate_mod

    real_engine_root = Path(gate_mod.__file__).resolve().parent.parent
    fake_router_file = tmp_path / "engine" / "routers" / "phase3_readiness_router.py"
    fake_router_file.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(gate_mod, "__file__", str(fake_router_file))

    app = FastAPI()
    app.include_router(gate_mod.router)
    return TestClient(app), tmp_path


def test_bracket_sidecar_increments_gate_count(gate_client_isolated):
    """Writing the sidecar JSON directly is what the gate reads."""
    client, tmp_path = gate_client_isolated
    sidecar = tmp_path / "engine" / "data" / "bracket_trade_count.json"
    sidecar.parent.mkdir(parents=True, exist_ok=True)

    # Empty state → gate reports 0/5.
    resp = client.get("/system/mes-sprint-gate")
    bracket = next(c for c in resp.json()["checks"] if c["name"] == "bracket_trades")
    assert bracket["pass"] is False
    assert bracket["value"] == "0/5"

    # Simulate 5 bracket trades (per-symbol format).
    sidecar.write_text(json.dumps({"MES": {"count": 5}}), encoding="utf-8")
    resp = client.get("/system/mes-sprint-gate")
    bracket = next(c for c in resp.json()["checks"] if c["name"] == "bracket_trades")
    assert bracket["pass"] is True
    assert bracket["value"] == "5/5"


@pytest.mark.asyncio
async def test_safety_layer_submit_entry_bumps_sidecar(tmp_path, monkeypatch):
    """submit_entry_with_stop increments the sidecar when STP places successfully."""
    from risk import safety_layer as sl_mod

    fake_sl_file = tmp_path / "engine" / "risk" / "safety_layer.py"
    fake_sl_file.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(sl_mod, "__file__", str(fake_sl_file))

    sidecar = tmp_path / "engine" / "data" / "bracket_trade_count.json"

    from config import settings

    # Build a SafetyLayer with a fully-mocked gateway so we don't need IB.
    fake_gw = AsyncMock()
    fake_gw.place_paper_order = AsyncMock(side_effect=[1001, 1002, 1003, 2001, 2002])
    sl = sl_mod.SafetyLayer(config=settings, ib_gateway=fake_gw)

    # Stub out submit_paper_order to simulate a clean approval/route.
    async def fake_entry(**kwargs):
        return {"approved": True, "routed_to_ib": True, "order_id": 1001}

    # Stub parent verification — we're testing the counter, not the verify path.
    async def fake_verify(child_id, parent_id):
        return True

    with (
        patch.object(sl, "submit_paper_order", side_effect=fake_entry),
        patch.object(sl, "_verify_parent_linkage", side_effect=fake_verify),
    ):
        result = await sl.submit_entry_with_stop(
            symbol="MES",
            action="BUY",
            quantity=1,
            price=5700.0,
            stop_price=5692.0,
            target_price=5710.0,
        )

    assert result["approved"] is True
    assert result["routed_to_ib"] is True
    assert result["stp_order_id"] is not None

    # Sidecar should now show MES count=1 (per-symbol format).
    assert sidecar.exists(), "sidecar was not written"
    state = json.loads(sidecar.read_text(encoding="utf-8"))
    assert state["MES"]["count"] == 1
    assert state["MES"]["last_entry_order_id"] == 1001
