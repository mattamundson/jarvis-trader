"""OMSManager — bracket lifecycle + OCO coverage (offline, fakes only).

Drives execution/oms_v2.py with a fake router / IB order manager. Covers the
bracket state machine (PENDING_ENTRY -> ACTIVE / ERROR), the OCO safety logic
(when one leg fills, the other is cancelled), stop-loss modification, trade
adoption, options-spread routing, and the active-trade filter. No broker, no
network — pure state-machine assertions.
"""

from __future__ import annotations

import pytest

from execution.oms_v2 import OMSManager, TradeState


class FakeRouter:
    def __init__(self, is_fut: bool = False, bracket_result=None, route_result=None):
        self._is_fut = is_fut
        self.bracket_result = bracket_result or {
            "status": "placed",
            "order_id": "entry-1",
            "sl_id": "sl-1",
            "tp_id": "tp-1",
        }
        self.route_result = route_result or {"status": "placed", "order_id": "opt-1"}
        self.cancelled: list = []
        self.modified: list = []
        self.routed: list = []

    def is_futures(self, symbol: str) -> bool:
        return self._is_fut

    async def route_bracket_order(self, **kwargs):
        self.routed.append(("bracket", kwargs))
        return self.bracket_result

    async def route_order(self, order):
        self.routed.append(("order", order))
        return self.route_result

    async def cancel_order(self, order_id):
        self.cancelled.append(order_id)
        return {"status": "cancelled", "order_id": order_id}

    async def modify_order(self, order_id, new_price):
        self.modified.append((order_id, new_price))
        return {"status": "modified", "order_id": order_id}


class FakeIBOM:
    def __init__(self, result=None):
        self.result = result or {
            "approved": True,
            "entry_id": "fut-entry",
            "sl_id": "fut-sl",
            "tp_id": "fut-tp",
        }
        self.calls: list = []

    async def submit_bracket_order(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


# ── execute_bracket ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_execute_bracket_futures_routes_to_ib_order_manager():
    router = FakeRouter(is_fut=True)
    ibom = FakeIBOM()
    oms = OMSManager(router, ib_order_manager=ibom)

    trade = await oms.execute_bracket(
        "MES", "BUY", 1, 5300.0, stop_loss=5280.0, take_profit=5350.0
    )

    assert trade.status == TradeState.ACTIVE
    assert trade.entry_order_id == "fut-entry"
    assert trade.stop_loss_id == "fut-sl"
    assert trade.take_profit_id == "fut-tp"
    assert len(ibom.calls) == 1
    assert not router.routed  # did NOT use the standard router path
    assert trade.trade_id in oms.active_trades


@pytest.mark.asyncio
async def test_execute_bracket_futures_without_ibom_falls_back_to_router():
    router = FakeRouter(is_fut=True)
    oms = OMSManager(router)  # no ib_order_manager
    trade = await oms.execute_bracket("MES", "BUY", 1, 5300.0)
    assert trade.status == TradeState.ACTIVE
    assert router.routed and router.routed[0][0] == "bracket"


@pytest.mark.asyncio
async def test_execute_bracket_nonfutures_uses_router():
    router = FakeRouter(is_fut=False)
    oms = OMSManager(router)
    trade = await oms.execute_bracket(
        "SPY", "BUY", 1, 500.0, stop_loss=495.0, take_profit=510.0
    )
    assert trade.status == TradeState.ACTIVE
    assert trade.entry_order_id == "entry-1"
    assert trade.stop_loss_id == "sl-1"
    assert trade.take_profit_id == "tp-1"


@pytest.mark.asyncio
async def test_execute_bracket_rejected_result_sets_error_and_not_tracked():
    router = FakeRouter(is_fut=False, bracket_result={"status": "rejected", "reason": "risk gate"})
    oms = OMSManager(router)
    trade = await oms.execute_bracket("SPY", "BUY", 1, 500.0)
    assert trade.status == TradeState.ERROR
    assert trade.trade_id not in oms.active_trades


@pytest.mark.asyncio
async def test_execute_bracket_exception_sets_error():
    class BoomRouter(FakeRouter):
        async def route_bracket_order(self, **kwargs):
            raise RuntimeError("broker down")

    oms = OMSManager(BoomRouter(is_fut=False))
    trade = await oms.execute_bracket("SPY", "BUY", 1, 500.0)
    assert trade.status == TradeState.ERROR
    assert trade.trade_id not in oms.active_trades


# ── OCO: one leg fills -> the other is cancelled ──────────────────────────


@pytest.mark.asyncio
async def test_oco_take_profit_fill_cancels_stop_loss():
    router = FakeRouter()
    oms = OMSManager(router)
    tid = await oms.adopt_existing_trade(
        "MES", 1, 5300.0, stop_loss_id="sl-9", take_profit_id="tp-9"
    )

    await oms.update_trade_status("tp-9", "filled", 5350.0)

    trade = oms.active_trades[tid]
    assert trade.status == TradeState.CLOSED
    assert trade.exit_reason == "tp"
    assert trade.closed_at is not None
    assert "sl-9" in router.cancelled  # OCO cancelled the opposite leg
    assert "tp-9" not in router.cancelled


@pytest.mark.asyncio
async def test_oco_stop_loss_fill_cancels_take_profit():
    router = FakeRouter()
    oms = OMSManager(router)
    tid = await oms.adopt_existing_trade(
        "MES", 1, 5300.0, stop_loss_id="sl-9", take_profit_id="tp-9"
    )

    await oms.update_trade_status("sl-9", "filled", 5280.0)

    trade = oms.active_trades[tid]
    assert trade.status == TradeState.CLOSED
    assert trade.exit_reason == "sl"
    assert "tp-9" in router.cancelled
    assert "sl-9" not in router.cancelled


@pytest.mark.asyncio
async def test_update_trade_status_ignores_non_fill_and_unknown_ids():
    router = FakeRouter()
    oms = OMSManager(router)
    tid = await oms.adopt_existing_trade(
        "MES", 1, 5300.0, stop_loss_id="sl-9", take_profit_id="tp-9"
    )

    # A non-"filled" status on a known leg does nothing.
    await oms.update_trade_status("tp-9", "submitted", 0.0)
    # A "filled" on an unrelated id does nothing.
    await oms.update_trade_status("unknown-id", "filled", 1.0)

    assert oms.active_trades[tid].status == TradeState.ACTIVE
    assert router.cancelled == []


@pytest.mark.asyncio
async def test_handle_exit_tolerates_cancel_failure():
    class BadCancelRouter(FakeRouter):
        async def cancel_order(self, order_id):
            raise RuntimeError("cancel failed")

    oms = OMSManager(BadCancelRouter())
    tid = await oms.adopt_existing_trade(
        "MES", 1, 5300.0, stop_loss_id="sl-9", take_profit_id="tp-9"
    )
    # Must not raise even though the OCO cancel fails — the trade still closes.
    await oms.update_trade_status("tp-9", "filled", 5350.0)
    assert oms.active_trades[tid].status == TradeState.CLOSED


# ── update_stop_loss ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_stop_loss_modifies_active_trade():
    router = FakeRouter()
    oms = OMSManager(router)
    tid = await oms.adopt_existing_trade("MES", 1, 5300.0, stop_loss_id="sl-9")

    await oms.update_stop_loss(tid, 5290.0)

    assert ("sl-9", 5290.0) in router.modified
    assert oms.active_trades[tid].stop_loss_price == 5290.0


@pytest.mark.asyncio
async def test_update_stop_loss_noop_when_trade_not_active():
    router = FakeRouter()
    oms = OMSManager(router)
    tid = await oms.adopt_existing_trade("MES", 1, 5300.0, stop_loss_id="sl-9")
    oms.active_trades[tid].status = TradeState.CLOSED

    await oms.update_stop_loss(tid, 5290.0)

    assert router.modified == []


@pytest.mark.asyncio
async def test_update_stop_loss_noop_when_no_sl_id():
    router = FakeRouter()
    oms = OMSManager(router)
    tid = await oms.adopt_existing_trade("MES", 1, 5300.0)  # no stop_loss_id

    await oms.update_stop_loss(tid, 5290.0)

    assert router.modified == []


# ── get_active_trades / adopt / options spread ────────────────────────────


@pytest.mark.asyncio
async def test_get_active_trades_filters_closed():
    router = FakeRouter()
    oms = OMSManager(router)
    tid = await oms.adopt_existing_trade(
        "MES", 1, 5300.0, stop_loss_id="sl-9", take_profit_id="tp-9"
    )
    assert len(oms.get_active_trades()) == 1

    await oms.update_trade_status("tp-9", "filled", 5350.0)  # closes the trade
    active = oms.get_active_trades()
    assert active == []
    # the closed trade is still retained in active_trades (not deleted)
    assert oms.active_trades[tid].status == TradeState.CLOSED


@pytest.mark.asyncio
async def test_execute_options_spread_activates_on_placed():
    router = FakeRouter()
    oms = OMSManager(router)
    trade = await oms.execute_options_spread(
        "SPX", "put_credit", "SPX_short", "SPX_long", 1, 1.50
    )
    assert trade.status == TradeState.ACTIVE
    assert trade.entry_order_id == "opt-1"
    assert router.routed and router.routed[0][0] == "order"


@pytest.mark.asyncio
async def test_execute_options_spread_error_when_not_placed():
    router = FakeRouter(route_result={"status": "rejected", "reason": "no liquidity"})
    oms = OMSManager(router)
    trade = await oms.execute_options_spread(
        "SPX", "put_credit", "SPX_short", "SPX_long", 1, 1.50
    )
    assert trade.status == TradeState.ERROR
    assert trade.trade_id not in oms.active_trades


# ── resolve_stop_for_symbol — stop-monitor fallback (trade #287 Bug 2) ─────
#
# OMS v2 bracket-executed paper trades never persist stop_loss onto the
# paper_trades DB row (PortfolioTracker.open_trade() has no stop_loss param --
# a separate, documented data-hygiene gap). Both stop-loss monitors
# (PaperStopMonitor and the 5-minute "Open Position Stop Monitor" job) key off
# that DB column, so they were silently blind to every OMS-opened position.
# resolve_stop_for_symbol() lets them fall back to the OMS's own in-memory
# bracket record, which DOES hold the real stop from execute_bracket() time.


@pytest.mark.asyncio
async def test_resolve_stop_for_symbol_returns_active_bracket_stop():
    router = FakeRouter(is_fut=True)
    ibom = FakeIBOM()
    oms = OMSManager(router, ib_order_manager=ibom)

    trade = await oms.execute_bracket(
        "MGC", "BUY", 1, 4153.85, stop_loss=4134.6666, take_profit=None
    )
    assert trade.status == TradeState.ACTIVE

    assert oms.resolve_stop_for_symbol("MGC") == 4134.6666
    # Case-insensitive symbol match.
    assert oms.resolve_stop_for_symbol("mgc") == 4134.6666


@pytest.mark.asyncio
async def test_resolve_stop_for_symbol_ignores_closed_trades():
    router = FakeRouter()
    oms = OMSManager(router)
    tid = await oms.adopt_existing_trade(
        "MES", 1, 5300.0, stop_loss_id="sl-9", take_profit_id="tp-9"
    )
    oms.active_trades[tid].stop_loss_price = 5280.0
    await oms.update_trade_status("sl-9", "filled", 5280.0)  # closes the trade

    assert oms.resolve_stop_for_symbol("MES") is None


def test_resolve_stop_for_symbol_no_match_or_empty():
    router = FakeRouter()
    oms = OMSManager(router)
    assert oms.resolve_stop_for_symbol("MES") is None  # nothing tracked at all
    assert oms.resolve_stop_for_symbol("") is None
    assert oms.resolve_stop_for_symbol(None) is None


@pytest.mark.asyncio
async def test_resolve_stop_for_symbol_none_when_bracket_has_no_stop():
    router = FakeRouter(is_fut=True)
    ibom = FakeIBOM()
    oms = OMSManager(router, ib_order_manager=ibom)
    trade = await oms.execute_bracket("MGC", "BUY", 1, 4153.85)  # no stop_loss
    assert trade.status == TradeState.ACTIVE
    assert oms.resolve_stop_for_symbol("MGC") is None


@pytest.mark.asyncio
async def test_resolve_stop_for_symbol_picks_most_recent_when_multiple_active():
    """
    US-006 correctness audit: if two ACTIVE brackets ever exist for the same
    symbol at once (scale-in, re-entry race), resolve_stop_for_symbol()'s
    docstring promises "the most recent ACTIVE bracket". The prior
    implementation returned the first match from dict.values() iteration
    order instead, which is oldest-inserted-first, not most-recent -- a
    latent mismatch between the doc and the code. Explicitly seed opened_at
    out of insertion order (older trade inserted last) to prove the fix
    picks by timestamp, not by dict order.
    """
    router = FakeRouter(is_fut=True)
    ibom = FakeIBOM()
    oms = OMSManager(router, ib_order_manager=ibom)

    older = await oms.execute_bracket("MGC", "BUY", 1, 4100.0, stop_loss=4080.0)
    newer = await oms.execute_bracket("MGC", "BUY", 1, 4200.0, stop_loss=4180.0)

    # Force the "older" trade to have a LATER insertion into the dict than
    # "newer" by touching it after the fact, while its opened_at timestamp
    # stays earlier -- this is what would make dict-iteration-order and
    # opened_at-order actually disagree (e.g. after adopt_existing_trade()
    # or reload_from_db() reorders the map).
    del oms.active_trades[older.trade_id]
    oms.active_trades[older.trade_id] = older

    assert oms.resolve_stop_for_symbol("MGC") == 4180.0
