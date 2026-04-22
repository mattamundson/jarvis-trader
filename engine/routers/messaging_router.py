from __future__ import annotations

import logging
import os
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from notifications.openclaw_notifier import send_raw as send_openclaw_whatsapp
from notifications.telegram import get_notifier as get_telegram_notifier
from notifications.whatsapp import send_whatsapp_message
from services.telegram_poller import start_telegram_poller, stop_telegram_poller
from services.agent_gateway import (
    GatewayConfig,
    GatewaySessionStore,
    InboundMessage,
    OllamaAgentAdapter,
    OllamaBackendConfig,
    OpenAICompatBackendConfig,
    SharedAgentGateway,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/messaging", tags=["messaging"])

_gateway: Optional[SharedAgentGateway] = None
_db_path: Optional[str] = None


class DirectChatRequest(BaseModel):
    channel: str = Field(default="api")
    user_id: str
    message: str
    reply_target: str | None = None
    display_name: str = ""


def inject_dependencies(db_path: str) -> None:
    global _db_path, _gateway
    _db_path = db_path
    _gateway = None


def _parse_csv(raw: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def _normalize_whatsapp_sender(raw: str) -> str:
    return raw.replace("whatsapp:", "").replace("+", "").strip()


def _build_gateway() -> SharedAgentGateway:
    if _db_path is None:
        raise RuntimeError("messaging gateway not initialized")

    config = GatewayConfig(
        default_agent=os.getenv("MESSAGING_DEFAULT_AGENT", "openclaw"),
        max_history_messages=int(os.getenv("MESSAGING_MAX_HISTORY_MESSAGES", "10")),
        allowed_telegram_chat_ids=_parse_csv(os.getenv("MESSAGING_ALLOWED_TELEGRAM_CHAT_IDS", "")),
        allowed_whatsapp_numbers=tuple(
            _normalize_whatsapp_sender(v) for v in _parse_csv(os.getenv("MESSAGING_ALLOWED_WHATSAPP_NUMBERS", ""))
        ),
    )
    store = GatewaySessionStore(_db_path)
    ollama_base = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")

    # Both adapters use direct Ollama for fast local inference.
    # OpenClaw/Hermes CLIs are too slow (~240s) because their system prompts
    # overwhelm the 7B model. Direct Ollama gives 10-40s responses.
    openclaw_adapter = OllamaAgentAdapter(
        "openclaw",
        primary=OllamaBackendConfig(
            backend="ollama-direct",
            model=os.getenv("OPENCLAW_LOCAL_MODEL", "qwen2.5:7b").removeprefix("ollama/"),
            base_url=ollama_base,
        ),
    )
    hermes_adapter = OllamaAgentAdapter(
        "hermes",
        primary=OllamaBackendConfig(
            backend="ollama-direct",
            model=os.getenv("HERMES_LOCAL_MODEL", "qwen2.5:7b"),
            base_url=ollama_base,
        ),
        fallback=(
            OpenAICompatBackendConfig(
                backend="hermes-cloud",
                model=os.getenv("HERMES_CLOUD_MODEL", ""),
                base_url=os.getenv("HERMES_CLOUD_BASE_URL", ""),
                api_key=os.getenv("HERMES_CLOUD_API_KEY", ""),
            )
            if os.getenv("HERMES_CLOUD_BASE_URL")
            else None
        ),
    )

    return SharedAgentGateway(
        store=store,
        config=config,
        adapters={"openclaw": openclaw_adapter, "hermes": hermes_adapter},
    )


def _get_gateway() -> SharedAgentGateway:
    global _gateway
    if _gateway is None:
        _gateway = _build_gateway()
    return _gateway


async def _send_telegram_reply(chat_id: str, message: str) -> bool:
    notifier = get_telegram_notifier()
    return await notifier.send(message, chat_id=chat_id, parse_mode=None)


async def _send_whatsapp_reply(recipient: str, message: str) -> bool:
    normalized = recipient if recipient.startswith("+") else f"+{recipient}"
    sent = await send_openclaw_whatsapp(message, phone=normalized)
    if sent:
        return True
    return await send_whatsapp_message(message, recipient=f"whatsapp:{normalized}")


@router.post("/chat")
async def direct_chat(request: DirectChatRequest) -> dict[str, Any]:
    gateway = _get_gateway()
    reply = await gateway.handle(
        InboundMessage(
            channel=request.channel,  # type: ignore[arg-type]
            user_id=request.user_id,
            text=request.message,
            reply_target=request.reply_target or request.user_id,
            display_name=request.display_name,
        )
    )
    return {
        "agent": reply.agent,
        "backend": reply.backend,
        "model": reply.model,
        "session_id": reply.session_id,
        "reply_text": reply.reply_text,
        "health_state": reply.health_state,
        "fallback_used": reply.fallback_used,
        "error": reply.error,
    }


@router.get("/status")
async def gateway_status() -> dict[str, Any]:
    gateway = _get_gateway()
    openclaw_health = await gateway.adapters["openclaw"].health()
    hermes_health = await gateway.adapters["hermes"].health()
    return {
        "default_agent": gateway.config.default_agent,
        "telegram_allowlist": list(gateway.config.allowed_telegram_chat_ids),
        "whatsapp_allowlist": list(gateway.config.allowed_whatsapp_numbers),
        "agents": {
            "openclaw": {
                "backend": openclaw_health.backend,
                "model": openclaw_health.model,
                "state": openclaw_health.state,
                "detail": openclaw_health.detail,
            },
            "hermes": {
                "backend": hermes_health.backend,
                "model": hermes_health.model,
                "state": hermes_health.state,
                "detail": hermes_health.detail,
            },
        },
    }


@router.get("/health")
async def messaging_health() -> dict[str, Any]:
    """Detailed health check for all messaging backends."""
    from services.messaging_health import check_ollama
    from services.telegram_poller import get_poller
    ollama = await check_ollama()
    gateway = _get_gateway()
    poller = get_poller()
    return {
        "ollama": ollama,
        "telegram_poller": "running" if poller and poller._running else "stopped",
        "gateway_initialized": gateway is not None,
        "agents": {
            name: {
                "backend": adapter.primary.backend if hasattr(adapter, "primary") else "cli",
                "model": adapter.primary.model if hasattr(adapter, "primary") else "n/a",
            }
            for name, adapter in gateway.adapters.items()
        },
    }


@router.post("/inbound/telegram")
async def telegram_webhook(request: Request) -> dict[str, Any]:
    payload = await request.json()
    message = payload.get("message") or payload.get("edited_message") or {}
    chat = message.get("chat") or {}
    text = (message.get("text") or "").strip()
    chat_id = str(chat.get("id") or "")
    if not chat_id:
        raise HTTPException(status_code=400, detail="telegram chat id missing")

    reply = await _get_gateway().handle(
        InboundMessage(
            channel="telegram",
            user_id=chat_id,
            text=text,
            reply_target=chat_id,
            display_name=(chat.get("username") or chat.get("title") or ""),
        )
    )
    await _send_telegram_reply(chat_id, reply.reply_text)
    return {"ok": True, "agent": reply.agent, "state": reply.health_state}


@router.post("/inbound/whatsapp")
async def whatsapp_webhook(request: Request) -> dict[str, Any]:
    try:
        payload = await request.json()
    except Exception:
        form = await request.form()
        payload = dict(form)

    raw_text = (payload.get("message") or payload.get("text") or payload.get("body") or payload.get("Body") or "").strip()
    raw_sender = str(payload.get("from") or payload.get("from_number") or payload.get("sender") or payload.get("From") or "")
    sender = _normalize_whatsapp_sender(raw_sender)
    if not sender:
        raise HTTPException(status_code=400, detail="whatsapp sender missing")

    reply = await _get_gateway().handle(
        InboundMessage(
            channel="whatsapp",
            user_id=sender,
            text=raw_text,
            reply_target=sender,
            display_name=sender,
        )
    )
    await _send_whatsapp_reply(sender, reply.reply_text)
    return {"ok": True, "agent": reply.agent, "state": reply.health_state}


async def _telegram_handler(chat_id: str, text: str, username: str) -> str:
    """Handler called by the Telegram poller for each inbound message."""
    gateway = _get_gateway()
    reply = await gateway.handle(
        InboundMessage(
            channel="telegram",
            user_id=chat_id,
            text=text,
            reply_target=chat_id,
            display_name=username,
        )
    )
    return reply.reply_text


async def start_messaging_services() -> None:
    """Start background messaging services (called from engine startup)."""
    await start_telegram_poller(_telegram_handler)


async def stop_messaging_services() -> None:
    """Stop background messaging services (called from engine shutdown)."""
    await stop_telegram_poller()
