"""
IBOrderManager.sync_positions_from_ib — naked-row backfill for broker-synced
positions.

Background: unlike OMS-bracket trades (fixed by PR #331 via
resolve_stop_for_symbol), a position discovered via sync_positions_from_ib()
was never opened through execute_bracket() -- it has no entry in
OMSManager.active_trades at all, so the read-time fallback in
main._monitor_open_stops() cannot resolve a stop for it either. The only
place a real stop might exist is IB itself, as a resting STP/STP LMT order.
This fix queries IBGatewayManager.get_open_orders() for such an order and,
if found, persists it via DatabaseManager.update_paper_trade_stop_loss()
(same guarded write path added in PR #331) immediately after the tracker
row is created. Best-effort: no open order, or a lookup/write failure, must
never block the position sync itself.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

ENGINE_DIR = Path(__file__).resolve().parent.parent
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))

from database.manager import DatabaseManager  # noqa: E402
from execution.ib_order_manager import IBOrderManager  # noqa: E402
from portfolio.tracker import PortfolioTracker  # noqa: E402


def _make_manager(tmp_path, ib_positions, open_orders):
    db = DatabaseManager(db_path=str(tmp_path / "sync_backfill.db"))
    db.initialize()
    tracker = PortfolioTracker(store_path=tmp_path / "trades.jsonl", db_manager=db)

    gateway = MagicMock()
    gateway.is_connected.return_value = True
    gateway.get_positions = AsyncMock(return_value=ib_positions)
    gateway.get_open_orders = AsyncMock(return_value=open_orders)

    safety = MagicMock()
    manager = IBOrderManager(safety_layer=safety, ib_gateway=gateway, portfolio_tracker=tracker)
    return manager, tracker, db


@pytest.mark.asyncio
async def test_backfills_stop_from_matching_stp_order(tmp_path):
    ib_positions = [
        {"symbol": "MES", "position": 1, "avg_cost": 5000.0, "sec_type": "FUT", "exchange": "CME"}
    ]
    open_orders = [
        {"symbol": "MES", "order_type": "STP", "aux_price": 4950.0, "action": "SELL"}
    ]
    manager, tracker, db = _make_manager(tmp_path, ib_positions, open_orders)

    await manager.sync_positions_from_ib()

    rows = db.get_open_trades()
    row = next(r for r in rows if r["symbol"] == "MES")
    assert row["stop_loss"] == 4950.0


@pytest.mark.asyncio
async def test_no_matching_order_leaves_stop_null(tmp_path):
    ib_positions = [
        {"symbol": "MGC", "position": 1, "avg_cost": 2400.0, "sec_type": "FUT", "exchange": "COMEX"}
    ]
    manager, tracker, db = _make_manager(tmp_path, ib_positions, open_orders=[])

    await manager.sync_positions_from_ib()

    rows = db.get_open_trades()
    row = next(r for r in rows if r["symbol"] == "MGC")
    assert row["stop_loss"] is None


@pytest.mark.asyncio
async def test_non_stop_order_type_is_ignored(tmp_path):
    ib_positions = [
        {"symbol": "MES", "position": 1, "avg_cost": 5000.0, "sec_type": "FUT", "exchange": "CME"}
    ]
    open_orders = [
        {"symbol": "MES", "order_type": "LMT", "aux_price": None, "action": "SELL"}
    ]
    manager, tracker, db = _make_manager(tmp_path, ib_positions, open_orders)

    await manager.sync_positions_from_ib()

    rows = db.get_open_trades()
    row = next(r for r in rows if r["symbol"] == "MES")
    assert row["stop_loss"] is None


@pytest.mark.asyncio
async def test_get_open_orders_failure_does_not_block_sync(tmp_path):
    ib_positions = [
        {"symbol": "MES", "position": 1, "avg_cost": 5000.0, "sec_type": "FUT", "exchange": "CME"}
    ]
    manager, tracker, db = _make_manager(tmp_path, ib_positions, open_orders=[])
    manager._gateway.get_open_orders = AsyncMock(side_effect=RuntimeError("IB disconnected"))

    result = await manager.sync_positions_from_ib()

    assert len(result) == 1
    rows = db.get_open_trades()
    row = next(r for r in rows if r["symbol"] == "MES")
    assert row["stop_loss"] is None
