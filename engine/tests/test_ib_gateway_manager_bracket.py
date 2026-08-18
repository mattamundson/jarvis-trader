"""Hermetic tests for IBGatewayManager.place_bracket_order (P0 — real broker stops).

These prove the native ib_async bracket satisfies the exact drop-in contract of
the simulator's IBGatewayConnector.place_bracket_order (ib_gateway_connector.py:719)
WITHOUT a live IB connection: self._ib is a MagicMock whose placeOrder returns a
Trade with an incrementing orderId, and contract resolution/qualification are
stubbed. _build_order_object is NOT mocked — the tests inspect the REAL ib_async
Order objects to confirm transmit/ocaGroup/ocaType/parentId are wired correctly.

The safety-critical properties under test:
  - parent placed transmit=False; only the LAST leg carries transmit=True
    (atomic bundle — no naked-entry window)
  - both children share an OCA group with ocaType=1 (one fill cancels the other)
  - children carry parentId == entry orderId (broker-side linkage that
    SafetyLayer._verify_parent_linkage confirms via get_order_status)
  - a child failure rolls back every un-transmitted leg and errors out

Run:
    cd engine
    .venv\\Scripts\\python.exe -m pytest tests/test_ib_gateway_manager_bracket.py -v
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock

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

# The bracket method builds real ib_async Order objects; skip the whole module
# if the library is unavailable rather than false-fail.
pytest.importorskip("ib_async")


def _build_bracket_manager(account: str = "", start_id: int = 1000):
    """IBGatewayManager whose fake _ib.placeOrder returns incrementing orderIds.

    The fake Trade wraps the SAME real Order object that was passed in, with an
    orderId stamped on it, so tests can inspect transmit/oca/parentId on the
    actual order the code built and read distinct ids per leg.
    """
    from execution.ib_gateway import IBConnectionStatus, IBGatewayConfig, IBGatewayManager

    mgr = IBGatewayManager(
        IBGatewayConfig(host="127.0.0.1", port=4002, client_id=99, account=account)
    )

    counter = {"n": start_id}

    def _place(contract, order):
        counter["n"] += 1
        order.orderId = counter["n"]
        trade = MagicMock()
        trade.order = order
        return trade

    fake_ib = MagicMock()
    fake_ib.isConnected = MagicMock(return_value=True)
    fake_ib.placeOrder = MagicMock(side_effect=_place)
    fake_ib.cancelOrder = MagicMock()

    mgr._ib = fake_ib
    mgr._status = IBConnectionStatus.CONNECTED

    async def _fake_qualify(contract):
        return contract

    mgr._qualify_contract = _fake_qualify
    mgr._resolve_contract = lambda symbol: MagicMock(symbol=symbol)
    return mgr, fake_ib


def _placed_orders(fake_ib):
    """The Order object from each placeOrder call, in call order."""
    return [call.args[1] for call in fake_ib.placeOrder.call_args_list]


# ── Connectivity / validation gates ────────────────────────────────────────


@pytest.mark.asyncio
async def test_not_connected_returns_error():
    mgr, fake_ib = _build_bracket_manager()
    fake_ib.isConnected = MagicMock(return_value=False)

    result = await mgr.place_bracket_order(
        symbol="MES", action="BUY", quantity=1,
        stop_loss=7000.0, take_profit=7100.0,
    )
    assert result == {"status": "error", "error": "Not connected"}
    assert not fake_ib.placeOrder.called


@pytest.mark.asyncio
@pytest.mark.parametrize("action,quantity", [("HOLD", 1), ("BUY", 0)])
async def test_bad_action_or_qty_rejected(action, quantity):
    mgr, fake_ib = _build_bracket_manager()
    result = await mgr.place_bracket_order(
        symbol="MES", action=action, quantity=quantity,
        stop_loss=7000.0, take_profit=7100.0,
    )
    assert result["status"] == "error"
    assert result["error"] == "Failed to place entry order"
    assert not fake_ib.placeOrder.called


# ── Happy-path contract ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_full_bracket_returns_placed_with_three_ids():
    mgr, fake_ib = _build_bracket_manager(start_id=1000)
    result = await mgr.place_bracket_order(
        symbol="MES", action="BUY", quantity=2,
        entry_type="MKT", stop_loss=7000.0, take_profit=7200.0,
    )
    assert fake_ib.placeOrder.call_count == 3
    assert result == {
        "status": "placed",
        "entry_id": 1001,
        "sl_id": 1002,
        "tp_id": 1003,
        "symbol": "MES",
        "action": "BUY",
        "quantity": 2,
    }
    assert all(isinstance(result[k], int) for k in ("entry_id", "sl_id", "tp_id"))


@pytest.mark.asyncio
async def test_transmit_sequencing():
    mgr, fake_ib = _build_bracket_manager()
    await mgr.place_bracket_order(
        symbol="MES", action="BUY", quantity=1,
        stop_loss=7000.0, take_profit=7200.0,
    )
    parent, sl, tp = _placed_orders(fake_ib)
    assert parent.transmit is False, "parent must not transmit until children staged"
    assert sl.transmit is False, "non-final leg must not transmit"
    assert tp.transmit is True, "final leg must transmit to release the bundle"


@pytest.mark.asyncio
async def test_children_parentid_equals_entry_id():
    mgr, fake_ib = _build_bracket_manager(start_id=5000)
    await mgr.place_bracket_order(
        symbol="MES", action="BUY", quantity=1,
        stop_loss=7000.0, take_profit=7200.0,
    )
    parent, sl, tp = _placed_orders(fake_ib)
    entry_id = parent.orderId
    assert sl.parentId == entry_id
    assert tp.parentId == entry_id
    assert parent.parentId == 0, "parent itself must have no parent"


@pytest.mark.asyncio
async def test_children_share_oca_group_and_type_1():
    mgr, fake_ib = _build_bracket_manager()
    await mgr.place_bracket_order(
        symbol="MES", action="BUY", quantity=1,
        stop_loss=7000.0, take_profit=7200.0,
    )
    parent, sl, tp = _placed_orders(fake_ib)
    assert sl.ocaGroup and sl.ocaGroup == tp.ocaGroup, "children must share one OCA group"
    assert sl.ocaType == 1 and tp.ocaType == 1
    assert not parent.ocaGroup, "parent must not be in the OCA group"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "entry_action,expected_child", [("BUY", "SELL"), ("SELL", "BUY")]
)
async def test_children_are_opposite_action(entry_action, expected_child):
    mgr, fake_ib = _build_bracket_manager()
    await mgr.place_bracket_order(
        symbol="MES", action=entry_action, quantity=1,
        stop_loss=7000.0, take_profit=7200.0,
    )
    parent, sl, tp = _placed_orders(fake_ib)
    assert parent.action == entry_action
    assert sl.action == expected_child
    assert tp.action == expected_child


# ── Entry-type handling ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mkt_entry_builds_market_parent():
    mgr, fake_ib = _build_bracket_manager()
    await mgr.place_bracket_order(
        symbol="MES", action="BUY", quantity=1, entry_type="MKT",
        stop_loss=7000.0, take_profit=7200.0,
    )
    parent = _placed_orders(fake_ib)[0]
    assert parent.orderType == "MKT"


@pytest.mark.asyncio
async def test_lmt_entry_builds_limit_parent():
    mgr, fake_ib = _build_bracket_manager()
    await mgr.place_bracket_order(
        symbol="MES", action="BUY", quantity=1,
        entry_type="LMT", limit_price=7050.0,
        stop_loss=7000.0, take_profit=7200.0,
    )
    parent = _placed_orders(fake_ib)[0]
    assert parent.orderType == "LMT"
    assert parent.lmtPrice == 7050.0


@pytest.mark.asyncio
@pytest.mark.parametrize("entry_type", ["mkt", "market", "MARKET"])
async def test_entry_type_lowercase_and_alias_normalise(entry_type):
    """The safety layer passes a lowercased order_type — bracket must accept it."""
    mgr, fake_ib = _build_bracket_manager()
    result = await mgr.place_bracket_order(
        symbol="MES", action="BUY", quantity=1, entry_type=entry_type,
        stop_loss=7000.0, take_profit=7200.0,
    )
    assert result["status"] == "placed"
    assert _placed_orders(fake_ib)[0].orderType == "MKT"


# ── Partial brackets ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stop_only_bracket():
    mgr, fake_ib = _build_bracket_manager(start_id=2000)
    result = await mgr.place_bracket_order(
        symbol="MES", action="BUY", quantity=1, stop_loss=7000.0,
    )
    assert fake_ib.placeOrder.call_count == 2
    assert result["sl_id"] == 2002
    assert result["tp_id"] is None
    parent, sl = _placed_orders(fake_ib)
    assert parent.transmit is False
    assert sl.transmit is True, "the sole child is the last leg — must transmit"


@pytest.mark.asyncio
async def test_take_profit_only_bracket():
    mgr, fake_ib = _build_bracket_manager(start_id=3000)
    result = await mgr.place_bracket_order(
        symbol="MES", action="BUY", quantity=1, take_profit=7200.0,
    )
    assert fake_ib.placeOrder.call_count == 2
    assert result["tp_id"] == 3002
    assert result["sl_id"] is None
    parent, tp = _placed_orders(fake_ib)
    assert parent.transmit is False
    assert tp.transmit is True


@pytest.mark.asyncio
async def test_no_children_places_parent_only():
    mgr, fake_ib = _build_bracket_manager()
    result = await mgr.place_bracket_order(
        symbol="MES", action="BUY", quantity=1,
    )
    assert fake_ib.placeOrder.call_count == 1
    assert result["status"] == "placed"
    assert result["sl_id"] is None
    assert result["tp_id"] is None
    parent = _placed_orders(fake_ib)[0]
    assert parent.transmit is True, "entry-only bracket: parent is the last leg"


# ── Failure handling ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_entry_failure_returns_failed_entry():
    mgr, fake_ib = _build_bracket_manager()
    fake_ib.placeOrder = MagicMock(side_effect=RuntimeError("IB rejected parent"))

    result = await mgr.place_bracket_order(
        symbol="MES", action="BUY", quantity=1,
        stop_loss=7000.0, take_profit=7200.0,
    )
    assert result == {"status": "error", "error": "Failed to place entry order"}
    assert fake_ib.placeOrder.call_count == 1
    assert not fake_ib.cancelOrder.called


@pytest.mark.asyncio
async def test_child_failure_rolls_back_and_errors():
    """A child failure must leave NO naked position: roll back the un-transmitted
    parent and error out rather than degrade to a partial bracket."""
    mgr, fake_ib = _build_bracket_manager(start_id=8000)

    calls = {"n": 0}
    real_place = fake_ib.placeOrder.side_effect

    def _place_then_fail(contract, order):
        calls["n"] += 1
        if calls["n"] == 2:  # the SL child
            raise RuntimeError("IB rejected stop child")
        return real_place(contract, order)

    fake_ib.placeOrder = MagicMock(side_effect=_place_then_fail)

    result = await mgr.place_bracket_order(
        symbol="MES", action="BUY", quantity=1,
        stop_loss=7000.0, take_profit=7200.0,
    )
    assert result["status"] == "error"
    assert result["error"] == "Failed to place bracket child order"
    # The parent (only successfully-placed leg) must be cancelled during rollback.
    assert fake_ib.cancelOrder.called
    # And it was never transmitted, so no fill could have occurred.
    parent = fake_ib.placeOrder.call_args_list[0].args[1]
    assert parent.transmit is False


# ── Reconciliation metadata ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_shared_order_ref_across_legs():
    mgr, fake_ib = _build_bracket_manager()
    await mgr.place_bracket_order(
        symbol="MES", action="BUY", quantity=1,
        stop_loss=7000.0, take_profit=7200.0,
    )
    refs = {o.orderRef for o in _placed_orders(fake_ib)}
    assert len(refs) == 1, "all legs must share one orderRef for reconciliation"
    assert next(iter(refs)).startswith("JARVIS-")


@pytest.mark.asyncio
async def test_account_stamped_on_all_legs():
    mgr, fake_ib = _build_bracket_manager(account="DUP662235")
    await mgr.place_bracket_order(
        symbol="MES", action="BUY", quantity=1,
        stop_loss=7000.0, take_profit=7200.0,
    )
    for o in _placed_orders(fake_ib):
        assert o.account == "DUP662235"
