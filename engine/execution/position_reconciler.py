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

try:
    from backtest.contract_specs import CONTRACT_SPECS
except ImportError:  # pragma: no cover - keep the reconciler importable if specs move
    CONTRACT_SPECS = {}

logger = logging.getLogger(__name__)

# Fallback tick when a symbol has no registered ContractSpec. 0.25 is the CME
# equity-micro grid (MES/MNQ); it is only a last resort so the emergency stop
# still rounds to *something* placeable rather than crashing the reconciler.
_DEFAULT_TICK = 0.25


def round_to_tick(price: float, symbol: str) -> float:
    """Snap a price to the symbol's real tick grid.

    The emergency-stop path previously hardcoded a 0.25 tick for every symbol,
    which produces an INVALID price for instruments on a finer grid -- MGC (0.10)
    and MCL (0.01) -- so IB can reject the emergency stop and the orphaned
    position is left unprotected. Use the canonical per-symbol tick; fall back to
    0.25 only for unregistered symbols. Never raises (orphan-recovery path).
    """
    spec = CONTRACT_SPECS.get(symbol.upper()) if symbol else None
    tick = spec.tick_size if spec else _DEFAULT_TICK
    if not spec:
        logger.warning(
            "[RECONCILER] No contract spec for %s; using %.2f tick fallback for emergency stop",
            symbol,
            _DEFAULT_TICK,
        )
    # round(.., 4) strips float-division noise; all registered ticks are >= 0.01.
    return round(round(price / tick) * tick, 4)


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
            # This is the sole crash-recovery sweep that detects positions left
            # without a stop-loss after an engine restart (2026-08-11
            # fail-open-safety-checks audit finding #5). A failure here means
            # the sweep never ran at all -- any real orphaned position stays
            # silently unprotected with no signal beyond this log line. Alert
            # separately from the per-position failure below, which fires only
            # once a specific orphan was already found.
            await self._alert(
                f"🚨 POSITION RECONCILER FAILED: {e}\n"
                "Crash-recovery orphaned-position sweep did not complete -- "
                "any position missing a stop-loss after a restart may be "
                "unprotected right now. Check engine logs and current "
                "positions/orders manually."
            )

    async def _alert(self, message: str) -> None:
        """Best-effort WhatsApp alert -- a notifier failure must never mask
        the original exception it's reporting on."""
        try:
            from notifications.whatsapp import get_notifier

            notifier = get_notifier()
            if getattr(notifier, "enabled", False):
                await notifier.send(message)
        except Exception as notify_exc:
            logger.warning("[RECONCILER] alert notify failed: %s", notify_exc)

    async def _handle_orphaned_position(self, symbol: str, quantity: int, avg_cost: float) -> None:
        # Default emergency stop-loss: 2% adverse from avg fill price.
        emergency_pct = 0.02
        if quantity > 0:
            stop_price = avg_cost * (1 - emergency_pct)
            action = "SELL"
        else:
            stop_price = avg_cost * (1 + emergency_pct)
            action = "BUY"

        # Snap to the symbol's real tick grid (MGC=0.10, MCL=0.01, MES/MNQ=0.25).
        # Hardcoding 0.25 produced invalid prices on finer grids -> IB rejection
        # -> orphaned position left unprotected.
        stop_price = round_to_tick(stop_price, symbol)

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
                    stop_loss_id=sl_id,
                    stop_loss_price=stop_price
                )

            await self._alert(
                f"🚨 ORPHANED POSITION ALERT: {symbol} qty={quantity}.\n"
                f"Crash recovery active. Force-attached emergency 2% STP @ {stop_price:.2f}."
            )

        except Exception as e:
            logger.error(f"[RECONCILER] Failed to attach emergency stop for {symbol}: {e}")
            # A known orphaned position (already detected, unlike the sweep
            # failure above) still has no stop-loss after this failure -- the
            # highest-urgency case in this file, since the risk is confirmed,
            # not hypothetical.
            await self._alert(
                f"🚨 EMERGENCY STOP ATTACH FAILED: {symbol} qty={quantity} is "
                f"ORPHANED (no stop-loss) and the crash-recovery attempt to "
                f"protect it also failed: {e}\n"
                "This position is unprotected right now -- attach a stop-loss "
                "manually."
            )
