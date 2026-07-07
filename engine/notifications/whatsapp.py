"""
WhatsApp Notifications via Twilio
==================================
Sends trading alerts to WhatsApp when JARVIS produces actionable signals.

Setup:
  1. Sign up at https://www.twilio.com/ (free trial available)
  2. Enable WhatsApp Sandbox at https://console.twilio.com/us1/develop/sms/try-it-out/whatsapp-learn
  3. From your phone, send "join <sandbox-word>" to +1 415 523 8886
  4. Add these to .env:
       TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
       TWILIO_AUTH_TOKEN=your_auth_token
       TWILIO_WHATSAPP_FROM=whatsapp:+14155238886   (sandbox number)
       WHATSAPP_TO=whatsapp:+1YOURNUMBER            (your number with country code)

For production (non-sandbox): request a WhatsApp-approved number from Twilio.
"""

import logging
from datetime import datetime
from typing import Optional

import httpx

from config import settings

logger = logging.getLogger(__name__)


class WhatsAppNotifier:
    """Sends trading alerts via Twilio WhatsApp API."""

    TWILIO_API = "https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"

    def __init__(self):
        self.account_sid = settings.TWILIO_ACCOUNT_SID
        self.auth_token = settings.TWILIO_AUTH_TOKEN
        self.from_number = settings.TWILIO_WHATSAPP_FROM
        self.to_number = settings.WHATSAPP_TO

        placeholders = {
            "your_account_sid_here",
            "your_auth_token_here",
            "your_whatsapp_from_here",
            "your_whatsapp_to_here",
            None,
            "",
        }
        self.enabled = all([self.account_sid, self.auth_token, self.from_number, self.to_number]) and not any(
            v in placeholders
            for v in [self.account_sid, self.auth_token, self.from_number, self.to_number]
        )

        if self.enabled:
            logger.info(f"WhatsApp notifications enabled → {self.to_number}")
        else:
            logger.info("WhatsApp not configured — add TWILIO_* + WHATSAPP_TO to .env")

    async def send(self, message: str, to_number: Optional[str] = None) -> bool:
        """Send a WhatsApp message via Twilio. Returns True on success."""
        target = (to_number or self.to_number or "").strip()
        if not self.enabled or not target:
            return False

        url = self.TWILIO_API.format(sid=self.account_sid)
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    url,
                    data={"From": self.from_number, "To": target, "Body": message},
                    auth=(self.account_sid, self.auth_token),
                )
                if resp.status_code in (200, 201):
                    data = resp.json()
                    logger.info(f"WhatsApp sent SID={data.get('sid')}")
                    return True

                # Diagnostic for 401 Unauthorized
                error_msg = f"Twilio error {resp.status_code}: {resp.text[:200]}"
                if resp.status_code == 401:
                    sid_status = "HIDDEN" if self.account_sid and self.account_sid.startswith("AC") else "INVALID_OR_MISSING_AC_PREFIX"
                    token_status = "PRESENT" if self.auth_token else "MISSING"
                    error_msg += f" | SID Status: {sid_status} | Token Status: {token_status}"
                    # Dead credential: retrying every alert floods the log
                    # (66x 401s in the 2026-06-11 audit). Latch the channel
                    # off for this process; rotation + restart re-enables it.
                    self.enabled = False
                    logger.error(
                        "WhatsApp channel DISABLED for this process — Twilio auth "
                        "rejected (401). Rotate the Twilio credentials (1Password "
                        "'Twilio' item), update engine/.env, restart the engine. %s",
                        error_msg,
                    )
                    return False

                logger.warning(error_msg)
                return False
        except Exception as e:
            logger.error(f"WhatsApp send failed: {e}")
            return False

    async def alert_pipeline_result(self, symbol: str, result: dict) -> bool:
        action = result.get("final_action", "hold").lower()
        if action == "hold":
            return False

        _ACTION_LABELS = {"buy": "LONG", "sell": "SHORT", "long": "LONG", "short": "SHORT"}
        action_text = _ACTION_LABELS.get(action, action.upper().replace("_", " "))

        confidence = (
            result.get("boosted_confidence")
            or result.get("raw_confidence")
            or result.get("trade_decision", {}).get("conviction", 0.0)
        )
        if confidence is None:
            confidence = 0.0

        debate = result.get("debate_result") or {}
        bull_score = debate.get("bull_score", 0)
        bear_score = debate.get("bear_score", 0)

        lines = [
            f"*JARVIS TRADER — {action_text}*",
            "",
            f"Symbol: {symbol}",
            f"Action: {action_text}",
            f"Confidence: {float(confidence):.0%}",
            f"Bull: {float(bull_score):.2f}  Bear: {float(bear_score):.2f}",
        ]

        trade = result.get("trade_decision") or {}
        entry_price = trade.get("entry_price", 0.0)
        stop_price = trade.get("stop_price", 0.0)
        rr = trade.get("rr_ratio") or trade.get("risk_reward", 0.0)
        notes = trade.get("notes", "")

        if entry_price:
            lines.append(f"Entry: {entry_price:.2f}  Stop: {stop_price:.2f}")
        if rr:
            lines.append(f"R:R  {rr:.2f}")
        if notes:
            lines.extend(["", notes[:200]])

        fund = result.get("fund_decision") or {}
        if fund:
            fd_entry = fund.get("entry_price", 0.0)
            fd_stop = fund.get("stop_price", 0.0)
            if fd_entry and fd_entry != entry_price:
                lines.append(f"Fund entry: {fd_entry:.2f}  stop: {fd_stop:.2f}")

        risk = result.get("risk_decision") or {}
        if risk and not risk.get("approved", True):
            veto = risk.get("rejection_reason") or "Risk check failed"
            lines.extend(["", f"RISK VETO: {veto}"])

        human_required = (
            fund.get("human_approval_required", False)
            or result.get("requires_human", False)
        )
        if human_required:
            lines.extend(["", "HUMAN APPROVAL REQUIRED — check dashboard"])

        lines.extend(["", datetime.now().strftime("%Y-%m-%d %H:%M:%S")])
        return await self.send("\n".join(lines))

    async def alert_kill_switch(self, reason: str, details: str = "") -> bool:
        detail_line = f"\n{details}" if details else ""
        message = (
            f"*KILL SWITCH ACTIVATED*\n\n"
            f"Reason: {reason}{detail_line}\n\n"
            f"All trading halted. Open dashboard to deactivate.\n"
            f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        return await self.send(message)

    async def test(self) -> bool:
        return await self.send(
            "*JARVIS TRADER connected!*\n"
            "WhatsApp alerts are working. You will receive notifications for:\n"
            "- BUY signals\n"
            "- SELL signals\n"
            "- Human approval required\n"
            "- Kill switch activations"
        )


_notifier: Optional[WhatsAppNotifier] = None


def get_notifier() -> WhatsAppNotifier:
    global _notifier
    _notifier = WhatsAppNotifier()
    return _notifier


async def send_whatsapp_message(
    message: str,
    alert_type: str = "notification",
    symbol: Optional[str] = None,
    recipient: Optional[str] = None,
) -> bool:
    """
    Convenience wrapper — send a raw message via the singleton notifier.

    Every send attempt (success or failure) is persisted to the alert_log
    table so Matt can review the full notification history.
    """
    try:
        from database.schema import get_db

        _db = get_db()
    except Exception:
        _db = None

    try:
        success = await get_notifier().send(message, to_number=recipient)
        if _db is not None:
            try:
                _db.insert_alert_log(
                    alert_type=alert_type,
                    message=message,
                    symbol=symbol,
                    status="sent" if success else "failed",
                )
            except Exception as log_err:
                logger.warning(f"alert_log insert failed (non-fatal): {log_err}")
        return success
    except Exception as e:
        if _db is not None:
            try:
                _db.insert_alert_log(
                    alert_type=alert_type,
                    message=message,
                    symbol=symbol,
                    status="failed",
                    error=str(e),
                )
            except Exception as log_err:
                logger.warning(f"alert_log insert failed (non-fatal): {log_err}")
        raise


def format_trade_closed_alert(
    symbol: str,
    side: str,
    quantity: int,
    entry_price: float,
    exit_price: float,
    pnl: float,
    duration_minutes: Optional[float] = None,
) -> str:
    """Format a trade closed WhatsApp notification."""
    emoji = "\u2705" if pnl >= 0 else "\u274c"
    direction = "WIN" if pnl >= 0 else "LOSS"
    pnl_str = f"+${pnl:.0f}" if pnl >= 0 else f"-${abs(pnl):.0f}"

    pts = exit_price - entry_price if side.lower() in ("buy", "long") else entry_price - exit_price
    pts_str = f"+{pts:.2f}" if pts >= 0 else f"{pts:.2f}"

    lines = [
        f"{emoji} *Trade Closed — {direction}*",
        "",
        f"📊 {symbol} {side.upper()} {quantity}ct",
        f"📈 Entry: ${entry_price:.2f} → Exit: ${exit_price:.2f} ({pts_str} pts)",
        f"💰 P&L: *{pnl_str}*",
    ]

    if duration_minutes is not None:
        if duration_minutes < 60:
            dur_str = f"{duration_minutes:.0f}m"
        else:
            dur_str = f"{duration_minutes / 60:.1f}h"
        lines.append(f"⏱ Duration: {dur_str}")

    lines.append("")
    lines.append("JARVIS TRADER 📡")

    return "\n".join(lines)
