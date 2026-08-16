"""Regression tests for classify_positions_staleness() — salvaged from the
superseded PR #611 (draft, [safety-review] fix(brokers): read-only
real-broker fallback for /brokers/positions).

Background: #611 bundled two independent changes. Its read-only-fallback
mechanism for GET /brokers/positions (a settable `_real_ibkr` object) has
since been superseded by a different, already-merged mechanism on master —
`_real_ibkr()`, a lazily-resolving function (see PR #608, commit ff6a9232,
and PR #617, commit b0422bb9, in engine/routers/brokers_router.py). That part
of #611 is NOT reused here; master's existing `_real_ibkr()` approach stays
as-is.

What #611 also introduced, and what master genuinely still lacks, is
position-staleness classification: reqPositionsAsync() AND the local
position cache can BOTH come back empty even though a real position exists
on the account (the 2026-08-03 MES overage incident's failure signature) —
but "both empty" is ALSO exactly what a genuinely flat account looks like,
so naive emptiness-as-staleness would false-positive on every legitimate
flatten. classify_positions_staleness() resolves this by comparing against
the caller's last confirmed non-zero snapshot and cross-checking IB fills:
an unexplained flip to empty (no matching fill on record) is flagged stale
and triggers one reconnect+retry; a flip explained by a fill is not.

This is a fresh, minimal cherry-pick of just that classification concept
against current master — not a rebase of #611. It deliberately avoids two
real bugs #611's own commit had:
  1. `classify_positions_staleness()` was defined at module level but
     inserted BETWEEN two IBGatewayManager methods with class-method (4
     space) indentation on the code that followed it, silently nesting
     `get_cached_position`, `get_portfolio_value`, `get_executions`,
     `health_check`, `__aenter__`, `__aexit__`, and `__repr__` as unreachable
     local functions inside `classify_positions_staleness` instead of
     leaving them as IBGatewayManager methods. Here the function is placed
     cleanly AFTER the class body ends (see execution/ib_gateway.py) — this
     test file's method-resolution-order check below (`test_...` reading
     `IBGatewayManager.get_cached_position` etc.) guards that regression.
  2. `engine/data/market_data.py` already independently grew its own
     `IBKRDataConnector.get_positions()` (PR #608 follow-up, 2026-08-11) --
     a different implementation from #611's version of the same method.
     Re-adding #611's version verbatim would have been a silent duplicate
     get_positions() definition (git auto-merges duplicate methods with no
     conflict markers; the second definition silently wins and the first
     becomes dead code). This file wires staleness into the EXISTING
     get_positions() body instead of reintroducing a second one.

Run:
    cd engine
    .venv\\Scripts\\python.exe -m pytest tests/test_positions_staleness_classification.py -v
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
    IBConnectionStatus,
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
    ib_client = MagicMock()
    ib_client.fills.return_value = []
    is_stale, last_known, unexplained = classify_positions_staleness([], {}, ib_client)
    assert is_stale is False
    assert last_known == {}
    assert unexplained == []


def test_holding_position_updates_last_known_and_is_not_stale():
    result = [{"symbol": "MES", "position": 2.0}]
    ib_client = MagicMock()
    is_stale, last_known, unexplained = classify_positions_staleness(result, {}, ib_client)
    assert is_stale is False
    assert last_known == {"MES": 2.0}
    assert unexplained == []


def test_legitimate_flatten_with_matching_fill_is_not_stale():
    ib_client = MagicMock()
    ib_client.fills.return_value = [_fill("MES")]
    is_stale, last_known, unexplained = classify_positions_staleness(
        [], {"MES": 5.0}, ib_client
    )
    assert is_stale is False
    assert last_known == {}
    assert unexplained == []


def test_unexplained_empty_flip_is_stale():
    """The exact 2026-08-03/08-10 failure signature: previously held 5 MES,
    now reads empty, no fill on record to explain it."""
    ib_client = MagicMock()
    ib_client.fills.return_value = []
    is_stale, last_known, unexplained = classify_positions_staleness(
        [], {"MES": 5.0}, ib_client
    )
    assert is_stale is True
    assert last_known == {"MES": 5.0}
    assert unexplained == ["MES"]


def test_partial_fill_evidence_still_flags_unexplained_symbol():
    """Held MES + MGC; only MES has a fill on record -- MGC's disappearance is
    still unexplained and must not be masked by MES's legitimate close."""
    ib_client = MagicMock()
    ib_client.fills.return_value = [_fill("MES")]
    is_stale, last_known, unexplained = classify_positions_staleness(
        [], {"MES": 5.0, "MGC": 1.0}, ib_client
    )
    assert is_stale is True
    assert unexplained == ["MGC"]


def test_fills_lookup_exception_treated_as_no_evidence_not_a_crash():
    """A broken/unreachable ib_client.fills() call must not raise -- it should
    fall back to 'no fill evidence', same as an empty fills list."""
    ib_client = MagicMock()
    ib_client.fills.side_effect = RuntimeError("not connected")
    is_stale, last_known, unexplained = classify_positions_staleness(
        [], {"MES": 5.0}, ib_client
    )
    assert is_stale is True
    assert unexplained == ["MES"]


# ── Dead-code-orphaning regression guard ─────────────────────────────────────


def test_ibgatewaymanager_retains_all_methods_after_classify_positions_staleness():
    """PR #611's own commit inserted classify_positions_staleness() with
    module-level (0-indent) placement BETWEEN two class methods while the
    methods that followed kept their original 4-space class-method
    indentation -- Python silently parsed those as nested local functions
    INSIDE classify_positions_staleness rather than IBGatewayManager methods,
    orphaning get_cached_position, get_portfolio_value, get_executions,
    health_check, __aenter__, __aexit__, and __repr__ as unreachable dead
    code. This asserts every one of those methods is still reachable as a
    real IBGatewayManager attribute."""
    for name in (
        "get_positions",
        "get_cached_position",
        "get_portfolio_value",
        "get_executions",
        "health_check",
        "__aenter__",
        "__aexit__",
        "__repr__",
        "positions_stale",
    ):
        assert hasattr(IBGatewayManager, name), (
            f"IBGatewayManager.{name} missing -- classify_positions_staleness "
            "placement may have orphaned it as dead code (the #611 bug)"
        )
    assert callable(classify_positions_staleness)


# ── IBGatewayManager.get_positions() integration (reconnect + retry) ────────


def _build_manager() -> IBGatewayManager:
    mgr = IBGatewayManager(IBGatewayConfig(host="127.0.0.1", port=4002, client_id=99))
    mgr._ib = MagicMock()
    mgr._ib.isConnected.return_value = True
    mgr._status = IBConnectionStatus.CONNECTED
    return mgr


@pytest.mark.asyncio
async def test_get_positions_reconnects_and_resyncs_on_stale_signature():
    mgr = _build_manager()
    mgr._last_known_positions = {"MES": 5.0}

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
async def test_get_positions_legitimate_flatten_clears_stale_flag_no_reconnect():
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


@pytest.mark.asyncio
async def test_get_positions_first_ever_read_holding_position_not_stale():
    """No prior last_known snapshot yet (first call since startup) -- holding
    a real position must not be misclassified as stale."""
    mgr = _build_manager()
    mgr._ib.reqPositionsAsync = AsyncMock(return_value=[_pos("MES", 2.0)])
    mgr._ib.positions.return_value = []
    mgr.reconnect = AsyncMock()

    result = await mgr.get_positions()

    mgr.reconnect.assert_not_called()
    assert len(result) == 1
    assert mgr.positions_stale() is False
    assert mgr._last_known_positions == {"MES": 2.0}


# ── IBKRDataConnector.get_positions() integration (data leg) ────────────────


def _build_connector():
    from data.market_data import IBKRDataConnector

    conn = IBKRDataConnector()
    conn._ib = MagicMock()
    conn._ib.isConnected.return_value = True
    conn._connected = True
    return conn


@pytest.mark.asyncio
async def test_data_leg_get_positions_surfaces_stale_flag_when_reconnect_fails():
    """This is the connector GET /brokers/positions actually calls via
    _real_ibkr() on current master -- confirms the staleness wiring reaches
    the path that matters, not just the order-routing IBGatewayManager."""
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
    conn.disconnect.assert_awaited_once()
    conn.connect.assert_awaited_once()


@pytest.mark.asyncio
async def test_data_leg_get_positions_legitimate_flatten_is_not_stale():
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


# ── brokers_router surfacing ──────────────────────────────────────────────


def test_broker_positions_endpoint_surfaces_positions_stale_flag():
    """GET /brokers/positions must surface the read-only data leg's
    positions_stale() result under ibkr.positions_stale, using master's
    existing _real_ibkr() resolution (PR #608/#617) -- not #611's superseded
    settable-object mechanism."""
    from types import SimpleNamespace

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from routers.brokers_router import inject_dependencies
    from routers.brokers_router import router as brokers_router

    real_mock = MagicMock()
    real_mock.is_connected = True
    real_mock.get_positions = AsyncMock(return_value=[])
    real_mock.positions_stale.return_value = True

    inject_dependencies(ibkr=None, data_manager=SimpleNamespace(ibkr=real_mock))

    app = FastAPI()
    app.include_router(brokers_router)
    client = TestClient(app, headers={"X-API-Key": os.environ["API_KEY"]})

    resp = client.get("/brokers/positions")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ibkr"]["connected"] is True
    assert body["ibkr"]["positions_stale"] is True


def test_broker_positions_endpoint_defaults_stale_false_when_fresh():
    from types import SimpleNamespace

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from routers.brokers_router import inject_dependencies
    from routers.brokers_router import router as brokers_router

    real_mock = MagicMock()
    real_mock.is_connected = True
    real_mock.get_positions = AsyncMock(
        return_value=[
            {
                "symbol": "MES",
                "sec_type": "FUT",
                "exchange": "CME",
                "currency": "USD",
                "position": 2.0,
                "avg_cost": 7762.0,
                "market_price": None,
                "market_value": None,
                "unrealized_pnl": None,
                "account": "DUR375089",
            }
        ]
    )
    real_mock.positions_stale.return_value = False

    inject_dependencies(ibkr=None, data_manager=SimpleNamespace(ibkr=real_mock))

    app = FastAPI()
    app.include_router(brokers_router)
    client = TestClient(app, headers={"X-API-Key": os.environ["API_KEY"]})

    resp = client.get("/brokers/positions")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ibkr"]["positions_stale"] is False
    symbols = {p["symbol"] for p in body["ibkr"]["positions"]}
    assert "MES" in symbols
