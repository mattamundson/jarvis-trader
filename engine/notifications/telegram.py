"""
Telegram Notifications
======================
Sends trading alerts to Telegram when JARVIS produces actionable signals.
Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env to enable.
"""

import logging
from datetime import datetime
from typing import Optional

import httpx

from config import settings

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """Sends trading alerts to Telegram."""

    BASE_URL = "https://api.telegram.org/bot{token}/{method}"

    def __init__(self):
        self.token = settings.TELEGRAM_BOT_TOKEN
        self.chat_id = settings.TELEGRAM_CHAT_ID
        self.enabled = bool(
            self.token
            and self.chat_id
            and self.token != "your_bot_token_here"
            and self.chat_id != "your_chat_id_here"
        )

        if self.enabled:
            logger.info("Telegram notifications enabled")
        else:
            logger.info(
                "Telegram not configured — add TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID to .env"
            )

    async def send(self, message: str, parse_mode: str = "HTML") -> bool:
        """Send a message. Returns True on success."""
        if not self.enabled:
            return False

        url = self.BASE_URL.format(token=self.token, method="sendMessage")
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    url,
                    json={
                        "chat_id": self.chat_id,
                        "text": message,
                        "parse_mode": parse_mode,
                        "disable_web_page_preview": True,
                    },
                )
                if resp.status_code == 200:
                    return True
                else:
                    logger.warning(f"Telegram API error {resp.status_code}: {resp.text[:200]}")
                    return False
        except Exception as e:
            logger.error(f"Telegram send failed: {e}")
            return False

    async def alert_pipeline_result(self, symbol: str, result: dict) -> bool:
        """Send an alert for a pipeline result. Only sends for non-HOLD signals."""
        action = result.get("final_action", "hold").lower()

        if action == "hold":
            return False  # Skip pure holds

        confidence = result.get("confidence", 0)
        bull_score = result.get("bull_score", 0)
        bear_score = result.get("bear_score", 0)

        # Build the message
        if action == "buy":
            pass
        elif action == "sell":
            pass
        else:
            pass
        action_text = action.upper().replace("_", " ")

        lines = [
            f"<b>JARVIS TRADER — {action_text}</b>",
            "",
            f"<b>Symbol:</b> {symbol}",
            f"<b>Action:</b> {action_text}",
            f"<b>Confidence:</b> {confidence:.0%}",
            f"<b>Bull Score:</b> {bull_score:.2f}  <b>Bear Score:</b> {bear_score:.2f}",
        ]

        # Add trader reasoning if available
        trader = result.get("trader", {})
        if trader and trader.get("reasoning"):
            reasoning = trader["reasoning"][:200]
            lines.extend(["", f"<i>{reasoning}</i>"])

        # Risk notes
        risk = result.get("risk", {})
        if risk and not risk.get("approved"):
            lines.extend(["", f"<b>RISK VETO:</b> {risk.get('veto_reason', 'Risk check failed')}"])

        # Human approval required
        fund = result.get("fund_manager", {})
        if fund and fund.get("requires_human_approval"):
            lines.extend(["", "<b>HUMAN APPROVAL REQUIRED</b> — check dashboard"])

        lines.extend(
            [
                "",
                f"<code>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</code>",
                "<a href='http://localhost:3010'>Open Dashboard</a>",
            ]
        )

        message = "\n".join(lines)
        return await self.send(message)

    async def alert_kill_switch(self, reason: str, details: str = "") -> bool:
        """Alert when kill switch is activated."""
        detail_line = f"\n{details}" if details else ""
        message = (
            f"<b>KILL SWITCH ACTIVATED</b>\n\n"
            f"<b>Reason:</b> {reason}{detail_line}\n\n"
            f"All trading halted. Go to dashboard to deactivate.\n"
            f"<code>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</code>"
        )
        return await self.send(message)

    async def test(self) -> bool:
        """Send a test message to verify config."""
        return await self.send(
            "<b>JARVIS TRADER connected!</b>\n"
            "Telegram alerts are working. You will receive notifications for:\n"
            "- BUY signals\n"
            "- SELL signals\n"
            "- Human approval required\n"
            "- Kill switch activations"
        )


# Singleton
_notifier: Optional[TelegramNotifier] = None


def get_notifier() -> TelegramNotifier:
    global _notifier
    if _notifier is None:
        _notifier = TelegramNotifier()
    return _notifier
