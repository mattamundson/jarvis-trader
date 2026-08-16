"""Tests for execution/polymarket_connector.py — PolymarketConnector.

Not a router, so there is no TestClient here; instead we exercise the class
directly and mock its one external dependency, `py_clob_client.client.ClobClient`
(patched at `execution.polymarket_connector.ClobClient`, its import site), plus
the module-level `config.settings` object. No real network call, no real
private key, no real Polygon RPC.

Environment note (also see the PR description's findings — this is a real,
already-partially-known issue, not a test-writing artifact):

This venv has `py-clob-client==0.4.0` + `py-order-utils==0.3.2` installed, and
`execution/polymarket_connector.py` cannot actually be imported against that
pair — `engine/main.py` already guards the import in a try/except with the
comment "py-clob-client<->py-order-utils version skew", so the live engine is
aware ClobClient can fail to import and falls back to `polymarket = None`.
What main.py's guard does NOT cover: even with a matching version pair that
fixes the ClobClient import chain, this module imports `MarketOrderArgs` from
`py_clob_client.clob_types` — a class that does not exist anywhere in the
installed 0.4.0 release (verified: `dir(py_clob_client.clob_types)` has no
such name) — so `place_market_order()`'s import would still be broken. Same
story for `OpenOrderParams`, imported locally inside `get_open_orders()`
(also absent from 0.4.0) — that one only breaks lazily, on the first
authenticated call to `get_open_orders()`, since the import is inside the
method body. `OrderArgs`, `OrderType`, and `BUY` (from
`order_builder.constants`) DO exist in 0.4.0 and import fine standalone.

We stub the two broken import-time symbols (`ClobClient`, `MarketOrderArgs`)
via `monkeypatch.setitem(sys.modules, ...)`, scoped per-test and reverted at
teardown, so this test module exercises the connector's *own* logic (guard
clauses, state transitions, delegation to the client) rather than py-clob-client
internals — and keeps working whether or not this venv's dependency skew is
ever fixed.
"""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip(
    "py_clob_client",
    reason="py-clob-client is in engine/requirements.txt (full dev venv) but not "
    "requirements-core.txt (CI bootstrap) -- skip cleanly there rather than "
    "erroring; the module-level ClobClient/MarketOrderArgs version-skew this "
    "file otherwise exercises assumes the package is at least installed.",
)


def _stub_broken_clob_client_symbols(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub the 2 py_clob_client symbols that don't import in this venv (see module docstring).

    `OrderArgs` / `OrderType` are re-exported from the *real* installed
    `py_clob_client.clob_types` so behavior there stays faithful to the real
    package; only the missing `ClobClient` and `MarketOrderArgs` are faked.
    """
    import py_clob_client.clob_types as real_clob_types  # exists; MarketOrderArgs does not

    client_mod = types.ModuleType("py_clob_client.client")
    client_mod.ClobClient = MagicMock  # placeholder; every test patches this name directly

    clob_types_mod = types.ModuleType("py_clob_client.clob_types")
    clob_types_mod.OrderArgs = real_clob_types.OrderArgs
    clob_types_mod.OrderType = real_clob_types.OrderType
    clob_types_mod.MarketOrderArgs = lambda **kw: types.SimpleNamespace(**kw)
    clob_types_mod.OpenOrderParams = lambda **kw: types.SimpleNamespace(**kw)

    monkeypatch.setitem(sys.modules, "py_clob_client.client", client_mod)
    monkeypatch.setitem(sys.modules, "py_clob_client.clob_types", clob_types_mod)
    # Force a fresh import of the connector so its module-level
    # `from py_clob_client... import ...` binds to the stubs above.
    monkeypatch.delitem(sys.modules, "execution.polymarket_connector", raising=False)


@pytest.fixture()
def connector(monkeypatch):
    """A connector built with real settings defaults (no private key configured).

    `TradingConfig` (`config.settings`) is a pydantic model with no
    `POLYMARKET_*` fields defined at all, so `__init__`'s
    `getattr(settings, "POLYMARKET_HOST", <default>)` calls always fall
    through to their hardcoded defaults regardless — there is nothing to
    monkeypatch on `settings` itself (pydantic rejects assigning undeclared
    fields). Tests that need a private key set `connector.private_key`
    directly on the plain-object connector instance post-construction.
    """
    _stub_broken_clob_client_symbols(monkeypatch)

    from execution.polymarket_connector import PolymarketConnector

    return PolymarketConnector()


# ---------------------------------------------------------------------------
# connect()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connect_without_private_key_is_read_only(connector):
    """No private key -> read-only ClobClient, no authentication attempted."""
    mock_client = MagicMock()
    with patch(
        "execution.polymarket_connector.ClobClient", return_value=mock_client
    ) as MockClobClient:
        ok = await connector.connect()

    assert ok is True
    assert connector.authenticated is False
    assert connector.client is mock_client
    MockClobClient.assert_called_once_with(connector.host)
    mock_client.create_or_derive_api_creds.assert_not_called()


@pytest.mark.asyncio
async def test_connect_with_private_key_authenticates(connector):
    connector.private_key = "0xdeadbeef"

    mock_client = MagicMock()
    mock_creds = MagicMock()
    mock_client.create_or_derive_api_creds.return_value = mock_creds

    with patch("execution.polymarket_connector.ClobClient", return_value=mock_client):
        ok = await connector.connect()

    assert ok is True
    assert connector.authenticated is True
    mock_client.create_or_derive_api_creds.assert_called_once()
    mock_client.set_api_creds.assert_called_once_with(mock_creds)


@pytest.mark.asyncio
async def test_connect_returns_false_on_failure(connector):
    """A raised exception during authentication is swallowed -> False, not authenticated."""
    connector.private_key = "0xdeadbeef"

    with patch(
        "execution.polymarket_connector.ClobClient",
        side_effect=RuntimeError("bad RPC endpoint"),
    ):
        ok = await connector.connect()

    assert ok is False
    assert connector.authenticated is False


# ---------------------------------------------------------------------------
# get_order_book()
# ---------------------------------------------------------------------------


def test_get_order_book_returns_none_without_client(connector):
    assert connector.client is None
    assert connector.get_order_book("token-1") is None


def test_get_order_book_delegates_to_client(connector):
    connector.client = MagicMock()
    connector.client.get_order_book.return_value = {"bids": [], "asks": []}

    result = connector.get_order_book("token-1")

    assert result == {"bids": [], "asks": []}
    connector.client.get_order_book.assert_called_once_with("token-1")


# ---------------------------------------------------------------------------
# place_order()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_place_order_raises_when_not_authenticated(connector):
    assert connector.authenticated is False
    with pytest.raises(RuntimeError, match="Not authenticated"):
        await connector.place_order(token_id="tok-1", price=0.55, size=10.0)


@pytest.mark.asyncio
async def test_place_order_success_posts_signed_order(connector):
    connector.authenticated = True
    connector.client = MagicMock()
    signed = MagicMock()
    connector.client.create_order.return_value = signed
    connector.client.post_order.return_value = {"orderID": "abc123", "success": True}

    resp = await connector.place_order(token_id="tok-1", price=0.55, size=10.0)

    assert resp == {"orderID": "abc123", "success": True}
    connector.client.create_order.assert_called_once()
    connector.client.post_order.assert_called_once()


# ---------------------------------------------------------------------------
# place_market_order()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_place_market_order_raises_when_not_authenticated(connector):
    with pytest.raises(RuntimeError, match="Not authenticated"):
        await connector.place_market_order(token_id="tok-1", amount=25.0)


@pytest.mark.asyncio
async def test_place_market_order_success_posts_signed_order(connector):
    connector.authenticated = True
    connector.client = MagicMock()
    signed = MagicMock()
    connector.client.create_market_order.return_value = signed
    connector.client.post_order.return_value = {"orderID": "xyz789", "success": True}

    resp = await connector.place_market_order(token_id="tok-1", amount=25.0)

    assert resp == {"orderID": "xyz789", "success": True}
    connector.client.create_market_order.assert_called_once()
    connector.client.post_order.assert_called_once()


# ---------------------------------------------------------------------------
# get_open_orders() / cancel_order() / cancel_all()
# ---------------------------------------------------------------------------


def test_get_open_orders_empty_when_not_authenticated(connector):
    assert connector.get_open_orders() == []


def test_get_open_orders_delegates_to_client_when_authenticated(connector):
    connector.authenticated = True
    connector.client = MagicMock()
    connector.client.get_orders.return_value = [{"id": "o1"}]

    result = connector.get_open_orders()

    assert result == [{"id": "o1"}]
    connector.client.get_orders.assert_called_once()


def test_cancel_order_noop_when_not_authenticated(connector):
    assert connector.cancel_order("order-1") is None


def test_cancel_order_delegates_to_client_when_authenticated(connector):
    connector.authenticated = True
    connector.client = MagicMock()
    connector.client.cancel.return_value = {"canceled": ["order-1"]}

    result = connector.cancel_order("order-1")

    assert result == {"canceled": ["order-1"]}
    connector.client.cancel.assert_called_once_with("order-1")


def test_cancel_all_noop_when_not_authenticated(connector):
    assert connector.cancel_all() is None


def test_cancel_all_delegates_to_client_when_authenticated(connector):
    connector.authenticated = True
    connector.client = MagicMock()
    connector.client.cancel_all.return_value = {"canceled": "all"}

    result = connector.cancel_all()

    assert result == {"canceled": "all"}
    connector.client.cancel_all.assert_called_once()
