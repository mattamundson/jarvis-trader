"""
OpenClaw webhook router — receives inbound WhatsApp messages for trade approval.

Endpoint: POST /openclaw/webhook
Accepts OpenClaw webhook payload with incoming message body.
Parses: "yes"/"approve" → approve pending trade | "no"/"reject" → reject | "hold"/"skip" → no-op

Setup: Register JARVIS inbound URL with OpenClaw:
  curl -X POST http://localhost:8009/api/oc/webhook/register \\
    -H "Content-Type: application/json" \\
    -d '{"url": "http://localhost:8010/openclaw/webhook", "events": ["message.received"]}'
"""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from approval.service import (
    ApprovalFlowError,
    approve_pending_trade,
    get_latest_pending_approval_row,
    reject_pending_trade,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/openclaw", tags=["openclaw"])

# Injected at startup — mirror the approval_router pattern
_db_manager = None
_paper_tracker = None
_safety_layer = None


def inject_dependencies(db_manager, paper_tracker, safety_layer=None) -> None:
    """Wire database manager and paper tracker at engine startup."""
    global _db_manager, _paper_tracker, _safety_layer
    _db_manager = db_manager
    _paper_tracker = paper_tracker
    _safety_layer = safety_layer


def _allowed_sender() -> str:
    """Return normalised E.164 digits for OPENCLAW_WHATSAPP_TO (or empty string)."""
    raw = os.getenv("OPENCLAW_WHATSAPP_TO", "").strip()
    return raw.replace("whatsapp:", "").replace("+", "").strip()


def _normalise_sender(raw: str) -> str:
    return raw.replace("whatsapp:", "").replace("+", "").strip()


def _send_reply(message: str) -> None:
    """Send confirmation WhatsApp reply — fire-and-forget, never raises.

    send_whatsapp_message is async; we schedule it as a task on the
    running event loop and never await the result. Bug history: prior to
    2026-05-07 the call was `send_whatsapp_message(message)` which
    silently dropped the unawaited coroutine — every webhook reply
    quietly failed (mypy: unused-coroutine).
    """
    import asyncio

    try:
        from notifications.openclaw_notifier import send_whatsapp_message

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # Not inside an async context — fall back to a synchronous run
            asyncio.run(send_whatsapp_message(message))
        else:
            loop.create_task(send_whatsapp_message(message))
    except Exception as exc:
        logger.debug("[OPENCLAW] Reply send skipped: %s", exc)


@router.post("/webhook")
async def openclaw_webhook(request: Request) -> dict[str, Any]:
    """
    Receive inbound WhatsApp message from OpenClaw and act on pending trade approvals.

    Accepted commands (case-insensitive):
      - yes / approve / y  → approve most recent pending trade
      - no  / reject  / n  → reject most recent pending trade
      - hold / skip   / h  → no action

    Security: verifies sender matches OPENCLAW_WHATSAPP_TO env var (best-effort).
    Idempotent: returns informational message if no pending trades exist.
    """
    try:
        body = await request.json()
    except Exception:
        body = {}

    # Normalise message — support OpenClaw envelope variants
    message = (body.get("message") or body.get("text") or body.get("body") or "").strip().lower()
    from_number = (body.get("from_number") or body.get("from") or body.get("sender") or "").strip()

    logger.info("[OPENCLAW] Webhook received: message='%s' from='%s'", message, from_number)

    # Sender verification — best-effort, log warning but never 500
    allowed = _allowed_sender()
    incoming = _normalise_sender(from_number)
    if allowed and incoming and allowed != incoming:
        logger.warning("[OPENCLAW] Unauthorized sender: '%s' (allowed: '%s')", from_number, allowed)
        return {"status": "unauthorized", "message": "Sender not authorized"}

    # Route command
    if message in ("yes", "approve", "y"):
        return await _approve_latest_pending()
    if message in ("no", "reject", "n"):
        return await _reject_latest_pending()
    if message in ("hold", "skip", "h"):
        return {"status": "ok", "message": "JARVIS: Trade held — no action taken"}

    return {
        "status": "unknown_command",
        "message": (f"JARVIS: Unknown command '{message}'. Reply 'yes', 'no', or 'hold'."),
    }


async def _approve_latest_pending() -> dict[str, Any]:
    """Find the most recent pending approval and approve it via the standard flow."""
    try:
        row = get_latest_pending_approval_row(_db_manager)
    except ApprovalFlowError as exc:
        if exc.status_code == 404:
            msg = "JARVIS: No pending trades to approve"
            logger.info("[OPENCLAW] Approve command: no pending trades found")
            _send_reply(msg)
            return {"status": "no_pending", "message": msg}
        msg = f"JARVIS: {exc.detail}"
        _send_reply(msg)
        raise HTTPException(exc.status_code, detail=msg) from exc

    approval_id: str = row["approval_id"]
    try:
        result = await approve_pending_trade(
            approval_id=approval_id,
            db_manager=_db_manager,
            paper_tracker=_paper_tracker,
            safety_layer=_safety_layer,
            resolved_by="whatsapp",
        )
    except ApprovalFlowError as exc:
        msg = f"JARVIS: {exc.detail}"
        _send_reply(msg)
        raise HTTPException(exc.status_code, detail=msg) from exc

    confirm_msg = (
        f"JARVIS: Approved — {result['symbol'].upper()} {result['action'].upper()} "
        f"@ ${result['entry_price']:.2f} opened"
    )
    _send_reply(confirm_msg)
    result["message"] = confirm_msg
    return result


async def _reject_latest_pending() -> dict[str, Any]:
    """Find the most recent pending approval and reject it via the standard flow."""
    try:
        row = get_latest_pending_approval_row(_db_manager)
    except ApprovalFlowError as exc:
        if exc.status_code == 404:
            msg = "JARVIS: No pending trades to reject"
            _send_reply(msg)
            return {"status": "no_pending", "message": msg}
        msg = f"JARVIS: {exc.detail}"
        _send_reply(msg)
        raise HTTPException(exc.status_code, detail=msg) from exc

    try:
        result = reject_pending_trade(
            approval_id=row["approval_id"],
            db_manager=_db_manager,
            resolved_by="whatsapp",
            reason="rejected_via_whatsapp",
        )
    except ApprovalFlowError as exc:
        msg = f"JARVIS: {exc.detail}"
        _send_reply(msg)
        raise HTTPException(exc.status_code, detail=msg) from exc

    msg = f"JARVIS: {row['symbol'].upper()} trade rejected"
    _send_reply(msg)
    result["message"] = msg
    return result
