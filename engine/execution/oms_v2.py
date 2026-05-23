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
from typing import Dict, List, Optional, Any

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

    async def update_trade_status(self, broker_order_id: str, status: str, fill_price: float = 0.0):
        """
        Callback handler for broker order status updates.
        Implements OCO logic: if TP fills, cancel SL.
        """
        async with self._lock:
            for trade_id, trade in self.active_trades.items():
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

    def get_active_trades(self) -> List[Dict[str, Any]]:
        return [t.to_dict() for t in self.active_trades.values() if t.status == TradeState.ACTIVE]
