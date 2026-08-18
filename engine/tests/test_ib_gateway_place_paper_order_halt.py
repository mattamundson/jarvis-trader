"""Regression: IBGatewayManager.place_paper_order() must refuse
DO_NOT_TRADE_SYMBOLS instruments even when called directly, bypassing
SafetyLayer.

Origin: SafetyLayer._check_do_not_trade_symbols() is the designed choke
point for backtest/signals.py's halt list, but not every caller routes
through SafetyLayer first -- test_ib_gateway_connector_safety_wiring.py's
test_get_positions_list_shape_for_order_manager calls
gateway.place_paper_order("MCL", "BUY", 1) directly. On 2026-08-11 that
test almost placed a real, ungated MCL order (avoided only by an
incidental client-ID connection collision with a preceding test, not by
any actual safety check). This adds the same halt-list gate directly at
the gateway level so a bypass of SafetyLayer is no longer a bypass of the
halt list too.

Run:
    cd engine
    .venv\\Scripts\\python.exe -m pytest tests/test_ib_gateway_place_paper_order_halt.py -v
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from backtest.signals import DO_NOT_TRADE_SYMBOLS
from execution.ib_gateway import IBGatewayConfig, IBGatewayManager


def _manager() -> IBGatewayManager:
    return IBGatewayManager(IBGatewayConfig(host="127.0.0.1", port=4002, client_id=999))


@pytest.mark.asyncio
@pytest.mark.parametrize("symbol", sorted(DO_NOT_TRADE_SYMBOLS))
async def test_halted_symbol_rejected_before_any_ib_call(symbol) -> None:
    """Every current DO_NOT_TRADE_SYMBOLS member must be refused, and the
    rejection must happen before _resolve_contract (i.e. before anything
    touches the IB connection) -- proving this is a hard gate, not a
    downstream failure that happens to also return None. is_connected is
    patched True so this reaches past _validate_order_preconditions's own
    unrelated connectivity gate -- otherwise it would pass for the wrong
    reason (not connected) rather than the halt-list gate under test."""
    mgr = _manager()
    with patch.object(mgr, "is_connected", return_value=True), \
         patch.object(mgr, "_resolve_contract") as resolve_mock:
        order_id = await mgr.place_paper_order(symbol=symbol, action="BUY", quantity=1)

    assert order_id is None
    resolve_mock.assert_not_called()


@pytest.mark.asyncio
async def test_halted_symbol_check_is_case_insensitive() -> None:
    mgr = _manager()
    with patch.object(mgr, "is_connected", return_value=True), \
         patch.object(mgr, "_resolve_contract") as resolve_mock:
        order_id = await mgr.place_paper_order(symbol="mcl", action="BUY", quantity=1)

    assert order_id is None
    resolve_mock.assert_not_called()


@pytest.mark.asyncio
async def test_non_halted_symbol_proceeds_past_the_gate() -> None:
    """A symbol not on the halt list must still reach _resolve_contract --
    proving the gate is additive and doesn't block legitimate trading."""
    mgr = _manager()
    with patch.object(mgr, "is_connected", return_value=True), \
         patch.object(mgr, "_resolve_contract", return_value=None) as resolve_mock:
        await mgr.place_paper_order(symbol="MES", action="BUY", quantity=1)

    resolve_mock.assert_called_once_with("MES")
