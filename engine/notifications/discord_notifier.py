"""
Discord Webhook Notifier — send JARVIS alerts to a Discord channel.

Reads DISCORD_WEBHOOK_URL from environment. All functions are fire-and-forget
async coroutines that silently no-op when the URL is not set or TESTING=1.

Environment variables:
  DISCORD_WEBHOOK_URL  — full Discord webhook URL (required to send)
  DISCORD_ENABLED      — "false" to disable without removing the URL (default: true)

Usage:
  from notifications.discord_notifier import discord_signal, discord_kill_switch
  await discord_signal(symbol="MCL", action="BUY", confidence=0.87, reason="STC cross above 15")
  await discord_kill_switch(reason="daily_loss_limit", message="-2.1% P&L exceeded")
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

logger = logging.getLogger(__name__)

_WEBHOOK_URL = (os.getenv("DISCORD_WEBHOOK_URL") or "").strip()
_ENABLED = os.getenv("DISCORD_ENABLED", "true").lower() not in ("false", "0", "no")
_TESTING = os.getenv("TESTING", "0") in ("1", "true", "yes")

_CT = ZoneInfo("America/Chicago")


def _ct_time() -> str:
    return datetime.now(_CT).strftime("%I:%M %p CT")


def _ready() -> bool:
    if _TESTING:
        return False
    if not _ENABLED:
        return False
    if not _WEBHOOK_URL:
        return False
    return True


async def _send(content: str) -> bool:
    """POST content to the Discord webhook. Returns True on success."""
    if not _ready():
        logger.debug("Discord notifier not configured or disabled — skipping send.")
        return False
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                _WEBHOOK_URL,
                json={"content": content, "username": "JARVIS"},
            )
            if resp.status_code in (200, 204):
                return True
            logger.warning("Discord webhook returned %s: %s", resp.status_code, resp.text)
            return False
    except Exception as exc:
        logger.warning("Discord webhook send failed: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Public notification functions — mirror openclaw_notifier API
# ---------------------------------------------------------------------------


async def discord_signal(
    symbol: str,
    action: str,
    confidence: float,
    reason: str = "",
) -> bool:
    """Send a trade signal alert."""
    pct = int(confidence * 100)
    emoji = "🟢" if action.upper() in ("BUY", "LONG") else "🔴" if action.upper() in ("SELL", "SHORT") else "⚪"
    lines = [
        f"{emoji} **JARVIS SIGNAL** | {_ct_time()}",
        f"**{symbol}** → {action.upper()} @ {pct}% confidence",
    ]
    if reason:
        lines.append(f"> {reason}")
    return await _send("\n".join(lines))


async def discord_kill_switch(
    reason: str = "",
    message: str = "",
) -> bool:
    """Send a kill-switch alert."""
    lines = [
        f"🛑 **JARVIS KILL SWITCH ACTIVATED** | {_ct_time()}",
    ]
    if reason:
        lines.append(f"Reason: `{reason}`")
    if message:
        lines.append(f"> {message}")
    return await _send("\n".join(lines))


async def discord_kill_switch_deactivated() -> bool:
    """Send a kill-switch cleared alert."""
    return await _send(f"✅ **JARVIS KILL SWITCH CLEARED** | {_ct_time()}")


async def discord_approval_required(
    symbol: str,
    action: str,
    confidence: float,
    reason: str = "",
    approval_url: str = "http://localhost:3010/trades/pending-approvals",
) -> bool:
    """Send a pending approval alert."""
    pct = int(confidence * 100)
    lines = [
        f"⏳ **JARVIS APPROVAL REQUIRED** | {_ct_time()}",
        f"**{symbol}** → {action.upper()} @ {pct}% confidence",
    ]
    if reason:
        lines.append(f"> {reason}")
    lines.append(f"Approve: {approval_url}")
    return await _send("\n".join(lines))


async def discord_trade_closed(
    symbol: str,
    action: str,
    pnl: float,
    reason: str = "",
) -> bool:
    """Send a trade closed alert."""
    emoji = "✅" if pnl >= 0 else "❌"
    sign = "+" if pnl >= 0 else ""
    lines = [
        f"{emoji} **JARVIS TRADE CLOSED** | {_ct_time()}",
        f"**{symbol}** {action.upper()} → P&L: **{sign}${pnl:.2f}**",
    ]
    if reason:
        lines.append(f"> {reason}")
    return await _send("\n".join(lines))


async def discord_target(
    market: str,
    pnl: float,
    target: float,
) -> bool:
    """Send a daily target hit alert."""
    lines = [
        f"🎯 **JARVIS TARGET HIT** | {_ct_time()}",
        f"Market: **{market}** | P&L: **+${pnl:.2f}** vs target ${target:.2f}",
    ]
    return await _send("\n".join(lines))


async def discord_ib_disconnect(last_connected_at: str = "") -> bool:
    """Send an IB disconnect alert."""
    msg = f"⚠️ **JARVIS IB ALERT** | {_ct_time()} | IBKR disconnected"
    if last_connected_at:
        msg += f" (last seen: {last_connected_at})"
    return await _send(msg)


async def discord_regime_change(
    symbol: str,
    old_regime: str,
    new_regime: str,
) -> bool:
    """Send a regime change alert."""
    emoji = "📈" if new_regime.upper() == "TRENDING" else "📊"
    lines = [
        f"{emoji} **JARVIS REGIME CHANGE** | {_ct_time()}",
        f"**{symbol}**: {old_regime} → **{new_regime}**",
    ]
    return await _send("\n".join(lines))


async def discord_test() -> bool:
    """Send a test message. Used for setup verification only."""
    return await _send(
        f"🤖 **JARVIS Discord connected** | {_ct_time()}\nAlert routing is live."
    )
