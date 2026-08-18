"""IBGatewayManager.health_check() had the same shallow-flag blind spot as the
data-leg connector (data/market_data.py) and the router-level fix at
health_router.py -- it already attempted a reqCurrentTimeAsync() round-trip
probe, but never used a failed probe to revise its own `connected` field, so
a wedged execution leg (socket open, API dead) still reported connected=True.
Mirrors engine/tests/test_ib_blind_chaos.py::TestDataLegHealthCheckVerifiesRoundTrip.

Run:
    cd engine
    .venv\\Scripts\\python.exe -m pytest tests/test_ib_gateway_execution_leg_roundtrip.py -v
"""

from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

_TEST_ENV = {
    "API_KEY": "test-key",
    "POSTGRES_URL": "postgresql://test:test@localhost/test",
    "REDIS_URL": "redis://localhost",
    "POLYGON_API_KEY": "test-key",
    "ANTHROPIC_API_KEY": "test-key",
    "SCHWAB_APP_KEY": "test",
    "SCHWAB_APP_SECRET": "test",
    "FINNHUB_API_KEY": "test",
    "ALPACA_API_KEY": "test",
    "ALPACA_SECRET_KEY": "test",
    "TWILIO_ACCOUNT_SID": "test",
    "TWILIO_AUTH_TOKEN": "test",
    "TWILIO_WHATSAPP_FROM": "+1234567890",
    "WHATSAPP_TO": "+0987654321",
    "TRADINGVIEW_WEBHOOK_SECRET": "jarvis_test_secret_12345",
}
for _k, _v in _TEST_ENV.items():
    os.environ.setdefault(_k, _v)

_ENGINE_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if _ENGINE_ROOT not in sys.path:
    sys.path.insert(0, _ENGINE_ROOT)

pytest.importorskip("ib_async")


def _never_returns():
    async def _hang(*args, **kwargs):
        await asyncio.sleep(999)

    return _hang


def _build_manager(*, shallow_connected: bool):
    from execution.ib_gateway import IBConnectionStatus, IBGatewayConfig, IBGatewayManager

    mgr = IBGatewayManager(IBGatewayConfig(host="127.0.0.1", port=4002, client_id=99))

    fake_ib = MagicMock()
    fake_ib.isConnected = MagicMock(return_value=shallow_connected)

    mgr._ib = fake_ib
    mgr._status = (
        IBConnectionStatus.CONNECTED if shallow_connected else IBConnectionStatus.DISCONNECTED
    )
    return mgr, fake_ib


class TestExecutionLegHealthCheckVerifiesRoundTrip:
    @pytest.mark.asyncio
    async def test_reports_degraded_when_shallow_connected_but_roundtrip_fails(self):
        mgr, fake_ib = _build_manager(shallow_connected=True)
        fake_ib.reqCurrentTimeAsync = _never_returns()

        # health_check()'s own reqCurrentTimeAsync probe has a hardcoded 5.0s
        # internal timeout -- give it room to fire and be caught internally
        # before this outer bound would otherwise race it.
        result = await asyncio.wait_for(mgr.health_check(), timeout=8)

        # PRB-28 (2026-08-16, #630): the round-trip probe failure is surfaced
        # honestly as broker_probe_ok=False + degraded_reason, while `connected`
        # remains the shallow socket flag (is_connected()) so /health can
        # distinguish "socket up but broker unresponsive" from "disconnected".
        assert result["connected"] is True
        assert result["latency_ms"] is None
        assert result["broker_probe_ok"] is False
        assert "latency:" in (result["degraded_reason"] or "")

    @pytest.mark.asyncio
    async def test_reports_connected_when_roundtrip_succeeds(self):
        mgr, fake_ib = _build_manager(shallow_connected=True)
        fake_ib.reqCurrentTimeAsync = AsyncMock(return_value=None)

        result = await mgr.health_check()

        assert result["connected"] is True
        assert result["latency_ms"] is not None
        assert result["broker_probe_ok"] is True

    @pytest.mark.asyncio
    async def test_no_probe_attempted_when_shallow_already_false(self):
        mgr, fake_ib = _build_manager(shallow_connected=False)
        fake_ib.reqCurrentTimeAsync = AsyncMock(return_value=None)

        result = await mgr.health_check()

        assert result["connected"] is False
        fake_ib.reqCurrentTimeAsync.assert_not_called()
