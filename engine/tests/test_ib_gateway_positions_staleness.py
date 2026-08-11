"""Regression tests for the 2026-08-10 execution-leg position-staleness fix.

Origin: the 2026-08-03 MES overage incident. reqPositionsAsync() and the local
position cache can BOTH come back empty even though a real position exists on
the account (the execution leg's own subscription desynced after a Gateway
bounce) -- the 08-04 cache-fallback patch only helps when the cache itself is
populated, and on 2026-08-10 it wasn't. But "both empty" is ALSO exactly what
a genuinely flat account looks like, so classify_positions_staleness() must
NOT flag every legitimately flat read -- only an unexplained flip from a
previously-confirmed non-zero position to empty with no fill on record.

Run:
    cd engine
    .venv\\Scripts\\python.exe -m pytest tests/test_ib_gateway_positions_staleness.py -v
"""

from __future__ import annotations

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

from execution.ib_gateway import (  # noqa: E402
    IBGatewayConfig,
    IBGatewayManager,
    classify_positions_staleness,
)


def _pos(symbol: str, qty: float, account: str = "DUR375089"):
    p = MagicMock()
    p.contract.symbol = symbol
    p.contract.secType = "FUT"
    p.contract.currency = "USD"
    p.contract.exchange = "CME"
    p.position = qty
    p.avgCost = 100.0
    p.account = account
    return p


def _fill(symbol: str):
    f = MagicMock()
    f.contract.symbol = symbol
    return f


# ── classify_positions_staleness (pure decision logic) ──────────────────────


def test_genuinely_flat_from_start_is_not_stale():
    result = []
    ib_client = MagicMock()
    ib_client.fills.return_value = []
    is_stale, last_known, unexplained = classify_positions_staleness(result, {}, ib_client)
    assert is_stale is False
    assert last_known == {}
    assert unexplained == []


def test_holding_position_updates_last_known():
    result = [{"symbol": "MES", "position": 2.0}]
    ib_client = MagicMock()
    is_stale, last_known, unexplained = classify_positions_staleness(result, {}, ib_client)
    assert is_stale is False
    assert last_known == {"MES": 2.0}


def test_legitimate_flatten_with_matching_fill_is_not_stale():
    result = []
    ib_client = MagicMock()
    ib_client.fills.return_value = [_fill("MES")]
    is_stale, last_known, unexplained = classify_positions_staleness(
        result, {"MES": 5.0}, ib_client
    )
    assert is_stale is False
    assert last_known == {}
    assert unexplained == []


def test_unexplained_empty_flip_is_stale():
    """The exact 2026-08-03/08-10 failure signature: previously held 5 MES,
    now reads empty, no fill on record to explain it."""
    result = []
    ib_client = MagicMock()
    ib_client.fills.return_value = []
    is_stale, last_known, unexplained = classify_positions_staleness(
        result, {"MES": 5.0}, ib_client
    )
    assert is_stale is True
    assert last_known == {"MES": 5.0}
    assert unexplained == ["MES"]


def test_partial_fill_evidence_still_flags_unexplained_symbol():
    """Held MES + MGC; only MES has a fill on record -- MGC's disappearance is
    still unexplained and must not be masked by MES's legitimate close."""
    result = []
    ib_client = MagicMock()
    ib_client.fills.return_value = [_fill("MES")]
    is_stale, last_known, unexplained = classify_positions_staleness(
        result, {"MES": 5.0, "MGC": 1.0}, ib_client
    )
    assert is_stale is True
    assert unexplained == ["MGC"]


# ── IBGatewayManager.get_positions() integration (reconnect + retry) ────────


def _build_manager() -> IBGatewayManager:
    mgr = IBGatewayManager(IBGatewayConfig(host="127.0.0.1", port=4002, client_id=99))
    mgr._ib = MagicMock()
    mgr._ib.isConnected.return_value = True
    from execution.ib_gateway import IBConnectionStatus

    mgr._status = IBConnectionStatus.CONNECTED
    return mgr


@pytest.mark.asyncio
async def test_get_positions_reconnects_and_resyncs_on_stale_signature():
    mgr = _build_manager()
    mgr._last_known_positions = {"MES": 5.0}

    # First call (pre-reconnect): both empty, no fill evidence -> stale.
    # Second call (post-reconnect retry): resync succeeds, position reappears.
    call_count = {"n": 0}

    async def _req_positions():
        call_count["n"] += 1
        if call_count["n"] == 1:
            return []
        return [_pos("MES", 5.0)]

    mgr._ib.reqPositionsAsync = _req_positions
    mgr._ib.positions.return_value = []
    mgr._ib.fills.return_value = []
    mgr.reconnect = AsyncMock(return_value=True)

    result = await mgr.get_positions()

    mgr.reconnect.assert_awaited_once()
    assert len(result) == 1
    assert result[0]["symbol"] == "MES"
    assert mgr.positions_stale() is False


@pytest.mark.asyncio
async def test_get_positions_surfaces_stale_flag_when_reconnect_cannot_resync():
    mgr = _build_manager()
    mgr._last_known_positions = {"MES": 5.0}
    mgr._ib.reqPositionsAsync = AsyncMock(return_value=[])
    mgr._ib.positions.return_value = []
    mgr._ib.fills.return_value = []
    mgr.reconnect = AsyncMock(return_value=True)

    result = await mgr.get_positions()

    assert result == []
    assert mgr.positions_stale() is True


@pytest.mark.asyncio
async def test_get_positions_legitimate_flatten_clears_stale_flag():
    mgr = _build_manager()
    mgr._last_known_positions = {"MES": 5.0}
    mgr._ib.reqPositionsAsync = AsyncMock(return_value=[])
    mgr._ib.positions.return_value = []
    mgr._ib.fills.return_value = [_fill("MES")]
    mgr.reconnect = AsyncMock(return_value=False)

    result = await mgr.get_positions()

    mgr.reconnect.assert_not_called()
    assert result == []
    assert mgr.positions_stale() is False
