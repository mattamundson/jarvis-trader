"""
Position Reconciler
Checks for orphaned positions (positions without stop-losses) on boot.
Issues alerts and forcefully attaches stop-losses to protect the account
when the engine process restarts.
"""

import logging

try:
    from config import settings  # noqa: F401  (presence-check only)
except ImportError:
    pass

logger = logging.getLogger(__name__)


class PositionReconciler:
    def __init__(self, ib_gateway, oms_manager=None):
        self.ib_gateway = ib_gateway
        self.oms_manager = oms_manager

    async def reconcile(self) -> None:
        if not self.ib_gateway or not self.ib_gateway.is_connected():
            logger.error("PositionReconciler cannot run: IB Gateway not connected")
            return

        try:
            positions = await self.ib_gateway.get_positions()
            if not positions:
                logger.info("[RECONCILER] No open positions detected.")
                return

            open_orders = await self.ib_gateway.get_open_orders()

            # Group active STP orders by symbol
            stp_orders = {}
            for o in open_orders:
                order_type = str(o.get("order_type", "")).upper()
                status = str(o.get("status", "")).upper()
                if order_type in ("STP", "STP_LMT", "STOP", "STOP_LMT") and status not in (
                    "FILLED",
                    "CANCELLED",
                    "INACTIVE",
                ):
                    sym = o.get("symbol")
                    if sym not in stp_orders:
                        stp_orders[sym] = []
                    stp_orders[sym].append(o)

            # Analyze positions
            orphaned = 0
            for pos in positions:
                symbol = pos.get("symbol")
                quantity = int(pos.get("position", 0))
                avg_cost = float(pos.get("avg_cost", 0.0))

                if quantity == 0:
                    continue

                if symbol not in stp_orders or len(stp_orders[symbol]) == 0:
                    logger.warning(
                        f"[RECONCILER] Orphaned position detected: {symbol} Qty: {quantity}"
                    )
                    await self._handle_orphaned_position(symbol, quantity, avg_cost)
                    orphaned += 1

            if orphaned == 0:
                logger.info("[RECONCILER] All open positions are bracketed correctly.")

        except Exception as e:
            logger.error(f"[RECONCILER] Encountered an error: {e}", exc_info=True)

    async def _handle_orphaned_position(self, symbol: str, quantity: int, avg_cost: float) -> None:
        # Default emergency stop-loss: 2% adverse from avg fill price.
        emergency_pct = 0.02
        if quantity > 0:
            stop_price = avg_cost * (1 - emergency_pct)
            action = "SELL"
        else:
            stop_price = avg_cost * (1 + emergency_pct)
            action = "BUY"

        # Tick size rounding (assume minimum 0.25 tick size for CME micros)
        stop_price = round(stop_price / 0.25) * 0.25

        logger.info(f"[RECONCILER] Attaching emergency Stop Loss for {symbol} at {stop_price}")
        try:
            sl_id = await self.ib_gateway.place_paper_order(
                symbol=symbol,
                action=action,
                quantity=abs(quantity),
                order_type="STP",
                aux_price=stop_price,
            )

            # Adopt into OMS if available
            if self.oms_manager:
                await self.oms_manager.adopt_existing_trade(
                    symbol=symbol,
                    quantity=quantity,
                    entry_price=avg_cost,
                    stop_loss_id=sl_id
                )

            # Send notification
            try:
                from notifications.whatsapp import get_notifier

                notifier = get_notifier()
                if getattr(notifier, "enabled", False):
                    await notifier.send(
                        f"🚨 ORPHANED POSITION ALERT: {symbol} qty={quantity}.\n"
                        f"Crash recovery active. Force-attached emergency 2% STP @ {stop_price:.2f}."
                    )
            except ImportError:
                pass

        except Exception as e:
            logger.error(f"[RECONCILER] Failed to attach emergency stop for {symbol}: {e}")
