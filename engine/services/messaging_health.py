"""
Messaging Backend Health Monitor — JARVIS TRADER
=================================================
Periodic health check for Ollama + messaging gateway backends.
Runs via APScheduler, logs state, and alerts via Telegram if a backend goes down.
"""

from __future__ import annotations

import logging
import os
import subprocess
import time

import httpx

logger = logging.getLogger(__name__)

OLLAMA_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_ALERT_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

_last_ollama_state: str = "unknown"
_last_alert_time: float = 0.0
_ALERT_COOLDOWN = 300  # 5 min between repeated alerts


async def check_ollama() -> dict:
    """Check if Ollama is serving models."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{OLLAMA_URL}/api/tags")
            resp.raise_for_status()
            models = resp.json().get("models", [])
            return {"state": "ok", "models": len(models)}
    except Exception as exc:
        return {"state": "error", "error": str(exc)}


async def check_engine_messaging() -> dict:
    """Check if the messaging gateway endpoint responds."""
    api_key = os.getenv("ENGINE_API_KEY", "")
    try:
        headers = {"X-API-Key": api_key} if api_key else {}
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get("http://127.0.0.1:8010/messaging/status", headers=headers)
            resp.raise_for_status()
            data = resp.json()
            return {"state": "ok", "agents": data.get("agents", {})}
    except Exception as exc:
        return {"state": "error", "error": str(exc)}


def _try_restart_ollama() -> bool:
    """Attempt to restart Ollama if it's down."""
    try:
        # Try Windows-native Ollama
        result = subprocess.run(
            ["ollama", "serve"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


async def _send_telegram_alert(message: str) -> None:
    """Send a health alert via Telegram if configured."""
    global _last_alert_time
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_ALERT_CHAT_ID:
        return
    now = time.time()
    if now - _last_alert_time < _ALERT_COOLDOWN:
        return
    _last_alert_time = now
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={"chat_id": TELEGRAM_ALERT_CHAT_ID, "text": f"🔴 JARVIS Health Alert\n{message}"},
            )
    except Exception:
        logger.warning("Failed to send Telegram health alert")


async def run_health_check() -> None:
    """Run periodic health check — called by APScheduler."""
    global _last_ollama_state

    ollama = await check_ollama()
    ollama_state = ollama["state"]

    if ollama_state == "error" and _last_ollama_state == "ok":
        logger.error("Ollama went DOWN: %s", ollama.get("error"))
        _try_restart_ollama()
        await _send_telegram_alert(f"Ollama is down: {ollama.get('error')}\nAttempted auto-restart.")
    elif ollama_state == "ok" and _last_ollama_state == "error":
        logger.info("Ollama recovered — %d models available", ollama.get("models", 0))
        await _send_telegram_alert(f"Ollama recovered — {ollama.get('models', 0)} models available")

    _last_ollama_state = ollama_state

    if ollama_state == "ok":
        logger.debug("Health check: ollama=ok models=%d", ollama.get("models", 0))
    else:
        logger.warning("Health check: ollama=%s error=%s", ollama_state, ollama.get("error"))
