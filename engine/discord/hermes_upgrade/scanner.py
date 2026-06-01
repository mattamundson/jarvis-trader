"""Scans discord_analyses for Hermes-applicable candidates via heuristics.

Pre-LLM signal: a cheap, deterministic interest score over each analyzed
bookmark. Surfaces a candidate set for downstream LLM classification.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from pathlib import Path

from .models import Candidate

logger = logging.getLogger(__name__)

# Channel scope: Amo's #general bookmark channel
TARGET_CHANNEL = "1490851279180660819"

# Topic vocabulary that suggests Hermes applicability. Comparison is
# lowercase, exact-match against tokens that appear in `structured_json.topics`.
HERMES_TOPICS = frozenset(
    {
        "agent",
        "agents",
        "hermes",
        "mcp",
        "mcp-server",
        "cron",
        "skill",
        "skills",
        "memory",
        "rag",
        "tool",
        "tools",
        "llm",
        "claude-code",
        "opensource",
        "automation",
        "gepa",
        "kanban",
        "prompt",
        "prompts",
        "cli",
        "workflow",
        "integration",
        "model",
        "self-improving",
        "fine-tuning",
        "embedding",
        "embeddings",
        "ollama",
        "openrouter",
        "anthropic",
        "openai",
        "gemini",
        "local-model",
        "local-llm",
        "langchain",
        "llamaindex",
        "browser-use",
        "playwright",
        "cdp",
        "scraping",
        "ingest",
        "vault",
        "obsidian",
        "second-brain",
        "gbrain",
        "whisper",
        "vision",
        "ocr",
        "pdf",
        "sentiment",
        "analysis",
        "telegram",
        "discord",
        "slack",
        "whatsapp",
        "imessage",
        "webhook",
        "api",
        "bot",
        "voice",
        "voice-mode",
        "speech",
        "tts",
        "stt",
    }
)

KEYWORDS_RE = re.compile(
    r"(?i)\b(hermes|mcp\s*server|nous\s*research|claude\s*code|gepa|skill|cron|"
    r"agent|self.improving|autonomous|browser.use|playwright|cdp|"
    r"langchain|llamaindex|fine.tun|embedding|rag|ollama|openrouter|"
    r"local.llm|self.host|telegram|whatsapp|imessage|webhook|memory|"
    r"prompt.engineering|fine.grained|persona|soul)\b"
)


def score_candidate(
    topics: list[str],
    summary: str,
    has_action_item: bool,
    source_kind: str,
) -> float:
    """Heuristic 0.0-1.0 - higher = more likely Hermes-applicable.

    Composition (capped at 1.0):
        - topic_hits * 0.15 (capped 0.6)
        - +0.15 if has_action_item
        - +0.10 if source_kind in (x_post, github)
        - keyword_hits * 0.05 (capped 0.30)
    """
    score = 0.0
    topic_hits = sum(1 for t in topics if isinstance(t, str) and t.lower() in HERMES_TOPICS)
    score += min(topic_hits * 0.15, 0.6)
    if has_action_item:
        score += 0.15
    if source_kind in ("x_post", "github"):
        score += 0.10
    kw_hits = len(KEYWORDS_RE.findall(summary or ""))
    score += min(kw_hits * 0.05, 0.30)
    return min(score, 1.0)


def _parse_structured(raw: str | None) -> tuple[list[str], bool, str]:
    """Defensively parse structured_json -> (topics, has_action_item, source_kind)."""
    if not raw:
        return ([], False, "url")
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return ([], False, "url")
    if not isinstance(data, dict):
        return ([], False, "url")
    topics_raw = data.get("topics") or []
    topics: list[str] = (
        [t for t in topics_raw if isinstance(t, str)] if isinstance(topics_raw, list) else []
    )
    has_action_item = bool(data.get("has_action_item", False))
    source_kind = data.get("source_kind") or "url"
    if not isinstance(source_kind, str):
        source_kind = "url"
    return (topics, has_action_item, source_kind)


def scan_for_candidates(
    db_path: str | Path,
    *,
    channel_id: str = TARGET_CHANNEL,
    min_score: float = 0.25,
    limit: int | None = None,
) -> list[Candidate]:
    """Sweep discord_analyses. Return ranked candidates above min_score.

    READ-ONLY query against the discord_bookmarks JOIN discord_analyses view.
    Returns sorted (score desc) list, optionally truncated to `limit`.
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT b.message_id AS message_id,
                   b.posted_at AS posted_at,
                   b.url AS url,
                   a.id AS analysis_id,
                   a.summary AS summary,
                   a.structured_json AS structured_json,
                   a.artifact_type AS artifact_type
            FROM discord_bookmarks b
            JOIN discord_analyses a ON a.id = b.analysis_id
            WHERE b.channel_id = ?
              AND a.summary IS NOT NULL
              AND a.summary != ''
            """,
            (channel_id,),
        ).fetchall()
    finally:
        conn.close()

    candidates: list[Candidate] = []
    for row in rows:
        topics, has_action_item, source_kind = _parse_structured(row["structured_json"])
        summary = row["summary"] or ""
        score = score_candidate(topics, summary, has_action_item, source_kind)
        if score < min_score:
            continue
        candidates.append(
            Candidate(
                bookmark_id=row["message_id"],
                analysis_id=int(row["analysis_id"]),
                url=row["url"] or "",
                summary=summary,
                structured_json=row["structured_json"] or "",
                topics=topics,
                has_action_item=has_action_item,
                source_kind=source_kind,
                artifact_type=row["artifact_type"] or "url",
                posted_at=row["posted_at"],
                score=score,
            )
        )

    candidates.sort(key=lambda c: c.score, reverse=True)
    if limit is not None:
        candidates = candidates[:limit]
    logger.info(
        "hermes_upgrade.scanner: %d candidates >= %.2f (channel=%s)",
        len(candidates),
        min_score,
        channel_id,
    )
    return candidates
