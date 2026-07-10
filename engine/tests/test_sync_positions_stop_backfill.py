"""
IBOrderManager.sync_positions_from_ib — naked-row backfill for broker-synced
positions.

Background: unlike OMS-bracket trades (fixed via resolve_stop_for_symbol), a
position discovered via sync_positions_from_ib() was never opened through
execute_bracket() -- it has no entry in OMSManager.active_trades at all, so
the read-time fallback in main._monitor_open_stops() cannot resolve a stop
for it either. Two sources can supply a stop, checked in priority order:

  1. IB itself, as a resting STP/STP LMT order (queried via
     IBGatewayManager.get_open_orders()) -- the real broker-side stop, so it
     takes priority when one exists.
  2. A synthesized defensive stop from the same dollar-risk budget as
     PaperStopMonitor's catastrophe cap (services.paper_stop_monitor.
     synthesize_fallback_stop), used only when IB holds no resting stop.

Either way the resolved stop is threaded directly into open_trade(stop_loss=
...), tagged via stop_source ("ib_resting_order" or
"synthesized_fallback") so an audit can tell a real broker stop apart from a
guessed one. Best-effort throughout: no open order, no synthesis result, or
a lookup/write failure must never block the position sync itself.
"""

from __future__ import annotations

import json
import os
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


def _stop_source(row: dict) -> "str | None":
    """get_open_trades() returns strategy_params as a raw JSON string."""
    raw = row.get("strategy_params")
    if not raw:
        return None
    return json.loads(raw).get("stop_source")


def _set_max_loss_env(value):
    prev = os.environ.get("PAPER_MAX_LOSS_USD_PER_TRADE")
    if value is None:
        os.environ.pop("PAPER_MAX_LOSS_USD_PER_TRADE", None)
    else:
        os.environ["PAPER_MAX_LOSS_USD_PER_TRADE"] = str(value)
    return prev


def _restore_max_loss_env(prev):
    if prev is None:
        os.environ.pop("PAPER_MAX_LOSS_USD_PER_TRADE", None)
    else:
        os.environ["PAPER_MAX_LOSS_USD_PER_TRADE"] = prev


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
async def test_real_stop_tagged_as_ib_resting_order(tmp_path):
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
    assert _stop_source(row) == "ib_resting_order"


@pytest.mark.asyncio
async def test_no_matching_order_falls_back_to_synthesized_stop(tmp_path):
    # No resting IB stop for this symbol -> falls back to a synthesized
    # defensive stop (same dollar-risk budget as PaperStopMonitor's
    # catastrophe cap) rather than leaving the row naked (stop_loss=NULL).
    prev = _set_max_loss_env(300)
    try:
        ib_positions = [
            {
                "symbol": "MGC",
                "position": 1,
                "avg_cost": 2400.0,
                "sec_type": "FUT",
                "exchange": "COMEX",
            }
        ]
        manager, tracker, db = _make_manager(tmp_path, ib_positions, open_orders=[])

        await manager.sync_positions_from_ib()

        rows = db.get_open_trades()
        row = next(r for r in rows if r["symbol"] == "MGC")
        # MGC mult=10, qty=1 -> distance = 300/10 = 30.0; long -> entry - distance
        assert row["stop_loss"] == round(2400.0 - 30.0, 4)
        assert _stop_source(row) == "synthesized_fallback"
    finally:
        _restore_max_loss_env(prev)


@pytest.mark.asyncio
async def test_no_matching_order_and_synthesis_disabled_leaves_stop_null(tmp_path):
    # Both sources unavailable (no IB stop, catastrophe cap disabled) -> stays
    # NULL. That is a genuinely naked broker position needing a human-placed
    # stop, not a bug in this code path.
    prev = _set_max_loss_env(0)
    try:
        ib_positions = [
            {
                "symbol": "MGC",
                "position": 1,
                "avg_cost": 2400.0,
                "sec_type": "FUT",
                "exchange": "COMEX",
            }
        ]
        manager, tracker, db = _make_manager(tmp_path, ib_positions, open_orders=[])

        await manager.sync_positions_from_ib()

        rows = db.get_open_trades()
        row = next(r for r in rows if r["symbol"] == "MGC")
        assert row["stop_loss"] is None
    finally:
        _restore_max_loss_env(prev)


@pytest.mark.asyncio
async def test_non_stop_order_type_is_ignored(tmp_path):
    # A non-STP resting order (e.g. a plain LMT) must not be mistaken for a
    # real stop -- falls through to the synthesized fallback instead.
    prev = _set_max_loss_env(300)
    try:
        ib_positions = [
            {
                "symbol": "MES",
                "position": 1,
                "avg_cost": 5000.0,
                "sec_type": "FUT",
                "exchange": "CME",
            }
        ]
        open_orders = [{"symbol": "MES", "order_type": "LMT", "aux_price": None, "action": "SELL"}]
        manager, tracker, db = _make_manager(tmp_path, ib_positions, open_orders)

        await manager.sync_positions_from_ib()

        rows = db.get_open_trades()
        row = next(r for r in rows if r["symbol"] == "MES")
        # MES mult=5, qty=1 -> distance = 300/5 = 60.0; long -> entry - distance
        assert row["stop_loss"] == round(5000.0 - 60.0, 4)
        assert _stop_source(row) == "synthesized_fallback"
    finally:
        _restore_max_loss_env(prev)


@pytest.mark.asyncio
async def test_get_open_orders_failure_does_not_block_sync(tmp_path):
    # get_open_orders() failing must never raise or block the sync -- falls
    # through to the synthesized fallback, same as "no matching order".
    prev = _set_max_loss_env(300)
    try:
        ib_positions = [
            {
                "symbol": "MES",
                "position": 1,
                "avg_cost": 5000.0,
                "sec_type": "FUT",
                "exchange": "CME",
            }
        ]
        manager, tracker, db = _make_manager(tmp_path, ib_positions, open_orders=[])
        manager._gateway.get_open_orders = AsyncMock(side_effect=RuntimeError("IB disconnected"))

        result = await manager.sync_positions_from_ib()

        assert len(result) == 1
        rows = db.get_open_trades()
        row = next(r for r in rows if r["symbol"] == "MES")
        assert row["stop_loss"] == round(5000.0 - 60.0, 4)
    finally:
        _restore_max_loss_env(prev)
