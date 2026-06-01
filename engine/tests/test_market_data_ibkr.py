"""Offline tests for IBKR contract qualification (conId before tickers/streaming)."""

from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

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


def _detail(yyyymmdd: str, name: str = "") -> MagicMock:
    """Build a contract-detail mock with the given lastTradeDateOrContractMonth."""
    d = MagicMock()
    d.contract = MagicMock()
    d.contract.lastTradeDateOrContractMonth = yyyymmdd
    d.contract.localSymbol = name or yyyymmdd
    return d


class _FakeDate:
    """Minimal stand-in for `datetime.date` that pins today() for tests."""
    def __init__(self, fixed_today: date):
        self._t = fixed_today
    def today(self) -> date:
        return self._t


@pytest.mark.asyncio
async def test_resolve_front_month_skips_expired_contracts():
    """Regression: with all-month MGC contracts including an expired one,
    _resolve_front_month must return the next live contract, not the expired
    one. Bug observed 2026-05-06: MGCJ6 (expired 2026-04-28) was returned for
    historical fetches dated 2026-05-07 and IBKR responded with empty data.
    """
    expired_april = _detail("20260428", "MGCJ6")
    live_june = _detail("20260626", "MGCM6")
    live_aug = _detail("20260828", "MGCQ6")

    conn = IBKRDataConnector()
    mock_ib = MagicMock()
    # Order shuffled to prove the filter (not just sorting) does the work.
    mock_ib.reqContractDetailsAsync = AsyncMock(return_value=[expired_april, live_june, live_aug])
    conn._ib = mock_ib

    with patch("data.market_data.date", new=_FakeDate(date(2026, 5, 7))):
        out = await conn._resolve_front_month("MGC", "COMEX")

    assert out.localSymbol == "MGCM6", f"expected MGCM6, got {out.localSymbol}"


@pytest.mark.asyncio
async def test_resolve_front_month_falls_back_when_all_expired():
    """If every returned contract is past today (degenerate case), fall back
    to the most-recent expired contract rather than returning the generic
    Future shell with conId=0 (which would skip qualifyContractsAsync)."""
    old1 = _detail("20260128", "MGCG6")
    old2 = _detail("20260328", "MGCJ6")  # most recent of the expired

    conn = IBKRDataConnector()
    mock_ib = MagicMock()
    mock_ib.reqContractDetailsAsync = AsyncMock(return_value=[old1, old2])
    conn._ib = mock_ib

    with patch("data.market_data.date", new=_FakeDate(date(2026, 5, 7))):
        out = await conn._resolve_front_month("MGC", "COMEX")

    assert out.localSymbol == "MGCJ6"
