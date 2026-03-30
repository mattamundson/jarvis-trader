"""
JARVIS TRADER — WebSocket Event Streaming
===========================================
Real-time event broadcasting for trading events, safety alerts, and pipeline updates.
"""

from .manager import WebSocketManager
from .events import (
    emit_order_fill,
    emit_kill_switch_change,
    emit_circuit_breaker,
    emit_pipeline_complete,
    emit_safety_event,
    emit_price_update,
)

__all__ = [
    "WebSocketManager",
    "emit_order_fill",
    "emit_kill_switch_change",
    "emit_circuit_breaker",
    "emit_pipeline_complete",
    "emit_safety_event",
    "emit_price_update",
]
