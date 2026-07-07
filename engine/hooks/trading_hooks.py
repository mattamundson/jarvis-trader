"""
Built-in trading hooks — register these at startup.
Handlers for logging, DB persistence, and notifications.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any, Optional

from .registry import (
    DAILY_PNL_UPDATE,
    KILL_SWITCH_TRIGGERED,
    SIGNAL_GENERATED,
    TARGET_REACHED,
    TRADE_CLOSED,
    HookRegistry,
)

logger = logging.getLogger("jarvis_trader.hooks.trading")


def log_signal(signal: Any = None, market: str = "", **kwargs) -> None:
    """Log every generated signal."""
    if signal:
        logger.info(
            f"[SIGNAL] {market} | {signal.symbol} {signal.action} "
            f"qty={signal.quantity} conf={signal.confidence:.2f} | {signal.reason}"
        )


def log_signal_to_db(
    db_conn: Optional[sqlite3.Connection] = None, signal: Any = None, market: str = "", **kwargs
) -> None:
    """Persist signal to hook_events table."""
    if not db_conn or not signal:
        return
    try:
        import json

        payload = {
            "symbol": signal.symbol,
            "action": signal.action,
            "quantity": signal.quantity,
            "confidence": signal.confidence,
            "strategy": signal.strategy,
            "reason": signal.reason,
        }
        db_conn.execute(
            "INSERT INTO hook_events (event_type, market, payload_json) VALUES (?, ?, ?)",
            (SIGNAL_GENERATED, market, json.dumps(payload)),
        )
        db_conn.commit()
    except Exception as exc:
        logger.error(f"hook log_signal_to_db error: {exc}")


def log_trade_closed(result: Any = None, market: str = "", **kwargs) -> None:
    """Log closed trade details."""
    if not result:
        return
    status = "✓" if result.executed else "✗"
    logger.info(
        f"[TRADE {status}] {market} | {result.signal.symbol} "
        f"fill={result.fill_price} qty={result.fill_qty} "
        f"pnl={result.realized_pnl}"
    )


def log_daily_pnl(market: str = "", pnl: float = 0.0, target: float = 0.0, **kwargs) -> None:
    """Log daily P&L update."""
    pct = (pnl / target * 100) if target else 0
    logger.info(f"[PNL] {market}: ${pnl:,.2f} / ${target:,.2f} ({pct:.1f}%)")


def notify_kill_switch(market: str = "", reason: str = "", **kwargs) -> None:
    """Log kill switch activation and send WhatsApp alert."""
    logger.critical(f"[KILL SWITCH] {market}: {reason}")
    try:
        import asyncio

        from notifications.openclaw_notifier import notify_kill_switch as _oc_ks

        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(_oc_ks(market=market, reason=reason))
        else:
            loop.run_until_complete(_oc_ks(market=market, reason=reason))
    except Exception:
        pass  # Non-blocking, best-effort


def whatsapp_signal(signal: Any = None, market: str = "", **kwargs) -> None:
    """Send WhatsApp alert for BUY/SELL signals (not HOLD/CLOSE)."""
    if not signal or signal.action not in ("BUY", "SELL"):
        return
    try:
        import asyncio

        from notifications.openclaw_notifier import notify_signal as _oc_sig

        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(
                _oc_sig(
                    symbol=signal.symbol,
                    action=signal.action,
                    confidence=signal.confidence,
                    reason=signal.reason,
                    market=market,
                )
            )
        else:
            loop.run_until_complete(
                _oc_sig(
                    symbol=signal.symbol,
                    action=signal.action,
                    confidence=signal.confidence,
                    reason=signal.reason,
                    market=market,
                )
            )
    except Exception:
        pass  # Non-blocking, best-effort


def whatsapp_trade_closed(result: Any = None, market: str = "", **kwargs) -> None:
    """Send WhatsApp alert when a trade closes with realized P&L."""
    if not result or not result.executed:
        return
    try:
        import asyncio

        from notifications.openclaw_notifier import notify_trade_closed as _oc_tc

        loop = asyncio.get_event_loop()
        entry = getattr(result, "entry_price", 0.0) or 0.0
        if loop.is_running():
            loop.create_task(
                _oc_tc(
                    symbol=result.signal.symbol,
                    action=result.signal.action,
                    entry_price=entry,
                    exit_price=result.fill_price,
                    pnl=result.realized_pnl,
                    quantity=result.fill_qty,
                )
            )
        else:
            loop.run_until_complete(
                _oc_tc(
                    symbol=result.signal.symbol,
                    action=result.signal.action,
                    entry_price=entry,
                    exit_price=result.fill_price,
                    pnl=result.realized_pnl,
                    quantity=result.fill_qty,
                )
            )
    except Exception:
        pass  # Non-blocking, best-effort


def drawdown_alert(market: str = "", pnl: float = 0.0, target: float = 0.0, **kwargs) -> None:
    """Send WhatsApp alert if daily loss exceeds 50% of daily target."""
    if target <= 0 or pnl >= 0:
        return
    if abs(pnl) < target * 0.5:
        return
    try:
        import asyncio

        from notifications.openclaw_notifier import notify_target as _oc_target

        msg = f"⚠️ DRAWDOWN ALERT {market}: -${abs(pnl):.0f} (target ${target:.0f})"
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(_oc_target(market=market, pnl=pnl, target=-target, message=msg))
        else:
            loop.run_until_complete(_oc_target(market=market, pnl=pnl, target=-target, message=msg))
    except Exception:
        pass  # Non-blocking, best-effort


def notify_target_reached(
    market: str = "", pnl: float = 0.0, target: float = 0.0, **kwargs
) -> None:
    """Log when daily target is reached."""
    logger.info(f"[TARGET REACHED] {market}: ${pnl:,.2f} ≥ ${target:,.2f} 🎯")
    # OpenClaw WhatsApp alert
    try:
        import asyncio

        from notifications.openclaw_notifier import notify_target as _oc_target

        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(_oc_target(market=market, pnl=pnl, target=target))
        else:
            loop.run_until_complete(_oc_target(market=market, pnl=pnl, target=target))
    except Exception:
        pass  # Non-blocking, best-effort


def register_default_hooks(registry: HookRegistry) -> None:
    """Register all built-in hooks on the provided registry."""
    registry.on(SIGNAL_GENERATED, log_signal)
    registry.on(SIGNAL_GENERATED, whatsapp_signal)
    registry.on(TRADE_CLOSED, log_trade_closed)
    registry.on(TRADE_CLOSED, whatsapp_trade_closed)
    registry.on(DAILY_PNL_UPDATE, log_daily_pnl)
    registry.on(DAILY_PNL_UPDATE, drawdown_alert)
    registry.on(KILL_SWITCH_TRIGGERED, notify_kill_switch)
    registry.on(TARGET_REACHED, notify_target_reached)
    logger.info("Default trading hooks registered")
