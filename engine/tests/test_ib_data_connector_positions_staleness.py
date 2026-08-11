"""Regression tests for IBKRDataConnector.get_positions() -- the 2026-08-10
read-only real-broker position check.

Origin: /brokers/positions previously had NO live check against the real
broker when IB_PAPER_BROKER_ENABLED=False (the order-routing side is then an
in-process simulator that never talks to IB). This method reuses the data
leg's always-on connection -- up regardless of that flag -- purely for reads,
so a real position placed outside the engine's own order path is still
visible. Same staleness-detection contract as IBGatewayManager.get_positions()
(see test_ib_gateway_positions_staleness.py); these tests confirm the
IBKRDataConnector wiring specifically (reqPositionsAsync/cache/reconnect glue
differ from IBGatewayManager's).

Run:
    cd engine
    .venv\\Scripts\\python.exe -m pytest tests/test_ib_data_connector_positions_staleness.py -v
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from data.market_data import IBKRDataConnector


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


def _build_connector() -> IBKRDataConnector:
    conn = IBKRDataConnector()
    conn._ib = MagicMock()
    conn._ib.isConnected.return_value = True
    conn._connected = True
    return conn


@pytest.mark.asyncio
async def test_not_connected_returns_empty_without_side_effects():
    conn = IBKRDataConnector()
    result = await conn.get_positions()
    assert result == []
    assert conn.positions_stale() is False


@pytest.mark.asyncio
async def test_holding_position_is_not_stale():
    conn = _build_connector()
    conn._ib.reqPositionsAsync = AsyncMock(return_value=[_pos("MES", 2.0)])
    conn._ib.positions.return_value = []

    result = await conn.get_positions()

    assert len(result) == 1
    assert result[0]["symbol"] == "MES"
    assert result[0]["position"] == 2.0
    assert conn.positions_stale() is False


@pytest.mark.asyncio
async def test_falls_back_to_cache_when_reqpositions_empty():
    conn = _build_connector()
    conn._ib.reqPositionsAsync = AsyncMock(return_value=[])
    conn._ib.positions.return_value = [_pos("MES", 2.0)]

    result = await conn.get_positions()

    assert len(result) == 1
    assert result[0]["symbol"] == "MES"


@pytest.mark.asyncio
async def test_unexplained_empty_flip_reconnects_and_resyncs():
    conn = _build_connector()
    conn._last_known_positions = {"MES": 3.0}

    call_count = {"n": 0}

    async def _req_positions():
        call_count["n"] += 1
        return [] if call_count["n"] == 1 else [_pos("MES", 3.0)]

    conn._ib.reqPositionsAsync = _req_positions
    conn._ib.positions.return_value = []
    conn._ib.fills.return_value = []
    conn.connect = AsyncMock(return_value=True)
    conn.disconnect = AsyncMock()

    result = await conn.get_positions()

    conn.disconnect.assert_awaited_once()
    conn.connect.assert_awaited_once()
    assert len(result) == 1
    assert conn.positions_stale() is False


@pytest.mark.asyncio
async def test_stale_flag_surfaces_when_reconnect_cannot_resync():
    conn = _build_connector()
    conn._last_known_positions = {"MES": 3.0}
    conn._ib.reqPositionsAsync = AsyncMock(return_value=[])
    conn._ib.positions.return_value = []
    conn._ib.fills.return_value = []
    conn.connect = AsyncMock(return_value=True)
    conn.disconnect = AsyncMock()

    result = await conn.get_positions()

    assert result == []
    assert conn.positions_stale() is True


@pytest.mark.asyncio
async def test_legitimate_flatten_with_fill_evidence_is_not_stale():
    conn = _build_connector()
    conn._last_known_positions = {"MES": 3.0}
    conn._ib.reqPositionsAsync = AsyncMock(return_value=[])
    conn._ib.positions.return_value = []
    conn._ib.fills.return_value = [_fill("MES")]
    conn.connect = AsyncMock()
    conn.disconnect = AsyncMock()

    result = await conn.get_positions()

    conn.connect.assert_not_called()
    assert result == []
    assert conn.positions_stale() is False
