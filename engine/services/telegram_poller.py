"""
Telegram Long-Polling Service — JARVIS TRADER
==============================================
Polls Telegram Bot API for new messages and routes them through the
SharedAgentGateway. No public URL or tunnel required.

Usage:
    Called from engine startup (main.py) as a background asyncio task.
    Stops gracefully when the engine shuts down.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_BASE = "https://api.telegram.org/bot{token}"
_POLL_TIMEOUT = 30  # Telegram long-poll seconds


class TelegramPoller:
    def __init__(
        self,
        token: str,
        message_handler,  # async callable(chat_id: str, text: str, username: str) -> str
        allowed_chat_ids: tuple[str, ...] = (),
    ):
        self.token = token
        self.base_url = _BASE.format(token=token)
        self.handler = message_handler
        self.allowed_chat_ids = allowed_chat_ids
        self._offset: int = 0
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        if self._running:
            return
        async with httpx.AsyncClient(timeout=10) as client:
            # Delete any existing webhook so polling works
            resp = await client.post(f"{self.base_url}/deleteWebhook")
            logger.info("Telegram webhook deleted: %s", resp.json().get("description", ""))
            # Fast-forward offset to current position so messages received while
            # the bot was offline are not replayed as duplicates on restart.
            upd = await client.get(
                f"{self.base_url}/getUpdates",
                params={"offset": -1, "limit": 1, "timeout": 0},
            )
            upd_data = upd.json()
            if upd_data.get("ok") and upd_data.get("result"):
                self._offset = upd_data["result"][-1]["update_id"] + 1
                logger.info("Telegram poller: fast-forwarded to offset %d", self._offset)
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("Telegram poller started for bot %s", self.token.split(":")[0])

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Telegram poller stopped")

    async def _poll_loop(self) -> None:
        while self._running:
            try:
                updates = await self._get_updates()
                for update in updates:
                    await self._process_update(update)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Telegram poll error — retrying in 5s")
                await asyncio.sleep(5)

    async def _get_updates(self) -> list[dict]:
        params = {
            "offset": self._offset,
            "timeout": _POLL_TIMEOUT,
            "allowed_updates": '["message"]',
        }
        async with httpx.AsyncClient(timeout=_POLL_TIMEOUT + 10) as client:
            resp = await client.get(f"{self.base_url}/getUpdates", params=params)
            data = resp.json()
        if not data.get("ok"):
            logger.warning("Telegram getUpdates failed: %s", data)
            return []
        results = data.get("result", [])
        if results:
            self._offset = results[-1]["update_id"] + 1
        return results

    async def _process_update(self, update: dict) -> None:
        message = update.get("message") or update.get("edited_message")
        if not message:
            return
        chat = message.get("chat", {})
        chat_id = str(chat.get("id", ""))
        text = (message.get("text") or "").strip()
        username = chat.get("username") or chat.get("first_name") or ""

        if not chat_id or not text:
            return

        # Allowlist check — empty means allow all, matches chat_id OR username
        if self.allowed_chat_ids:
            if chat_id not in self.allowed_chat_ids and username not in self.allowed_chat_ids:
                logger.warning(
                    "Telegram message from unauthorized chat %s (%s) — add to MESSAGING_ALLOWED_TELEGRAM_CHAT_IDS",
                    chat_id,
                    username,
                )
                return

        logger.info("Telegram message from %s (%s): %s", chat_id, username, text[:80])

        try:
            reply_text = await self.handler(chat_id, text, username)
        except Exception:
            logger.exception("Gateway handler failed for Telegram message")
            reply_text = "Error processing your message. Check /status for agent health."

        await self._send_reply(chat_id, reply_text)

    async def _send_reply(self, chat_id: str, text: str) -> None:
        # Telegram has a 4096 char limit per message
        chunks = [text[i : i + 4000] for i in range(0, len(text), 4000)]
        async with httpx.AsyncClient(timeout=15) as client:
            for chunk in chunks:
                try:
                    await client.post(
                        f"{self.base_url}/sendMessage",
                        json={"chat_id": chat_id, "text": chunk},
                    )
                except Exception:
                    logger.exception("Failed to send Telegram reply to %s", chat_id)


_poller: Optional[TelegramPoller] = None


def get_poller() -> Optional[TelegramPoller]:
    return _poller


async def start_telegram_poller(gateway_handle_fn) -> Optional[TelegramPoller]:
    """Start the Telegram poller if TELEGRAM_BOT_TOKEN is set.

    Args:
        gateway_handle_fn: async callable(chat_id, text, username) -> reply_text
    """
    global _poller
    enabled = os.getenv("TELEGRAM_POLLER_ENABLED", "").strip().lower()
    if enabled not in {"1", "true", "yes", "on"}:
        logger.info("TELEGRAM_POLLER_ENABLED is not true - Telegram poller disabled")
        return None

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        logger.info("TELEGRAM_BOT_TOKEN not set — Telegram poller disabled")
        return None

    allowed_raw = os.getenv("MESSAGING_ALLOWED_TELEGRAM_CHAT_IDS", "")
    allowed = tuple(s.strip() for s in allowed_raw.split(",") if s.strip())

    _poller = TelegramPoller(
        token=token, message_handler=gateway_handle_fn, allowed_chat_ids=allowed
    )
    await _poller.start()
    return _poller


async def stop_telegram_poller() -> None:
    global _poller
    if _poller:
        await _poller.stop()
        _poller = None
