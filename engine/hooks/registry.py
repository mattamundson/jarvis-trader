"""
HookRegistry — register and fire event hooks across the trading system.
Inspired by ECC's hook system. Hooks run synchronously in registration order.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any, Callable

logger = logging.getLogger("jarvis_trader.hooks")

# ── Event name constants ────────────────────────────────────────────────────────
SIGNAL_GENERATED = "signal_generated"
PRE_ORDER = "pre_order"
POST_ORDER = "post_order"
TRADE_CLOSED = "trade_closed"
DAILY_PNL_UPDATE = "daily_pnl_update"
KILL_SWITCH_TRIGGERED = "kill_switch_triggered"
TARGET_REACHED = "target_reached"
MARKET_CONNECTED = "market_connected"
MARKET_DISCONNECTED = "market_disconnected"

ALL_EVENTS = [
    SIGNAL_GENERATED,
    PRE_ORDER,
    POST_ORDER,
    TRADE_CLOSED,
    DAILY_PNL_UPDATE,
    KILL_SWITCH_TRIGGERED,
    TARGET_REACHED,
    MARKET_CONNECTED,
    MARKET_DISCONNECTED,
]

Handler = Callable[..., Any]

_registry: "HookRegistry | None" = None


def get_hook_registry() -> "HookRegistry":
    global _registry
    if _registry is None:
        _registry = HookRegistry()
    return _registry


class HookRegistry:
    """
    Central registry for event hooks.

    Usage:
        registry = get_hook_registry()
        registry.on(SIGNAL_GENERATED, my_handler)
        await registry.emit(SIGNAL_GENERATED, signal=signal_obj, market="futures")
    """

    def __init__(self):
        self._handlers: dict[str, list[Handler]] = defaultdict(list)
        self._emit_count: dict[str, int] = defaultdict(int)

    def on(self, event: str, handler: Handler) -> None:
        """Register a handler for an event."""
        self._handlers[event].append(handler)
        logger.debug(f"Registered hook: {event} → {handler.__name__}")

    def off(self, event: str, handler: Handler) -> None:
        """Unregister a handler."""
        if handler in self._handlers[event]:
            self._handlers[event].remove(handler)

    async def emit(self, event: str, **payload: Any) -> list[Any]:
        """
        Fire all handlers for an event with the given payload kwargs.
        Async handlers are awaited; sync handlers are called directly.
        Returns list of handler return values.
        """
        self._emit_count[event] += 1
        handlers = self._handlers.get(event, [])
        if not handlers:
            return []

        results = []
        for handler in handlers:
            try:
                result = handler(**payload)
                if asyncio.iscoroutine(result):
                    result = await result
                results.append(result)
            except Exception as exc:
                logger.error(f"Hook error [{event}] in {handler.__name__}: {exc}")
                results.append(None)

        return results

    def emit_sync(self, event: str, **payload: Any) -> list[Any]:
        """Fire sync handlers only (use from synchronous contexts)."""
        self._emit_count[event] += 1
        handlers = self._handlers.get(event, [])
        results = []
        for handler in handlers:
            try:
                result = handler(**payload)
                if asyncio.iscoroutine(result):
                    logger.warning(f"Skipping async hook {handler.__name__} in sync context")
                    result.close()
                    continue
                results.append(result)
            except Exception as exc:
                logger.error(f"Sync hook error [{event}] in {handler.__name__}: {exc}")
        return results

    def get_stats(self) -> dict:
        return {
            "registered_handlers": {e: len(h) for e, h in self._handlers.items() if h},
            "emit_counts": dict(self._emit_count),
        }
