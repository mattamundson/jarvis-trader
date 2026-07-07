"""LLM adapter for deep_analyzer.

Thin layer over `llm.client.JarvisLLMClient` — reuses Anthropic retry +
Gemini failover + cost tracking + `llm_path_healthy` health signal. Exposes
`call_text` and `call_vision` so handlers don't need to know about the
messages-format or model selection.
"""

from __future__ import annotations

import base64
import logging
import os
from dataclasses import dataclass
from typing import Any

from llm.client import JarvisLLMClient, LLMCallResult

from .models import LLMUsage

logger = logging.getLogger(__name__)


class LLMError(RuntimeError):
    """LLM call failed (after retries + fallback)."""


@dataclass(frozen=True)
class LLMResponse:
    reply: str
    model: str
    usage: LLMUsage
    cost_usd: float


# Singleton — JarvisLLMClient is expensive to construct (DB connection, anthropic client).
_client_singleton: JarvisLLMClient | None = None

# Default model for deep_analyzer: Haiku 4.5 (cheapest Claude tier).
# Failover chain inside JarvisLLMClient: Haiku → (if GOOGLE_API_KEY set) gemini-2.0-flash.
DEFAULT_MODEL = "claude-haiku-4-5-20251001"
AGENT_NAME = "deep_analyzer"


def _get_engine_client() -> JarvisLLMClient:
    """Singleton with provider locked to anthropic.

    The engine-wide default `JARVIS_LLM_PROVIDER` is `ollama` (cost), but
    deep_analyzer needs cloud routing for vision, large context, and
    internet-fetched URL analysis. We force anthropic for this client
    only — temporarily override the env var around construction so the
    rest of the engine is unaffected.
    """
    global _client_singleton
    if _client_singleton is None:
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        db_path = os.getenv("JARVIS_LLM_COST_DB", "data/llm_costs.db")
        prev = os.environ.get("JARVIS_LLM_PROVIDER")
        os.environ["JARVIS_LLM_PROVIDER"] = "anthropic"
        try:
            _client_singleton = JarvisLLMClient(api_key=api_key, db_path=db_path)
        finally:
            if prev is None:
                os.environ.pop("JARVIS_LLM_PROVIDER", None)
            else:
                os.environ["JARVIS_LLM_PROVIDER"] = prev
    return _client_singleton


def _to_response(r: LLMCallResult) -> LLMResponse:
    if not r.success:
        raise LLMError(r.error or "LLM call failed without error message")
    return LLMResponse(
        reply=r.content,
        model=r.model,
        usage=LLMUsage(input_tokens=r.input_tokens, output_tokens=r.output_tokens),
        cost_usd=float(r.cost_usd or 0.0),
    )


async def call_text(*, prompt: str, system: str | None = None) -> LLMResponse:
    """Single text turn. Returns the model's text reply + usage + cost."""
    client = _get_engine_client()
    messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
    r = await client.call(
        model=DEFAULT_MODEL,
        system=system or "",
        messages=messages,
        max_tokens=1024,
        agent_name=AGENT_NAME,
        temperature=0.2,
        tier="fast",
        compact=False,  # deep_analyzer prompts are short; skip compaction overhead
    )
    return _to_response(r)


async def call_vision(*, prompt: str, image_bytes: bytes, mime: str) -> LLMResponse:
    """Vision turn — single image + text prompt. Uses Anthropic multimodal."""
    client = _get_engine_client()
    b64 = base64.b64encode(image_bytes).decode("ascii")
    messages: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": mime, "data": b64},
                },
                {"type": "text", "text": prompt},
            ],
        }
    ]
    r = await client.call(
        model=DEFAULT_MODEL,
        system="",
        messages=messages,
        max_tokens=1024,
        agent_name=AGENT_NAME,
        temperature=0.2,
        tier="fast",
        compact=False,
    )
    return _to_response(r)
