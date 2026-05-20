"""URL artifact handler — fetch + readability + LLM."""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx
from readability import Document  # readability-lxml

from ..llm import call_text
from ..models import AnalysisResult, ArtifactType
from ..prompts import URL_SYSTEM
from .text import _parse_json_reply

logger = logging.getLogger(__name__)

USER_AGENT = "JarvisTrader/1.0 (+https://github.com/mattamundson)"
MAX_BODY_CHARS = 12_000
TIMEOUT = httpx.Timeout(20.0, read=30.0)


async def _fetch_html(url: str) -> str | None:
    try:
        async with httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT},
            timeout=TIMEOUT,
            follow_redirects=True,
        ) as cli:
            r = await cli.get(url)
            if r.status_code != 200:
                logger.info("url_handler: %s returned %s", url, r.status_code)
                return None
            return r.text
    except httpx.RequestError as e:
        logger.info("url_handler: fetch error %s on %s", e, url)
        return None


def _extract_body(html: str) -> str:
    """Use readability-lxml to pull the main article body. Cap at MAX_BODY_CHARS."""
    try:
        doc = Document(html)
        body = doc.summary(html_partial=True)
        text = re.sub(r"<[^>]+>", " ", body)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:MAX_BODY_CHARS]
    except Exception as e:  # noqa: BLE001
        logger.info("url_handler: readability failed %s", e)
        return ""


def _is_js_required(body: str) -> bool:
    lowered = body.lower()
    return "enable javascript" in lowered or len(body.strip()) < 50


class UrlHandler:
    async def analyze(self, row: dict[str, Any]) -> AnalysisResult:
        url = row.get("url") or ""
        html = await _fetch_html(url) if url else None
        body = _extract_body(html) if html else ""

        if not body or _is_js_required(body):
            prompt = f"URL only (fetch failed or JS-required): {url}"
        else:
            prompt = f"URL: {url}\n\nExtracted body:\n{body}"

        resp = await call_text(prompt=prompt, system=URL_SYSTEM)
        summary, structured = _parse_json_reply(resp.reply)

        return AnalysisResult(
            bookmark_id=str(row["message_id"]),
            artifact_type=ArtifactType.URL,
            summary=summary,
            structured=structured,
            model_used=resp.model,
            usage=resp.usage,
            cost_usd=resp.cost_usd,
        )
