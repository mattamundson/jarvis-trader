"""Offline tests for IBKR contract qualification (conId before tickers/streaming)."""

from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

import data.market_data as market_data_module
from data.market_data import IBKRDataConnector, MarketDataManager


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


def test_make_contract_uses_cbot_for_treasury_futures():
    """ZB/ZN must build on exchange CBOT, not the CME default.

    Bug 2026-06-26: FUTURES_EXCHANGE had no ZB/ZN entry, so the lookup defaulted to
    'CME'. IB rejected the nonexistent CME contract (Error 200 'no security
    definition') -> _resolve_front_month returned None -> historical fetch crashed
    on None.includeExpired -> waterfall served a stale CSV cache, freezing the ZB/ZN
    forward-shadow at 2026-06-24. ZB/ZN trade on CBOT. MES/MNQ are genuinely CME and
    must be unaffected (regression guard).
    """
    conn = IBKRDataConnector()
    assert conn._make_contract("ZB", True).exchange == "CBOT"
    assert conn._make_contract("ZN", True).exchange == "CBOT"
    # lowercase symbol must resolve the same (lookup uppercases)
    assert conn._make_contract("zb", True).exchange == "CBOT"
    # regression: CME index futures unchanged
    assert conn._make_contract("MES", True).exchange == "CME"
    assert conn._make_contract("MNQ", True).exchange == "CME"


def test_make_contract_exchange_for_copper_and_dow_micros():
    """MHG (copper) is COMEX and MYM (E-mini Dow) is CBOT — not the CME default.

    Same bug class as the ZB/ZN freeze (2026-06-26): both symbols are declared in
    mtf_analyzer._FUTURES_SYMBOLS but were absent from FUTURES_EXCHANGE, so the lookup
    defaulted them to 'CME'. A live bar fetch would then build a nonexistent CME
    contract -> IB Error 200 -> None contract -> stale-cache/404. Copper trades on
    COMEX; the Dow (YM/MYM) trades on CBOT. M2K (Russell micro) IS genuinely CME, so
    its CME default is correct and must stay that way (regression guard).
    """
    conn = IBKRDataConnector()
    assert conn._make_contract("MHG", True).exchange == "COMEX"  # micro copper
    assert conn._make_contract("HG", True).exchange == "COMEX"  # full copper
    assert conn._make_contract("MYM", True).exchange == "CBOT"  # micro Dow
    assert conn._make_contract("YM", True).exchange == "CBOT"  # full Dow
    # regression: Russell 2000 micro is correctly CME-by-default
    assert conn._make_contract("M2K", True).exchange == "CME"


# ---------------------------------------------------------------------------
# Delayed-tick tagging (2026-07-09) — a marketDataType 3/4 snapshot is a
# 15-20min-old quote, not a live one; entry_price_sanity's offline-fallback
# anchor and PaperStopMonitor's live-source allowlist both key off `source`
# to catch this, so get_snapshot_price must tag it distinctly.
# ---------------------------------------------------------------------------


def _fake_ticker(last: float, close: float, market_data_type: int) -> MagicMock:
    t = MagicMock()
    t.last = last
    t.close = close
    t.marketDataType = market_data_type
    return t


@pytest.mark.asyncio
async def test_get_snapshot_price_tags_live_marketdatatype_as_ibkr():
    conn = IBKRDataConnector()
    mock_ib = MagicMock()
    mock_ib.reqTickersAsync = AsyncMock(return_value=[_fake_ticker(228.5, 227.0, 1)])
    conn._ib = mock_ib
    conn._connected = True

    out = await conn.get_snapshot_price("AAPL", is_futures=False)
    assert out["source"] == "ibkr"
    assert out["last_price"] == 228.5


# ---------------------------------------------------------------------------
# GT-22 regression (2026-07-27): IBKR duration_map used to top out at 365
# days -> "1 Y", and `next(..., "1 M")` silently fell back to a 1-MONTH
# request for any lookback_days beyond that. /regime/vix-percentile's default
# lookback=252 + momentum_window=63 needs ~514 calendar days of daily bars,
# so it was quietly served ~21 daily bars from IBKR while its own response
# still labeled itself lookback=252 -- a dishonest label, not just a data gap.
# ---------------------------------------------------------------------------


def _empty_bars_df() -> pd.DataFrame:
    return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])


@pytest.mark.asyncio
async def test_get_bars_uses_multiyear_duration_for_long_lookback(monkeypatch):
    """A 514-day lookback (vix-percentile's default lookback+momentum_window
    window) must request more than 1 month of IBKR history -- it must land in
    a 2-year bucket, not silently fall back to the 1-month default."""
    # Force past Tier 0 (TradingView) deterministically, regardless of whether
    # TV Desktop happens to be live on the box running this test.
    monkeypatch.setattr(market_data_module, "_tv_feed", None)
    mgr = MarketDataManager(config=MagicMock())
    fake_ibkr = MagicMock()
    fake_ibkr.is_connected = True
    fake_ibkr.get_historical_bars = AsyncMock(return_value=_empty_bars_df())
    mgr.ibkr = fake_ibkr

    await mgr._get_bars_impl("VIX", lookback_days=514, timeframe="1d", is_futures=False)

    fake_ibkr.get_historical_bars.assert_awaited_once()
    called_args = fake_ibkr.get_historical_bars.await_args
    duration = called_args.args[1] if len(called_args.args) > 1 else called_args.kwargs["duration"]
    assert duration == "2 Y", f"514-day lookback should request '2 Y', got {duration!r}"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "lookback_days,expected_duration",
    [
        (1, "1 D"),
        (7, "1 W"),
        (30, "1 M"),
        (90, "3 M"),
        (180, "6 M"),
        (365, "1 Y"),
        (514, "2 Y"),
        (730, "2 Y"),
        (1000, "3 Y"),
        (1825, "5 Y"),
        (5000, "5 Y"),  # beyond every bucket -> caps at 5 Y, never regresses to 1 M
    ],
)
async def test_get_bars_duration_map_never_falls_back_to_one_month_for_long_windows(
    lookback_days, expected_duration, monkeypatch
):
    monkeypatch.setattr(market_data_module, "_tv_feed", None)
    mgr = MarketDataManager(config=MagicMock())
    fake_ibkr = MagicMock()
    fake_ibkr.is_connected = True
    fake_ibkr.get_historical_bars = AsyncMock(return_value=_empty_bars_df())
    mgr.ibkr = fake_ibkr

    await mgr._get_bars_impl("VIX", lookback_days=lookback_days, timeframe="1d", is_futures=False)

    called_args = fake_ibkr.get_historical_bars.await_args
    duration = called_args.args[1] if len(called_args.args) > 1 else called_args.kwargs["duration"]
    assert duration == expected_duration


@pytest.mark.asyncio
async def test_get_snapshot_price_tags_delayed_marketdatatype_as_ibkr_delayed():
    conn = IBKRDataConnector()
    mock_ib = MagicMock()
    mock_ib.reqTickersAsync = AsyncMock(return_value=[_fake_ticker(228.5, 227.0, 3)])
    conn._ib = mock_ib
    conn._connected = True

    out = await conn.get_snapshot_price("AAPL", is_futures=False)
    assert out["source"] == "ibkr_delayed"
    assert out["last_price"] == 228.5


@pytest.mark.asyncio
async def test_get_snapshot_price_tags_delayed_frozen_marketdatatype_as_ibkr_delayed():
    conn = IBKRDataConnector()
    mock_ib = MagicMock()
    mock_ib.reqTickersAsync = AsyncMock(return_value=[_fake_ticker(228.5, 227.0, 4)])
    conn._ib = mock_ib
    conn._connected = True

    out = await conn.get_snapshot_price("AAPL", is_futures=False)
    assert out["source"] == "ibkr_delayed"


@pytest.mark.asyncio
async def test_get_snapshot_price_tags_frozen_marketdatatype_as_ibkr_not_delayed():
    """marketDataType 2 (Frozen, non-delayed) is out of scope for this tag —
    only 3/4 (Delayed/Delayed-frozen) mean the price value itself is stale."""
    conn = IBKRDataConnector()
    mock_ib = MagicMock()
    mock_ib.reqTickersAsync = AsyncMock(return_value=[_fake_ticker(228.5, 227.0, 2)])
    conn._ib = mock_ib
    conn._connected = True

    out = await conn.get_snapshot_price("AAPL", is_futures=False)
    assert out["source"] == "ibkr"
