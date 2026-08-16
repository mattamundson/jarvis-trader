"""Tests for routers/polymarket_router.py — /polymarket/status, /markets, /scan, /pnl.

Design mirrors tests/test_altmarket_contract_endpoints.py: the router resolves its
module via `orchestrator.get_orchestrator().get_module("polymarket")`, imported
locally inside `_get_module()`. We stub the `orchestrator` module in `sys.modules`
so no real orchestrator, DB, or IB gateway is touched.

Every endpoint is exercised in its two real states:
  - Polymarket module not registered (the actual default: POLYMARKET_ENABLED=False)
  - Polymarket module registered (mocked client / scanner / health)
plus, where the router has its own try/except, a mocked-dependency-failure path.
"""

from __future__ import annotations

import sys
import types
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.polymarket_router import router


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _orchestrator_stub(module):
    """A fake `orchestrator` module whose get_orchestrator().get_module() -> module."""
    orch = MagicMock()
    orch.get_module.return_value = module
    stub = types.ModuleType("orchestrator")
    stub.get_orchestrator = lambda: orch
    return stub


def _enabled_module(*, markets=None, daily_pnl=42.5, daily_target=125.0):
    module = MagicMock()
    module._client = MagicMock()
    module._client.get_markets.return_value = markets if markets is not None else []
    module.get_daily_pnl = AsyncMock(return_value=daily_pnl)
    module.daily_target = daily_target
    module.health_check.return_value = types.SimpleNamespace(
        status=types.SimpleNamespace(value="paper"),
        message="Polymarket paper module healthy",
        daily_pnl=daily_pnl,
        open_positions=1,
    )
    return module


# ---------------------------------------------------------------------------
# GET /polymarket/status
# ---------------------------------------------------------------------------


def test_status_disabled_when_module_not_registered(client, monkeypatch):
    """Default production state: POLYMARKET_ENABLED=False -> module is None."""
    monkeypatch.setitem(sys.modules, "orchestrator", _orchestrator_stub(None))

    response = client.get("/polymarket/status")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "disabled"
    assert "POLYMARKET_ENABLED" in body["message"]


def test_status_reports_health_when_module_registered(client, monkeypatch):
    module = _enabled_module(daily_pnl=12.0)
    monkeypatch.setitem(sys.modules, "orchestrator", _orchestrator_stub(module))

    response = client.get("/polymarket/status")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "paper"
    assert body["message"] == "Polymarket paper module healthy"
    assert body["daily_pnl"] == 12.0
    assert body["open_positions"] == 1
    assert "regulatory_note" in body


# ---------------------------------------------------------------------------
# GET /polymarket/markets
# ---------------------------------------------------------------------------


def test_markets_empty_when_module_not_registered(client, monkeypatch):
    monkeypatch.setitem(sys.modules, "orchestrator", _orchestrator_stub(None))

    response = client.get("/polymarket/markets")

    assert response.status_code == 200
    body = response.json()
    assert body["markets"] == []
    assert body["error"] == "Polymarket not enabled"


def test_markets_returns_client_markets(client, monkeypatch):
    fake_markets = [{"question": f"Market {i}?", "tokens": []} for i in range(3)]
    module = _enabled_module(markets=fake_markets)
    monkeypatch.setitem(sys.modules, "orchestrator", _orchestrator_stub(module))

    response = client.get("/polymarket/markets")

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 3
    assert len(body["markets"]) == 3
    module._client.get_markets.assert_called_once_with(active_only=True)


def test_markets_degrades_gracefully_when_client_raises(client, monkeypatch):
    module = _enabled_module()
    module._client.get_markets.side_effect = RuntimeError("CLOB unreachable")
    monkeypatch.setitem(sys.modules, "orchestrator", _orchestrator_stub(module))

    response = client.get("/polymarket/markets")

    assert response.status_code == 200
    body = response.json()
    assert body["markets"] == []
    assert "CLOB unreachable" in body["error"]


# ---------------------------------------------------------------------------
# GET /polymarket/scan
# ---------------------------------------------------------------------------


def test_scan_empty_when_module_not_registered(client, monkeypatch):
    monkeypatch.setitem(sys.modules, "orchestrator", _orchestrator_stub(None))

    response = client.get("/polymarket/scan")

    assert response.status_code == 200
    body = response.json()
    assert body["opportunities"] == []
    assert body["error"] == "Polymarket not enabled"


def test_scan_returns_mapped_opportunities(client, monkeypatch):
    module = _enabled_module()
    monkeypatch.setitem(sys.modules, "orchestrator", _orchestrator_stub(module))

    opp = types.SimpleNamespace(
        token_id="tok-1",
        question="Will it rain in NYC tomorrow, no really, a very long question text here?",
        yes_price=0.62,
        no_price=0.35,
        spread=0.03,
        volume_24h=15000.0,
        opportunity_type="arb",
        confidence=0.8,
    )
    scanner_instance = MagicMock()
    scanner_instance.scan.return_value = [opp]
    scanner_mod = types.ModuleType("markets.polymarket.scanner")
    scanner_mod.PolymarketScanner = MagicMock(return_value=scanner_instance)
    monkeypatch.setitem(sys.modules, "markets.polymarket.scanner", scanner_mod)

    response = client.get("/polymarket/scan")

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    row = body["opportunities"][0]
    assert row["token_id"] == "tok-1"
    assert len(row["question"]) <= 80  # truncated
    assert row["yes_price"] == 0.62
    assert row["type"] == "arb"
    assert row["confidence"] == 0.8
    scanner_mod.PolymarketScanner.assert_called_once_with(client=module._client)


def test_scan_degrades_gracefully_when_scanner_raises(client, monkeypatch):
    module = _enabled_module()
    monkeypatch.setitem(sys.modules, "orchestrator", _orchestrator_stub(module))

    scanner_instance = MagicMock()
    scanner_instance.scan.side_effect = RuntimeError("scanner blew up")
    scanner_mod = types.ModuleType("markets.polymarket.scanner")
    scanner_mod.PolymarketScanner = MagicMock(return_value=scanner_instance)
    monkeypatch.setitem(sys.modules, "markets.polymarket.scanner", scanner_mod)

    response = client.get("/polymarket/scan")

    assert response.status_code == 200
    body = response.json()
    assert body["opportunities"] == []
    assert "scanner blew up" in body["error"]


# ---------------------------------------------------------------------------
# GET /polymarket/pnl
# ---------------------------------------------------------------------------


def test_pnl_default_payload_when_module_not_registered(client, monkeypatch):
    monkeypatch.setitem(sys.modules, "orchestrator", _orchestrator_stub(None))

    response = client.get("/polymarket/pnl")

    assert response.status_code == 200
    body = response.json()
    assert body == {"daily_pnl": 0.0, "target": 125.0, "status": "disabled"}


def test_pnl_computes_progress_pct(client, monkeypatch):
    module = _enabled_module(daily_pnl=25.0, daily_target=125.0)
    monkeypatch.setitem(sys.modules, "orchestrator", _orchestrator_stub(module))

    response = client.get("/polymarket/pnl")

    assert response.status_code == 200
    body = response.json()
    assert body["daily_pnl"] == 25.0
    assert body["target"] == 125.0
    assert body["progress_pct"] == 20.0  # 25/125 * 100


def test_pnl_progress_pct_zero_when_target_is_zero(client, monkeypatch):
    """Edge case: a zero daily_target must not raise a ZeroDivisionError."""
    module = _enabled_module(daily_pnl=10.0, daily_target=0.0)
    monkeypatch.setitem(sys.modules, "orchestrator", _orchestrator_stub(module))

    response = client.get("/polymarket/pnl")

    assert response.status_code == 200
    body = response.json()
    assert body["progress_pct"] == 0
