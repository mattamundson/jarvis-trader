"""Phase 5 contract tests — /crypto/* and /options/module/{scan,pnl}.

Assert that each alt-market endpoint emits exactly the shape the dashboard
reads, in both states:
  - module OFF / bridge unreachable  → clean disabled/empty payload (no 404/500)
  - module ON (mocked)               → real fields mapped to the frontend keys

Design: FastAPI TestClient in isolation; the module / bridge / scanner are
mocked at the import boundary via patch.dict(sys.modules), so no engine, no
network, no real .env.
"""

from __future__ import annotations

import sys
import types
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Clients
# ---------------------------------------------------------------------------


@pytest.fixture()
def crypto_client():
    from routers.crypto_router import router

    app = FastAPI()
    app.include_router(router)  # router carries its own /crypto prefix
    return TestClient(app)


@pytest.fixture()
def options_client():
    from routers.options_router import router

    app = FastAPI()
    app.include_router(router, prefix="/options")
    return TestClient(app)


def _orchestrator_stub(module):
    """A fake `orchestrator` module whose get_orchestrator().get_module() → module."""
    orch = MagicMock()
    orch.get_module.return_value = module
    stub = types.ModuleType("orchestrator")
    stub.get_orchestrator = lambda: orch
    return stub


# ---------------------------------------------------------------------------
# Crypto — disabled state
# ---------------------------------------------------------------------------

CRYPTO_STATUS_KEYS = {
    "enabled",
    "connected",
    "freqtrade_running",
    "daily_pnl",
    "open_positions_count",
    "last_sync",
}


def test_crypto_status_disabled_shape(crypto_client, monkeypatch):
    """No orchestrator → honest disabled payload with the full key set."""
    monkeypatch.setitem(sys.modules, "orchestrator", _orchestrator_stub(None))
    r = crypto_client.get("/crypto/status")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == CRYPTO_STATUS_KEYS
    assert body["enabled"] is False
    assert body["freqtrade_running"] is False


def test_crypto_positions_empty_when_no_bridge(crypto_client, monkeypatch):
    monkeypatch.setitem(sys.modules, "orchestrator", _orchestrator_stub(None))
    r = crypto_client.get("/crypto/positions")
    assert r.status_code == 200
    assert r.json() == {"positions": []}


def test_crypto_freqtrade_status_disabled_shape(crypto_client, monkeypatch):
    monkeypatch.setitem(sys.modules, "orchestrator", _orchestrator_stub(None))
    r = crypto_client.get("/crypto/freqtrade/status")
    assert r.status_code == 200
    body = r.json()
    assert body["running"] is False
    assert body["open_trade_count"] == 0
    assert "profit_today_abs" in body


def test_crypto_start_stop_without_bridge(crypto_client, monkeypatch):
    monkeypatch.setitem(sys.modules, "orchestrator", _orchestrator_stub(None))
    for action in ("start", "stop"):
        r = crypto_client.post(f"/crypto/freqtrade/{action}")
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is False
        assert body["action"] == action


# ---------------------------------------------------------------------------
# Crypto — enabled state (mocked module + bridge)
# ---------------------------------------------------------------------------


def _enabled_crypto_module():
    module = MagicMock()
    module.is_enabled.return_value = True
    module.daily_target = 100.0
    module.get_daily_pnl = AsyncMock(return_value=12.5)
    module.health_check.return_value = types.SimpleNamespace(
        status=types.SimpleNamespace(value="ok"),
        daily_pnl=12.5,
        open_positions=2,
        last_trade_at=None,
    )

    bridge = MagicMock()
    bridge.is_running = AsyncMock(return_value=True)
    bridge.get_config = AsyncMock(
        return_value={"version": "2024.1", "state": "running", "dry_run": True, "bot_name": "jt"}
    )
    bridge.get_status = AsyncMock(return_value=[{"pair": "BTC/USDT"}])
    bridge.get_profit = AsyncMock(
        return_value={"profit_closed_coin": 34.0, "profit_today_abs": 5.5}
    )
    bridge.get_trades = AsyncMock(
        return_value=[
            {
                "pair": "BTC/USDT",
                "open_date": "2026-07-07 12:00:00",
                "stake_amount": 100.0,
                "current_rate": 62000.0,
                "profit_ratio": 0.031,
                "profit_abs": 3.1,
            }
        ]
    )
    module._bridge = bridge
    return module


def test_crypto_positions_mapped_from_bridge(crypto_client, monkeypatch):
    monkeypatch.setitem(
        sys.modules, "orchestrator", _orchestrator_stub(_enabled_crypto_module())
    )
    r = crypto_client.get("/crypto/positions")
    assert r.status_code == 200
    positions = r.json()["positions"]
    assert len(positions) == 1
    p = positions[0]
    assert set(p) == {"pair", "open_date", "stake_amount", "current_rate", "profit_pct", "profit_abs"}
    assert p["pair"] == "BTC/USDT"
    # profit_ratio 0.031 → profit_pct 3.1
    assert p["profit_pct"] == pytest.approx(3.1)


def test_crypto_freqtrade_status_flattened(crypto_client, monkeypatch):
    monkeypatch.setitem(
        sys.modules, "orchestrator", _orchestrator_stub(_enabled_crypto_module())
    )
    r = crypto_client.get("/crypto/freqtrade/status")
    body = r.json()
    assert body["running"] is True
    assert body["version"] == "2024.1"
    assert body["dry_run"] is True
    assert body["bot_name"] == "jt"
    assert body["open_trade_count"] == 1
    assert body["profit_today_abs"] == 5.5


def test_crypto_status_enabled(crypto_client, monkeypatch):
    monkeypatch.setitem(
        sys.modules, "orchestrator", _orchestrator_stub(_enabled_crypto_module())
    )
    body = crypto_client.get("/crypto/status").json()
    assert body["enabled"] is True
    assert body["connected"] is True
    assert body["freqtrade_running"] is True
    assert body["daily_pnl"] == 12.5
    assert body["open_positions_count"] == 2


# ---------------------------------------------------------------------------
# Options /module/scan
# ---------------------------------------------------------------------------

SCAN_RESULT_KEYS = {"symbol", "strategy_type", "iv_rank", "expiry_date", "estimated_premium"}


def test_options_scan_mapped_shape(options_client, monkeypatch):
    # Mock the VIX lookup + regime classifier.
    md_mod = types.ModuleType("data.market_data")
    md_mgr = MagicMock()
    md_mgr.get_vix = AsyncMock(return_value={"value": 12.0})
    md_mod.MarketDataManager = MagicMock(return_value=md_mgr)

    se_mod = types.ModuleType("options.strategy_executor")
    se_mod.classify_vix_regime = lambda vix: types.SimpleNamespace(value="LOW")

    # Mock the scanner to return one opportunity.
    scan_row = types.SimpleNamespace(
        symbol="SPY", regime="low_vix", iv_rank=42.0, expiry="2026-08-15", current_price=500.0
    )
    scanner_mod = types.ModuleType("markets.options.scanner")
    scanner_inst = MagicMock()
    scanner_inst.scan.return_value = [scan_row]
    scanner_mod.OptionsScanner = MagicMock(return_value=scanner_inst)

    monkeypatch.setitem(sys.modules, "data.market_data", md_mod)
    monkeypatch.setitem(sys.modules, "options.strategy_executor", se_mod)
    monkeypatch.setitem(sys.modules, "markets.options.scanner", scanner_mod)

    body = options_client.get("/options/module/scan").json()
    assert body["vix_regime"] == "low"  # LOW → lowercase
    assert body["strategy_selected"] == "iron_condor"
    assert len(body["scan_results"]) == 1
    row = body["scan_results"][0]
    assert set(row) == SCAN_RESULT_KEYS
    assert row["symbol"] == "SPY"
    assert row["strategy_type"] == "iron_condor"  # low_vix → iron_condor
    assert row["iv_rank"] == 42.0
    assert row["estimated_premium"] > 0  # heuristic proxy, non-zero for IV-rich


def test_options_scan_empty_when_scanner_absent(options_client, monkeypatch):
    # Force the scanner import to fail → empty payload, still 200.
    monkeypatch.setitem(sys.modules, "markets.options.scanner", None)
    body = options_client.get("/options/module/scan").json()
    assert body["scan_results"] == []
    assert "vix_regime" in body


# ---------------------------------------------------------------------------
# Options /module/pnl
# ---------------------------------------------------------------------------

OPT_POS_KEYS = {"symbol", "strategy", "entry_price", "current_price", "pnl", "dte"}


def test_options_pnl_mapped_shape(options_client, monkeypatch):
    open_pos = types.SimpleNamespace(
        symbol="SPY",
        strategy="iron_condor",
        entry_premium=2.5,
        current_premium=1.2,
        unrealised_pnl=130.0,
        dte=21,
    )
    closed_pos = types.SimpleNamespace(realised_pnl=80.0)

    mgr = MagicMock()

    def _get_positions(status="OPEN"):
        return [open_pos] if status == "OPEN" else [closed_pos]

    mgr.get_positions.side_effect = _get_positions

    pm_mod = types.ModuleType("options.position_manager")
    pm_mod.OptionsPositionManager = MagicMock(return_value=mgr)
    monkeypatch.setitem(sys.modules, "options.position_manager", pm_mod)
    # No orchestrator → daily_pnl degrades to 0.0
    monkeypatch.setitem(sys.modules, "orchestrator", _orchestrator_stub(None))

    body = options_client.get("/options/module/pnl").json()
    assert set(body) == {"daily_pnl", "total_pnl", "open_positions"}
    assert body["daily_pnl"] == 0.0
    # total = realized 80 + unrealised 130
    assert body["total_pnl"] == pytest.approx(210.0)
    assert len(body["open_positions"]) == 1
    row = body["open_positions"][0]
    assert set(row) == OPT_POS_KEYS
    assert row["entry_price"] == 2.5
    assert row["current_price"] == 1.2
    assert row["pnl"] == 130.0
    assert row["dte"] == 21


def test_options_pnl_empty_when_store_absent(options_client, monkeypatch):
    monkeypatch.setitem(sys.modules, "options.position_manager", None)
    monkeypatch.setitem(sys.modules, "orchestrator", _orchestrator_stub(None))
    body = options_client.get("/options/module/pnl").json()
    assert body["open_positions"] == []
    assert body["daily_pnl"] == 0.0
    assert body["total_pnl"] == 0.0
