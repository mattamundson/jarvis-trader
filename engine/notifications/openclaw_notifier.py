"""
OpenClaw WhatsApp Notifier — send proactive alerts via OpenClaw gateway CLI.

Uses subprocess to call `openclaw message send` in WSL Ubuntu, which routes
through the OpenClaw gateway to WhatsApp. No REST API needed.

Environment variables:
  OPENCLAW_WHATSAPP_TO  — E.164 recipient phone (required to send; unset = no-op)
  OPENCLAW_ENABLED      — "false" to disable without removing code (default: true)

Usage:
  from notifications.openclaw_notifier import notify_signal, notify_kill_switch, notify_target
  await notify_signal(symbol="MCL", action="BUY", confidence=0.87, reason="STC cross above 15")
  await notify_kill_switch(reason="daily_loss_limit", message="-2.1% P&L exceeded")
  await notify_target(market="futures", pnl=512.0, target=500.0)
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
from datetime import datetime

logger = logging.getLogger(__name__)

_PHONE_TO = (os.getenv("OPENCLAW_WHATSAPP_TO") or "").strip()
_ENABLED = os.getenv("OPENCLAW_ENABLED", "true").lower() not in ("false", "0", "no")

# Rate limiting: track last send time per symbol to avoid spam
_last_sent: dict[str, float] = {}
_COOLDOWN_SECONDS = 7200  # 2 hours per symbol


def _ct_time() -> str:
    return datetime.now().strftime("%m/%d %I:%M %p")


def _is_cooldown(key: str) -> bool:
    import time

    last = _last_sent.get(key, 0)
    return (time.time() - last) < _COOLDOWN_SECONDS


def _mark_sent(key: str) -> None:
    import time

    _last_sent[key] = time.time()


def _send_sync(message: str, phone: str = _PHONE_TO) -> bool:
    """Send via openclaw CLI in WSL. Returns True on success."""
    if not phone:
        logger.debug("OpenClaw: OPENCLAW_WHATSAPP_TO unset — skip send")
        return False
    if not _ENABLED:
        logger.debug(f"OpenClaw notifier disabled — skipping: {message[:60]}")
        return False
    try:
        result = subprocess.run(
            [
                "wsl",
                "-d",
                "Ubuntu",
                "-e",
                "openclaw",
                "message",
                "send",
                "--channel",
                "whatsapp",
                "--target",
                phone,
                "--message",
                message,
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0:
            logger.info(f"OpenClaw WhatsApp sent to {phone}: {message[:80]}")
            return True
        logger.warning(
            f"OpenClaw send failed (rc={result.returncode}): {result.stderr.strip()[:120]}"
        )
        return False
    except Exception as exc:
        logger.warning(f"OpenClaw send exception: {exc}")
        return False


async def _send(message: str, phone: str = _PHONE_TO) -> bool:
    """Async wrapper — runs subprocess in thread pool to avoid blocking event loop."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _send_sync, message, phone)


async def notify_signal(
    *,
    symbol: str,
    action: str,
    confidence: float = 0.0,
    reason: str = "",
    market: str = "futures",
) -> bool:
    """Send WhatsApp alert when a non-HOLD signal fires. Rate-limited per symbol."""
    if action.upper() == "HOLD":
        return False
    cooldown_key = f"signal:{symbol}"
    if _is_cooldown(cooldown_key):
        logger.debug(f"OpenClaw signal cooldown active for {symbol}")
        return False
    ts = _ct_time()
    msg = (
        f"JARVIS SIGNAL — {ts}\n"
        f"{symbol}: {action.upper()}"
        + (f" (conf {confidence:.0%})" if confidence > 0 else "")
        + (f"\n{reason[:100]}" if reason else "")
        + "\nApprove at localhost:3010/trades/pending-approvals"
    )
    sent = await _send(msg)
    if sent:
        _mark_sent(cooldown_key)
    return sent


async def notify_kill_switch(
    *,
    reason: str = "",
    message: str = "",
    market: str = "",
) -> bool:
    """Send CRITICAL WhatsApp alert when kill switch activates. No cooldown."""
    ts = _ct_time()
    reason_str = reason.replace("_", " ").upper() if reason else "MANUAL"
    msg = (
        f"JARVIS KILL SWITCH — {ts}\n"
        f"REASON: {reason_str}"
        + (f"\n{message[:120]}" if message else "")
        + "\nAll trading halted. Deactivate at localhost:3010"
    )
    return await _send(msg)


async def notify_target(
    *,
    market: str = "futures",
    pnl: float = 0.0,
    target: float = 0.0,
) -> bool:
    """Send WhatsApp alert when daily target is reached."""
    cooldown_key = f"target:{market}"
    if _is_cooldown(cooldown_key):
        return False
    ts = _ct_time()
    msg = (
        f"JARVIS TARGET HIT — {ts}\n"
        f"{market.upper()}: ${pnl:,.2f} >= ${target:,.2f} daily target\n"
        f"Consider reducing exposure for remainder of session."
    )
    sent = await _send(msg)
    if sent:
        _mark_sent(cooldown_key)
    return sent
