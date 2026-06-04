"""
JARVIS TRADER — WhatsApp Interactive Router (Phase 4.1)
========================================================
Receives inbound WhatsApp messages from Twilio and processes interactive
commands (Y/N/S/KILL).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Form, Request
from twilio.twiml.messaging_response import MessagingResponse

from approval.service import (
    ApprovalFlowError,
    approve_pending_trade,
    get_latest_pending_approval_row,
    reject_pending_trade,
)

logger = logging.getLogger("jarvis_trader.whatsapp_router")

router = APIRouter(prefix="/webhook/whatsapp", tags=["webhook", "whatsapp"])

# ── Dependencies ──────────────────────────────────────────────────────────────
_db_manager = None
_paper_tracker = None
_safety_layer = None
_data_manager = None

def inject_dependencies(db_manager, paper_tracker, safety_layer, data_manager=None) -> None:
    global _db_manager, _paper_tracker, _safety_layer, _data_manager
    _db_manager = db_manager
    _paper_tracker = paper_tracker
    _safety_layer = safety_layer
    _data_manager = data_manager

# ── Webhook Handler ───────────────────────────────────────────────────────────

# ── Module-level state ────────────────────────────────────────────────────────
_pending_kill_confirm: set[str] = set() # Track senders who need to confirm KILL

@router.post("/reply")
async def receive_whatsapp_reply(
    request: Request,
    Body: str = Form(...),
    From: str = Form(...),
):
    """
    Handle inbound messages from Twilio.
    Supports:
      - "Y": Approve latest pending trade
      - "N": Reject latest pending trade
      - "KILL": Request system-wide kill switch
      - "CONFIRM KILL": Finalize emergency stop
      - "STATUS": Get current system health
    """
    command = Body.strip().upper()
    sender = From.replace("whatsapp:", "")

    logger.info(f"[WhatsApp] Inbound command from {sender}: {command}")

    twiml = MessagingResponse()

    try:
        if command == "Y":
            response = await _handle_approve()
            twiml.message(response)
        elif command == "N":
            response = _handle_reject()
            twiml.message(response)
        elif command == "KILL":
            _pending_kill_confirm.add(sender)
            twiml.message(
                "⚠️ *CRITICAL:* You are requesting a system-wide *KILL SWITCH* activation.\n\n"
                "This will flatten all active positions immediately. "
                "Reply *CONFIRM KILL* to proceed."
            )
        elif command == "CONFIRM KILL":
            if sender in _pending_kill_confirm:
                _pending_kill_confirm.remove(sender)
                response = await _handle_kill()
                twiml.message(response)
            else:
                twiml.message("⚠️ No pending kill switch request. Type *KILL* to start.")
        elif command == "STATUS":
            response = _handle_status()
            twiml.message(response)
        else:
            # If they typed something else, clear their pending kill if any
            if sender in _pending_kill_confirm:
                _pending_kill_confirm.remove(sender)

            twiml.message(
                "🤖 *JARVIS Interactive Commands:*\n"
                "- *Y*: Approve latest trade\n"
                "- *N*: Reject latest trade\n"
                "- *KILL*: Emergency stop\n"
                "- *STATUS*: System health"
            )

    except Exception as e:
        logger.error(f"[WhatsApp] Processing error: {e}", exc_info=True)
        twiml.message(f"❌ Error processing command: {str(e)}")

    return Request(scope={"type": "http"})._headers.update({"Content-Type": "text/xml"}) # Placeholder for raw TwiML return
    # Correct FastAPI way for TwiML:
    from fastapi.responses import Response
    return Response(content=str(twiml), media_type="text/xml")

# ── Command Handlers ──────────────────────────────────────────────────────────

async def _handle_approve() -> str:
    if not _db_manager or not _paper_tracker or not _safety_layer:
        return "❌ Approval system components not initialized."

    row = get_latest_pending_approval_row(_db_manager)
    if not row:
        return "⚠️ No pending trades found to approve."

    try:
        result = await approve_pending_trade(
            approval_id=row["id"],
            db_manager=_db_manager,
            paper_tracker=_paper_tracker,
            safety_layer=_safety_layer,
            resolved_by="whatsapp",
            data_manager=_data_manager
        )
        symbol = row["symbol"]
        action = row["action"]
        return f"✅ *APPROVED:* {action} {symbol}\nTrade ID: {result.get('trade_id', 'unknown')[:8]}"
    except ApprovalFlowError as exc:
        return f"❌ *Approval Failed:* {exc.detail}"

def _handle_reject() -> str:
    if not _db_manager:
        return "❌ System error: DB not initialized."

    row = get_latest_pending_approval_row(_db_manager)
    if not row:
        return "⚠️ No pending trades found to reject."

    try:
        reject_pending_trade(
            approval_id=row["id"],
            db_manager=_db_manager,
            resolved_by="whatsapp",
            reason="User rejected via WhatsApp"
        )
        return f"🚫 *REJECTED:* {row['action']} {row['symbol']}"
    except ApprovalFlowError as exc:
        return f"❌ *Rejection Failed:* {exc.detail}"

async def _handle_kill() -> str:
    if not _safety_layer:
        return "❌ Safety layer not initialized."

    # We require a two-step kill for safety in the roadmap,
    # but for P4.1 we'll implement the direct trigger.
    await _safety_layer.activate_kill_switch(reason="Emergency stop via WhatsApp")
    return "🚨 *KILL SWITCH ACTIVATED* 🚨\nAll trading halted system-wide."

def _handle_status() -> str:
    if not _safety_layer:
        return "❌ Status unavailable."

    status = _safety_layer.get_status()
    ks = "ACTIVE 🔴" if status.get("kill_switch_active") else "OFF 🟢"
    pnl = status.get("daily_pnl", 0.0)

    return (
        f"🤖 *JARVIS System Status*\n"
        f"Kill Switch: {ks}\n"
        f"Daily P&L: ${pnl:.2f}\n"
        f"Equity: ${status.get('current_equity', 0.0):,.0f}"
    )
