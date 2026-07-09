"""
JARVIS TRADER — Order Management System (OMS) v2
================================================
Manages complex order lifecycles (Brackets, OCO) and position synchronization.
Implements Roadmap Phase 2.3 logic.

The OMS sits between the TradingPipeline and the OrderRouter. It maintains
a state machine for each active trade, ensuring that stops and targets are
properly linked and cancelled when a position is closed.
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("jarvis_trader.oms")

class TradeState(Enum):
    PENDING_ENTRY = "pending_entry"
    ACTIVE = "active"
    CLOSING = "closing"
    CLOSED = "closed"
    CANCELLED = "cancelled"
    ERROR = "error"

@dataclass
class BracketOrder:
    trade_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    symbol: str = ""
    quantity: int = 0

    # Order IDs from the broker
    entry_order_id: Optional[str] = None
    stop_loss_id: Optional[str] = None
    take_profit_id: Optional[str] = None

    # Target prices
    entry_price: float = 0.0
    stop_loss_price: Optional[float] = None
    take_profit_price: Optional[float] = None

    status: TradeState = TradeState.PENDING_ENTRY
    opened_at: datetime = field(default_factory=datetime.utcnow)
    closed_at: Optional[datetime] = None

    exit_reason: Optional[str] = None # "tp", "sl", "manual", "flatten"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trade_id": self.trade_id,
            "symbol": self.symbol,
            "quantity": self.quantity,
            "entry_order_id": self.entry_order_id,
            "stop_loss_id": self.stop_loss_id,
            "take_profit_id": self.take_profit_id,
            "entry_price": self.entry_price,
            "stop_loss_price": self.stop_loss_price,
            "take_profit_price": self.take_profit_price,
            "status": self.status.value,
            "opened_at": self.opened_at.isoformat(),
            "closed_at": self.closed_at.isoformat() if self.closed_at else None,
            "exit_reason": self.exit_reason
        }

class OMSManager:
    """
    State machine for order brackets and position lifecycle.
    """

    def __init__(self, order_router, ib_order_manager=None):
        self.router = order_router
        self.ib_order_manager = ib_order_manager
        self.active_trades: Dict[str, BracketOrder] = {}
        self._lock = asyncio.Lock()

    async def execute_bracket(
        self,
        symbol: str,
        action: str,
        quantity: int,
        entry_price: float,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        entry_type: str = "MKT",
    ) -> BracketOrder:
        """
        Initiate a new bracket trade.
        """
        async with self._lock:
            trade = BracketOrder(
                symbol=symbol,
                quantity=quantity,
                entry_price=entry_price,
                stop_loss_price=stop_loss,
                take_profit_price=take_profit,
            )

            logger.info(
                "[OMS] Executing bracket for %s: %s %d @ %.2f (SL: %s, TP: %s)",
                symbol,
                action,
                quantity,
                entry_price,
                stop_loss,
                take_profit,
            )

            try:
                # 1. Choose the execution path (Future -> IBOrderManager, Else -> Router)
                sym_upper = symbol.upper()
                is_future = self.router.is_futures(sym_upper)

                if is_future and self.ib_order_manager:
                    logger.info("[OMS] Routing futures bracket to IBOrderManager (with Safety)")
                    result = await self.ib_order_manager.submit_bracket_order(
                        symbol=symbol,
                        action=action,
                        quantity=quantity,
                        price=entry_price,
                        stop_loss=stop_loss,
                        take_profit=take_profit,
                        order_type=entry_type,
                        limit_price=entry_price if entry_type == "LMT" else None,
                    )
                else:
                    logger.info("[OMS] Routing bracket to standard OrderRouter")
                    result = await self.router.route_bracket_order(
                        symbol=symbol,
                        action=action,
                        quantity=quantity,
                        entry_type=entry_type,
                        limit_price=entry_price if entry_type == "LMT" else None,
                        stop_loss=stop_loss,
                        take_profit=take_profit,
                    )

                if result.get("approved") or result.get("status") == "placed":
                    trade.entry_order_id = result.get("entry_id") or result.get("order_id")
                    trade.stop_loss_id = result.get("sl_id")
                    trade.take_profit_id = result.get("tp_id")
                    trade.status = (
                        TradeState.ACTIVE
                    )  # Assuming immediate entry fill for paper sim
                    self.active_trades[trade.trade_id] = trade
                    logger.info(
                        "[OMS] Bracket placed successfully for %s. ID: %s",
                        symbol,
                        trade.trade_id,
                    )
                else:
                    trade.status = TradeState.ERROR
                    logger.error(
                        "[OMS] Failed to place bracket for %s: %s",
                        symbol,
                        result.get("reason") or result.get("error"),
                    )

            except Exception as e:
                trade.status = TradeState.ERROR
                logger.error("[OMS] Exception during bracket execution for %s: %s", symbol, e)

            return trade

    async def execute_options_spread(
        self,
        symbol: str,
        spread_type: str,
        short_opt: str,
        long_opt: str,
        quantity: int,
        net_credit: float,
    ) -> BracketOrder:
        """
        Execute a multi-leg vertical options spread.
        """
        async with self._lock:
            trade = BracketOrder(
                symbol=symbol,
                quantity=quantity,
                entry_price=net_credit,
                status=TradeState.PENDING_ENTRY,
            )

            logger.info(
                "[OMS] Executing Options Spread for %s: %s %d @ %.2f (Short: %s, Long: %s)",
                symbol,
                spread_type,
                quantity,
                net_credit,
                short_opt,
                long_opt,
            )

            try:
                # 1. Dispatch to router
                order = {
                    "symbol": symbol,
                    "is_options": True,
                    "is_spread": True,
                    "type": spread_type,
                    "short_option_symbol": short_opt,
                    "long_option_symbol": long_opt,
                    "quantity": quantity,
                    "limit_price": net_credit,
                    "order_type": "limit",
                }

                result = await self.router.route_order(order)

                if result.get("status") == "placed":
                    trade.entry_order_id = result.get("order_id")
                    trade.status = TradeState.ACTIVE
                    self.active_trades[trade.trade_id] = trade
                    logger.info("[OMS] Options Spread placed successfully. ID: %s", trade.trade_id)
                else:
                    trade.status = TradeState.ERROR
                    logger.error(
                        "[OMS] Failed to place spread: %s", result.get("reason") or result.get("error")
                    )

            except Exception as e:
                trade.status = TradeState.ERROR
                logger.error("[OMS] Exception during spread execution for %s: %s", symbol, e)

            return trade

    async def update_trade_status(self, broker_order_id: str, status: str, fill_price: float = 0.0):
        """
        Callback handler for broker order status updates.
        Implements OCO logic: if TP fills, cancel SL.
        """
        async with self._lock:
            for _trade_id, trade in self.active_trades.items():
                # Check if this order belongs to this trade
                if broker_order_id == trade.stop_loss_id and status == "filled":
                    await self._handle_exit(trade, "sl", fill_price)
                    return
                elif broker_order_id == trade.take_profit_id and status == "filled":
                    await self._handle_exit(trade, "tp", fill_price)
                    return

    async def _handle_exit(self, trade: BracketOrder, reason: str, price: float):
        """
        Handle a partial or full exit of a bracket.
        """
        logger.info("[OMS] Trade %s exited via %s @ %.2f", trade.trade_id, reason.upper(), price)
        trade.status = TradeState.CLOSED
        trade.closed_at = datetime.utcnow()
        trade.exit_reason = reason

        # OCO: Cancel the other leg
        other_id = trade.take_profit_id if reason == "sl" else trade.stop_loss_id
        if other_id:
            try:
                await self.router.cancel_order(other_id)
                logger.info("[OMS] OCO cancelled other leg: %s", other_id)
            except Exception as e:
                logger.warning("[OMS] Failed to cancel OCO leg %s: %s", other_id, e)

        # Cleanup
        # In a real system, we'd persist to DB first
        # del self.active_trades[trade.trade_id]

    async def update_stop_loss(self, trade_id: str, new_stop_price: float):
        """
        Update the stop loss price for an active trade.
        """
        async with self._lock:
            trade = self.active_trades.get(trade_id)
            if not trade or trade.status != TradeState.ACTIVE:
                logger.warning("[OMS] Cannot update SL: Trade %s not active", trade_id)
                return

            if not trade.stop_loss_id:
                logger.warning("[OMS] Cannot update SL: Trade %s has no SL order ID", trade_id)
                return

            logger.info("[OMS] Updating SL for %s: %.2f -> %.2f",
                        trade.symbol, trade.stop_loss_price or 0.0, new_stop_price)

            try:
                # Dispatch to router for modification
                result = await self.router.modify_order(
                    order_id=trade.stop_loss_id,
                    new_price=new_stop_price
                )

                if result.get("status") == "modified":
                    trade.stop_loss_price = new_stop_price
                    logger.info("[OMS] SL updated successfully for %s", trade.symbol)
                else:
                    logger.error("[OMS] Failed to update SL for %s: %s",
                                 trade.symbol, result.get("error"))
            except Exception as e:
                logger.error("[OMS] Exception during SL update for %s: %s", trade.symbol, e)

    def get_active_trades(self) -> List[Dict[str, Any]]:
        return [t.to_dict() for t in self.active_trades.values() if t.status == TradeState.ACTIVE]

    def resolve_stop_for_symbol(self, symbol: str) -> Optional[float]:
        """
        Return the resting stop_loss_price for the most recent ACTIVE bracket
        on ``symbol``, or None if none is tracked.

        Backstop for stop-monitor callers whose own stop-loss record is
        missing/NULL -- e.g. paper_trades rows opened via this OMS's bracket
        path, where the entry fill is ultimately logged through
        ``PortfolioTracker.open_trade()`` (no ``stop_loss`` parameter -- a
        separate, documented data-hygiene gap, not fixed here). This OMS
        already holds the real ``stop_loss_price`` in-memory on the
        ``BracketOrder`` from ``execute_bracket()`` time, independent of that
        gap, so callers (the 5-minute "Open Position Stop Monitor" job and
        ``PaperStopMonitor``) can fall back to it before giving up on
        enforcing a per-trade stop entirely.

        Matches by symbol only -- ``BracketOrder`` does not record side/action.
        Safe under this account's one-position-per-symbol trading pattern
        (MES/MGC, 1-2 micro contracts, never simultaneous long+short on the
        same root).
        """
        sym_upper = str(symbol or "").upper()
        if not sym_upper:
            return None
        candidates = [
            trade
            for trade in self.active_trades.values()
            if trade.status == TradeState.ACTIVE
            and trade.symbol.upper() == sym_upper
            and trade.stop_loss_price is not None
        ]
        if not candidates:
            return None
        # dict insertion order is NOT the same as recency once
        # adopt_existing_trade()/reload_from_db() are in play, so sort
        # explicitly by opened_at rather than relying on iteration order.
        most_recent = max(candidates, key=lambda t: t.opened_at)
        return most_recent.stop_loss_price

    async def adopt_existing_trade(self, symbol: str, quantity: int, entry_price: float,
                                 stop_loss_id: Optional[str] = None,
                                 take_profit_id: Optional[str] = None) -> str:
        """
        Adopt an existing position (e.g. found during reconciliation) into the OMS.
        """
        async with self._lock:
            trade = BracketOrder(
                symbol=symbol,
                quantity=quantity,
                entry_price=entry_price,
                status=TradeState.ACTIVE,
                stop_loss_id=stop_loss_id,
                take_profit_id=take_profit_id
            )
            self.active_trades[trade.trade_id] = trade
            logger.info("[OMS] Adopted existing position: %s Qty: %d ID: %s",
                        symbol, quantity, trade.trade_id)
            return trade.trade_id

    async def reload_from_db(self, db_manager):
        """
        Rebuild active_trades map from the paper_trades database.
        Allows OMS to recover state after an engine restart.
        """
        if not db_manager:
            return

        try:
            # Query for open paper trades
            # SQLite query against paper_trades table
            rows = db_manager.get_open_trades() # Assuming this method exists
            if not rows:
                logger.info("[OMS] No open trades found in DB to reload.")
                return

            async with self._lock:
                for row in rows:
                    # Map DB row to BracketOrder
                    trade = BracketOrder(
                        trade_id=row.get("id"),
                        symbol=row.get("symbol"),
                        quantity=int(row.get("quantity", 0)),
                        entry_price=float(row.get("entry_price", 0.0)),
                        entry_order_id=row.get("order_id"),
                        status=TradeState.ACTIVE
                    )
                    # We might need to find SL/TP IDs from the broker if not in DB
                    self.active_trades[trade.trade_id] = trade

                logger.info("[OMS] Reloaded %d active trades from DB", len(rows))
        except Exception as e:
            logger.error("[OMS] Failed to reload trades from DB: %s", e)
