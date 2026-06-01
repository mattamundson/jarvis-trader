"""Image artifact handler — Gemini/Anthropic vision LLM."""

from __future__ import annotations

import logging
import os
import re
from typing import Any

import certifi
import httpx

if not os.path.exists(os.environ.get("SSL_CERT_FILE", "")):
    os.environ["SSL_CERT_FILE"] = certifi.where()

from ..llm import call_vision
from ..models import AnalysisResult, ArtifactType
from ..prompts import IMAGE_SYSTEM
from .text import _parse_json_reply

logger = logging.getLogger(__name__)

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".gif")
MAX_BYTES = 8 * 1024 * 1024  # 8 MB cap
TIMEOUT = httpx.Timeout(30.0, read=60.0)


def _split_urls(field: str) -> list[str]:
    return [u for u in re.split(r"[\s,]+", field.strip()) if u]


def _looks_like_image(url: str) -> bool:
    low = url.lower().split("?", 1)[0]
    return any(low.endswith(ext) for ext in IMAGE_EXTS)


async def _download(url: str) -> tuple[bytes, str]:
    async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True) as cli:
        r = await cli.get(url)
        r.raise_for_status()
        mime = r.headers.get("content-type", "application/octet-stream").split(";", 1)[0].strip()
        data = r.content[:MAX_BYTES]
        return data, mime


class ImageHandler:
    async def analyze(self, row: dict[str, Any]) -> AnalysisResult:
        urls = _split_urls(row.get("attachment_urls") or "")
        image_urls = [u for u in urls if _looks_like_image(u)]
        if not image_urls:
            raise ValueError(f"no image attachment in row {row.get('message_id')}")

        data, mime = await _download(image_urls[0])
        resp = await call_vision(prompt=IMAGE_SYSTEM, image_bytes=data, mime=mime)
        summary, structured = _parse_json_reply(resp.reply)

        return AnalysisResult(
            bookmark_id=str(row["message_id"]),
            artifact_type=ArtifactType.IMAGE,
            summary=summary,
            structured=structured,
            model_used=resp.model,
            usage=resp.usage,
            cost_usd=resp.cost_usd,
        )
