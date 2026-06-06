"""
A2 — broker-health honesty tests.

A socket that reports `connected=True` can still have every RPC probe time out
or auth-fail. Before this change health_check() swallowed those failures and
returned latency_ms=None / net_liq=0 behind connected=True, so /health read
green on a degraded broker. These tests pin:

  1. health_check() reports broker_probe_ok=False + degraded_reason when the
     latency / portfolio / open-orders probes raise.
  2. health_check() reports broker_probe_ok=True with no degraded_reason when
     all probes respond.
  3. /health flips status -> "degraded" when the broker is connected but its
     probes failed, and stays "ok" when probes pass.
  4. A fully-disconnected paper broker does NOT degrade /health (known state).

Run with the engine venv:
    engine/.venv/Scripts/python.exe -m pytest engine/tests/test_health_broker_probe.py -q
"""

import asyncio
import os
import pathlib
import sys
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("API_KEY", "test-key")

import routers.health_router as hr  # noqa: E402
from execution.ib_gateway import IBGatewayConfig, IBGatewayManager  # noqa: E402


def _manager() -> IBGatewayManager:
    # Paper port 4002 is allowed; live ports raise in __init__.
    return IBGatewayManager(IBGatewayConfig(host="127.0.0.1", port=4002, client_id=99))


async def test_health_check_degraded_when_probes_fail():
    mgr = _manager()
    mgr.is_connected = lambda: True  # type: ignore[assignment]
    mgr._ib = SimpleNamespace(reqCurrentTimeAsync=AsyncMock(side_effect=asyncio.TimeoutError()))
    mgr.get_portfolio_value = AsyncMock(side_effect=ConnectionError("broker rpc down"))  # type: ignore[assignment]
    mgr.get_open_orders = AsyncMock(return_value=[])  # type: ignore[assignment]

    res = await mgr.health_check()

    assert res["connected"] is True
    assert res["broker_probe_ok"] is False
    assert res["latency_ms"] is None
    assert "latency:TimeoutError" in res["degraded_reason"]
    assert "net_liq:ConnectionError" in res["degraded_reason"]


async def test_health_check_ok_when_probes_respond():
    mgr = _manager()
    mgr.is_connected = lambda: True  # type: ignore[assignment]
    mgr._ib = SimpleNamespace(reqCurrentTimeAsync=AsyncMock(return_value=datetime.now(timezone.utc)))
    mgr.get_portfolio_value = AsyncMock(return_value=50_000.0)  # type: ignore[assignment]
    mgr.get_open_orders = AsyncMock(return_value=[])  # type: ignore[assignment]

    res = await mgr.health_check()

    assert res["connected"] is True
    assert res["broker_probe_ok"] is True
    assert res["degraded_reason"] is None
    assert res["latency_ms"] is not None


def _fake_gateway(health: dict):
    return SimpleNamespace(is_connected=lambda: True, health_check=AsyncMock(return_value=health))


def _wire_globals(monkeyish, gateway):
    """Set the minimal health_router globals for a _health_inner() run."""
    hr.safety_layer = SimpleNamespace(
        _ib_gateway=gateway,
        get_status=lambda: {"kill_switch_active": False},
    )
    hr.data_manager = None
    hr.db_manager = SimpleNamespace(
        health_check=lambda: None,
        get_pending_approval_stats=lambda: {"count": 0, "oldest_created_at": None},
    )
    hr.settings = SimpleNamespace(LIVE_TRADING_ENABLED=False, IBKR_PORT=65000)
    hr.schwab_connector = None
    hr._start_time = datetime.now(timezone.utc)


async def test_health_status_degraded_when_broker_probe_failed():
    gw = _fake_gateway(
        {"connected": True, "status": "connected", "broker_probe_ok": False,
         "degraded_reason": "latency:TimeoutError"}
    )
    _wire_globals(None, gw)
    with patch("routers.health_router._compute_brier_30d_rolling", return_value=None):
        resp = await hr._health_inner()

    assert resp["status"] == "degraded"
    assert resp["ibkr_broker_probe_ok"] is False
    assert resp["ibkr_degraded_reason"] == "latency:TimeoutError"


async def test_health_status_ok_when_broker_probe_passes():
    gw = _fake_gateway(
        {"connected": True, "status": "connected", "broker_probe_ok": True, "degraded_reason": None}
    )
    _wire_globals(None, gw)
    with patch("routers.health_router._compute_brier_30d_rolling", return_value=None):
        resp = await hr._health_inner()

    assert resp["status"] == "ok"
    assert resp["ibkr_broker_probe_ok"] is True
    assert resp["ibkr_degraded_reason"] is None


async def test_disconnected_broker_does_not_degrade_health():
    # No `connected` key (the no-health_check fallback / fully-down broker): must
    # NOT flip status to degraded — that is the known paper-hours state.
    gw = SimpleNamespace(is_connected=lambda: False)  # no health_check attr
    _wire_globals(None, gw)
    with patch("routers.health_router._compute_brier_30d_rolling", return_value=None):
        resp = await hr._health_inner()

    assert resp["status"] == "ok"  # db_ok + llm_healthy, broker down but not "degraded"
    assert resp["ibkr_broker_probe_ok"] is False  # honestly reports the probe state
