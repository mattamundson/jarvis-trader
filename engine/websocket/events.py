"""
WebSocket Event Emitters
========================
Helper functions to broadcast trading events to connected clients.
"""

import logging
from typing import Any, Optional

from .manager import WebSocketManager

logger = logging.getLogger(__name__)

# Global WebSocket manager instance (initialized in main.py)
_ws_manager: Optional[WebSocketManager] = None


def set_ws_manager(manager: WebSocketManager):
    """Set the global WebSocket manager instance."""
    global _ws_manager
    _ws_manager = manager


def _get_manager() -> Optional[WebSocketManager]:
    """Get the global WebSocket manager (returns None if not initialized)."""
    return _ws_manager


# ─────────────────────────────────────────────────────────────────────────────
# Event Emitters
# ─────────────────────────────────────────────────────────────────────────────


async def emit_order_fill(order_data: dict):
    """
    Broadcast an order fill event.

    Args:
        order_data: Dict containing order details
                    (symbol, quantity, price, side, order_id, etc.)
    """
    manager = _get_manager()
    if not manager:
        return

    try:
        await manager.broadcast("order_fill", order_data)
        logger.debug(f"Emitted order_fill event: {order_data.get('order_id', 'unknown')}")
    except Exception as e:
        logger.error(f"Error emitting order_fill: {e}")


async def emit_kill_switch_change(active: bool, reason: str = ""):
    """
    Broadcast kill switch state change.

    Args:
        active: Whether kill switch is now active
        reason: Optional reason for the change
    """
    manager = _get_manager()
    if not manager:
        return

    try:
        data = {
            "active": active,
            "reason": reason,
            "action": "activated" if active else "deactivated",
        }
        await manager.broadcast("kill_switch", data)
        logger.info(f"Emitted kill_switch event: {data['action']} ({reason})")
    except Exception as e:
        logger.error(f"Error emitting kill_switch: {e}")


async def emit_circuit_breaker(breaker_name: str, triggered: bool, value: Optional[float] = None):
    """
    Broadcast circuit breaker event.

    Args:
        breaker_name: Name of the circuit breaker (e.g., "daily_loss", "max_drawdown")
        triggered: Whether the breaker has been triggered
        value: Optional current value that triggered the breaker
    """
    manager = _get_manager()
    if not manager:
        return

    try:
        data = {
            "breaker_name": breaker_name,
            "triggered": triggered,
            "value": value,
        }
        await manager.broadcast("circuit_breaker", data)
        logger.info(f"Emitted circuit_breaker event: {breaker_name} = {triggered}")
    except Exception as e:
        logger.error(f"Error emitting circuit_breaker: {e}")


async def emit_pending_approval_created(
    approval_id: str,
    symbol: str,
    final_action: str,
    *,
    quantity: Optional[float] = None,
    entry_price: Optional[float] = None,
    extra: Optional[dict[str, Any]] = None,
):
    """Notify dashboards that a human-gated approval row was created."""
    manager = _get_manager()
    if not manager:
        return
    try:
        payload: dict[str, Any] = {
            "approval_id": approval_id,
            "symbol": symbol,
            "final_action": final_action,
        }
        if quantity is not None:
            payload["quantity"] = quantity
        if entry_price is not None:
            payload["entry_price"] = entry_price
        if extra:
            payload.update(extra)
        await manager.broadcast("pending_approval_created", payload)
        logger.debug("Emitted pending_approval_created: %s → %s", symbol, approval_id[:8])
    except Exception as e:
        logger.error("Error emitting pending_approval_created: %s", e)


async def emit_pipeline_complete(symbol: str, decision: str, timing: dict):
    """
    Broadcast pipeline completion event.

    Args:
        symbol: Trading symbol
        decision: Final decision ("buy", "sell", "hold")
        timing: Dict with timing info (started_at, completed_at, elapsed_ms, etc.)
    """
    manager = _get_manager()
    if not manager:
        return

    try:
        data = {
            "symbol": symbol,
            "decision": decision,
            "timing": timing,
        }
        await manager.broadcast("pipeline_complete", data)
        logger.debug(f"Emitted pipeline_complete event: {symbol} → {decision}")
    except Exception as e:
        logger.error(f"Error emitting pipeline_complete: {e}")


async def emit_safety_event(event_type: str, details: dict):
    """
    Broadcast a safety/risk event.

    Args:
        event_type: Type of safety event ("position_limit", "margin_warning", etc.)
        details: Dict with event details (symbol, reason, current_value, limit, etc.)
    """
    manager = _get_manager()
    if not manager:
        return

    try:
        data = {
            "event_type": event_type,
            "details": details,
        }
        await manager.broadcast("safety_event", data)
        logger.info(f"Emitted safety_event: {event_type}")
    except Exception as e:
        logger.error(f"Error emitting safety_event: {e}")


async def emit_price_update(
    symbol: str, price: float, bid: Optional[float] = None, ask: Optional[float] = None
):
    """
    Broadcast a price update event.

    Args:
        symbol: Trading symbol
        price: Current price
        bid: Optional bid price
        ask: Optional ask price
    """
    manager = _get_manager()
    if not manager:
        return

    try:
        data = {
            "symbol": symbol,
            "price": price,
            "bid": bid,
            "ask": ask,
        }
        await manager.broadcast("price_update", data)
        logger.debug(f"Emitted price_update event: {symbol} = {price}")
    except Exception as e:
        logger.error(f"Error emitting price_update: {e}")
