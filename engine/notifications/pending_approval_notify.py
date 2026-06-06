"""Fan out pending-trade-approval events to WebSocket, WhatsApp, Telegram, and optional Discord."""

from __future__ import annotations

import logging
import os
from typing import Optional

from config import settings

logger = logging.getLogger(__name__)


def _approval_dashboard_url() -> str:
    base = (getattr(settings, "DASHBOARD_PUBLIC_URL", None) or "http://localhost:3010").rstrip("/")
    return f"{base}/trades/pending-approvals"


def _fmt_qty(quantity: Optional[float]) -> str:
    if quantity is None:
        return ""
    try:
        q = float(quantity)
    except (TypeError, ValueError):
        return ""
    if q == int(q):
        return f" qty={int(q)}"
    return f" qty={q:g}"


def _fmt_entry(entry_price: Optional[float]) -> str:
    if entry_price is None:
        return ""
    try:
        return f" @ {float(entry_price):.4f}"
    except (TypeError, ValueError):
        return ""


async def notify_pending_approval_queued(
    *,
    approval_id: str,
    symbol: str,
    action: str,
    quantity: Optional[float] = None,
    entry_price: Optional[float] = None,
    stop_price: Optional[float] = None,
    target_price: Optional[float] = None,
    confidence: Optional[float] = None,
) -> None:
    """Non-raising: WebSocket + WhatsApp + Telegram (if configured) + optional Discord."""
    from websocket.events import emit_pending_approval_created

    try:
        await emit_pending_approval_created(
            approval_id,
            symbol,
            action,
            quantity=quantity,
            entry_price=entry_price,
        )
    except Exception as e:
        logger.error("[APPROVAL-NOTIFY] WebSocket emit failed: %s", e)

    approve_url = _approval_dashboard_url()
    qty_part = _fmt_qty(quantity)
    px_part = _fmt_entry(entry_price)
    sym = (symbol or "").upper()
    act = (action or "").upper()

    try:
        from notifications.whatsapp import send_whatsapp_message

        stp_str = f" | STP: {float(stop_price):.4f}" if stop_price else ""
        tgt_str = f" | TGT: {float(target_price):.4f}" if target_price else ""
        conf_str = f" | Conf: {float(confidence):.2f}" if confidence else ""
        px_clean = f" @ {float(entry_price):.4f}" if entry_price else ""

        msg = (
            f"JARVIS: {sym} {act}{px_clean}{stp_str}{tgt_str}{conf_str}\n"
            f"ID: {approval_id[:8]}…\n"
            f"Reply Y to approve, N to reject"
        )
        await send_whatsapp_message(msg, alert_type="pending_approval", symbol=sym)
    except Exception as e:
        logger.debug("WhatsApp pending_approval skipped or failed: %s", e)

    try:
        from notifications.telegram import get_notifier as get_telegram_notifier

        tg = get_telegram_notifier()
        if tg.enabled:
            html_msg = (
                f"<b>JARVIS — APPROVAL REQUIRED</b>\n\n"
                f"<b>{sym}</b> <b>{act}</b>{qty_part}{px_part}\n"
                f"ID: <code>{approval_id[:8]}…</code>\n\n"
                f'<a href="{approve_url}">Pending Approvals</a>'
            )
            ok = await tg.send(html_msg)
            # A *configured* channel that fails to deliver is a real problem —
            # the approval is queued but nobody is told. Escalate (was debug).
            if not ok:
                logger.warning(
                    "[APPROVAL-NOTIFY] Telegram send failed for approval %s "
                    "(config_valid=%s) — candidate is queued but the DM did not go out",
                    approval_id[:8],
                    getattr(tg, "config_valid", None),
                )
    except Exception as e:
        logger.warning("[APPROVAL-NOTIFY] Telegram pending_approval failed: %s", e)

    wh_url = (os.environ.get("JARVIS_DISCORD_APPROVAL_WEBHOOK") or "").strip()
    if wh_url:
        try:
            import httpx

            content = (
                f"**JARVIS — approval required** — `{sym}` **{act}**"
                f"{qty_part}{px_part}\n→ {approve_url}"
            )
            async with httpx.AsyncClient(timeout=8.0) as client:
                r = await client.post(wh_url, json={"content": content[:1900]})
                if r.status_code >= 400:
                    logger.warning("[APPROVAL-NOTIFY] Discord webhook HTTP %s", r.status_code)
        except Exception as e:
            logger.warning("[APPROVAL-NOTIFY] Discord webhook failed: %s", e)
