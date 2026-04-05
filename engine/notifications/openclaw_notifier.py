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
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

_PHONE_TO = (os.getenv("OPENCLAW_WHATSAPP_TO") or "").strip()
_ENABLED = os.getenv("OPENCLAW_ENABLED", "true").lower() not in ("false", "0", "no")

# Rate limiting: track last send time per symbol to avoid spam
_last_sent: dict[str, float] = {}
_COOLDOWN_SECONDS = 7200  # 2 hours per symbol


_CT = ZoneInfo("America/Chicago")


def _ct_time() -> str:
    return datetime.now(_CT).strftime("%m/%d %I:%M %p")


def _is_globex_open() -> bool:
    """Return True if CME Globex is currently open for MCL/MNQ/MES.

    Schedule (all times CT / America/Chicago):
      - Sun 5:00 PM → Fri 4:00 PM  (continuous)
      - Daily maintenance break: 4:00 PM – 5:00 PM CT (Mon–Thu)
      - Closed: Fri 4:00 PM → Sun 5:00 PM
    """
    now = datetime.now(_CT)
    dow = now.weekday()  # 0=Mon … 4=Fri, 5=Sat, 6=Sun
    t = now.hour * 60 + now.minute  # minutes since midnight CT

    if dow == 5:  # Saturday — always closed
        return False
    if dow == 6 and t < 17 * 60:  # Sunday before 5:00 PM
        return False
    if dow == 4 and t >= 16 * 60:  # Friday at/after 4:00 PM
        return False
    # Mon–Thu: daily maintenance window 4:00 PM – 5:00 PM
    if dow < 4 and 16 * 60 <= t < 17 * 60:
        return False
    return True


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


async def send_raw(message: str, phone: str = _PHONE_TO) -> bool:
    """Send a raw message string directly via OpenClaw WhatsApp. No cooldown."""
    return await _send(message, phone)


async def notify_signal(
    *,
    symbol: str,
    action: str,
    confidence: float = 0.0,
    reason: str = "",
    market: str = "futures",
) -> bool:
    """Send WhatsApp alert when a non-HOLD signal fires. Rate-limited per symbol."""
    if os.getenv("TESTING"):
        logger.debug("OpenClaw signal notify suppressed in TESTING mode")
        return False
    if action.upper() == "HOLD":
        return False
    if not _is_globex_open():
        logger.debug("OpenClaw signal suppressed — CME Globex closed for %s", symbol)
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
    if os.getenv("TESTING"):
        logger.debug("OpenClaw kill-switch notify suppressed in TESTING mode")
        return False
    ts = _ct_time()
    reason_str = reason.replace("_", " ").upper() if reason else "MANUAL"
    msg = (
        f"JARVIS KILL SWITCH — {ts}\n"
        f"REASON: {reason_str}"
        + (f"\n{message[:120]}" if message else "")
        + "\nAll trading halted. Deactivate at localhost:3010"
    )
    return await _send(msg)


async def notify_approval_required(
    *,
    symbol: str,
    action: str,
    quantity: float = 0.0,
    entry_price: float = 0.0,
) -> bool:
    """Send WhatsApp alert when a trade requires human approval. No cooldown — every approval matters."""
    if os.getenv("TESTING"):
        logger.debug("OpenClaw approval notify suppressed in TESTING mode")
        return False
    if not _is_globex_open():
        logger.debug("OpenClaw approval notify suppressed — CME Globex closed for %s", symbol)
        return False
    ts = _ct_time()
    act = action.upper()
    qty_str = f" qty={int(quantity)}" if quantity else ""
    px_str = f" @ ${entry_price:.2f}" if entry_price else ""
    msg = (
        f"JARVIS APPROVAL NEEDED — {ts}\n"
        f"{symbol.upper()} {act}{qty_str}{px_str}\n"
        f"Approve at localhost:3010/trades/pending-approvals"
    )
    return await _send(msg)


async def notify_trade_closed(
    *,
    symbol: str,
    action: str,
    entry_price: float = 0.0,
    exit_price: float = 0.0,
    pnl: float = 0.0,
    quantity: float = 1.0,
) -> bool:
    """Send WhatsApp alert when a paper trade is closed. Rate-limited per symbol."""
    if os.getenv("TESTING"):
        logger.debug("OpenClaw trade-close notify suppressed in TESTING mode")
        return False
    cooldown_key = f"close:{symbol}"
    if _is_cooldown(cooldown_key):
        logger.debug("OpenClaw trade-close cooldown active for %s", symbol)
        return False
    ts = _ct_time()
    result_word = "WIN" if pnl >= 0 else "LOSS"
    pnl_str = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
    msg = (
        f"JARVIS TRADE CLOSED — {ts}\n"
        f"{symbol.upper()} {action.upper()}\n"
        f"Entry: ${entry_price:.2f} | Exit: ${exit_price:.2f}\n"
        f"P&L: {pnl_str} ({result_word})"
    )
    sent = await _send(msg)
    if sent:
        _mark_sent(cooldown_key)
    return sent


async def notify_target(
    *,
    market: str = "futures",
    pnl: float = 0.0,
    target: float = 0.0,
    message: str | None = None,
) -> bool:
    """Send WhatsApp for daily target hit, or a custom alert (e.g. drawdown) with rate limit."""
    if os.getenv("TESTING"):
        logger.debug("OpenClaw target notify suppressed in TESTING mode")
        return False
    cooldown_key = f"drawdown:{market}" if message else f"target:{market}"
    if _is_cooldown(cooldown_key):
        return False
    ts = _ct_time()
    if message:
        msg = f"{message}\nTime: {ts} CT"
    else:
        msg = (
            f"JARVIS TARGET HIT — {ts}\n"
            f"{market.upper()}: ${pnl:,.2f} >= ${target:,.2f} daily target\n"
            f"Consider reducing exposure for remainder of session."
        )
    sent = await _send(msg)
    if sent:
        _mark_sent(cooldown_key)
    return sent


async def notify_ib_disconnect(last_connected_at: str = "") -> bool:
    """Send WhatsApp alert when IB Gateway disconnects during market hours. No cooldown."""
    if os.getenv("TESTING"):
        logger.debug("OpenClaw IB disconnect notify suppressed in TESTING mode")
        return False
    ts = _ct_time()
    last_conn_str = last_connected_at or "unknown"
    msg = (
        f"JARVIS IB ALERT\n"
        f"IB Gateway disconnected during market hours.\n"
        f"Time: {ts} CT\n"
        f"Last connected: {last_conn_str}\n"
        f"Restart IB Gateway and reconnect."
    )
    return await _send(msg)


async def notify_regime_change(symbol: str, old_regime: str, new_regime: str) -> bool:
    """Send WhatsApp alert when regime changes. No cooldown (regimes change rarely)."""
    if os.getenv("TESTING"):
        logger.debug("OpenClaw regime change notify suppressed in TESTING mode")
        return False
    ts = _ct_time()
    msg = f"JARVIS Regime Alert\n" f"{symbol}: {old_regime} → {new_regime}\n" f"Time: {ts} CT"
    return await _send(msg)
