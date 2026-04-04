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
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request

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
    """Send confirmation WhatsApp reply — fire-and-forget, never raises."""
    try:
        from notifications.openclaw_notifier import send_whatsapp_message

        send_whatsapp_message(message)
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
    if _db_manager is None:
        raise HTTPException(503, detail="Database not available")
    if _paper_tracker is None:
        raise HTTPException(503, detail="Paper tracker not available")

    # Kill switch check
    if _safety_layer is not None and _safety_layer.get_status().get("kill_switch_active"):
        msg = "JARVIS: Kill switch active — cannot approve trade"
        _send_reply(msg)
        raise HTTPException(409, detail=msg)

    rows = _db_manager.list_pending_approvals(limit=1)
    if not rows:
        msg = "JARVIS: No pending trades to approve"
        logger.info("[OPENCLAW] Approve command: no pending trades found")
        _send_reply(msg)
        return {"status": "no_pending", "message": msg}

    row = rows[0]
    approval_id: str = row["approval_id"]
    symbol: str = row["symbol"]
    action: str = row["action"]
    quantity: float = float(row["quantity"])
    entry_price: Optional[float] = row.get("entry_price")
    snap: dict = row.get("pipeline_snapshot") or {}

    # Resolve entry price from snapshot if not stored directly
    if entry_price is None:
        try:
            from approval.snapshot import entry_price_from_snapshot

            entry_price = entry_price_from_snapshot(snap)
        except Exception:
            pass

    if entry_price is None:
        msg = f"JARVIS: Cannot approve {symbol} — no entry price available"
        _send_reply(msg)
        raise HTTPException(400, detail=msg)

    notes = str(snap.get("summary") or "")[:2000]

    try:
        trade_id = _paper_tracker.open_trade(
            symbol=symbol,
            action=action,
            quantity=quantity,
            price=float(entry_price),
            notes=notes,
        )
    except Exception as exc:
        logger.exception("[OPENCLAW] open_trade failed for %s", approval_id[:8])
        raise HTTPException(500, detail=str(exc)) from exc

    ok = _db_manager.resolve_pending_approval(
        approval_id,
        new_status="approved",
        resolved_by="whatsapp",
        paper_trade_id=trade_id,
    )
    if not ok:
        logger.error(
            "[OPENCLAW] resolve_pending_approval failed after open_trade id=%s", trade_id[:8]
        )
        raise HTTPException(409, detail="Could not mark approval resolved (race condition?)")

    logger.info(
        "[OPENCLAW] Trade approved via WhatsApp: approval_id=%s %s %s @ %.2f",
        approval_id[:8],
        symbol,
        action.upper(),
        entry_price,
    )

    confirm_msg = (
        f"JARVIS: Approved — {symbol.upper()} {action.upper()} @ ${entry_price:.2f} opened"
    )
    _send_reply(confirm_msg)

    return {
        "status": "approved",
        "approval_id": approval_id,
        "paper_trade_id": trade_id,
        "symbol": symbol,
        "action": action,
        "quantity": quantity,
        "entry_price": float(entry_price),
        "message": confirm_msg,
    }


async def _reject_latest_pending() -> dict[str, Any]:
    """Find the most recent pending approval and reject it via the standard flow."""
    if _db_manager is None:
        raise HTTPException(503, detail="Database not available")

    rows = _db_manager.list_pending_approvals(limit=1)
    if not rows:
        msg = "JARVIS: No pending trades to reject"
        _send_reply(msg)
        return {"status": "no_pending", "message": msg}

    row = rows[0]
    approval_id: str = row["approval_id"]
    symbol: str = row["symbol"]

    ok = _db_manager.resolve_pending_approval(
        approval_id,
        new_status="rejected",
        resolved_by="whatsapp",
        rejection_reason="rejected_via_whatsapp",
    )
    if not ok:
        logger.error(
            "[OPENCLAW] resolve_pending_approval failed for rejection id=%s", approval_id[:8]
        )
        raise HTTPException(409, detail="Could not mark approval resolved (race condition?)")

    logger.info(
        "[OPENCLAW] Trade rejected via WhatsApp: approval_id=%s %s", approval_id[:8], symbol
    )

    msg = f"JARVIS: {symbol.upper()} trade rejected"
    _send_reply(msg)

    return {
        "status": "rejected",
        "approval_id": approval_id,
        "symbol": symbol,
        "message": msg,
    }
