"""
Discord Intelligence MCP Server — READ-ONLY

Wraps Discord intelligence queries so Claude Code sessions can ask:
  "What did Corey say about MES today?"
  "Show me recent ES signals from the last 4 hours"

Tools (all read-only, no DB writes):
  get_session_bias       — Corey's structured session bias for a trading date
  get_recent_signals     — Recent Discord bot signals for a symbol
  get_daily_sentiment    — Keyword-based daily sentiment score
  search_commentary      — Full-text (FTS5/LIKE) search Corey's raw commentary
  semantic_search        — KNN vector search via nomic-embed-text embeddings
  get_recent_bookmarks   — Recent URLs dropped into Matt's #general bookmark channel
  search_bookmarks       — Full-text search bookmark URL / title / description / content
  get_bookmark_stats     — Counts by source_type + domain for the bookmark feed
  get_engine_health      — Engine health, IBKR status, kill switch, uptime
  get_open_positions     — Open IBKR positions with PnL

Run as MCP server:
  python -m discord.mcp_server
  python engine/discord/mcp_server.py
"""

from __future__ import annotations

import logging
import os
import sqlite3
import sys
from datetime import date as date_type
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiohttp

# When invoked as a script (per ~/.claude.json mcpServers config), Python adds
# only this file's directory to sys.path — so `from discord.commentary_processor`
# fails to find `engine.discord` as a package. Add `engine/` (parent of this
# file's parent) to sys.path so sibling-package imports resolve.
# Observed 2026-05-06: `get_session_bias` raised "No module named 'discord'"
# while `get_recent_signals` worked (it doesn't import discord.* siblings).
_ENGINE_ROOT = str(Path(__file__).resolve().parent.parent)
if _ENGINE_ROOT not in sys.path:
    sys.path.insert(0, _ENGINE_ROOT)

# Load engine/.env so ANTHROPIC_API_KEY is available regardless of the parent
# process env. Without this, the MCP server inherits whatever env Claude Code
# was launched with — and on 2026-05-19 that meant the processor's
# get_session_bias call silently fell through to the empty-key neutral branch
# while the engine itself (which loads .env via uvicorn startup) extracted
# correctly. Loading here keeps the MCP server's env aligned with the engine.
try:
    from dotenv import load_dotenv  # type: ignore  # noqa: E402

    _ENV_PATH = Path(_ENGINE_ROOT) / ".env"
    if _ENV_PATH.exists():
        load_dotenv(_ENV_PATH)
except ImportError:
    pass

from mcp.server.fastmcp import FastMCP  # noqa: E402

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _default_db_path() -> str:
    """engine/data/jarvis_trader.db — anchored at engine/ root."""
    engine_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(engine_root, "data", "jarvis_trader.db")


def _parse_date(s: str) -> date_type:
    """Parse ISO date string; default to today if empty."""
    return date_type.fromisoformat(s) if s else date_type.today()


# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------

mcp = FastMCP("discord-intelligence")

# Engine API — read from env (loaded above from engine/.env).
# engine/.env uses API_KEY; Hermes .env uses ENGINE_API_KEY — accept both.
# Prioritise API_KEY (loaded from engine/.env dotenv) as the ground truth;
# ENGINE_API_KEY is the fallback for callers whose env doesn't include engine/.env.
_ENGINE_URL = os.environ.get("ENGINE_URL", "http://127.0.0.1:8010")
_ENGINE_API_KEY = os.environ.get("API_KEY") or os.environ.get("ENGINE_API_KEY", "")


@mcp.tool()
async def get_session_bias(date: str = "") -> dict:
    """
    Get Corey's structured session bias for a trading date.

    Args:
        date: ISO date string YYYY-MM-DD. Defaults to today.

    Returns dict with: date, session_type, directional_bias, key_levels,
        ib_bias, specific_triggers, conviction, corey_quote,
        message_count, data_quality
    """
    from discord.commentary_processor import (  # noqa: PLC0415
        CoreyCommentaryProcessor,
        build_default_llm_client,
    )

    parsed = _parse_date(date)
    # Route extraction through the engine's Vertex/Gemini/OpenAI failover client
    # rather than the raw direct-Anthropic POST. engine/.env is already loaded at
    # module import (see top of file), so the failover config is present.
    # (2026-06-29: the direct-Anthropic account's credit ran dry and every MCP
    # session-bias read silently degraded to data_quality='none'.)
    processor = CoreyCommentaryProcessor(llm_client=build_default_llm_client())
    bias = await processor.get_session_bias(parsed)
    return bias.to_dict()


@mcp.tool()
async def get_recent_signals(symbol: str, hours: int = 4) -> list[dict]:
    """
    Get recent Discord bot signals for a symbol.

    Args:
        symbol: Trading symbol (ES, CL, NQ, GC, etc.)
        hours: Lookback window in hours (default 4)

    Returns list of signal dicts with: symbol, direction, signal_type,
        entry_price, target1, target2, stop1, win_rate, timestamp
    """
    sym = symbol.upper()
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    db_path = _default_db_path()

    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT symbol, direction, signal_type, entry_price,
                       target1, target2, stop1, win_rate, timestamp
                FROM discord_bot_signals
                WHERE symbol = ? AND timestamp >= ?
                ORDER BY timestamp DESC
                LIMIT 10
                """,
                (sym, cutoff),
            ).fetchall()
        return [dict(row) for row in rows]
    except Exception as exc:
        logger.warning("[get_recent_signals] DB error for %s: %s", symbol, exc)
        return []


@mcp.tool()
async def get_daily_sentiment(date: str = "") -> dict:
    """
    Get keyword-based daily sentiment score from Corey's commentary.

    Args:
        date: ISO date YYYY-MM-DD. Defaults to today.

    Returns dict with: date, sentiment_score (-1.0 to +1.0),
        regime_multiplier, interpretation (bullish/bearish/neutral)
    """
    from discord.sentiment_provider import SentimentProvider  # noqa: PLC0415

    parsed = _parse_date(date)
    provider = SentimentProvider()
    score = provider.get_sentiment(parsed)
    multiplier = provider.get_regime_multiplier(parsed)

    if score > 0.2:
        interpretation = "bullish"
    elif score < -0.2:
        interpretation = "bearish"
    else:
        interpretation = "neutral"

    return {
        "date": parsed.isoformat(),
        "sentiment_score": score,
        "regime_multiplier": multiplier,
        "interpretation": interpretation,
    }


@mcp.tool()
async def search_commentary(query: str, days: int = 7) -> list[dict]:
    """
    Full-text search Corey's raw commentary for a keyword or phrase.

    Args:
        query: Search string (case-insensitive)
        days: How many days back to search (default 7)

    Returns list of matching messages: timestamp, content, channel
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    db_path = _default_db_path()

    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            try:
                # FTS5 MATCH is 10–100× faster than LIKE on 280K+ rows.
                # Falls back to LIKE if the FTS table doesn't exist yet or
                # if the query contains FTS5 syntax that doesn't parse.
                rows = conn.execute(
                    """
                    SELECT c.timestamp, c.content, c.channel
                    FROM discord_corey_commentary c
                    JOIN discord_commentary_fts fts ON fts.rowid = c.id
                    WHERE discord_commentary_fts MATCH ?
                      AND c.timestamp >= ?
                    ORDER BY c.timestamp DESC
                    LIMIT 20
                    """,
                    (query, cutoff),
                ).fetchall()
            except sqlite3.OperationalError as exc:
                # FTS5 unavailable (table missing) or query syntax error;
                # fall back to LIKE search. Log so silent FTS corruption is
                # visible (vs. the prior bare-except that hid all errors).
                logger.warning(
                    "[search_commentary] FTS5 fallback to LIKE for %r: %s",
                    query,
                    exc,
                )
                rows = conn.execute(
                    """
                    SELECT timestamp, content, channel
                    FROM discord_corey_commentary
                    WHERE content LIKE ? AND timestamp >= ?
                    ORDER BY timestamp DESC
                    LIMIT 20
                    """,
                    (f"%{query}%", cutoff),
                ).fetchall()
        return [dict(row) for row in rows]
    except Exception as exc:
        logger.warning("[search_commentary] DB error for %r: %s", query, exc)
        return []


# ---------------------------------------------------------------------------
# Bookmark tools — Matt's personal #general dump (channel 1490851279180660819)
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_recent_bookmarks(
    hours: int = 168,
    source_type: str = "",
    domain: str = "",
    before: str = "",
    limit: int = 100,
) -> dict:
    """
    Get recent bookmarks from Matt's jarvis-trader #general channel.

    Args:
        hours: Lookback window in hours (default 168 = 7 days).
        source_type: Optional filter — "x_post", "github", "video", "other".
        domain: Optional substring filter on domain (e.g. "x.com", "github.com").
        before: ISO timestamp — return bookmarks strictly older than this. Use
            the previous response's `next_before` value to walk the full corpus.
            Empty string = start from newest.
        limit: Page size, default 100, hard-capped at 200.

    Returns dict:
        {
            "bookmarks": [ {posted_at, url, domain, source_type, embed_title,
                            embed_description, content, author_name}, ... ],
            "next_before": "<ISO timestamp>" or None,   # feed back as `before`
            "has_more": bool,
            "page_size": int,
        }

    Note: response shape changed from `list[dict]` to `dict` to carry pagination
    metadata. Old callers reading the result as a list will break; update them
    to read `result["bookmarks"]`.
    """
    # Clamp limit defensively — keep MCP payload bounded.
    page_size = max(1, min(int(limit), 200))

    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    db_path = _default_db_path()

    clauses = ["posted_at >= ?"]
    params: list = [cutoff]
    if source_type:
        clauses.append("source_type = ?")
        params.append(source_type)
    if domain:
        clauses.append("domain LIKE ?")
        params.append(f"%{domain}%")
    if before:
        # Strict `<` so the previous page's last row is not duplicated on the
        # next page. Caller passes `next_before` from the previous response.
        clauses.append("posted_at < ?")
        params.append(before)
    where = " AND ".join(clauses)

    # Fetch one extra row to detect has_more without a second COUNT query.
    fetch_n = page_size + 1
    params_with_limit = [*params, fetch_n]

    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"""
                SELECT posted_at, url, domain, source_type, embed_title,
                       embed_description, content, author_name
                FROM discord_bookmarks
                WHERE {where}
                ORDER BY posted_at DESC
                LIMIT ?
                """,
                params_with_limit,
            ).fetchall()
    except Exception as exc:
        logger.warning("[get_recent_bookmarks] DB error: %s", exc)
        return {
            "bookmarks": [],
            "next_before": None,
            "has_more": False,
            "page_size": page_size,
        }

    has_more = len(rows) > page_size
    page_rows = rows[:page_size]
    next_before = page_rows[-1]["posted_at"] if (has_more and page_rows) else None

    return {
        "bookmarks": [dict(row) for row in page_rows],
        "next_before": next_before,
        "has_more": has_more,
        "page_size": page_size,
    }


@mcp.tool()
async def search_bookmarks(
    query: str,
    days: int = 30,
    source_type: str = "",
) -> list[dict]:
    """
    Full-text search the bookmark feed across URL, embed title, embed
    description, and message content.

    Args:
        query: Search string (case-insensitive)
        days: How many days back to search (default 30)
        source_type: Optional filter — "x_post", "github", "video", "other"

    Returns list of bookmark dicts with: posted_at, url, domain, source_type,
        embed_title, embed_description, content
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    db_path = _default_db_path()
    like = f"%{query}%"

    clauses = [
        "posted_at >= ?",
        "(url LIKE ? OR embed_title LIKE ? OR embed_description LIKE ? OR content LIKE ?)",
    ]
    params: list = [cutoff, like, like, like, like]
    if source_type:
        clauses.append("source_type = ?")
        params.append(source_type)
    where = " AND ".join(clauses)

    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"""
                SELECT posted_at, url, domain, source_type, embed_title,
                       embed_description, content
                FROM discord_bookmarks
                WHERE {where}
                ORDER BY posted_at DESC
                LIMIT 30
                """,
                params,
            ).fetchall()
        return [dict(row) for row in rows]
    except Exception as exc:
        logger.warning("[search_bookmarks] DB error for %r: %s", query, exc)
        return []


@mcp.tool()
async def get_tweet_by_url(url: str) -> dict:
    """
    Look up a stored X/Twitter post by URL from the discord_bookmarks table.

    Use this instead of WebFetch for x.com URLs — WebFetch cannot access X.com
    but the nightly DiscordChatExporter pipeline stores tweet content in the
    local database.

    Args:
        url: The full x.com/twitter.com URL (e.g. https://x.com/KoroushAK/status/...)

    Returns dict with:
        found: bool
        url: str
        embed_title: str
        embed_description: str (tweet body if stored)
        content: str (Discord message context)
        posted_at: str (ISO timestamp)
    If not found, returns {found: false, url: url, message: "not in bookmarks"}.
    """
    db_path = _default_db_path()
    normalized = url.replace("twitter.com", "x.com")
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT posted_at, url, domain, source_type, embed_title,
                       embed_description, content, author_name
                FROM discord_bookmarks
                WHERE url = ? OR url = ?
                ORDER BY posted_at DESC
                LIMIT 1
                """,
                (url, normalized),
            ).fetchone()
        if row:
            return {"found": True, **dict(row)}
        # Fuzzy fallback: match on status ID
        import re as _re

        m = _re.search(r"/status/(\d+)", url)
        if m:
            status_id = m.group(1)
            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    """
                    SELECT posted_at, url, domain, source_type, embed_title,
                           embed_description, content, author_name
                    FROM discord_bookmarks
                    WHERE url LIKE ?
                    ORDER BY posted_at DESC
                    LIMIT 1
                    """,
                    (f"%{status_id}%",),
                ).fetchone()
            if row:
                return {"found": True, **dict(row)}
        return {
            "found": False,
            "url": url,
            "message": "not in bookmarks — run nightly sync or check URL",
        }
    except Exception as exc:
        logger.warning("[get_tweet_by_url] DB error for %r: %s", url, exc)
        return {"found": False, "url": url, "message": f"DB error: {exc}"}


@mcp.tool()
async def get_bookmark_stats(days: int = 30) -> dict:
    """
    Aggregate stats for the bookmark feed over the last N days.

    Args:
        days: Lookback window in days (default 30)

    Returns dict with: total, by_source_type (dict), top_domains (list of
        {domain, count}), latest_posted_at, oldest_posted_at
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    db_path = _default_db_path()

    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            totals = conn.execute(
                "SELECT COUNT(*) c, MIN(posted_at) lo, MAX(posted_at) hi "
                "FROM discord_bookmarks WHERE posted_at >= ?",
                (cutoff,),
            ).fetchone()
            by_type = conn.execute(
                "SELECT source_type, COUNT(*) c FROM discord_bookmarks "
                "WHERE posted_at >= ? GROUP BY source_type ORDER BY c DESC",
                (cutoff,),
            ).fetchall()
            top_domains = conn.execute(
                "SELECT domain, COUNT(*) c FROM discord_bookmarks "
                "WHERE posted_at >= ? AND domain IS NOT NULL "
                "GROUP BY domain ORDER BY c DESC LIMIT 10",
                (cutoff,),
            ).fetchall()
        return {
            "days": days,
            "total": totals["c"] if totals else 0,
            "oldest_posted_at": totals["lo"] if totals else None,
            "latest_posted_at": totals["hi"] if totals else None,
            "by_source_type": {r["source_type"]: r["c"] for r in by_type},
            "top_domains": [{"domain": r["domain"], "count": r["c"]} for r in top_domains],
        }
    except Exception as exc:
        logger.warning("[get_bookmark_stats] DB error: %s", exc)
        return {"days": days, "total": 0, "error": str(exc)}


# ---------------------------------------------------------------------------
# Engine API tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_engine_health() -> dict:
    """
    Get JARVIS engine health — IBKR connections, TV MCP, LLM path, uptime, kill switch.

    Call this at the start of any brief or position check to confirm the engine
    is healthy before relying on its data. Returns 'status=error' with an
    'error' key if the engine is unreachable.

    Returns dict with: status, ibkr_connected, ibkr_execution_connected,
        ibkr_data_connected, tradingview_mcp_healthy, llm_path_healthy,
        uptime_seconds, kill_switch_active, paper_mode, version
    """
    url = os.environ.get("ENGINE_URL", _ENGINE_URL)
    key = os.environ.get("API_KEY") or os.environ.get("ENGINE_API_KEY", _ENGINE_API_KEY)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{url}/health",
                headers={"X-API-Key": key},
                timeout=aiohttp.ClientTimeout(total=8),
            ) as resp:
                if resp.status != 200:
                    return {"status": "error", "error": f"HTTP {resp.status}"}
                return await resp.json()
    except Exception as exc:
        return {"status": "unreachable", "error": str(exc)}


@mcp.tool()
async def get_open_positions() -> dict:
    """
    Get currently open IBKR positions from the JARVIS engine.

    Returns 'positions' list (empty when flat) with each position containing
    symbol, position (qty), avg_cost, unrealized_pnl where available.
    Returns 'error' key if the engine is unreachable.
    """
    url = os.environ.get("ENGINE_URL", _ENGINE_URL)
    key = os.environ.get("API_KEY") or os.environ.get("ENGINE_API_KEY", _ENGINE_API_KEY)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{url}/brokers/positions",
                headers={"X-API-Key": key},
                timeout=aiohttp.ClientTimeout(total=8),
            ) as resp:
                if resp.status != 200:
                    return {"positions": [], "error": f"HTTP {resp.status}"}
                data = await resp.json()
                if isinstance(data, list):
                    positions = data
                elif isinstance(data, dict) and "ibkr" in data:
                    # Engine returns {"ibkr": {"positions": [...]}, "paper": {...}, ...}
                    ibkr_pos = data.get("ibkr", {}).get("positions", [])
                    paper_pos = data.get("paper", {}).get("positions", [])
                    paper_mode = data.get("ibkr", {}).get("connected") is False
                    positions = paper_pos if paper_mode and not ibkr_pos else ibkr_pos
                else:
                    positions = data.get("positions", [])
                return {"positions": positions, "count": len(positions)}
    except Exception as exc:
        return {"positions": [], "error": str(exc)}


# ---------------------------------------------------------------------------
# RAG semantic search
# ---------------------------------------------------------------------------

# vec_index.db lives in engine/data/ (same dir as jarvis_trader.db) so both
# Windows (this MCP server) and WSL (run-vec-index.py via /mnt/c/...) can open
# it natively without cross-OS locking incompatibilities.
_VEC_INDEX_DB = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "vec_index.db"
)


@mcp.tool()
async def semantic_search(query: str, limit: int = 8, min_score: float = 0.2) -> dict:
    """
    Semantic (vector) search over Corey's indexed Discord commentary.

    Embeds the query via local nomic-embed-text (Ollama) then runs KNN search
    over vec_index.db. Unlike search_commentary (FTS keyword match), this finds
    conceptually related messages even if exact words don't appear.

    Args:
        query:      Natural-language question, e.g. "ES breakout above value area"
        limit:      Number of results to return (default 8, max 20)
        min_score:  Reranker relevance floor (default 0.2) — candidates scoring
                    below it are dropped before the top-`limit` cut, so weak
                    vocabulary-only matches don't pad results. Pass 0.0 to keep
                    everything (no-op on the "off"/identity rerank tier).

    Returns dict with 'results' list (rowid, similarity, content, ts, channel)
    and 'index_size' count. Returns 'error' key if index is unavailable.
    """
    import json as _json

    limit = min(max(1, limit), 20)

    # Embed the query via Ollama (accessible from Windows at 127.0.0.1:11434)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "http://127.0.0.1:11434/api/embed",
                json={"model": "nomic-embed-text", "input": [query]},
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status != 200:
                    return {"results": [], "error": f"Ollama embed HTTP {resp.status}"}
                q_vec = _json.dumps((await resp.json())["embeddings"][0])
    except Exception as exc:
        return {"results": [], "error": f"Ollama embed error: {exc}"}

    # Query the WSL-native vec_index.db via UNC path
    import sqlite3 as _sqlite3

    try:
        import sqlite_vec as _sqlite_vec
    except ImportError:
        return {"results": [], "error": "sqlite_vec not installed in engine venv"}

    if not os.path.exists(_VEC_INDEX_DB):
        return {"results": [], "error": "vec_index.db not found — run vec-index cron first"}

    try:
        idx = _sqlite3.connect(_VEC_INDEX_DB, timeout=5.0)
        idx.enable_load_extension(True)
        _sqlite_vec.load(idx)
        idx.enable_load_extension(False)
        idx.execute("PRAGMA journal_mode=WAL")

        index_size = idx.execute("SELECT COUNT(*) FROM vec_commentary").fetchone()[0]
        if index_size == 0:
            idx.close()
            return {"results": [], "index_size": 0, "error": "Index is empty"}

        # Over-fetch a larger candidate pool so the cross-encoder reranker has
        # room to reorder; it is then cut down to `limit`. Without reranking
        # (Tier 3) this collapses to the original top-`limit` vector order.
        from engine.discord.reranker import overfetch_k, rerank

        fetch_k = overfetch_k(limit)
        rows = idx.execute(
            """
            SELECT v.rowid, v.distance, m.content, m.ts, m.channel
            FROM vec_commentary v
            JOIN commentary_meta m ON m.rowid = v.rowid
            WHERE v.embedding MATCH ?
              AND k = ?
            ORDER BY v.distance
            """,
            [q_vec, fetch_k],
        ).fetchall()
        idx.close()
    except Exception as exc:
        return {"results": [], "error": f"vec_index query error: {exc}"}

    # Build candidates carrying the FULL content (rerank quality depends on the
    # whole document, not a 400-char preview); truncate only on the way out.
    candidates = [
        {
            "rowid": rid,
            "similarity": round(1 - dist, 4),
            "ts": ts or "",
            "channel": channel or "market-updates",
            "_full_content": content or "",
        }
        for rid, dist, content, ts, channel in rows
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
        "index_size": index_size,
        "rerank": rerank_tier,
        "results": results,
    }


@mcp.tool()
async def search_knowledge(query: str, limit: int = 8, min_score: float = 0.2) -> dict:
    """
    Semantic search over the curated trading KNOWLEDGE brain (gbrain daemon).

    This is the vault knowledge base — concepts, strategy/setup notes, X-bookmark
    tool cards, and synthesis pages — embedded with voyage-finance-2 (1024-dim) and
    served by the single-writer brain daemon (it embeds the query server-side; this
    tool sends text only, never a key). Use it for "what do we KNOW about X" (e.g.
    gamma exposure, a risk-sizing rule, a tool's capability). For "what did Corey
    SAY" about live price action, use semantic_search (Discord commentary) instead.

    Thin wrapper over engine.discord.knowledge.search_knowledge_core — the same
    code path the enriched Discord briefing uses, so the relevance floor and
    rerank behavior stay identical across both callers.

    Args:
        query:      Natural-language question, e.g. "how do we size risk on a breakout"
        limit:      Number of results to return (default 8, max 20)
        min_score:  Reranker relevance floor (default 0.2) — drops weakly-relevant
                    hits (e.g. archive/handoff pages that match on vocabulary but
                    not intent) before the top-`limit` cut. Pass 0.0 to keep all.

    Returns dict with 'results' list (slug, similarity, type, title, content) and
    'rerank' tier. Returns 'error' key if the brain daemon is unavailable.
    """
    from engine.discord.knowledge import search_knowledge_core

    return await search_knowledge_core(query, limit=limit, min_score=min_score)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
