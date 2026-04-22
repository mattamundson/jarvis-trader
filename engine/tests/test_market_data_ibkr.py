"""Offline tests for IBKR contract qualification (conId before tickers/streaming)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from data.market_data import IBKRDataConnector


@pytest.mark.asyncio
async def test_qualified_contract_skips_qualify_when_conid_present():
    conn = IBKRDataConnector()
    mock_ib = MagicMock()
    mock_ib.qualifyContractsAsync = AsyncMock()
    conn._ib = mock_ib
    conn._connected = True

    resolved = MagicMock()
    resolved.conId = 999
    conn._resolve_front_month = AsyncMock(return_value=resolved)

    out = await conn._qualified_contract("MES", True)
    assert out is resolved
    mock_ib.qualifyContractsAsync.assert_not_called()


@pytest.mark.asyncio
async def test_qualified_contract_calls_qualify_when_no_conid():
    conn = IBKRDataConnector()
    mock_ib = MagicMock()
    qualified = MagicMock()
    qualified.conId = 123456
    mock_ib.qualifyContractsAsync = AsyncMock(return_value=[qualified])
    conn._ib = mock_ib
    conn._connected = True

    unresolved = MagicMock()
    unresolved.conId = 0
    conn._resolve_front_month = AsyncMock(return_value=unresolved)

    out = await conn._qualified_contract("MES", True)
    assert out is qualified
    mock_ib.qualifyContractsAsync.assert_awaited_once()
