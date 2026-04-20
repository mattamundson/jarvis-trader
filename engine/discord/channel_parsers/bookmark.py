import logging
import re
from typing import List, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

JARVIS_TRADER_GENERAL_ID = "1490851279180660819"

URL_RE = re.compile(r"https?://\S+")

_SOURCE_TYPE_MAP = {
    "x.com": "x_post",
    "twitter.com": "x_post",
    "t.co": "x_post",
    "mobile.twitter.com": "x_post",
    "github.com": "github",
    "raw.githubusercontent.com": "github",
    "gist.github.com": "github",
    "youtube.com": "video",
    "youtu.be": "video",
    "m.youtube.com": "video",
}


def _normalize_domain(url: str) -> Optional[str]:
    try:
        netloc = urlparse(url).netloc.lower()
    except Exception:
        return None
    if not netloc:
        return None
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc


def _classify(domain: Optional[str]) -> str:
    if not domain:
        return "other"
    return _SOURCE_TYPE_MAP.get(domain, "other")


def parse_channel(messages: list, source_channel: str = "jarvis-trader-general") -> List[dict]:
    """
    Parse Matt's Jarvis-Trader #general bookmark dump.

    Rule: message qualifies as a bookmark iff `content` contains a URL. No author
    filter — the channel is private to Matt, so any URL posted there is signal.
    First URL in the content wins; additional URLs in the same message are ignored.
    """
    results = []
    skipped_no_url = 0

    for msg in messages:
        content = msg.get("content", "") or ""
        match = URL_RE.search(content)
        if not match:
            skipped_no_url += 1
            continue

        url = match.group(0).rstrip(").,;")
        domain = _normalize_domain(url)
        source_type = _classify(domain)

        embed_title: Optional[str] = None
        embed_description: Optional[str] = None
        embeds = msg.get("embeds") or []
        if embeds:
            first = embeds[0] or {}
            embed_title = (first.get("title") or "").strip() or None
            embed_description = (first.get("description") or "").strip() or None

        author = msg.get("author") or {}
        author_id = str(author.get("id")) if author.get("id") else None
        # Real DiscordChatExporter shape uses `username` + `global_name`;
        # fixtures/legacy callers use `name`. Prefer the display form.
        author_name = (
            (author.get("global_name") or "").strip()
            or (author.get("username") or "").strip()
            or (author.get("name") or "").strip()
            or None
        )

        result = {
            "message_id": str(msg.get("id", "")),
            "channel_id": JARVIS_TRADER_GENERAL_ID,
            "posted_at": msg.get("timestamp", ""),
            "url": url[:2000],
            "domain": domain,
            "source_type": source_type,
            "embed_title": embed_title[:500] if embed_title else None,
            "embed_description": embed_description[:5000] if embed_description else None,
            "content": content[:5000],
            "author_id": author_id,
            "author_name": author_name,
        }
        results.append(result)

    logger.info(
        f"bookmark: parsed {len(results)} bookmarks, skipped {skipped_no_url} no-url messages"
    )
    return results
