"""URL artifact handler — fetch + readability + LLM."""

from __future__ import annotations

import logging
import os
import re
from typing import Any

import certifi
import httpx
from readability import Document  # readability-lxml

# Anaconda leaves SSL_CERT_FILE pointing at a path that doesn't exist on this
# box. Force it to certifi's bundle so httpx can establish TLS connections.
if not os.path.exists(os.environ.get("SSL_CERT_FILE", "")):
    os.environ["SSL_CERT_FILE"] = certifi.where()

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
<<<<<<< HEAD
    except httpx.RequestError as e:
=======
    except (httpx.RequestError, httpx.InvalidURL) as e:
        # InvalidURL is raised at request-build time (e.g. a bookmarked link
        # with a malformed port like "http://host:8010`") and is NOT a subclass
        # of RequestError, so it must be caught explicitly. Degrade gracefully
        # to the embed/URL-only prompt instead of failing the whole row.
>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2
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
        # Discord captures the post's preview text in `embed_description` (and
        # sometimes the title in `embed_title`). For X.com posts and other
        # JS-required pages this is far more useful than the empty fetched
        # HTML body — use it as the LLM context.
        embed_title = (row.get("embed_title") or "").strip()
        embed_desc = (row.get("embed_description") or "").strip()
        embed_block = "\n".join(p for p in (embed_title, embed_desc) if p)

        html = await _fetch_html(url) if url else None
        body = _extract_body(html) if html else ""

        if not body or _is_js_required(body):
            if embed_block:
                prompt = f"URL: {url}\n\nPreview text:\n{embed_block}"
            else:
                prompt = f"URL only (fetch failed or JS-required): {url}"
        else:
            # Prefer embed text when present — it's a clean human-written summary
            ctx_parts = [f"URL: {url}"]
            if embed_block:
                ctx_parts.append(f"Preview text:\n{embed_block}")
            ctx_parts.append(f"Extracted body:\n{body}")
            prompt = "\n\n".join(ctx_parts)

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
