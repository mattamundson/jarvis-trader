"""
JARVIS TRADER — Bookmark thematic clusterer
============================================

Consumer for the Phase B `discord_bookmarks` pipeline (2026-04-20).

Queries the Jarvis-Trader #general bookmark dump over a rolling window,
sends the batch to Claude, and returns structured thematic clusters
suitable for the morning brief or dashboard consumption.

Design choices
--------------
* **Model default = Haiku.** Thematic clustering of ~100-300 short text
  records does not need frontier reasoning. Haiku is ~15× cheaper per
  weekly run (~$0.01-0.03 vs ~$0.30 with Sonnet).
* **Structured JSON output.** Strict format in the system prompt; parsed
  with `json.loads` in a try/except with graceful fallback.
* **In-memory TTL cache.** A single cached result per lookback window for
  6 hours — dashboard reloads and morning-brief regeneration don't each
  burn an API call.
* **Graceful degradation.** If the LLM client can't initialize, or the
  API call fails, or the response doesn't parse, return
  `ClusterResult(themes=[], error=<reason>)`. Callers never raise.

Integration points (not yet wired — this is v1 standalone)
-----------------------------------------------------------
* Scheduler: weekly Sunday 18:00 CT via APScheduler in `engine/main.py`
* Morning brief: add a section via `engine/notifications/morning_brief.py`
* Dashboard: expose via a new `/bookmarks/weekly-themes` endpoint

Future tuning
-------------
* If 200+ bookmarks/week becomes common, split into two passes:
  extract-then-cluster, instead of one monolithic prompt.
* Add a per-theme "actionable" flag — clusters referencing specific
  tickers/levels get flagged for WhatsApp promotion.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional

logger = logging.getLogger(__name__)

# Sentinel for BookmarkClusterer.__init__ to distinguish "no argument"
# (autoload JarvisLLMClient) from explicit `llm_client=None` (disable).
_DEFAULT_LLM: Any = object()


# ── Models ────────────────────────────────────────────────────────────────────


@dataclass
class Theme:
    """A single thematic cluster extracted from a batch of bookmarks."""

    name: str  # short label, e.g. "MES gamma positioning"
    description: str  # 1-sentence summary of what ties the cluster together
    count: int  # number of bookmarks in this cluster
    urls: List[str] = field(default_factory=list)  # supporting bookmark URLs
    confidence: float = 0.0  # 0.0-1.0 self-rated by the model


@dataclass
class ClusterResult:
    """Result of one clustering run. Never raises — errors go into `error`."""

    themes: List[Theme] = field(default_factory=list)
    bookmark_count: int = 0  # how many bookmarks went into the prompt
    lookback_days: int = 7
    model: str = ""
    latency_ms: int = 0
    cost_usd: float = 0.0
    cached: bool = False
    error: Optional[str] = None

    @property
    def actionable(self) -> bool:
        """True if we got at least one theme with conviction ≥ 0.5."""
        return any(t.confidence >= 0.5 for t in self.themes)

    def to_dict(self) -> dict:
        return {
            "themes": [
                {
                    "name": t.name,
                    "description": t.description,
                    "count": t.count,
                    "urls": t.urls,
                    "confidence": t.confidence,
                }
                for t in self.themes
            ],
            "bookmark_count": self.bookmark_count,
            "lookback_days": self.lookback_days,
            "model": self.model,
            "latency_ms": self.latency_ms,
            "cost_usd": round(self.cost_usd, 4),
            "cached": self.cached,
            "actionable": self.actionable,
            "error": self.error,
        }


# ── DB helpers ────────────────────────────────────────────────────────────────


DEFAULT_DB_PATH = str(Path(__file__).resolve().parents[1] / "data" / "jarvis_trader.db")


def fetch_recent_bookmarks(
    lookback_days: int = 7,
    db_path: str = DEFAULT_DB_PATH,
    max_rows: int = 200,
) -> List[dict]:
    """Pull up to `max_rows` bookmarks newer than `lookback_days`, most-recent first."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            """
            SELECT url, domain, source_type, embed_title, embed_description, posted_at
              FROM discord_bookmarks
             WHERE posted_at >= datetime('now', ?)
             ORDER BY posted_at DESC
             LIMIT ?
            """,
            (f"-{lookback_days} days", max_rows),
        ).fetchall()
    finally:
        conn.close()
    return [
        {
            "url": r[0],
            "domain": r[1],
            "source_type": r[2],
            "embed_title": r[3],
            "embed_description": r[4],
            "posted_at": r[5],
        }
        for r in rows
    ]


# ── Clusterer ─────────────────────────────────────────────────────────────────


SYSTEM_PROMPT = """You are a trading research analyst clustering a week's worth of links a quant trader saved from his Twitter/X feed, GitHub browsing, and trading research.

Your job: identify 3-7 dominant THEMES across the bookmark set. For each theme, give:
  - `name`: short label, 2-6 words (e.g. "MES gamma positioning", "AI coding agents")
  - `description`: ONE sentence explaining what ties these bookmarks together
  - `indices`: the 1-based indices from the bookmark list that belong to this theme (at least 2)
  - `confidence`: 0.0-1.0 — how clearly these bookmarks cluster together

Guidelines:
  - Prefer TRADING-RELEVANT themes (market structure, indicators, positioning, specific tickers) over generic tech themes when the bookmarks support them.
  - A bookmark may appear in AT MOST ONE theme — pick the strongest fit.
  - Ignore single-bookmark themes — a theme needs ≥2 supporting bookmarks.
  - If bookmarks don't cluster cleanly into ≥3 themes, return fewer themes rather than forcing weak clusters.
  - Confidence ≥ 0.7 = tight thematic match; 0.4-0.7 = loose; < 0.4 = don't bother emitting it.
  - DO NOT echo back full URLs — reference bookmarks only by their 1-based index to stay within the output budget.

Output ONLY a JSON object, nothing else. Schema:
{
  "themes": [
    {
      "name": "...",
      "description": "...",
      "indices": [1, 2, 5],
      "confidence": 0.0
    }
  ]
}
"""


def _format_bookmarks_for_prompt(bookmarks: List[dict]) -> str:
    lines = []
    for i, b in enumerate(bookmarks, 1):
        desc = (b.get("embed_description") or "").strip().replace("\n", " ")
        if len(desc) > 280:
            desc = desc[:277] + "..."
        title = (b.get("embed_title") or "").strip()
        line = f"{i}. [{b.get('source_type', 'other')}] {b['url']}"
        if title:
            line += f"\n   title: {title}"
        if desc:
            line += f"\n   blurb: {desc}"
        lines.append(line)
    return "\n".join(lines)


_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


def parse_cluster_response(
    content: str,
    bookmarks: Optional[List[dict]] = None,
) -> List[Theme]:
    """Parse the LLM's JSON output into Theme list. Never raises.

    If the model emits `indices` (1-based positions in `bookmarks`), they
    are resolved to URLs. Falls back to `urls` when the model emits those
    directly (legacy path, still tolerated).
    """
    if not content or not content.strip():
        return []
    # Best-effort extraction — model may emit prose around the JSON despite the prompt
    match = _JSON_BLOCK_RE.search(content)
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    themes_raw = data.get("themes") if isinstance(data, dict) else None
    if not isinstance(themes_raw, list):
        return []
    themes: List[Theme] = []
    for t in themes_raw:
        if not isinstance(t, dict):
            continue
        urls = _resolve_urls(t, bookmarks)
        if len(urls) < 2:
            continue  # enforce "≥2 supporting bookmarks"
        try:
            conf = float(t.get("confidence", 0) or 0)
        except (TypeError, ValueError):
            conf = 0.0
        name = str(t.get("name") or "").strip()
        if not name:
            continue
        themes.append(
            Theme(
                name=name,
                description=str(t.get("description") or "").strip(),
                count=len(urls),
                urls=urls,
                confidence=max(0.0, min(1.0, conf)),
            )
        )
    return themes


def _resolve_urls(theme: dict, bookmarks: Optional[List[dict]]) -> List[str]:
    """Resolve a theme's URL list, preferring `indices` (compact) over `urls`."""
    indices = theme.get("indices")
    if isinstance(indices, list) and bookmarks is not None:
        urls: List[str] = []
        for idx in indices:
            try:
                i = int(idx)
            except (TypeError, ValueError):
                continue
            if 1 <= i <= len(bookmarks):
                u = bookmarks[i - 1].get("url")
                if u:
                    urls.append(str(u))
        if urls:
            return urls
    raw_urls = theme.get("urls")
    if isinstance(raw_urls, list):
        return [str(u) for u in raw_urls if u]
    return []


class BookmarkClusterer:
    """Consult Claude to cluster recent bookmarks thematically.

    Usage:
        clusterer = BookmarkClusterer()  # lazy-loads JarvisLLMClient
        result = await clusterer.cluster_recent(lookback_days=7)
        for theme in result.themes:
            print(f"{theme.name}: {theme.count} bookmarks (conf {theme.confidence:.2f})")
    """

    MODEL_HAIKU = "claude-haiku-4-5-20251001"
    MODEL_SONNET = "claude-sonnet-4-6"
    MAX_TOKENS = 4096  # indices are cheap; 4K is plenty for 7 themes × ~30 indices each
    TEMPERATURE = 0.3  # low temp — we want stable thematic extraction, not creativity
    CACHE_TTL_SEC = 6 * 3600  # 6 hours

    def __init__(self, llm_client: Any = _DEFAULT_LLM, model: Optional[str] = None):
        # sentinel lets callers pass `None` to explicitly disable the LLM
        # (distinct from "no argument = autoload default")
        if llm_client is _DEFAULT_LLM:
            self.llm = self._try_construct_llm()
        else:
            self.llm = llm_client
        self.model = model or self.MODEL_HAIKU
        # {(lookback_days, max_rows): (expires_at_epoch, ClusterResult)}
        self._cache: dict[tuple[int, int], tuple[float, ClusterResult]] = {}

    @staticmethod
    def _try_construct_llm() -> Optional[Any]:
        """Construct JarvisLLMClient if possible; return None on any failure."""
        try:
            try:
                from llm.client import JarvisLLMClient  # type: ignore
            except ImportError:
                from engine.llm.client import JarvisLLMClient  # type: ignore
        except Exception as e:
            logger.warning("BookmarkClusterer: JarvisLLMClient not importable (%s)", e)
            return None
        api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if not api_key:
            logger.warning("BookmarkClusterer: ANTHROPIC_API_KEY not set; disabled")
            return None
        try:
            return JarvisLLMClient(api_key=api_key)
        except Exception as e:
            logger.warning("BookmarkClusterer: JarvisLLMClient init failed (%s)", e)
            return None

    async def cluster_recent(
        self,
        lookback_days: int = 7,
        max_rows: int = 200,
        db_path: str = DEFAULT_DB_PATH,
        force_refresh: bool = False,
    ) -> ClusterResult:
        """Cluster recent bookmarks into themes.

        Returns a `ClusterResult`. Caches for 6h per (lookback_days, max_rows).
        """
        cache_key = (lookback_days, max_rows)

        if not force_refresh:
            cached = self._cache.get(cache_key)
            if cached and cached[0] > time.time():
                hit = cached[1]
                # Shallow-copy with cached=True so callers know
                return ClusterResult(
                    themes=list(hit.themes),
                    bookmark_count=hit.bookmark_count,
                    lookback_days=hit.lookback_days,
                    model=hit.model,
                    latency_ms=hit.latency_ms,
                    cost_usd=hit.cost_usd,
                    cached=True,
                    error=hit.error,
                )

        if self.llm is None:
            return ClusterResult(
                lookback_days=lookback_days,
                error="llm client unavailable",
            )

        try:
            bookmarks = fetch_recent_bookmarks(lookback_days, db_path, max_rows)
        except sqlite3.OperationalError as e:
            return ClusterResult(
                lookback_days=lookback_days,
                error=f"db error: {e}",
            )

        if len(bookmarks) < 4:
            return ClusterResult(
                bookmark_count=len(bookmarks),
                lookback_days=lookback_days,
                error=f"insufficient bookmarks for clustering ({len(bookmarks)})",
            )

        user_prompt = (
            f"Here are {len(bookmarks)} bookmarks from the last {lookback_days} days "
            f"(most recent first). Cluster them.\n\n"
            + _format_bookmarks_for_prompt(bookmarks)
        )

        try:
            result = await self.llm.call(
                model=self.model,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
                max_tokens=self.MAX_TOKENS,
                temperature=self.TEMPERATURE,
                agent_name="bookmark_clusterer",
                tier="fast",
            )
        except Exception as e:
            logger.warning("BookmarkClusterer.cluster_recent: llm.call raised: %s", e)
            return ClusterResult(
                bookmark_count=len(bookmarks),
                lookback_days=lookback_days,
                error=f"llm error: {e}",
            )

        if not getattr(result, "success", False):
            return ClusterResult(
                bookmark_count=len(bookmarks),
                lookback_days=lookback_days,
                model=getattr(result, "model", self.model),
                error=f"llm call failed: {getattr(result, 'error', 'unknown')}",
            )

        themes = parse_cluster_response(result.content, bookmarks=bookmarks)
        out = ClusterResult(
            themes=themes,
            bookmark_count=len(bookmarks),
            lookback_days=lookback_days,
            model=result.model,
            latency_ms=result.latency_ms,
            cost_usd=result.cost_usd,
        )
        self._cache[cache_key] = (time.time() + self.CACHE_TTL_SEC, out)
        return out


# ── CLI entry (for ad-hoc runs / testing) ────────────────────────────────────


async def _cli_main(lookback_days: int = 7, max_rows: int = 200, use_sonnet: bool = False) -> int:
    clusterer = BookmarkClusterer(
        model=BookmarkClusterer.MODEL_SONNET if use_sonnet else BookmarkClusterer.MODEL_HAIKU
    )
    result = await clusterer.cluster_recent(lookback_days=lookback_days, max_rows=max_rows)
    print(json.dumps(result.to_dict(), indent=2))
    return 0 if not result.error else 1


if __name__ == "__main__":
    import sys

    days = int(sys.argv[1]) if len(sys.argv) > 1 else 7
    use_sonnet = "--sonnet" in sys.argv
    sys.exit(asyncio.run(_cli_main(lookback_days=days, use_sonnet=use_sonnet)))
