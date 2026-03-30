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
        self.from_number = settings.TWILIO_WHATSAPP_FROM   # e.g. whatsapp:+14155238886
        self.to_number = settings.WHATSAPP_TO               # e.g. whatsapp:+12125551234

        placeholders = {"your_account_sid_here", "your_auth_token_here",
                        "your_whatsapp_from_here", "your_whatsapp_to_here", None, ""}
        self.enabled = not any(v in placeholders for v in [
            self.account_sid, self.auth_token, self.from_number, self.to_number
        ])

        if self.enabled:
            logger.info(f"WhatsApp notifications enabled → {self.to_number}")
        else:
            logger.info("WhatsApp not configured — add TWILIO_* + WHATSAPP_TO to .env")

    async def send(self, message: str) -> bool:
        """Send a WhatsApp message via Twilio. Returns True on success."""
        if not self.enabled:
            return False

        url = self.TWILIO_API.format(sid=self.account_sid)
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    url,
                    data={"From": self.from_number, "To": self.to_number, "Body": message},
                    auth=(self.account_sid, self.auth_token),
                )
                if resp.status_code in (200, 201):
                    data = resp.json()
                    logger.info(f"WhatsApp sent SID={data.get('sid')}")
                    return True
                else:
                    logger.warning(f"Twilio error {resp.status_code}: {resp.text[:200]}")
                    return False
        except Exception as e:
            logger.error(f"WhatsApp send failed: {e}")
            return False

    async def alert_pipeline_result(self, symbol: str, result: dict) -> bool:
        """Send an alert for a pipeline result. Only sends for non-HOLD signals."""
        action = result.get("final_action", "hold").lower()
        if action == "hold":
            return False

        confidence = result.get("confidence", 0)
        bull_score = result.get("bull_score", 0)
        bear_score = result.get("bear_score", 0)
        action_text = action.upper().replace("_", " ")

        lines = [
            f"*JARVIS TRADER — {action_text}*",
            "",
            f"Symbol: {symbol}",
            f"Action: {action_text}",
            f"Confidence: {confidence:.0%}",
            f"Bull: {bull_score:.2f}  Bear: {bear_score:.2f}",
        ]

        trader = result.get("trader", {})
        if trader and trader.get("reasoning"):
            lines.extend(["", trader["reasoning"][:200]])

        risk = result.get("risk", {})
        if risk and not risk.get("approved"):
            lines.extend(["", f"RISK VETO: {risk.get('veto_reason', 'Risk check failed')}"])

        fund = result.get("fund_manager", {})
        if fund and fund.get("requires_human_approval"):
            lines.extend(["", "HUMAN APPROVAL REQUIRED — check dashboard"])

        lines.extend(["", datetime.now().strftime("%Y-%m-%d %H:%M:%S")])
        return await self.send("\n".join(lines))

    async def alert_kill_switch(self, reason: str, details: str = "") -> bool:
        """Alert when kill switch is activated."""
        detail_line = f"\n{details}" if details else ""
        message = (
            f"*KILL SWITCH ACTIVATED*\n\n"
            f"Reason: {reason}{detail_line}\n\n"
            f"All trading halted. Open dashboard to deactivate.\n"
            f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        return await self.send(message)

    async def test(self) -> bool:
        """Send a test message to verify config."""
        return await self.send(
            "*JARVIS TRADER connected!*\n"
            "WhatsApp alerts are working. You will receive notifications for:\n"
            "- BUY signals\n"
            "- SELL signals\n"
            "- Human approval required\n"
            "- Kill switch activations"
        )


# Singleton
_notifier: Optional[WhatsAppNotifier] = None


def get_notifier() -> WhatsAppNotifier:
    global _notifier
    # Always create a fresh instance so updated .env values are picked up
    # even if the engine was started before the .env was populated.
    _notifier = WhatsAppNotifier()
    return _notifier


async def send_whatsapp_message(
    message: str,
    alert_type: str = "notification",
    symbol: Optional[str] = None,
) -> bool:
    """
    Convenience wrapper — send a raw message via the singleton notifier.

    Every send attempt (success or failure) is persisted to the alert_log
    table so Matt can review the full notification history.

    Parameters
    ----------
    message:
        The WhatsApp message body to send.
    alert_type:
        Category label stored in alert_log — e.g. 'trade_opened',
        'trade_closed', 'morning_briefing', 'vix_alert', 'circuit_breaker'.
        Defaults to 'notification' for backwards-compatible callers.
    symbol:
        Optional ticker symbol (e.g. 'MES') to tag the log entry.
    """
    # Lazy import to avoid circular dependencies at module load time
    try:
        from database.schema import get_db
        _db = get_db()
    except Exception:
        _db = None

    try:
        success = await get_notifier().send(message)
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

    # Price movement (points) relative to trade direction
    pts = exit_price - entry_price if side.lower() in ("buy", "long") else entry_price - exit_price
    pts_str = f"+{pts:.2f}" if pts >= 0 else f"{pts:.2f}"

    lines = [
        f"{emoji} *Trade Closed \u2014 {direction}*",
        "",
        f"\U0001f4ca {symbol} {side.upper()} {quantity}ct",
        f"\U0001f4c8 Entry: ${entry_price:.2f} \u2192 Exit: ${exit_price:.2f} ({pts_str} pts)",
        f"\U0001f4b0 P&L: *{pnl_str}*",
    ]

    if duration_minutes is not None:
        if duration_minutes < 60:
            dur_str = f"{duration_minutes:.0f}m"
        else:
            dur_str = f"{duration_minutes / 60:.1f}h"
        lines.append(f"\u23f1 Duration: {dur_str}")

    lines.append("")
    lines.append("JARVIS TRADER \U0001f4e1")

    return "\n".join(lines)
