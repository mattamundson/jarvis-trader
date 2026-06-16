"""
Unified signal broadcast — one fan-out for every real-time channel.
=====================================================================

Before this module, a non-HOLD pipeline signal was delivered inconsistently:
the scheduler scan loop (``main.py``) sent WhatsApp only, ``agents/pipeline.py``
fired WhatsApp again, and ``routers/pipeline_router.py`` sent Telegram via a
different helper. WhatsApp was the only channel wired into the scan loop and it
self-disables on a Twilio 401, so in practice no signal reached the user.

``broadcast_signal`` is the single entry point. Every call site funnels through
it; it applies the shared per-symbol cooldown **once** (so redundant call sites
collapse to a single send per cooldown window) and then fans out concurrently —
best-effort — to every *enabled* channel:

  * Telegram  (notifications.telegram)
  * Discord   (notifications.discord_notifier — rich embed)
  * WhatsApp  (notifications.whatsapp — Twilio)
  * Windows toast (notifications.windows_toast — native desktop notification)

Design constraints (match the rest of the notifications package):
  * Never raises into the order path — every channel is try/except'd.
  * No new config.py keys (stays outside the strategy-config safety gate);
    per-channel enablement reuses each notifier's own env-driven flags plus
    ``WINDOWS_TOAST_ENABLED`` read straight from the environment.
  * Canonical fields are extracted once here (reusing the *correct* pipeline
    result keys) so a divergent-key bug in any single channel formatter can't
    silently blank the message.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from config import settings
from notifications.pipeline_alert_cooldown import (
    get_last_pipeline_alert_sent,
    mark_pipeline_alert_sent,
    pipeline_alert_decision,
)

logger = logging.getLogger(__name__)

# Actions that are not tradeable signals — never broadcast.
_NON_SIGNAL_ACTIONS = {"hold", "pending_human_approval", "none", ""}

_ACTION_LABELS = {
    "buy": "LONG",
    "long": "LONG",
    "sell": "SHORT",
    "short": "SHORT",
}


@dataclass
class SignalFields:
    """Canonical, channel-agnostic view of a pipeline signal."""

    symbol: str
    action: str          # raw action (buy/sell/long/short)
    label: str           # display label (LONG/SHORT/...)
    confidence: float    # 0.0 - 1.0
    entry_price: float
    stop_price: float
    target_price: float
    rr_ratio: float
    reason: str
    human_required: bool


def _f(value, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def extract_signal_fields(symbol: str, result: dict) -> SignalFields:
    """Pull the canonical signal fields from a pipeline result dict.

    Reads the *actual* pipeline keys (``boosted_confidence``, ``trade_decision``,
    ``debate_result``, ``fund_decision``, ``risk_decision``) — the same keys
    ``whatsapp.alert_pipeline_result`` reads correctly — rather than the stale
    top-level keys the Telegram formatter historically assumed.
    """
    action = str(result.get("final_action", "hold")).lower()
    label = _ACTION_LABELS.get(action, action.upper().replace("_", " "))

    confidence = (
        result.get("boosted_confidence")
        or result.get("raw_confidence")
        or (result.get("fund_decision") or {}).get("final_conviction")
        or (result.get("trade_decision") or {}).get("conviction")
        or 0.0
    )

    trade = result.get("trade_decision") or {}
    fund = result.get("fund_decision") or {}

    entry_price = _f(
        trade.get("entry_price")
        or trade.get("limit_price")
        or fund.get("entry_price")
    )
    stop_price = _f(trade.get("stop_price") or fund.get("stop_price"))
    target_price = _f(
        trade.get("target_1")
        or trade.get("target_price")
        or trade.get("take_profit")
    )

    rr_ratio = _f(trade.get("rr_ratio") or trade.get("risk_reward"))
    if not rr_ratio and entry_price and stop_price and target_price and stop_price != entry_price:
        risk_amt = abs(entry_price - stop_price)
        reward_amt = abs(target_price - entry_price)
        rr_ratio = round(reward_amt / risk_amt, 2) if risk_amt else 0.0

    reason = (
        trade.get("reasoning")
        or trade.get("notes")
        or result.get("summary")
        or ""
    )

    human_required = bool(
        fund.get("human_approval_required", False)
        or result.get("requires_human", False)
    )

    return SignalFields(
        symbol=symbol,
        action=action,
        label=label,
        confidence=_f(confidence),
        entry_price=entry_price,
        stop_price=stop_price,
        target_price=target_price,
        rr_ratio=rr_ratio,
        reason=reason,
        human_required=human_required,
    )


def _plain_message(f: SignalFields) -> str:
    """Plain-text body (WhatsApp / Windows toast)."""
    lines = [
        f"JARVIS: {f.symbol} -> {f.label}",
        f"Confidence: {f.confidence:.0%}",
    ]
    if f.entry_price:
        lines.append(f"Entry: {f.entry_price:.2f}  Stop: {f.stop_price:.2f}")
    if f.rr_ratio:
        lines.append(f"R:R {f.rr_ratio:.2f}")
    if f.reason:
        lines.append(f"Reason: {f.reason[:140]}")
    if f.human_required:
        lines.append("HUMAN APPROVAL REQUIRED - check dashboard")
    return "\n".join(lines)


def _html_message(f: SignalFields) -> str:
    """Telegram HTML body — built here so it never shows 0% from a key mismatch."""
    import html

    lines = [
        f"<b>JARVIS TRADER — {html.escape(f.label)}</b>",
        "",
        f"<b>Symbol:</b> {html.escape(f.symbol)}",
        f"<b>Confidence:</b> {f.confidence:.0%}",
    ]
    if f.entry_price:
        lines.append(f"<b>Entry:</b> {f.entry_price:.2f}  <b>Stop:</b> {f.stop_price:.2f}")
    if f.target_price:
        lines.append(f"<b>Target:</b> {f.target_price:.2f}")
    if f.rr_ratio:
        lines.append(f"<b>R:R:</b> {f.rr_ratio:.2f}")
    if f.reason:
        lines.extend(["", f"<i>{html.escape(f.reason[:200])}</i>"])
    if f.human_required:
        lines.extend(["", "<b>HUMAN APPROVAL REQUIRED</b> — check dashboard"])
    lines.extend(
        [
            "",
            f"<code>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</code>",
        ]
    )
    return "\n".join(lines)


def _log_channel(symbol: str, channel: str, status: str, message: str, error: str = "") -> None:
    """Best-effort alert_log row per channel. Never raises."""
    try:
        from database.schema import get_db

        db = get_db()
    except Exception:
        return
    try:
        db.insert_alert_log(
            alert_type="pipeline_signal",
            message=message[:500],
            symbol=symbol,
            channel=channel,
            status=status,
            error=error or None,
        )
    except TypeError:
        # Older insert_alert_log signature without channel/status — degrade.
        try:
            db.insert_alert_log(alert_type="pipeline_signal", message=message[:500], symbol=symbol)
        except Exception:
            pass
    except Exception:
        pass


# --- per-channel senders (each returns bool, never raises) -------------------


async def _send_telegram(f: SignalFields) -> Optional[bool]:
    try:
        from notifications.telegram import get_notifier

        notifier = get_notifier()
        if not getattr(notifier, "enabled", False):
            return None
        ok = await notifier.send(_html_message(f))
        _log_channel(f.symbol, "telegram", "sent" if ok else "failed", _plain_message(f))
        return ok
    except Exception as exc:
        logger.warning("Telegram broadcast failed for %s: %s", f.symbol, exc)
        return False


async def _send_whatsapp(f: SignalFields) -> Optional[bool]:
    try:
        from notifications.whatsapp import get_notifier

        notifier = get_notifier()
        if not getattr(notifier, "enabled", False):
            return None
        ok = await notifier.send(_plain_message(f))
        _log_channel(f.symbol, "whatsapp", "sent" if ok else "failed", _plain_message(f))
        return ok
    except Exception as exc:
        logger.warning("WhatsApp broadcast failed for %s: %s", f.symbol, exc)
        return False


async def _send_discord(f: SignalFields) -> Optional[bool]:
    try:
        from notifications import discord_notifier

        # discord_signal no-ops internally when not configured/disabled.
        ok = await discord_notifier.discord_signal(
            symbol=f.symbol,
            action=f.label,
            confidence=f.confidence,
            reason=f.reason,
        )
        return ok
    except Exception as exc:
        logger.warning("Discord broadcast failed for %s: %s", f.symbol, exc)
        return False


async def _send_windows_toast(f: SignalFields) -> Optional[bool]:
    try:
        from notifications import windows_toast

        if not windows_toast.enabled():
            return None
        ok = await windows_toast.notify_signal(f.symbol, f.label, f.confidence, _plain_message(f))
        _log_channel(f.symbol, "windows_toast", "sent" if ok else "failed", _plain_message(f))
        return ok
    except Exception as exc:
        logger.warning("Windows toast broadcast failed for %s: %s", f.symbol, exc)
        return False


def _any_channel_enabled() -> bool:
    """True if at least one delivery channel is configured/enabled."""
    try:
        from notifications.telegram import get_notifier as _tg

        if getattr(_tg(), "enabled", False):
            return True
    except Exception:
        pass
    try:
        from notifications.whatsapp import get_notifier as _wa

        if getattr(_wa(), "enabled", False):
            return True
    except Exception:
        pass
    if (os.getenv("DISCORD_WEBHOOK_URL") or "").strip() and os.getenv(
        "DISCORD_ENABLED", "true"
    ).lower() not in ("false", "0", "no"):
        return True
    try:
        from notifications import windows_toast

        if windows_toast.enabled():
            return True
    except Exception:
        pass
    return False


async def broadcast_signal(symbol: str, result: dict, *, source: str = "pipeline") -> dict:
    """Fan a non-HOLD pipeline result out to every enabled channel.

    Applies the shared per-symbol cooldown once, so multiple call sites firing
    for the same pipeline run collapse to a single delivery. Returns a summary
    dict; never raises into the caller.
    """
    summary = {"symbol": symbol, "source": source, "sent": [], "failed": [], "skipped": [], "suppressed": None}

    try:
        action = str(result.get("final_action", "hold")).lower()
        if action in _NON_SIGNAL_ACTIONS:
            summary["suppressed"] = "non_signal_action"
            return summary

        now = datetime.now()
        decision = pipeline_alert_decision(
            last_sent=get_last_pipeline_alert_sent(symbol),
            now=now,
            cooldown_minutes=getattr(settings, "ALERT_COOLDOWN_MINUTES", 15),
            notifier_enabled=_any_channel_enabled(),
        )
        if decision == "suppressed_no_channel":
            logger.info("Signal broadcast for %s suppressed — no channel configured", symbol)
            summary["suppressed"] = "no_channel"
            return summary
        if decision == "suppressed_cooldown":
            logger.info("Signal broadcast for %s suppressed — cooldown active (source=%s)", symbol, source)
            summary["suppressed"] = "cooldown"
            return summary

        fields = extract_signal_fields(symbol, result)

        results = await asyncio.gather(
            _send_telegram(fields),
            _send_discord(fields),
            _send_whatsapp(fields),
            _send_windows_toast(fields),
            return_exceptions=True,
        )
        channels = ("telegram", "discord", "whatsapp", "windows_toast")
        any_sent = False
        for name, res in zip(channels, results, strict=False):
            if isinstance(res, Exception) or res is False:
                summary["failed"].append(name)
            elif res is None:
                summary["skipped"].append(name)
            else:
                summary["sent"].append(name)
                any_sent = True

        if any_sent:
            mark_pipeline_alert_sent(symbol, now)
        logger.info(
            "Signal broadcast %s %s (source=%s) -> sent=%s failed=%s skipped=%s",
            symbol,
            fields.label,
            source,
            summary["sent"],
            summary["failed"],
            summary["skipped"],
        )
        return summary
    except Exception as exc:  # absolute backstop — never break the order path
        logger.error("broadcast_signal crashed for %s (non-fatal): %s", symbol, exc)
        summary["suppressed"] = f"error:{exc}"
        return summary
