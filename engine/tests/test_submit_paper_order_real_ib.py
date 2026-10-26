"""SafetyLayer.submit_paper_order against the REAL IB paper broker (offline).

Regression for 2026-10-26: with IB_PAPER_BROKER_ENABLED=1 the approval path
called IBGatewayManager.place_paper_order(take_profit=...), which raised
TypeError; submit_paper_order still returned approved=True, so the approval
router booked phantom paper_trades row 346 with no order at IB.

The real manager is a MagicMock(spec=IBGatewayManager), so isinstance() holds
without a socket.
"""

from __future__ import annotations

import sqlite3
from unittest.mock import AsyncMock, MagicMock

import pytest

from config import settings
from execution.ib_gateway import IBGatewayManager
from risk.safety_layer import SafetyLayer


def _cfg():
    return settings.model_copy(
        update={
            "LIVE_TRADING_ENABLED": False,
            "ALLOW_PAPER_SIMULATED_ORDERS": True,
            "REQUIRE_HUMAN_APPROVAL": False,
            "MAX_SINGLE_ORDER_VALUE": 500_000.0,
            "MAX_POSITION_SIZE_PCT": 1.0,
            "MAX_TRADE_LOSS_USD": 10_000.0,
        }
    )


def _real_gateway(bracket_result=None, bracket_exc=None):
    gw = MagicMock(spec=IBGatewayManager)
    gw.is_connected.return_value = True
    if bracket_exc is not None:
        gw.place_bracket_order = AsyncMock(side_effect=bracket_exc)
    else:
        gw.place_bracket_order = AsyncMock(return_value=bracket_result)
    gw.place_paper_order = AsyncMock(side_effect=TypeError("unexpected keyword 'take_profit'"))
    return gw


async def _submit(safety):
    return await safety.submit_paper_order(
        symbol="MES",
        action="BUY",
        quantity=1,
        price=7671.25,
        order_type="MKT",
        stop_price=7654.98,
        take_profit=7711.93,
    )


@pytest.mark.asyncio
async def test_real_broker_routes_native_bracket_with_stop_and_target():
    safety = SafetyLayer(_cfg(), pnl_monitor=None)
    gw = _real_gateway(
        {
            "status": "placed",
            "entry_id": 101,
            "sl_id": 102,
            "tp_id": 103,
            "symbol": "MES",
            "action": "BUY",
            "quantity": 1,
        }
    )
    safety.attach_ib_gateway(gw)

    out = await _submit(safety)

    assert out["approved"] is True
    assert out["routed_to_ib"] is True
    assert out["order_id"] == "101"
    assert out["stop_order_id"] == 102
    assert out["target_order_id"] == 103
    gw.place_paper_order.assert_not_called()
    kwargs = gw.place_bracket_order.await_args.kwargs
    assert kwargs["stop_loss"] == pytest.approx(7654.98)
    assert kwargs["take_profit"] == pytest.approx(7711.93)
    assert kwargs["action"] == "BUY"


@pytest.mark.asyncio
async def test_real_broker_bracket_error_not_routed():
    safety = SafetyLayer(_cfg(), pnl_monitor=None)
    safety.attach_ib_gateway(_real_gateway({"status": "error", "error": "Not connected"}))

    out = await _submit(safety)

    assert out["approved"] is True  # safety passed; routed_to_ib says nothing placed
    assert out["routed_to_ib"] is False
    assert out["order_id"] is None


@pytest.mark.asyncio
async def test_real_broker_bracket_raise_not_routed():
    safety = SafetyLayer(_cfg(), pnl_monitor=None)
    safety.attach_ib_gateway(_real_gateway(bracket_exc=RuntimeError("socket closed")))

    out = await _submit(safety)

    assert out["approved"] is True  # safety passed; routed_to_ib says nothing placed
    assert out["routed_to_ib"] is False


@pytest.mark.asyncio
async def test_any_gateway_place_paper_order_raise_not_routed():
    """Simulator-shaped gateway: a raising broker call reports routed_to_ib=False."""
    safety = SafetyLayer(_cfg(), pnl_monitor=None)
    gw = MagicMock()
    gw.is_connected.return_value = True
    gw.place_paper_order = AsyncMock(side_effect=RuntimeError("broker down"))
    safety.attach_ib_gateway(gw)

    out = await _submit(safety)

    assert out["approved"] is True  # safety passed; routed_to_ib says nothing placed
    assert out["routed_to_ib"] is False


@pytest.mark.asyncio
async def test_real_broker_without_stop_is_refused_not_sent_naked():
    safety = SafetyLayer(_cfg(), pnl_monitor=None)
    gw = _real_gateway({"status": "placed", "entry_id": 1, "sl_id": 2, "tp_id": 3})
    safety.attach_ib_gateway(gw)

    out = await safety.submit_paper_order(
        symbol="MES", action="BUY", quantity=1, price=7671.25, order_type="MKT"
    )

    assert out["routed_to_ib"] is False
    gw.place_bracket_order.assert_not_called()
    gw.place_paper_order.assert_not_called()


def test_stamp_bracket_ids_writes_paper_trades_row(tmp_path):
    from routers.approval_queue_router import _stamp_bracket_ids

    db = str(tmp_path / "t.db")
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE paper_trades (trade_id TEXT, stop_order_id TEXT, "
            "target_order_id TEXT, bracket_status TEXT)"
        )
        conn.execute("INSERT INTO paper_trades (trade_id) VALUES ('t-1')")

    assert _stamp_bracket_ids(db, "t-1", {"stop_order_id": 102, "target_order_id": 103}) is True
    with sqlite3.connect(db) as conn:
        row = conn.execute(
            "SELECT stop_order_id, target_order_id, bracket_status FROM paper_trades"
        ).fetchone()
    assert row == ("102", "103", "attached")
    assert _stamp_bracket_ids(db, "t-1", {"order_id": "101"}) is False
