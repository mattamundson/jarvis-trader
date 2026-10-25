"""Offline chaos contracts for IBOrderManager boundaries."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from execution.ib_order_manager import IBOrderManager


def _gateway(*, connected: bool = True, positions=None, error: Exception | None = None):
    gateway = MagicMock()
    gateway.is_connected.return_value = connected
    if error is None:
        gateway.get_positions = AsyncMock(return_value=positions or [])
    else:
        gateway.get_positions = AsyncMock(side_effect=error)
    return gateway


def _safety(*, killed: bool = False, submit_result: dict | None = None):
    safety = MagicMock()
    safety.is_killed = killed
    safety.get_status.return_value = {"kill_switch_active": killed}
    safety.submit_paper_order = AsyncMock(
        return_value=submit_result
        or {
            "approved": True,
            "reason": "Order approved",
            "order_id": "paper-1",
            "routed_to_ib": True,
        }
    )
    safety.submit_paper_bracket_order = AsyncMock(
        return_value={
            "approved": True,
            "reason": "Bracket approved",
            "order_id": "bracket-1",
            "routed_to_ib": True,
        }
    )
    return safety


@pytest.mark.asyncio
async def test_submit_order_delegates_to_safety_layer_not_gateway() -> None:
    safety = _safety()
    gateway = _gateway()
    manager = IBOrderManager(safety, ib_gateway=gateway)

    result = await manager.submit_order("MES", "BUY", 1, 5800.0)

    assert result["approved"] is True
    safety.submit_paper_order.assert_awaited_once_with(
        symbol="MES",
        action="BUY",
        quantity=1,
        price=5800.0,
        order_type="MKT",
        limit_price=None,
    )
    assert "submit_order" not in {
        call[0] for call in gateway.mock_calls if call[0] != "is_connected"
    }


@pytest.mark.asyncio
async def test_submit_order_returns_safety_rejection_unchanged() -> None:
    rejection = {
        "approved": False,
        "reason": "daily loss limit breached",
        "order_id": None,
        "routed_to_ib": False,
    }
    manager = IBOrderManager(_safety(submit_result=rejection), ib_gateway=_gateway())

    result = await manager.submit_order("MES", "SELL", 1, 5800.0)

    assert result == rejection


@pytest.mark.asyncio
async def test_bracket_order_kill_switch_short_circuits_before_safety_submit() -> None:
    safety = _safety(killed=True)
    manager = IBOrderManager(safety, ib_gateway=_gateway())

    result = await manager.submit_bracket_order(
        "MES",
        "BUY",
        1,
        5800.0,
        stop_loss=5785.0,
        take_profit=5830.0,
    )

    assert result == {"approved": False, "reason": "Kill switch active"}
    safety.submit_paper_bracket_order.assert_not_awaited()


@pytest.mark.asyncio
async def test_sync_positions_disconnected_returns_empty_without_tracker_mutation() -> None:
    tracker = MagicMock()
    tracker._open = {}
    manager = IBOrderManager(_safety(), ib_gateway=_gateway(connected=False), portfolio_tracker=tracker)

    result = await manager.sync_positions_from_ib()

    assert result == []
    tracker.open_trade.assert_not_called()


@pytest.mark.asyncio
async def test_sync_positions_get_positions_error_returns_empty() -> None:
    tracker = MagicMock()
    tracker._open = {}
    manager = IBOrderManager(
        _safety(),
        ib_gateway=_gateway(error=RuntimeError("gateway timeout")),
        portfolio_tracker=tracker,
    )

    result = await manager.sync_positions_from_ib()

    assert result == []
    tracker.open_trade.assert_not_called()


@pytest.mark.asyncio
async def test_reconcile_disconnected_returns_not_in_sync_empty_state() -> None:
    manager = IBOrderManager(_safety(), ib_gateway=_gateway(connected=False))

    result = await manager.reconcile()

    assert result == {
        "ib_positions": [],
        "tracker_positions": [],
        "missing_in_tracker": [],
        "missing_in_ib": [],
        "qty_mismatches": [],
        "in_sync": False,
    }


@pytest.mark.asyncio
async def test_reconcile_get_positions_error_returns_not_in_sync_empty_state() -> None:
    manager = IBOrderManager(_safety(), ib_gateway=_gateway(error=RuntimeError("drop")))

    result = await manager.reconcile()

    assert result == {
        "ib_positions": [],
        "tracker_positions": [],
        "missing_in_tracker": [],
        "missing_in_ib": [],
        "qty_mismatches": [],
        "in_sync": False,
    }
