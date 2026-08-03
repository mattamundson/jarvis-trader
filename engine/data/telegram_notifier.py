# telegram_notifier.py
"""Lightweight Telegram notifier used by watchdogs and feeds."""

from __future__ import annotations

import json
import logging
import os
import urllib.parse
import urllib.request
from typing import Optional

logger = logging.getLogger(__name__)

_TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
_TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


def send_telegram(message: str) -> bool:
    if not _TELEGRAM_BOT_TOKEN or not _TELEGRAM_CHAT_ID:
        return False
    try:
        payload = urllib.parse.urlencode(
            {"chat_id": _TELEGRAM_CHAT_ID, "text": message}
        ).encode("utf-8")
        url = f"https://api.telegram.org/bot{_TELEGRAM_BOT_TOKEN}/sendMessage"
        req = urllib.request.Request(url, data=payload, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.status == 200
    except Exception as exc:
        logger.warning("telegram send failed: %s", exc)
        return False
