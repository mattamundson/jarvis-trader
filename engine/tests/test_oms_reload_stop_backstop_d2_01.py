"""D2-01 regression: OMS restart / reconciliation must not drop the stop-loss backstop.

reload_from_db() and adopt_existing_trade() both used to construct BracketOrder(...)
without stop_loss_price, so resolve_stop_for_symbol() (the "Open Position Stop Monitor"
/ PaperStopMonitor backstop) returned None for every trade reloaded after an engine
restart or adopted during position reconciliation -- silently disabling the enforceable
stop. Covers the fix: both paths now thread the persisted/computed stop price through.
"""

from __future__ import annotations

import pytest

from execution.oms_v2 import OMSManager


class FakeRouter:
    """Minimal router stub -- reload_from_db/adopt_existing_trade never call it."""

    def is_futures(self, symbol: str) -> bool:
        return True


class FakeDB:
    def __init__(self, rows):
        self._rows = rows

    def get_open_trades(self):
        return self._rows


@pytest.mark.asyncio
async def test_reload_from_db_rehydrates_stop_loss_price():
    row = {
        "id": 42,
        "trade_id": "uuid-abc",
        "symbol": "MGC",
        "quantity": 1,
        "entry_price": 4153.85,
        "order_id": None,
        "stop_loss": 4134.67,
        "status": "open",
    }
    oms = OMSManager(FakeRouter())
    await oms.reload_from_db(FakeDB([row]))

    assert oms.resolve_stop_for_symbol("MGC") == 4134.67


@pytest.mark.asyncio
async def test_reload_from_db_keeps_none_when_stop_absent():
    row = {
        "id": 43,
        "trade_id": "uuid-def",
        "symbol": "MES",
        "quantity": 1,
        "entry_price": 5300.0,
        "order_id": None,
        "stop_loss": None,
        "status": "open",
    }
    oms = OMSManager(FakeRouter())
    await oms.reload_from_db(FakeDB([row]))

    assert oms.resolve_stop_for_symbol("MES") is None


@pytest.mark.asyncio
async def test_adopt_existing_trade_threads_stop_loss_price():
    oms = OMSManager(FakeRouter())
    await oms.adopt_existing_trade(
        "MGC", 1, 4153.85, stop_loss_id="sl-1", stop_loss_price=4134.67
    )

    assert oms.resolve_stop_for_symbol("MGC") == 4134.67
