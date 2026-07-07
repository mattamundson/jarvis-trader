"""Shared core for curated-knowledge retrieval (gbrain daemon /search + rerank).

One code path behind BOTH the `search_knowledge` MCP tool and the enriched
Discord briefing, so the relevance floor and rerank behavior never diverge
between the two callers. The MCP tool is a thin `@mcp.tool()` wrapper around
`search_knowledge_core`; the briefing calls the core directly.

The curated KNOWLEDGE brain (concepts, strategy/setup notes, X-bookmark tool
cards, synthesis pages) lives in a pglite/pgvector store embedded with
voyage-finance-2 (1024-dim), served by the single-writer gbrain daemon. We
never open that store here — we POST text to its /search, which embeds
server-side and runs hybrid keyword+vector retrieval against its one
connection (no Voyage key ever leaves the daemon).

Relative import of `.reranker` is deliberate: the engine loads this package as
both `discord.knowledge` (engine/ on sys.path — the briefing context) and
`engine.discord.knowledge` (repo root on sys.path — the MCP subprocess), and a
relative import resolves correctly under either __package__.
"""

from __future__ import annotations

import logging
import os

import aiohttp

logger = logging.getLogger(__name__)

# Single-writer gbrain daemon (owns the one pglite connection). Override via env.
GBRAIN_DAEMON_URL = os.environ.get("GBRAIN_DAEMON_URL", "http://127.0.0.1:8077")


async def search_knowledge_core(
    query: str,
    limit: int = 8,
    min_score: float = 0.2,
) -> dict:
    """Retrieve curated knowledge for `query` from the gbrain daemon, reranked.

    Asks the daemon for an over-fetched candidate pool (server-side Voyage embed
    + hybrid retrieval), then reorders with the shared cross-encoder rerank and
    applies the `min_score` relevance floor so weak vocabulary-only matches
    (e.g. archive/handoff pages) don't pad the result set.

    Returns a dict:
        {query, source, rerank, results:[{slug, similarity, type, title, content}]}
    on success, or {query, results: [], error: ...} when the daemon is
    unreachable / errors / returns no hits. Never raises — callers (the MCP
    tool and the briefing) treat retrieval as advisory and must degrade safely.
    """
    from .reranker import overfetch_k, rerank

    limit = min(max(1, limit), 20)
    fetch_k = overfetch_k(limit)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{GBRAIN_DAEMON_URL}/search",
                json={"query": query, "opts": {"limit": fetch_k}},
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status != 200:
                    return {
                        "query": query,
                        "results": [],
                        "error": f"brain daemon /search HTTP {resp.status}",
                    }
                payload = await resp.json()
    except Exception as exc:
        return {
            "query": query,
            "results": [],
            "error": f"brain daemon unreachable at {GBRAIN_DAEMON_URL}: {exc}",
        }

    hits = payload.get("results", []) or []
    if not hits:
        return {"query": query, "results": [], "rerank": "off"}

    # Carry FULL content into reranking (cross-encoder quality depends on the
    # whole document); truncate to a preview only on the way out.
    candidates = [
        {
            "slug": h.get("slug", ""),
            "similarity": round(float(h.get("score", 0.0)), 4),
            "type": h.get("type") or h.get("chunk_source") or "",
            "title": h.get("title", ""),
            "_full_content": h.get("chunk_text") or h.get("content") or "",
        }
        for h in hits
    ]

    ranked, rerank_tier = await rerank(
        query, candidates, top_n=limit, text_key="_full_content", min_score=min_score
    )

    results = []
    for cand in ranked:
        full = cand.pop("_full_content", "")
        cand["content"] = full[:400]
        results.append(cand)

    return {
        "query": query,
        "source": "gbrain-knowledge (voyage-finance-2/1024)",
        "rerank": rerank_tier,
        "results": results,
    }
