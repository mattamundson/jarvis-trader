"""Document artifact handler — extract text from PDFs and analyze."""

from __future__ import annotations

import logging
import os
import re
from io import BytesIO
from typing import Any

import certifi
import httpx
from pypdf import PdfReader

if not os.path.exists(os.environ.get("SSL_CERT_FILE", "")):
    os.environ["SSL_CERT_FILE"] = certifi.where()

from ..llm import call_text
from ..models import AnalysisResult, ArtifactType
from ..prompts import DOCUMENT_SYSTEM
from .text import _parse_json_reply

logger = logging.getLogger(__name__)

DOC_EXTS = (".pdf",)
MAX_TEXT_CHARS = 16_000
TIMEOUT = httpx.Timeout(30.0, read=60.0)


def _split_urls(field: str) -> list[str]:
    return [u for u in re.split(r"[\s,]+", field.strip()) if u]


def _looks_like_doc(url: str) -> bool:
    low = url.lower().split("?", 1)[0]
    return any(low.endswith(ext) for ext in DOC_EXTS)


async def _download(url: str) -> bytes:
    async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True) as cli:
        r = await cli.get(url)
        r.raise_for_status()
        return r.content


def _extract_text(pdf_bytes: bytes) -> str:
    reader = PdfReader(BytesIO(pdf_bytes))
    parts = []
    for page in reader.pages:
        try:
            parts.append(page.extract_text() or "")
        except Exception as e:  # noqa: BLE001
            logger.info("document_handler: page extract error %s", e)
    return "\n".join(parts)[:MAX_TEXT_CHARS]


class DocumentHandler:
    async def analyze(self, row: dict[str, Any]) -> AnalysisResult:
        urls = _split_urls(row.get("attachment_urls") or "")
        doc_urls = [u for u in urls if _looks_like_doc(u)]
        if not doc_urls:
            raise ValueError(f"no document attachment in row {row.get('message_id')}")

        data = await _download(doc_urls[0])
        text = _extract_text(data)
        if not text.strip():
            text = "(no extractable text)"

        resp = await call_text(prompt=text, system=DOCUMENT_SYSTEM)
        summary, structured = _parse_json_reply(resp.reply)
        structured.setdefault("doc_chars", len(text))

        return AnalysisResult(
            bookmark_id=str(row["message_id"]),
            artifact_type=ArtifactType.DOCUMENT,
            summary=summary,
            structured=structured,
            model_used=resp.model,
            usage=resp.usage,
            cost_usd=resp.cost_usd,
        )
