from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from routers import orders_router
from routers import trade_intents_router as R


class FakeDB:
    def __init__(self, rows=None):
        self.rows = list(rows or [])

    def get_open_trades(self):
        return list(self.rows)


class FakeGateway:
    def __init__(self, positions=None, connected=True):
        self.positions = list(positions or [])
        self.connected = connected

    def is_connected(self):
        return self.connected

    async def get_positions(self):
        return list(self.positions)


class FakeDataManager:
    def __init__(self, price=6500.0):
        self.price = price

    async def get_current_price(self, symbol, is_futures=True):
        assert is_futures is True
        return {"last_price": self.price, "source": "ibkr"}


class FakeSafety:
    def __init__(self, db_path, *, equity=3000.0, broker_result=None, db_rows=None, broker_positions=None):
        self._db_path = str(db_path)
        self._db_manager = FakeDB(db_rows)
        self._ib_gateway = FakeGateway(broker_positions)
        self._equity = equity
        self.is_killed = False
        self.calls = 0
        self.broker_result = broker_result or {
            "approved": True,
            "reason": "Bracket approved and routed to IBKR",
            "entry_id": "entry-1",
            "sl_id": "stop-1",
            "tp_id": "target-1",
            "routed_to_ib": True,
        }

    def get_status(self):
        return {"current_equity": self._equity, "is_killed": self.is_killed}

    async def submit_paper_bracket_order(self, **kwargs):
        self.calls += 1
        self.last_order = kwargs
        return dict(self.broker_result)


@pytest.fixture(autouse=True)
def isolated_parent_state(tmp_path, monkeypatch):
    safety = FakeSafety(tmp_path / "jarvis.db")
    data = FakeDataManager()
    orders_router._safety_layer = safety
    orders_router._data_manager = data
    monkeypatch.setattr(R, "approved_watchlist_symbols", lambda: {"MES"})

    async def sane(**kwargs):
        return True, ""

    monkeypatch.setattr(R, "check_entry_price_sanity", sane)
    monkeypatch.setattr(R.settings, "LIVE_TRADING_ENABLED", False)
    monkeypatch.setattr(R.settings, "PAPER_TRADING", True)
    monkeypatch.setattr(R.settings, "MAX_TRADE_LOSS_USD", 50.0)
    monkeypatch.setattr(R.settings, "MAX_CONTRACTS_PER_INSTRUMENT", 2)
    yield safety, data
    orders_router._safety_layer = None
    orders_router._data_manager = None


def request(**overrides):
    base = {
        "idempotency_key": "intent-test-0001",
        "symbol": "MES",
        "direction": "BUY",
        "order_type": "MARKET",
        "stop_loss": 6498.0,
        "take_profit": 6504.0,
        "max_risk_fraction": 0.005,
        "requested_quantity": 2,
        "ttl_seconds": 60,
    }
    base.update(overrides)
    return R.TradeIntentPreviewRequest(**base)


@pytest.mark.asyncio
async def test_preview_can_fail_closed_to_zero_quantity(isolated_parent_state):
    result = await R.preview_trade_intent(request(stop_loss=6490.0))
    assert result.status == "BLOCKED"
    assert result.preview["final_quantity"] == 0
    assert result.preview["can_submit"] is False
    assert "cannot support one MES unit" in (result.terminal_reason or "")


@pytest.mark.asyncio
async def test_preview_then_submit_routes_one_frozen_or_smaller_bracket(isolated_parent_state):
    safety, _ = isolated_parent_state
    preview = await R.preview_trade_intent(request())
    assert preview.status == "PREVIEWED"
    assert preview.preview["final_quantity"] == 1

    submitted = await R.submit_trade_intent(preview.intent_id)
    assert submitted.status == "SUBMITTED"
    assert submitted.order_id == "entry-1"
    assert safety.calls == 1
    assert safety.last_order["quantity"] == 1
    assert safety.last_order["stop_loss"] == 6498.0
    assert safety.last_order["take_profit"] == 6504.0

    # Idempotent read-back: a repeat submit returns the persisted result and does
    # not reach the broker again.
    repeated = await R.submit_trade_intent(preview.intent_id)
    assert repeated.status == "SUBMITTED"
    assert safety.calls == 1


@pytest.mark.asyncio
async def test_reconciliation_mismatch_blocks_before_broker(isolated_parent_state):
    safety, _ = isolated_parent_state
    safety._db_manager = FakeDB([{"symbol": "MES", "quantity": 1, "action": "BUY"}])
    safety._ib_gateway = FakeGateway([])
    preview = await R.preview_trade_intent(request())

    with pytest.raises(HTTPException) as excinfo:
        await R.submit_trade_intent(preview.intent_id)
    assert excinfo.value.status_code == 409
    assert safety.calls == 0


@pytest.mark.asyncio
async def test_live_mode_blocks_preview(isolated_parent_state, monkeypatch):
    monkeypatch.setattr(R.settings, "LIVE_TRADING_ENABLED", True)
    with pytest.raises(HTTPException) as excinfo:
        await R.preview_trade_intent(request())
    assert excinfo.value.status_code == 409
    assert "live mode" in str(excinfo.value.detail).lower()


@pytest.mark.asyncio
async def test_ambiguous_broker_result_remains_submitting_and_cannot_retry(
    isolated_parent_state,
):
    safety, _ = isolated_parent_state
    safety.broker_result = {
        "approved": True,
        "reason": "Safety check PASSED, but broker placement failed: timeout",
        "routed_to_ib": False,
    }
    preview = await R.preview_trade_intent(request())

    with pytest.raises(HTTPException) as excinfo:
        await R.submit_trade_intent(preview.intent_id)
    assert excinfo.value.status_code == 502
    assert safety.calls == 1

    record = R._store().get(preview.intent_id)
    assert record is not None
    assert record["status"] == "SUBMITTING"

    with pytest.raises(HTTPException) as second:
        await R.submit_trade_intent(preview.intent_id)
    assert second.value.status_code == 409
    assert safety.calls == 1


@pytest.mark.asyncio
async def test_safety_rejection_becomes_terminal_block(isolated_parent_state):
    safety, _ = isolated_parent_state
    safety.broker_result = {
        "approved": False,
        "reason": "TRADE_LOSS_LIMIT",
        "routed_to_ib": False,
    }
    preview = await R.preview_trade_intent(request())

    with pytest.raises(HTTPException) as excinfo:
        await R.submit_trade_intent(preview.intent_id)
    assert excinfo.value.status_code == 409
    assert safety.calls == 1
    record = R._store().get(preview.intent_id)
    assert record is not None
    assert record["status"] == "BLOCKED"
    assert record["terminal_reason"] == "TRADE_LOSS_LIMIT"
