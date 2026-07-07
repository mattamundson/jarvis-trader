"""X.com / twitter.com URL handler — fxtwitter API for JS-free content extraction.

The standard URL handler relies on readability-lxml against the rendered HTML
body, but X.com pages require JS to render the tweet content; the body that
comes back is a "Please enable JavaScript" shell. fxtwitter exposes the tweet
as structured JSON (text, author, engagement, optional long-form `article`),
so this handler skips HTML extraction entirely and feeds the LLM a synthesized
text block built from the API response.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

import certifi
import httpx

# Anaconda leaves SSL_CERT_FILE pointing at a path that doesn't exist on this
# box. Force it to certifi's bundle so httpx can establish TLS connections.
if not os.path.exists(os.environ.get("SSL_CERT_FILE", "")):
    os.environ["SSL_CERT_FILE"] = certifi.where()

from ..llm import call_text
from ..models import AnalysisResult, ArtifactType
from ..prompts import X_POST_SYSTEM
from .text import _parse_json_reply

logger = logging.getLogger(__name__)

# Match x.com, twitter.com, nitter.*, fxtwitter.com, vxtwitter.com — anything
# with the canonical `/<screen_name>/status/<id>` shape. Trailing slashes and
# query strings (?s=20, ?ref=..., etc.) are ignored.
X_URL_RE = re.compile(
    r"^https?://(?:www\.)?(?:x|twitter|nitter|fxtwitter|vxtwitter)\.com/" r"([^/]+)/status/(\d+)",
    re.IGNORECASE,
)

FXTWITTER_BASE = "https://api.fxtwitter.com"
REQUEST_TIMEOUT = httpx.Timeout(15.0, read=20.0)
USER_AGENT = "JarvisTrader/1.0 (+https://github.com/mattamundson)"

# Cap article content to avoid blowing past LLM context window. 8K chars ≈ 2K
# tokens; combined with author + engagement + tweet body the full prompt stays
# well under Haiku 4.5's 200K limit.
MAX_ARTICLE_CHARS = 8000
MAX_MEDIA_URLS = 10


async def _fetch_fxtwitter(screen_name: str, tweet_id: str) -> dict[str, Any] | None:
    """Hit api.fxtwitter.com and return the `tweet` sub-object, or None."""
    url = f"{FXTWITTER_BASE}/{screen_name}/status/{tweet_id}"
    try:
        async with httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT,
            follow_redirects=True,
        ) as cli:
            r = await cli.get(url)
            if r.status_code >= 400:
                logger.info("x_post_handler: fxtwitter %s returned %s", url, r.status_code)
                return None
            data = r.json()
    except (httpx.RequestError, ValueError) as e:
        logger.info("x_post_handler: fxtwitter fetch error %s on %s", e, url)
        return None
    if not isinstance(data, dict):
        return None
    tweet = data.get("tweet")
    if not isinstance(tweet, dict):
        return None
    return tweet


def _extract_body_text(tweet: dict[str, Any]) -> str:
    """Pull the user-readable body. `raw_text` may be a dict or a string."""
    text = (tweet.get("text") or "").strip()
    raw = tweet.get("raw_text")
    raw_text = ""
    if isinstance(raw, dict):
        raw_text = (raw.get("text") or "").strip()
    elif isinstance(raw, str):
        raw_text = raw.strip()
    # Prefer `text` (formatted with t.co expansions); fall back to raw.
    return text or raw_text


def _extract_article_block(tweet: dict[str, Any]) -> str:
    """Build a multi-line article section if the tweet has long-form content."""
    article = tweet.get("article") or {}
    if not article:
        return ""
    parts: list[str] = []
    title = article.get("title")
    if title:
        parts.append(f"Article title: {title}")
    preview = article.get("preview_text")
    if preview:
        parts.append(f"Article preview: {preview}")
    blocks = (article.get("content") or {}).get("blocks") or []
    block_texts: list[str] = []
    for blk in blocks:
        if not isinstance(blk, dict):
            continue
        bt = (blk.get("text") or "").strip()
        if bt:
            block_texts.append(bt)
    if block_texts:
        joined = "\n\n".join(block_texts)
        parts.append(f"Article content:\n{joined[:MAX_ARTICLE_CHARS]}")
    return "\n\n".join(parts)


def _extract_media_urls(tweet: dict[str, Any]) -> list[str]:
    """Collect photo/video URLs plus article media-entity images."""
    urls: list[str] = []
    media = tweet.get("media") or {}
    for ph in media.get("photos") or []:
        if isinstance(ph, dict) and ph.get("url"):
            urls.append(ph["url"])
    for vid in media.get("videos") or []:
        if isinstance(vid, dict) and vid.get("url"):
            urls.append(vid["url"])
    article = tweet.get("article") or {}
    for me in article.get("media_entities") or []:
        if not isinstance(me, dict):
            continue
        mi = me.get("media_info") or {}
        img_url = mi.get("original_img_url")
        if img_url:
            urls.append(img_url)
    return urls


def _build_prompt(url: str, tweet: dict[str, Any]) -> str:
    """Synthesize the full text block the LLM analyzes."""
    parts: list[str] = []
    author = tweet.get("author") or {}
    screen_name = author.get("screen_name") or "?"
    name = author.get("name") or ""
    header = f"X post by @{screen_name}"
    if name:
        header += f" ({name})"
    verification = author.get("verification") or {}
    if isinstance(verification, dict) and verification.get("verified"):
        header += " (verified)"
    elif isinstance(verification, str) and verification:
        # Some fxtwitter responses return a string like "Blue" / "Business".
        header += f" (verified: {verification})"
    parts.append(header)
    parts.append(f"URL: {url}")
    if tweet.get("created_at"):
        parts.append(f"Posted {tweet['created_at']}")

    engagement = (
        f"Engagement: {int(tweet.get('views') or 0):,} views, "
        f"{int(tweet.get('likes') or 0):,} likes, "
        f"{int(tweet.get('retweets') or 0):,} retweets, "
        f"{int(tweet.get('replies') or 0):,} replies, "
        f"{int(tweet.get('bookmarks') or 0):,} bookmarks"
    )
    parts.append(engagement)
    parts.append("")

    body = _extract_body_text(tweet)
    if body:
        parts.append(f"Tweet body: {body}")
        parts.append("")

    article_block = _extract_article_block(tweet)
    if article_block:
        parts.append(article_block)
        parts.append("")

    media_urls = _extract_media_urls(tweet)
    if media_urls:
        parts.append(f"Media: {len(media_urls)} attached")
        capped = media_urls[:MAX_MEDIA_URLS]
        parts.append("\n".join(f"  - {u}" for u in capped))

    return "\n".join(parts).rstrip()


class XPostHandler:
    """Fetches X.com tweets via fxtwitter and LLM-analyzes the structured content."""

    async def analyze(self, row: dict[str, Any]) -> AnalysisResult:
        url = (row.get("url") or "").strip()
        m = X_URL_RE.match(url)
        if not m:
            return await self._embed_fallback(row, url, reason="not_an_x_url")

        screen_name, tweet_id = m.group(1), m.group(2)
        try:
            tweet = await _fetch_fxtwitter(screen_name, tweet_id)
        except Exception as exc:  # noqa: BLE001 — record + fall through
            logger.info("x_post_handler: fetch raised %s", exc)
            tweet = None

        if not tweet:
            return await self._embed_fallback(row, url, reason="fxtwitter_empty_or_failed")

        prompt = _build_prompt(url, tweet)
        resp = await call_text(prompt=prompt, system=X_POST_SYSTEM)
        summary, structured = _parse_json_reply(resp.reply)

        # Ensure source_kind is recorded even if the LLM omitted it.
        structured.setdefault("source_kind", "x_post")
        author = tweet.get("author") or {}
        if author.get("screen_name") and not structured.get("author"):
            structured["author"] = f"@{author['screen_name']}"

        return AnalysisResult(
            bookmark_id=str(row["message_id"]),
            artifact_type=ArtifactType.X_POST,
            summary=summary,
            structured=structured,
            model_used=resp.model,
            usage=resp.usage,
            cost_usd=resp.cost_usd,
        )

    async def _embed_fallback(
        self, row: dict[str, Any], url: str, *, reason: str
    ) -> AnalysisResult:
        """Last resort when fxtwitter fails — synthesize from Discord embed text.

        Mirrors the URL handler's JS-required path: hand the LLM whatever
        preview text Discord captured. If even that's missing, the prompt is
        URL-only and the post-LLM `_is_broken_extract` will route to P0.
        """
        embed_title = (row.get("embed_title") or "").strip()
        embed_desc = (row.get("embed_description") or "").strip()
        embed_block = "\n".join(p for p in (embed_title, embed_desc) if p)
        if embed_block:
            prompt = (
                f"URL: {url}\n\n"
                f"(fxtwitter unavailable — {reason}; using Discord embed preview)\n\n"
                f"Preview text:\n{embed_block}"
            )
        else:
            prompt = f"URL only (fxtwitter unavailable — {reason}; no embed text): {url}"
        resp = await call_text(prompt=prompt, system=X_POST_SYSTEM)
        summary, structured = _parse_json_reply(resp.reply)
        structured.setdefault("source_kind", "x_post")
        return AnalysisResult(
            bookmark_id=str(row["message_id"]),
            artifact_type=ArtifactType.X_POST,
            summary=summary,
            structured=structured,
            model_used=resp.model,
            usage=resp.usage,
            cost_usd=resp.cost_usd,
        )
