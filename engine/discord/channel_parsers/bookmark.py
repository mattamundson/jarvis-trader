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

    Rule: message qualifies for ingestion if EITHER (a) `content` contains a URL,
    OR (b) the message has Discord-uploaded attachments. URL-bearing messages
    are bookmarks (the URL is the primary signal). Attachment-only messages
    (images, voice memos, PDFs uploaded directly) are routed through
    deep_analyzer's image/audio/document handlers via the empty-url + populated-
    attachment_urls pattern (runner.py:_infer_artifact_type dispatches on
    attachment_urls extension when url is empty/falsy).
    """
    results = []
    skipped_no_signal = 0

    for msg in messages:
        content = msg.get("content", "") or ""
        match = URL_RE.search(content)

        # Discord-uploaded attachments. Each DiscordChatExporter entry has
        # `url` + `fileName` + `fileSizeBytes`. We concatenate URLs with spaces
        # for storage; deep_analyzer.handlers._split_urls accepts space- or
        # comma-separated.
        attachments = msg.get("attachments") or []
        attachment_urls_list = [
            a.get("url") for a in attachments if isinstance(a, dict) and a.get("url")
        ]
        attachment_urls = " ".join(attachment_urls_list)[:4000] if attachment_urls_list else None

        # Skip messages with neither a URL nor an attachment — pure text or
        # emoji-only replies are noise for this channel.
        if not match and not attachment_urls:
            skipped_no_signal += 1
            continue

        if match:
            url = match.group(0).rstrip(").,;")
            domain = _normalize_domain(url)
            source_type = _classify(domain)
        else:
            # Attachment-only message. Empty url is a sentinel for runner.py
            # dispatch to route by attachment extension; schema requires url
            # NOT NULL but empty string satisfies that.
            url = ""
            domain = None
            source_type = "attachment_only"

        embed_title: Optional[str] = None
        embed_description: Optional[str] = None
        embeds = msg.get("embeds") or []
        if embeds:
            first = embeds[0] or {}
            embed_title = (first.get("title") or "").strip() or None
            embed_description = (first.get("description") or "").strip() or None

        # For attachment-only messages, fall back to the first attachment's
        # fileName as the embed_title (so vault page slugs are recognizable).
        if not embed_title and source_type == "attachment_only" and attachments:
            first_attach = attachments[0] or {}
            file_name = (first_attach.get("fileName") or "").strip()
            if file_name:
                embed_title = file_name

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
            "attachment_urls": attachment_urls,
        }
        results.append(result)

    logger.info(
        f"bookmark: parsed {len(results)} bookmarks, skipped {skipped_no_signal} no-signal messages"
    )
    return results
