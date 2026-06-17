"""
System 2 — Real-Time Fill Callbacks (ib_async)
===============================================
Hooks ib_async IB events into the System2OrderManager so position
state transitions (T1→BE, T2→flat, stop→flat) happen on actual fills
rather than on the polling bar loop.

Events wired:
  orderStatusEvent (trade: Trade)
    → fired whenever an order's status changes (Filled, Cancelled, etc.)
  execDetailsEvent (trade: Trade, fill: Fill)
    → fired for every partial or full execution with fill price + qty
  commissionReportEvent (trade: Trade, fill: Fill, report: CommissionReport)
    → fired after each fill with cost breakdown (used for PnL logging)

Usage:
    from system2.fill_callbacks import wire_fill_callbacks
    wire_fill_callbacks(ib_instance, order_manager)

After wiring, the order manager's state machine advances on real fills.
The bar_advance_loop in executor.py becomes a backstop safety net only
(not the primary state driver).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


def wire_fill_callbacks(ib, order_manager) -> None:
    """
    Attach fill event handlers to a connected ib_async IB instance.

    Parameters
    ----------
    ib            : ib_async.IB — connected, authenticated IB instance
    order_manager : System2OrderManager — the order manager to advance
    """
    loop = asyncio.get_event_loop()

    def _on_order_status(trade):
        """
        Fires when an order status changes: Submitted, Filled, Cancelled, etc.
        We care about: Filled, Cancelled (to clean up dead orders).
        """
        try:
            status    = trade.orderStatus.status
            order_id  = trade.order.orderId
            symbol    = trade.contract.localSymbol or trade.contract.symbol
            filled    = trade.orderStatus.filled
            remaining = trade.orderStatus.remaining
            avg_fill  = trade.orderStatus.avgFillPrice

            logger.info(
                "[FillCallback] orderStatus: %s %s orderId=%d "
                "filled=%d remaining=%d avgFill=%.2f",
                symbol, status, order_id, filled, remaining, avg_fill
            )

            if status == "Filled":
                asyncio.ensure_future(
                    _handle_order_filled(order_manager, symbol, order_id, avg_fill, filled),
                    loop=loop,
                )
            elif status in ("Cancelled", "ApiCancelled"):
                logger.warning(
                    "[FillCallback] Order %d cancelled for %s", order_id, symbol
                )

        except Exception as e:
            logger.error("[FillCallback] orderStatus handler error: %s", e, exc_info=True)

    def _on_exec_details(trade, fill):
        """
        Fires for every partial or complete execution.
        Use this as the authoritative price source for PnL.
        """
        try:
            symbol    = trade.contract.localSymbol or trade.contract.symbol
            exec_price = fill.execution.price
            exec_qty   = fill.execution.shares
            exec_side  = fill.execution.side   # "BOT" or "SLD"
            order_id   = trade.order.orderId
            exec_time  = fill.execution.time

            logger.info(
                "[FillCallback] execDetails: %s %s %d @ %.2f orderId=%d time=%s",
                symbol, exec_side, exec_qty, exec_price, order_id, exec_time
            )

            # Update PnL tracking in order manager
            asyncio.ensure_future(
                _handle_exec_detail(
                    order_manager, symbol, order_id, exec_price, exec_qty, exec_side
                ),
                loop=loop,
            )

        except Exception as e:
            logger.error("[FillCallback] execDetails handler error: %s", e, exc_info=True)

    def _on_commission_report(trade, fill, report):
        """
        Fires after each fill with commission breakdown.
        Used to track actual round-trip costs vs. modeled costs.
        """
        try:
            symbol    = trade.contract.localSymbol or trade.contract.symbol
            commission = report.commission
            realized_pnl = getattr(report, "realizedPNL", None)

            logger.info(
                "[FillCallback] commission: %s comm=%.2f realizedPnL=%s",
                symbol, commission,
                f"${realized_pnl:.2f}" if realized_pnl is not None else "N/A"
            )

            # Log actual commission divergence vs. modeled
            modeled_comm = 4.50  # from order_manager._COMMISSION_RT_USD
            if abs(commission - modeled_comm) > 1.0:
                logger.warning(
                    "[FillCallback] Commission divergence: actual=%.2f modeled=%.2f",
                    commission, modeled_comm
                )

        except Exception as e:
            logger.error("[FillCallback] commissionReport handler error: %s", e, exc_info=True)

    # Wire the events
    ib.orderStatusEvent    += _on_order_status
    ib.execDetailsEvent    += _on_exec_details
    ib.commissionReportEvent += _on_commission_report

    logger.info(
        "[FillCallback] Wired: orderStatusEvent, execDetailsEvent, "
        "commissionReportEvent → System2OrderManager"
    )


# ── Async handlers ─────────────────────────────────────────────────────────────

async def _handle_order_filled(
    order_manager,
    symbol: str,
    order_id: int,
    avg_fill_price: float,
    filled_qty: int,
):
    """
    Map a filled orderId back to our position state and advance the machine.

    Logic:
      - Look up which order type (entry/stop/t1/t2) this orderId belongs to
      - Advance position state accordingly
      - Stop fill       → mark position closed, clean up
      - T1 fill         → mark t1_hit, trigger BE stop placement
      - T2 fill         → mark position closed
      - Backstop fill   → mark position closed
    """
    pos = order_manager._positions.get(symbol)
    if pos is None:
        logger.debug("[FillCallback] No active position for %s (orderId=%d)", symbol, order_id)
        return

    orders = pos.orders
    ts = datetime.now(timezone.utc)

    # Determine fill type by matching order_id
    if order_id == orders.stop_order_id:
        pnl = pos.pnl_from_price(avg_fill_price, filled_qty)
        pos.pnl_usd += pnl
        logger.info(
            "[FillCallback] STOP FILLED: %s %dct @ %.2f | PnL=$%.2f",
            symbol, filled_qty, avg_fill_price, pnl
        )
        await order_manager._close_position(pos, avg_fill_price, "STOP_FILL", ts)

    elif order_id == orders.t1_order_id:
        pnl = pos.pnl_from_price(avg_fill_price, filled_qty)
        pos.pnl_usd += pnl
        pos.t1_hit = True
        logger.info(
            "[FillCallback] T1 FILLED: %s %dct @ %.2f | PnL=$%.2f | Moving stop to BE",
            symbol, filled_qty, avg_fill_price, pnl
        )
        # Import here to avoid circular import
        from system2.order_manager import PositionState
        pos.state = PositionState.OPEN_HALF
        await order_manager._move_stop_to_be(pos)

    elif order_id == orders.t2_order_id:
        pnl = pos.pnl_from_price(avg_fill_price, filled_qty)
        pos.pnl_usd += pnl
        pos.t2_hit = True
        logger.info(
            "[FillCallback] T2 FILLED: %s %dct @ %.2f | PnL=$%.2f",
            symbol, filled_qty, avg_fill_price, pnl
        )
        await order_manager._close_position(pos, avg_fill_price, "T2_FILL", ts)

    elif order_id == orders.backstop_order_id:
        pnl = pos.pnl_from_price(avg_fill_price, filled_qty)
        pos.pnl_usd += pnl
        logger.info(
            "[FillCallback] BACKSTOP FILLED: %s %dct @ %.2f | PnL=$%.2f",
            symbol, filled_qty, avg_fill_price, pnl
        )
        await order_manager._close_position(pos, avg_fill_price, "BACKSTOP_FILL", ts)

    elif order_id == orders.entry_order_id:
        pos.entry_fill_price = avg_fill_price
        logger.info(
            "[FillCallback] ENTRY FILLED: %s %dct @ %.2f (signal was %.2f, slip=%.2f)",
            symbol, filled_qty, avg_fill_price, pos.entry_price,
            abs(avg_fill_price - pos.entry_price)
        )
        # Recalculate levels from actual fill price (not signal close)
        _recalculate_levels_from_fill(pos, avg_fill_price)

    else:
        logger.debug(
            "[FillCallback] Unknown orderId=%d for %s — may be a manual order",
            order_id, symbol
        )


async def _handle_exec_detail(
    order_manager,
    symbol: str,
    order_id: int,
    exec_price: float,
    exec_qty: int,
    exec_side: str,
):
    """
    Secondary handler — logs execution quality vs. modeled assumptions.
    Does not advance state (that's done by _handle_order_filled on full fill).
    """
    pos = order_manager._positions.get(symbol)
    if pos is None:
        return

    # Slippage analysis vs. signal price
    if exec_side == "BOT" and order_id == pos.orders.entry_order_id:
        slip = exec_price - pos.entry_price
        slip_ticks = slip / 0.25  # ES/NQ tick = 0.25
        if abs(slip_ticks) > 2:
            logger.warning(
                "[FillCallback] High entry slippage on %s: %.2f ticks (%.2f pts)",
                symbol, slip_ticks, slip
            )


def _recalculate_levels_from_fill(pos, actual_fill: float) -> None:
    """
    If entry fill differs from signal close (slippage), recalculate
    stop/T1/T2 levels from the actual fill price.
    Only adjusts if slippage > 2 ticks to avoid noise.
    """
    slip = abs(actual_fill - pos.entry_price)
    if slip < 0.50:  # < 2 ticks on ES
        return

    logger.info(
        "[FillCallback] Recalculating levels from actual fill %.2f (signal %.2f, slip %.2f)",
        actual_fill, pos.entry_price, slip
    )

    pos.entry_price  = actual_fill
    pos.stop_price   = round(actual_fill - 0.75 * pos.atr, 2)
    pos.t1_price     = round(actual_fill + 0.80 * pos.atr, 2)
    pos.t2_price     = round(actual_fill + 2.00 * pos.atr, 2)
    tick             = 0.25
    pos.be_price     = round(actual_fill + tick, 2)

    logger.info(
        "[FillCallback] Recalculated: stop=%.2f T1=%.2f T2=%.2f BE=%.2f",
        pos.stop_price, pos.t1_price, pos.t2_price, pos.be_price
    )
