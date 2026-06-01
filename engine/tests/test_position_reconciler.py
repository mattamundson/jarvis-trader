"""
Tests for PositionReconciler — crash-survival verification (Day 3 AM sprint task).

Verifies:
  1. Reconciler skips gracefully when IB Gateway not connected
  2. Reconciler detects orphaned positions (no STP) and places emergency stop
  3. Reconciler logs clean bill of health when all positions are bracketed
  4. Emergency stop price calculation: 2% adverse, tick-rounded to 0.25
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from execution.position_reconciler import PositionReconciler


@pytest.fixture
def mock_ib():
    gw = MagicMock()
    gw.is_connected = MagicMock(return_value=True)
    gw.get_positions = AsyncMock(return_value=[])
    gw.get_open_orders = AsyncMock(return_value=[])
    gw.place_paper_order = AsyncMock(return_value={"order_id": "TEST-999"})
    return gw


# ── 1. Not connected ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_reconciler_skips_when_not_connected():
    gw = MagicMock()
    gw.is_connected = MagicMock(return_value=False)
    gw.get_positions = AsyncMock()
    reconciler = PositionReconciler(gw)
    await reconciler.reconcile()
    gw.get_positions.assert_not_called()


# ── 2. Orphaned position — no STP present ──────────────────────────────────

@pytest.mark.asyncio
async def test_reconciler_attaches_emergency_stop_for_long(mock_ib):
    mock_ib.get_positions = AsyncMock(return_value=[
        {"symbol": "MES", "position": 1, "avg_cost": 5200.0}
    ])
    mock_ib.get_open_orders = AsyncMock(return_value=[])  # no STP

    reconciler = PositionReconciler(mock_ib)
    await reconciler.reconcile()

    mock_ib.place_paper_order.assert_called_once()
    call_kwargs = mock_ib.place_paper_order.call_args.kwargs
    assert call_kwargs["symbol"] == "MES"
    assert call_kwargs["action"] == "SELL"
    assert call_kwargs["order_type"] == "STP"
    # 5200 * 0.98 = 5096.0 → rounded to nearest 0.25 = 5096.0
    assert call_kwargs["aux_price"] == pytest.approx(5096.0, abs=0.25)


@pytest.mark.asyncio
async def test_reconciler_attaches_emergency_stop_for_short(mock_ib):
    mock_ib.get_positions = AsyncMock(return_value=[
        {"symbol": "MES", "position": -1, "avg_cost": 5200.0}
    ])
    mock_ib.get_open_orders = AsyncMock(return_value=[])

    reconciler = PositionReconciler(mock_ib)
    await reconciler.reconcile()

    call_kwargs = mock_ib.place_paper_order.call_args.kwargs
    assert call_kwargs["action"] == "BUY"
    # 5200 * 1.02 = 5304.0
    assert call_kwargs["aux_price"] == pytest.approx(5304.0, abs=0.25)


# ── 3. Position already bracketed ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_reconciler_no_action_when_stp_present(mock_ib):
    mock_ib.get_positions = AsyncMock(return_value=[
        {"symbol": "MES", "position": 1, "avg_cost": 5200.0}
    ])
    mock_ib.get_open_orders = AsyncMock(return_value=[
        {"symbol": "MES", "order_type": "STP", "status": "SUBMITTED"}
    ])

    reconciler = PositionReconciler(mock_ib)
    await reconciler.reconcile()

    mock_ib.place_paper_order.assert_not_called()


# ── 4. Zero-quantity positions are ignored ─────────────────────────────────

@pytest.mark.asyncio
async def test_reconciler_ignores_zero_quantity(mock_ib):
    mock_ib.get_positions = AsyncMock(return_value=[
        {"symbol": "MES", "position": 0, "avg_cost": 5200.0}
    ])
    mock_ib.get_open_orders = AsyncMock(return_value=[])

    reconciler = PositionReconciler(mock_ib)
    await reconciler.reconcile()

    mock_ib.place_paper_order.assert_not_called()


# ── 5. Filled/cancelled STP is treated as missing ─────────────────────────

@pytest.mark.asyncio
async def test_reconciler_treats_filled_stp_as_absent(mock_ib):
    mock_ib.get_positions = AsyncMock(return_value=[
        {"symbol": "MES", "position": 1, "avg_cost": 5200.0}
    ])
    mock_ib.get_open_orders = AsyncMock(return_value=[
        {"symbol": "MES", "order_type": "STP", "status": "FILLED"}
    ])

    reconciler = PositionReconciler(mock_ib)
    await reconciler.reconcile()

    # Filled STP means no active protection — should place emergency stop
    mock_ib.place_paper_order.assert_called_once()


# ── 6. Tick rounding ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_emergency_stop_tick_rounded(mock_ib):
    # 5201.0 * 0.98 = 5096.98 → nearest 0.25 = 5097.0
    mock_ib.get_positions = AsyncMock(return_value=[
        {"symbol": "MES", "position": 1, "avg_cost": 5201.0}
    ])
    mock_ib.get_open_orders = AsyncMock(return_value=[])

    reconciler = PositionReconciler(mock_ib)
    await reconciler.reconcile()

    call_kwargs = mock_ib.place_paper_order.call_args.kwargs
    # Must be a multiple of 0.25
    price = call_kwargs["aux_price"]
    assert price % 0.25 == pytest.approx(0, abs=1e-9), f"{price} not tick-aligned"
