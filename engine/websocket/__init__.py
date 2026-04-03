"""
JARVIS TRADER — WebSocket Event Streaming
===========================================
Real-time event broadcasting for trading events, safety alerts, and pipeline updates.
"""

from .events import (
    emit_circuit_breaker,
    emit_kill_switch_change,
    emit_order_fill,
    emit_pending_approval_created,
    emit_pipeline_complete,
    emit_price_update,
    emit_safety_event,
)
from .manager import WebSocketManager
from .price_feed import PriceFeedManager, get_price_feed_manager, price_feed_endpoint

__all__ = [
    "WebSocketManager",
    "emit_order_fill",
    "emit_kill_switch_change",
    "emit_circuit_breaker",
    "emit_pending_approval_created",
    "emit_pipeline_complete",
    "emit_safety_event",
    "emit_price_update",
    "PriceFeedManager",
    "get_price_feed_manager",
    "price_feed_endpoint",
]
