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

from notifications import discord_notifier as _discord

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
                "-u",
                "root",
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
            timeout=45,
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
    # Supervisor gate (Hermes pattern) — ACK clean signals, escalate only noisy ones.
    try:
        from .supervisor import SupervisorEvent, SupervisorMarker, get_supervisor
        _sup = get_supervisor()
        if _sup.enabled:
            _decision = await _sup.review(SupervisorEvent(
                event_type="signal",
                payload={
                    "symbol": symbol, "action": action, "confidence": confidence,
                    "reason": reason, "market": market,
                },
            ))
            if not _decision.pass_through:
                logger.info("Supervisor ACK'd signal %s: %s", symbol, _decision.reason)
                return False
            if _decision.marker == SupervisorMarker.REVIEW:
                reason = f"[REVIEW: {_decision.reason}] {reason}"
    except Exception as _sup_exc:
        logger.warning("Supervisor gate failed (fail-open pass-through): %s", _sup_exc)
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
    asyncio.ensure_future(
        _discord.discord_signal(
            symbol=symbol, action=action, confidence=confidence, reason=reason
        )
    )
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
    # Supervisor gate — ALWAYS_ESCALATE event, logs decision but never swallows.
    try:
        from .supervisor import SupervisorEvent, get_supervisor
        _sup = get_supervisor()
        if _sup.enabled:
            await _sup.review(SupervisorEvent(
                event_type="kill_switch",
                payload={"reason": reason, "message": message, "market": market},
            ))
    except Exception as _sup_exc:
        logger.warning("Supervisor kill_switch gate failed (fail-open): %s", _sup_exc)
    ts = _ct_time()
    reason_str = reason.replace("_", " ").upper() if reason else "MANUAL"
    msg = (
        f"JARVIS KILL SWITCH — {ts}\n"
        f"REASON: {reason_str}"
        + (f"\n{message[:120]}" if message else "")
        + "\nAll trading halted. Deactivate at localhost:3010"
    )
    result = await _send(msg)
    asyncio.ensure_future(
        _discord.discord_kill_switch(reason=reason, message=message)
    )
    return result


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
    # Supervisor gate — ACK clean approvals (high confidence, in-regime, in size band).
    try:
        from .supervisor import SupervisorEvent, get_supervisor
        _sup = get_supervisor()
        if _sup.enabled:
            _decision = await _sup.review(SupervisorEvent(
                event_type="approval",
                payload={
                    "symbol": symbol, "action": action,
                    "quantity": quantity, "entry_price": entry_price,
                },
            ))
            if not _decision.pass_through:
                logger.info("Supervisor ACK'd approval %s: %s", symbol, _decision.reason)
                return False
    except Exception as _sup_exc:
        logger.warning("Supervisor approval gate failed (fail-open): %s", _sup_exc)
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
    result = await _send(msg)
    asyncio.ensure_future(
        _discord.discord_approval_required(
            symbol=symbol, action=action, confidence=0.0,
        )
    )
    return result


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
    # Supervisor gate — trade closes are FYI; supervisor can ACK small wins and only escalate losses.
    try:
        from .supervisor import SupervisorEvent, get_supervisor
        _sup = get_supervisor()
        if _sup.enabled:
            _decision = await _sup.review(SupervisorEvent(
                event_type="trade_closed",
                payload={
                    "symbol": symbol, "action": action, "entry_price": entry_price,
                    "exit_price": exit_price, "pnl": pnl, "quantity": quantity,
                },
            ))
            if not _decision.pass_through:
                logger.info("Supervisor ACK'd trade_closed %s: %s", symbol, _decision.reason)
                return False
    except Exception as _sup_exc:
        logger.warning("Supervisor trade_closed gate failed (fail-open): %s", _sup_exc)
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
    asyncio.ensure_future(
        _discord.discord_trade_closed(
            symbol=symbol, action=action, pnl=pnl
        )
    )
    return sent


async def notify_trade_opened(
    *,
    symbol: str,
    action: str,
    quantity: float = 1.0,
    entry_price: float = 0.0,
    stop_price: float | None = None,
    target_price: float | None = None,
    source: str = "autonomous",
) -> bool:
    """Send an alert when an autonomous paper trade is OPENED (executed).

    Unlike notify_signal (which says "approve at..."), this fires only after a
    trade has actually been booked in fully-autonomous mode, so it is a true
    execution confirmation — closing the visibility gap on auto-trades.
    No per-symbol cooldown: every executed open is a distinct, material event.
    """
    if os.getenv("TESTING"):
        logger.debug("OpenClaw trade-open notify suppressed in TESTING mode")
        return False
    ts = _ct_time()
    direction = "LONG" if action.upper() in ("BUY", "LONG") else "SHORT"
    lines = [
        f"JARVIS TRADE OPENED — {ts}",
        f"{symbol.upper()} {direction} x{int(quantity) if quantity else 1}",
        f"Entry: ${entry_price:.2f}",
    ]
    if stop_price is not None:
        lines.append(f"Stop: ${float(stop_price):.2f}")
    if target_price is not None:
        lines.append(f"Target: ${float(target_price):.2f}")
    lines.append(f"({source}, paper)")
    msg = "\n".join(lines)
    sent = await _send(msg)
    asyncio.ensure_future(
        _discord.discord_trade_opened(
            symbol=symbol,
            action=action,
            quantity=float(quantity) if quantity else 1.0,
            entry_price=float(entry_price),
        )
    )
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
    # Supervisor gate — route target vs drawdown distinctly so the classifier sees both.
    try:
        from .supervisor import SupervisorEvent, get_supervisor
        _sup = get_supervisor()
        if _sup.enabled:
            _decision = await _sup.review(SupervisorEvent(
                event_type="drawdown" if message else "target",
                payload={"market": market, "pnl": pnl, "target": target, "message": message},
            ))
            if not _decision.pass_through:
                logger.info("Supervisor ACK'd target/drawdown %s: %s", market, _decision.reason)
                return False
    except Exception as _sup_exc:
        logger.warning("Supervisor target gate failed (fail-open): %s", _sup_exc)
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
    asyncio.ensure_future(
        _discord.discord_target(market=market, pnl=pnl, target=target)
    )
    return sent


async def notify_ib_disconnect(last_connected_at: str = "") -> bool:
    """Send WhatsApp alert when IB Gateway disconnects during market hours. No cooldown."""
    if os.getenv("TESTING"):
        logger.debug("OpenClaw IB disconnect notify suppressed in TESTING mode")
        return False
    # Supervisor gate — ALWAYS_ESCALATE event, logs decision but never swallows.
    try:
        from .supervisor import SupervisorEvent, get_supervisor
        _sup = get_supervisor()
        if _sup.enabled:
            await _sup.review(SupervisorEvent(
                event_type="ib_disconnect",
                payload={"last_connected_at": last_connected_at},
            ))
    except Exception as _sup_exc:
        logger.warning("Supervisor ib_disconnect gate failed (fail-open): %s", _sup_exc)
    ts = _ct_time()
    last_conn_str = last_connected_at or "unknown"
    msg = (
        f"JARVIS IB ALERT\n"
        f"IB Gateway disconnected during market hours.\n"
        f"Time: {ts} CT\n"
        f"Last connected: {last_conn_str}\n"
        f"Restart IB Gateway and reconnect."
    )
    result = await _send(msg)
    asyncio.ensure_future(
        _discord.discord_ib_disconnect(last_connected_at=last_connected_at)
    )
    return result


async def notify_kill_switch_cleared(*, authorized_by: str = "") -> bool:
    """Send WhatsApp alert when kill switch is manually deactivated. No cooldown."""
    if os.getenv("TESTING"):
        logger.debug("OpenClaw kill-switch cleared notify suppressed in TESTING mode")
        return False
    ts = _ct_time()
    by_str = f"\nAuthorized by: {authorized_by}" if authorized_by else ""
    msg = (
        f"JARVIS KILL SWITCH CLEARED — {ts}\n"
        f"Trading RESUMED.{by_str}\n"
        f"Review positions before new entries."
    )
    result = await _send(msg)
    asyncio.ensure_future(
        _discord.discord_kill_switch_deactivated()
    )
    return result


async def notify_kill_switch_deactivated(
    *,
    authorized_by: str = "",
    message: str = "",
) -> bool:
    """Send WhatsApp alert when kill switch is manually deactivated. No cooldown.

    Alias for notify_kill_switch_cleared() with an optional extra message param.
    Exists so callers can import notify_kill_switch_deactivated by name.
    """
    if os.getenv("TESTING"):
        logger.debug("OpenClaw kill-switch deactivated notify suppressed in TESTING mode")
        return False
    ts = _ct_time()
    by_str = f"\nAuthorized by: {authorized_by}" if authorized_by else ""
    extra_str = f"\n{message[:120]}" if message else ""
    msg = (
        f"JARVIS KILL SWITCH DEACTIVATED — {ts}\n"
        f"Trading RESUMED.{by_str}{extra_str}\n"
        f"Review positions before new entries."
    )
    result = await _send(msg)
    asyncio.ensure_future(
        _discord.discord_kill_switch_deactivated()
    )
    return result


# Corey staleness alerts — dedupe by day so we don't spam while the DCE
# pipeline is broken for multiple days. Reset on successful recovery.
_corey_stale_last_alert_date: str = ""


async def notify_corey_stale(days_stale: int, last_message_date: str) -> bool:
    """Send WhatsApp alert when Corey's discord_corey_commentary stops refreshing.

    Corey's session bias is an agent input — silent staleness = silent signal drift.
    Fires at most once per calendar day to avoid spam during multi-day outages.
    """
    if os.getenv("TESTING"):
        logger.debug("OpenClaw Corey-stale notify suppressed in TESTING mode")
        return False

    global _corey_stale_last_alert_date
    today_ct = datetime.now(_CT).strftime("%Y-%m-%d")
    if _corey_stale_last_alert_date == today_ct:
        logger.info("Corey-stale alert already sent today (%s) — suppressing dedupe", today_ct)
        return False

    ts = _ct_time()
    msg = (
        f"JARVIS CORey FEED STALE — {ts} CT\n"
        f"discord_corey_commentary has not refreshed in {days_stale} days.\n"
        f"Last ingested message: {last_message_date}\n"
        f"Agents are consuming a stale corey_session_bias.\n"
        f"Rotate DCE token and run: python -m scripts.nightly_discord_export"
    )
    result = await _send(msg)
    if result:
        _corey_stale_last_alert_date = today_ct
    return result


_credits_exhausted_last_alert_date: str = ""


async def notify_credits_exhausted(reason: str = "", agent: str = "") -> bool:
    """Send WhatsApp alert when Anthropic returns a credit_balance_too_low error.

    This is the loudest failure mode the LLM path can silently inhabit — /health
    stays green while 100% of calls 400 out. One alert per calendar day dedupe.
    """
    if os.getenv("TESTING"):
        logger.debug("OpenClaw credits-exhausted notify suppressed in TESTING mode")
        return False

    global _credits_exhausted_last_alert_date
    today_ct = datetime.now(_CT).strftime("%Y-%m-%d")
    if _credits_exhausted_last_alert_date == today_ct:
        logger.info(
            "credits-exhausted alert already sent today (%s) — suppressing dedupe", today_ct
        )
        return False

    ts = _ct_time()
    agent_line = f"Triggered by: {agent}\n" if agent else ""
    reason_line = f"Anthropic reply: {reason}\n" if reason else ""
    msg = (
        f"JARVIS LLM PATH DOWN — {ts} CT\n"
        f"Anthropic rejected a call with credit_balance_too_low.\n"
        f"{agent_line}{reason_line}"
        f"All paid LLM calls will fail until credits are topped up.\n"
        f"https://console.anthropic.com/settings/billing"
    )
    result = await _send(msg)
    if result:
        _credits_exhausted_last_alert_date = today_ct
    return result


async def notify_regime_change(symbol: str, old_regime: str, new_regime: str) -> bool:
    """Send WhatsApp alert when regime changes. No cooldown (regimes change rarely)."""
    if os.getenv("TESTING"):
        logger.debug("OpenClaw regime change notify suppressed in TESTING mode")
        return False
    ts = _ct_time()
    msg = f"JARVIS Regime Alert\n" f"{symbol}: {old_regime} → {new_regime}\n" f"Time: {ts} CT"
    result = await _send(msg)
    asyncio.ensure_future(
        _discord.discord_regime_change(
            symbol=symbol, old_regime=old_regime, new_regime=new_regime
        )
    )
    return result


async def send_whatsapp_message(message: str, phone: str = _PHONE_TO) -> bool:
    """Backward-compatible alias for inbound reply paths."""
    return await send_raw(message, phone=phone)

