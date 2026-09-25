"""TOSRTDConnector — thinkorswim desktop RTD (market-data waterfall Tier 0).

These are OFFLINE tests: no thinkorswim, no COM, no port 12001. The connector's
contract with the waterfall is what is pinned here — a live TOS is exercised
separately by ``scripts/tos_rtd_probe.py``.

The threading test at the bottom is a regression guard for the single nastiest
failure mode found while building this adapter: ``RTDService.dll`` registers no
``ThreadingModel``, so COM treats it as Apartment-threaded and the object must be
created in the process's FIRST apartment. Driving it from a worker thread while
anything else had already touched COM made ``ServerStart`` hang forever, with no
exception — a silent Tier-0 outage. The adapter therefore creates and uses the
session on the calling (event-loop) thread and must never grow a COM worker
thread or an eager ``win32com`` import.
"""

from __future__ import annotations

import asyncio
import socket
import subprocess
import sys
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from data import market_data as market_data_module
from data import provenance
from data.market_data import MarketDataManager
from data.tos_rtd_adapter import (
    SOURCE_TOS_RTD,
    TOS_RTD_SYMBOLS,
    TOSRTDConnector,
    _coerce_value,
    _option_root,
    default_weekly_expiry,
    probe_tcp_handshake,
    resolve_tos_symbol,
)

ENGINE_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _disable_other_tier0_sources(monkeypatch):
    """TV Tier 0 intercepts before IBKR whenever TradingView Desktop is running.

    Same rationale as test_market_data_waterfall._disable_tv_tier_0.
    """
    monkeypatch.setattr(market_data_module, "_tv_feed", None)


class _MinimalConfig:
    IBKR_HOST = "127.0.0.1"
    IBKR_PORT = 4002
    IBKR_CLIENT_ID = 1
    POLYGON_API_KEY = ""
    FINNHUB_API_KEY = ""
    FRED_API_KEY = None


def _manager_with_tos(tos) -> MarketDataManager:
    mgr = MarketDataManager(_MinimalConfig())
    mgr.inject_tos_rtd(tos)
    return mgr


def _fake_rtd(*, connected=True, last=767.18, bid=769.7, ask=769.74, prev=767.0):
    """Stand-in with the same attribute/callable shape as TOSRTDConnector."""
    fake = MagicMock()
    fake.is_connected = connected
    fake.get_current_price = AsyncMock(
        return_value={
            "last_price": last,
            "prev_close": prev,
            "change_pct": None if not (last and prev) else ((last - prev) / prev) * 100.0,
            "bid": bid,
            "ask": ask,
            "as_of": 1_760_000_000.0,
            "source": SOURCE_TOS_RTD,
        }
    )
    fake.get_options_chain = AsyncMock(return_value=[])
    return fake


# ── symbol mapping ──────────────────────────────────────────────────────────


def test_resolve_tos_symbol_maps_engine_conventions() -> None:
    """MES needs the exchange suffix: bare 'MES' returns 0.0 from TOS and
    '/MES' returns 'N/A' — only '/MES:XCME' prices (verified live)."""
    assert resolve_tos_symbol("MES") == "/MES:XCME"
    assert resolve_tos_symbol("mes") == "/MES:XCME"
    assert resolve_tos_symbol("ES") == "/ES:XCME"
    assert resolve_tos_symbol("SPY") == "SPY"
    assert resolve_tos_symbol("QQQ") == "QQQ"
    assert resolve_tos_symbol("VIX") == "VIX"


def test_resolve_tos_symbol_handles_caret_index_convention() -> None:
    """The engine's index convention (^VIX) must not be sent to TOS verbatim —
    '$VIX.X' and 'VIX.X' both fail; the bare 'VIX' root is what prices."""
    assert resolve_tos_symbol("^VIX") == "VIX"
    assert resolve_tos_symbol("^spy") == "SPY"


def test_resolve_tos_symbol_passes_through_native_tos_symbols() -> None:
    assert resolve_tos_symbol("/MES:XCME") == "/MES:XCME"
    assert resolve_tos_symbol(".SPY260925C763") == ".SPY260925C763"
    assert resolve_tos_symbol("AAPL") == "AAPL"


def test_resolve_tos_symbol_rejects_nonsense() -> None:
    """Unresolvable input must return None so the tier falls through — never a
    live subscription to garbage that would silently return 'N/A'."""
    assert resolve_tos_symbol("") is None
    assert resolve_tos_symbol(None) is None
    assert resolve_tos_symbol("SPY260925C763") is None  # unbalanced option form
    assert resolve_tos_symbol("12345") is None
    assert resolve_tos_symbol("TOOLONGTICKER") is None


def test_option_root_is_limited_to_supported_etfs() -> None:
    assert _option_root("SPY") == "SPY"
    assert _option_root("^VIX") == "VIX"
    assert _option_root("MES") is None  # futures options are out of scope


def test_default_weekly_expiry_lands_on_a_friday() -> None:
    exp = default_weekly_expiry(date(2026, 9, 22))  # Tuesday
    assert exp.weekday() == 4
    assert exp == date(2026, 9, 25)
    # A Friday maps to itself, never to next week.
    assert default_weekly_expiry(date(2026, 9, 25)) == date(2026, 9, 25)


# ── value coercion (the "never emit a silent zero" invariant) ───────────────


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("N/A", None),
        ("n/a", None),
        ("", None),
        ("   ", None),
        ("-", None),
        (None, None),
        ("NaN", None),
        (float("nan"), None),
        (float("inf"), None),
        (True, None),
        ("15.43", 15.43),
        ("$1,234.50", 1234.50),
        (767.18, 767.18),
        (0, 0.0),
        (0.0, 0.0),
        ([15.5], 15.5),
    ],
)
def test_coerce_value_never_fabricates_a_price(raw, expected) -> None:
    assert _coerce_value(raw) == expected


# ── transport pre-flight ────────────────────────────────────────────────────


def test_probe_tcp_handshake_reports_dead_port_without_raising() -> None:
    """Port 1 is never TOS. The probe is a pre-flight, so it must report
    failure as data — an exception here would abort the whole tier."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        free_port = probe.getsockname()[1]  # bound then closed: nothing listens

    result = probe_tcp_handshake(port=free_port, timeout_s=1.0)

    assert result["ok"] is False
    assert result["error"]
    assert result["banner"] is None


# ── disconnected / disabled behaviour ───────────────────────────────────────


def test_is_connected_is_falsy_when_disconnected_in_both_styles() -> None:
    """The waterfall reads `connector.is_connected` as a plain attribute while
    the documented contract is `is_connected()`. Both must work, and a missed
    call must NOT read as connected."""
    conn = TOSRTDConnector()
    assert bool(conn.is_connected) is False
    assert bool(conn.is_connected()) is False
    # Attribute-then-call must not raise either.
    assert conn.is_connected() is False


@pytest.mark.asyncio
async def test_get_current_price_without_session_returns_all_none() -> None:
    conn = TOSRTDConnector()
    out = await conn.get_current_price("SPY")

    assert out["source"] == SOURCE_TOS_RTD
    for field in ("last_price", "bid", "ask", "prev_close", "change_pct"):
        assert out[field] is None, f"{field} must be None, never a silent zero"
    assert out["tos_symbol"] is None  # nothing was even resolved/subscribed


@pytest.mark.asyncio
async def test_get_options_chain_without_session_returns_empty() -> None:
    conn = TOSRTDConnector()
    assert await conn.get_options_chain("SPY") == []


@pytest.mark.asyncio
async def test_disabled_connector_is_inert() -> None:
    conn = TOSRTDConnector(enabled=False)
    assert bool(conn.is_connected) is False
    assert await conn.get_current_price("SPY") is not None  # shape preserved
    assert (await conn.get_current_price("SPY"))["last_price"] is None
    assert await conn.get_options_chain("SPY") == []


@pytest.mark.asyncio
async def test_options_chain_returns_empty_for_unsupported_root() -> None:
    conn = TOSRTDConnector()
    conn._session._server_started = True
    conn._session._last_heartbeat_ok = True
    conn._session._last_heartbeat_at = __import__("time").time()

    assert bool(conn.is_connected) is True  # session is up...
    assert await conn.get_options_chain("MES") == []  # ...but MES has no chain


@pytest.mark.asyncio
async def test_status_is_serialisable_and_never_raises() -> None:
    conn = TOSRTDConnector()
    status = conn.status()

    assert status["enabled"] is True
    assert status["port"] == 12001
    assert status["source"] == SOURCE_TOS_RTD
    assert status["connected"] is False
    assert isinstance(status["watch_symbols"], list)


# ── waterfall integration ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_waterfall_tier0_tos_rtd_wins_over_ibkr() -> None:
    """Tier 0 sits ahead of IBKR: a heartbeating RTD session is the freshest
    broker-direct source, so IBKR must not even be consulted."""
    mgr = _manager_with_tos(_fake_rtd(last=767.18))
    mock_ib = MagicMock()
    mock_ib.is_connected = True
    mock_ib.get_snapshot_price = AsyncMock(return_value={"last_price": 111.0, "source": "ibkr"})
    mgr.ibkr = mock_ib

    out = await mgr.get_current_price("SPY")

    assert out["source"] == "rtd_tos"
    assert out["last_price"] == 767.18
    assert out["bid"] == 769.7 and out["ask"] == 769.74
    mock_ib.get_snapshot_price.assert_not_awaited()


@pytest.mark.asyncio
async def test_waterfall_falls_through_when_tos_rtd_returns_no_price() -> None:
    """A disconnected session (or a mute topic) must fall through to IBKR
    without side effects."""
    fake = _fake_rtd(connected=False)
    mgr = _manager_with_tos(fake)
    mock_ib = MagicMock()
    mock_ib.is_connected = True
    mock_ib.get_snapshot_price = AsyncMock(return_value={"last_price": 325.89, "source": "ibkr"})
    mgr.ibkr = mock_ib

    out = await mgr.get_current_price("AAPL")

    assert out["source"] == "ibkr"
    assert out["last_price"] == 325.89
    fake.get_current_price.assert_not_awaited()


@pytest.mark.asyncio
async def test_waterfall_ignores_zero_price_from_tos_rtd() -> None:
    """0.0 is falsy and must not be promoted to last_price — otherwise a mute
    feed would look like a $0 quote (the documented silent-zero failure)."""
    mgr = _manager_with_tos(_fake_rtd(last=0.0, bid=0.0, ask=0.0, prev=0.0))
    mock_ib = MagicMock()
    mock_ib.is_connected = True
    mock_ib.get_snapshot_price = AsyncMock(return_value={"last_price": 767.18, "source": "ibkr"})
    mgr.ibkr = mock_ib

    out = await mgr.get_current_price("SPY")

    assert out["source"] == "ibkr"
    assert out["last_price"] == 767.18


@pytest.mark.asyncio
async def test_waterfall_survives_a_raising_tos_rtd() -> None:
    """The tier is best-effort: an exception (COM fault, TOS closing mid-read)
    must be swallowed and the waterfall must continue."""
    fake = MagicMock()
    fake.is_connected = True
    fake.get_current_price = AsyncMock(side_effect=RuntimeError("COM fault"))
    mgr = _manager_with_tos(fake)
    mock_ib = MagicMock()
    mock_ib.is_connected = True
    mock_ib.get_snapshot_price = AsyncMock(return_value={"last_price": 741.1, "source": "ibkr"})
    mgr.ibkr = mock_ib

    out = await mgr.get_current_price("QQQ")

    assert out["source"] == "ibkr"
    assert out["last_price"] == 741.1


@pytest.mark.asyncio
async def test_inject_tos_rtd_is_skippable_and_reversible() -> None:
    """Injection is opt-in: absent connector means the tier is simply not there
    (no AttributeError on a manager that never received one)."""
    mgr = MarketDataManager(_MinimalConfig())
    assert mgr.tos_rtd is None

    mgr.inject_tos_rtd(_fake_rtd())
    assert mgr.tos_rtd is not None
    mgr.inject_tos_rtd(None)
    assert mgr.tos_rtd is None


@pytest.mark.asyncio
async def test_get_tick_price_uses_tos_rtd_tier0() -> None:
    mgr = _manager_with_tos(_fake_rtd(last=767.18))
    mock_ib = MagicMock()
    mock_ib.is_connected = True
    mock_ib.get_snapshot_price = AsyncMock(return_value={"last_price": 111.0, "source": "ibkr"})
    mgr.ibkr = mock_ib

    out = await mgr.get_tick_price("SPY")

    assert out["source"] == "rtd_tos"
    assert out["last_price"] == 767.18
    mock_ib.get_snapshot_price.assert_not_awaited()


# ── provenance ──────────────────────────────────────────────────────────────


def test_rtd_tos_is_a_live_source() -> None:
    """Without this, build_envelope() would classify a genuinely live RTD
    quote as non-live and downgrade freshness downstream."""
    assert SOURCE_TOS_RTD == "rtd_tos"
    assert SOURCE_TOS_RTD in provenance.LIVE_SOURCES


def test_build_envelope_marks_fresh_rtd_tos_as_live() -> None:
    import time

    env = provenance.build_envelope(
        value=767.18,
        source=SOURCE_TOS_RTD,
        as_of=time.time(),
        stale_after_s=60.0,
        ibkr_data_connected=False,
    )
    assert env.is_live is True
    assert env.source == SOURCE_TOS_RTD


def test_build_envelope_marks_stale_rtd_tos_as_not_live() -> None:
    """RTD only pushes CHANGES, so a quiet symbol's cached value must be judged
    by its age, not by the feed merely existing."""
    import time

    env = provenance.build_envelope(
        value=767.18,
        source=SOURCE_TOS_RTD,
        as_of=time.time() - 3600.0,
        stale_after_s=60.0,
        ibkr_data_connected=False,
    )
    assert env.is_live is False


# ── regression guards: COM apartment safety ─────────────────────────────────


def test_adapter_import_does_not_touch_com() -> None:
    """Importing the adapter must not import pywin32/pythoncom.

    If it did, importing the engine anywhere would initialise COM on whatever
    thread got there first — and because RTDService.dll is Apartment-threaded
    with no ThreadingModel, that is exactly the condition that makes a later
    RTD ServerStart hang forever. Import must stay lazy.
    """
    code = (
        "import sys; sys.path.insert(0, r'%s'); "
        "import data.tos_rtd_adapter as a; "
        "assert a.TOSRTDConnector() is not None; "
        "bad = [m for m in ('win32com', 'win32com.client', 'pythoncom', "
        "'comtypes') if m in sys.modules]; "
        "print(','.join(bad))" % str(ENGINE_ROOT)
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=120
    )

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "", f"adapter import pulled in COM: {proc.stdout!r}"


def test_session_has_no_com_worker_thread() -> None:
    """Guard the architecture, not just today's behaviour: the RTD session must
    stay on the calling thread. A re-introduced worker thread would bring back
    the silent, exception-free ServerStart hang."""
    from data.tos_rtd_adapter import _RtdSession

    session = _RtdSession()
    assert not hasattr(session, "_thread"), "RTD session must not own a COM worker thread"
    assert not hasattr(session, "_jobs"), "RTD session must not queue work to another thread"

    # And the connect path must not defer COM setup to another thread. (The TCP
    # pre-flight may use to_thread — it touches no COM — but the session start
    # specifically must stay on the calling thread.)
    import inspect

    connector_src = inspect.getsource(TOSRTDConnector.connect)
    assert "run_in_executor" not in connector_src, (
        "connect() must not move COM setup onto an executor thread"
    )
    for pattern in ("to_thread(self._session", "to_thread(self._rtd", "to_thread(connector"):
        assert pattern not in connector_src, (
            f"connect() must not move COM setup onto a worker thread ({pattern})"
        )
    assert "self._session.start()" in connector_src, (
        "connect() must call the RTD session start inline on the calling thread"
    )


@pytest.mark.asyncio
async def test_close_is_idempotent_and_never_raises() -> None:
    conn = TOSRTDConnector()
    await conn.close()
    await conn.close()
    assert bool(conn.is_connected) is False


@pytest.mark.asyncio
async def test_keepwarm_task_is_cancelled_on_close() -> None:
    """No leaked asyncio task after teardown."""
    conn = TOSRTDConnector()
    conn._start_keepwarm()
    assert conn._keepwarm_task is not None
    task = conn._keepwarm_task

    await conn.close()

    assert conn._keepwarm_task is None
    assert task.cancelled() or task.done()
    await asyncio.sleep(0)  # let the cancellation settle


def test_symbol_table_covers_the_required_watchlist() -> None:
    """Scope is MES/SPY/QQQ/VIX (per the task constraints) — if someone widens
    it, this test should be updated deliberately rather than silently."""
    assert set(TOS_RTD_SYMBOLS) == {"MES", "ES", "MNQ", "NQ", "SPY", "QQQ", "VIX"}
