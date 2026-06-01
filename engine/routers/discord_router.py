"""FastAPI router for Discord intelligence data."""

import logging
import sqlite3
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

logger = logging.getLogger("jarvis_trader.discord")

router = APIRouter(prefix="/discord", tags=["discord"])

# Injected from main.py (optional — intelligence still works without live prices)
_data_manager = None


def inject_data_manager(dm) -> None:
    """Wire MarketDataManager for live quotes on /discord/intelligence."""
    global _data_manager
    _data_manager = dm


def get_db_path() -> str:
    """Get the SQLite database path."""
    import os

    return os.environ.get("DB_PATH", "data/jarvis_trader.db")


def query_db(db_path: str, sql: str, params: tuple = ()) -> list:
    """Execute a SELECT query and return results as list of dicts."""
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(sql, params)
        return [dict(row) for row in cursor.fetchall()]


@router.get("/signals")
async def get_signals(
    symbol: Optional[str] = Query(None, description="Filter by symbol (ES, NQ, GC, etc.)"),
    direction: Optional[str] = Query(None, description="Filter by direction (LONG, SHORT)"),
    signal_type: Optional[str] = Query(None, description="Filter by type (ENTRY, EXIT)"),
    channel_id: Optional[str] = Query(
        None,
        description=(
            "Filter by raw Discord channel snowflake. NO-OP today — "
            "discord_bot_signals does not yet persist channel_id "
            "(slug→snowflake migration is a separate patch). Field "
            "is accepted now so callers can be written forward-compatibly."
        ),
    ),
    limit: int = Query(100, le=1000),
    offset: int = Query(0),
    db_path: str = Depends(get_db_path),
):
    """Get bot signals with optional filters."""
    conditions = []
    params = []

    if symbol:
        conditions.append("symbol = ?")
        params.append(symbol.upper())
    if direction:
        conditions.append("direction = ?")
        params.append(direction.upper())
    if signal_type:
        conditions.append("signal_type = ?")
        params.append(signal_type.upper())
    # TODO: requires slug→snowflake migration on discord_bot_signals
    # (no channel_id column today). channel_id param accepted but not applied.
    _ = channel_id

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    sql = f"""
        SELECT *, NULL AS channel_id FROM discord_bot_signals
        {where}
        ORDER BY timestamp DESC
        LIMIT ? OFFSET ?
    """
    params.extend([limit, offset])

    try:
        rows = query_db(db_path, sql, tuple(params))
        total_sql = f"SELECT COUNT(*) as cnt FROM discord_bot_signals {where}"
        total = query_db(db_path, total_sql, tuple(params[:-2]))[0]["cnt"]
        return {"data": rows, "total": total, "limit": limit, "offset": offset}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/ib-reports")
async def get_ib_reports(
    symbol: Optional[str] = Query(None),
    channel_id: Optional[str] = Query(
        None,
        description=(
            "Filter by raw Discord channel snowflake. NO-OP today — "
            "discord_ib_reports does not yet persist channel_id "
            "(slug→snowflake migration is a separate patch)."
        ),
    ),
    limit: int = Query(50, le=500),
    offset: int = Query(0),
    db_path: str = Depends(get_db_path),
):
    """Get IB reports with optional symbol filter."""
    conditions = []
    params = []

    if symbol:
        conditions.append("symbol = ?")
        params.append(symbol.upper())
    # TODO: requires slug→snowflake migration on discord_ib_reports
    # (no channel_id column today). channel_id param accepted but not applied.
    _ = channel_id

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    sql = f"""
        SELECT *, NULL AS channel_id FROM discord_ib_reports
        {where}
        ORDER BY timestamp DESC
        LIMIT ? OFFSET ?
    """
    params.extend([limit, offset])

    try:
        rows = query_db(db_path, sql, tuple(params))
        total_sql = f"SELECT COUNT(*) as cnt FROM discord_ib_reports {where}"
        total = query_db(db_path, total_sql, tuple(params[:-2]))[0]["cnt"]
        return {"data": rows, "total": total, "limit": limit, "offset": offset}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/corey-alerts")
async def get_corey_alerts(
    symbol: Optional[str] = Query(None),
    channel_id: Optional[str] = Query(
        None,
        description=(
            "Filter by raw Discord channel snowflake. NO-OP today — "
            "discord_corey_alerts does not yet persist channel_id "
            "(slug→snowflake migration is a separate patch)."
        ),
    ),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    db_path: str = Depends(get_db_path),
):
    """Get Corey's manual trade alerts."""
    conditions = []
    params = []

    if symbol:
        conditions.append("symbol = ?")
        params.append(symbol.upper())
    # TODO: requires slug→snowflake migration on discord_corey_alerts
    # (no channel_id column today). channel_id param accepted but not applied.
    _ = channel_id

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    sql = f"""
        SELECT *, NULL AS channel_id FROM discord_corey_alerts
        {where}
        ORDER BY timestamp DESC
        LIMIT ? OFFSET ?
    """
    params.extend([limit, offset])

    try:
        rows = query_db(db_path, sql, tuple(params))
        total_sql = f"SELECT COUNT(*) as cnt FROM discord_corey_alerts {where}"
        total = query_db(db_path, total_sql, tuple(params[:-2]))[0]["cnt"]
        return {"data": rows, "total": total, "limit": limit, "offset": offset}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/commentary")
async def get_commentary(
    channel: Optional[str] = Query(None, description="Filter by channel (general, market-updates)"),
    channel_id: Optional[str] = Query(
        None,
        description=(
            "Filter by raw Discord channel snowflake. NO-OP today — "
            "discord_corey_commentary keys by slug (`channel`), not by "
            "snowflake (slug→snowflake migration is a separate patch). "
            "Use ?channel=<slug> for filtering."
        ),
    ),
    limit: int = Query(50, le=500),
    offset: int = Query(0),
    db_path: str = Depends(get_db_path),
):
    """Get Corey's commentary from general and market-updates channels."""
    conditions = []
    params = []

    if channel:
        conditions.append("channel = ?")
        params.append(channel)
    # TODO: requires slug→snowflake migration on discord_corey_commentary
    # (no channel_id column today). channel_id param accepted but not applied.
    _ = channel_id

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    sql = f"""
        SELECT *, NULL AS channel_id FROM discord_corey_commentary
        {where}
        ORDER BY timestamp DESC
        LIMIT ? OFFSET ?
    """
    params.extend([limit, offset])

    try:
        rows = query_db(db_path, sql, tuple(params))
        total_sql = f"SELECT COUNT(*) as cnt FROM discord_corey_commentary {where}"
        total = query_db(db_path, total_sql, tuple(params[:-2]))[0]["cnt"]
        return {"data": rows, "total": total, "limit": limit, "offset": offset}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/stats")
async def get_stats(db_path: str = Depends(get_db_path)):
    """Get import statistics for all Discord tables."""
    try:
        stats = {}
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row

            for table in [
                "discord_bot_signals",
                "discord_ib_reports",
                "discord_corey_alerts",
                "discord_corey_commentary",
            ]:
                try:
                    row = conn.execute(
                        f"SELECT COUNT(*) as cnt, MIN(timestamp) as earliest, MAX(timestamp) as latest FROM {table}"
                    ).fetchone()
                    stats[table] = {
                        "count": row["cnt"],
                        "earliest": row["earliest"],
                        "latest": row["latest"],
                    }
                except Exception:
                    stats[table] = {"count": 0, "earliest": None, "latest": None}

            # Per-symbol signal counts
            try:
                symbols = conn.execute(
                    "SELECT symbol, COUNT(*) as cnt, "
                    "SUM(CASE WHEN direction='LONG' THEN 1 ELSE 0 END) as longs, "
                    "SUM(CASE WHEN direction='SHORT' THEN 1 ELSE 0 END) as shorts, "
                    "AVG(win_rate) as avg_win_rate "
                    "FROM discord_bot_signals "
                    "WHERE signal_type='ENTRY' "
                    "GROUP BY symbol ORDER BY cnt DESC"
                ).fetchall()
                stats["signals_by_symbol"] = [dict(row) for row in symbols]
            except Exception:
                stats["signals_by_symbol"] = []

        return stats
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/intelligence")
async def get_discord_intelligence(
    jarvis_bias: str = Query(
        "NEUTRAL",
        description="JARVIS directional bias for alignment: LONG, SHORT, or NEUTRAL",
    ),
    db_path: str = Depends(get_db_path),
):
    """
    Aggregated Discord bot features for MCL and MNQ (dashboard widget).

    Uses ``DiscordSignalContext`` — same five features as the RL state vector.
    Live last prices come from ``data_manager`` when connected; otherwise
    proximity uses the signal entry price when a recent signal exists.
    """
    from zoneinfo import ZoneInfo

    from discord.signal_context import DiscordSignalContext

    bias = (jarvis_bias or "NEUTRAL").upper()
    if bias not in ("LONG", "SHORT", "NEUTRAL"):
        raise HTTPException(
            status_code=400, detail="jarvis_bias must be LONG, SHORT, or NEUTRAL"
        ) from None

    ctx = DiscordSignalContext(db_path=db_path)
    now_ct = datetime.now(ZoneInfo("America/Chicago"))
    symbols: dict[str, dict[str, float]] = {}

    for sym in ("MCL", "MNQ"):
        live: Optional[float] = None
        if _data_manager is not None:
            try:
                snap = await _data_manager.get_current_price(sym)
                if isinstance(snap, dict) and snap.get("last_price") is not None:
                    lp = float(snap["last_price"])
                    if lp > 0:
                        live = lp
            except Exception as exc:
                logger.debug("discord intelligence price %s: %s", sym, exc)

        # 0.0 lets get_features fall back to signal entry for proximity when IBKR is offline
        price_arg = live if live is not None else 0.0
        feats = ctx.get_features(sym, now_ct, price_arg, 1.0, jarvis_bias=bias)
        symbols[sym] = feats

    return {
        "symbols": symbols,
        "last_updated": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/bookmarks/stats")
async def get_bookmark_stats(
    lookback_days: int = Query(7, ge=1, le=90),
    db_path: str = Depends(get_db_path),
):
    """Quick counts for the #general bookmark dump (Phase B pipeline)."""
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            total = conn.execute("SELECT COUNT(*) as cnt FROM discord_bookmarks").fetchone()["cnt"]
            recent = conn.execute(
                "SELECT COUNT(*) as cnt FROM discord_bookmarks "
                "WHERE posted_at >= datetime('now', ?)",
                (f"-{lookback_days} days",),
            ).fetchone()["cnt"]
            by_type = conn.execute(
                "SELECT source_type, COUNT(*) as cnt FROM discord_bookmarks "
                "WHERE posted_at >= datetime('now', ?) "
                "GROUP BY source_type ORDER BY cnt DESC",
                (f"-{lookback_days} days",),
            ).fetchall()
            latest = conn.execute(
                "SELECT posted_at FROM discord_bookmarks " "ORDER BY posted_at DESC LIMIT 1"
            ).fetchone()
        return {
            "total": total,
            "recent_count": recent,
            "lookback_days": lookback_days,
            "source_type_breakdown": [dict(row) for row in by_type],
            "latest_posted_at": latest["posted_at"] if latest else None,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/bookmarks/recent")
async def get_bookmarks_recent(
    hours: int = Query(168, ge=1, le=8760, description="Lookback window in hours (default 168=7d)"),
    source_type: Optional[str] = Query(
        None, description="Filter by source_type (x_post, github, video, other)"
    ),
    domain: Optional[str] = Query(None, description="Substring filter on domain"),
    channel_id: Optional[str] = Query(
        None,
        description=(
            "Filter by raw Discord channel snowflake (e.g. "
            "1490851279180660819). Populated — discord_bookmarks keys "
            "by channel_id directly."
        ),
    ),
    limit: int = Query(50, ge=1, le=500),
    db_path: str = Depends(get_db_path),
):
    """Recent rows from the #general bookmark dump with optional filters.

    Mirrors the discord-jarvis MCP `get_recent_bookmarks` tool so dashboard
    widgets and external integrations don't need to talk to SQLite directly.
    """
    clauses = ["posted_at >= datetime('now', ?)"]
    params: list = [f"-{hours} hours"]
    if source_type:
        clauses.append("source_type = ?")
        params.append(source_type)
    if domain:
        clauses.append("domain LIKE ?")
        params.append(f"%{domain}%")
    if channel_id:
        clauses.append("channel_id = ?")
        params.append(channel_id)
    where = " AND ".join(clauses)
    sql = f"""
        SELECT posted_at, channel_id, url, domain, source_type, embed_title,
               embed_description, content, author_name
        FROM discord_bookmarks
        WHERE {where}
        ORDER BY posted_at DESC
        LIMIT ?
    """
    params.append(limit)
    try:
        return {"data": query_db(db_path, sql, tuple(params)), "hours": hours, "limit": limit}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/bookmarks/search")
async def get_bookmarks_search(
    query: str = Query(..., min_length=1, description="Case-insensitive substring query"),
    days: int = Query(30, ge=1, le=365),
    source_type: Optional[str] = Query(None),
    channel_id: Optional[str] = Query(
        None,
        description=(
            "Filter by raw Discord channel snowflake. Populated — "
            "discord_bookmarks keys by channel_id directly."
        ),
    ),
    limit: int = Query(30, ge=1, le=200),
    db_path: str = Depends(get_db_path),
):
    """Substring search across URL / embed_title / embed_description / content.

    Mirrors the discord-jarvis MCP `search_bookmarks` tool. LIKE-based — fine
    at ~1K rows; revisit if the table grows past ~100K.
    """
    like = f"%{query}%"
    clauses = [
        "posted_at >= datetime('now', ?)",
        "(url LIKE ? OR embed_title LIKE ? OR embed_description LIKE ? OR content LIKE ?)",
    ]
    params: list = [f"-{days} days", like, like, like, like]
    if source_type:
        clauses.append("source_type = ?")
        params.append(source_type)
    if channel_id:
        clauses.append("channel_id = ?")
        params.append(channel_id)
    where = " AND ".join(clauses)
    sql = f"""
        SELECT posted_at, channel_id, url, domain, source_type, embed_title,
               embed_description, content
        FROM discord_bookmarks
        WHERE {where}
        ORDER BY posted_at DESC
        LIMIT ?
    """
    params.append(limit)
    try:
        return {
            "data": query_db(db_path, sql, tuple(params)),
            "query": query,
            "days": days,
            "limit": limit,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


# Module-level singleton — preserves the clusterer's 6-hour in-memory cache
# across requests so dashboard reloads don't burn LLM budget.
_bookmark_clusterer_singleton = None


def _get_bookmark_clusterer():
    global _bookmark_clusterer_singleton
    if _bookmark_clusterer_singleton is None:
        from agents.bookmark_clusterer import BookmarkClusterer

        _bookmark_clusterer_singleton = BookmarkClusterer()
    return _bookmark_clusterer_singleton


@router.get("/bookmarks/weekly-themes")
async def get_bookmark_weekly_themes(
    lookback_days: int = Query(7, ge=1, le=30),
    max_rows: int = Query(200, ge=10, le=500),
    refresh: bool = Query(False, description="Bypass the 6h cache and re-call the LLM"),
    db_path: str = Depends(get_db_path),
):
    """Claude-clustered themes across the rolling #general bookmark dump.

    Served from an in-memory 6h cache after the first call; pass
    `?refresh=true` to force a fresh LLM call (costs ~$0.02 per run at Haiku).
    """
    clusterer = _get_bookmark_clusterer()
    result = await clusterer.cluster_recent(
        lookback_days=lookback_days,
        max_rows=max_rows,
        db_path=db_path,
        force_refresh=refresh,
    )
    return result.to_dict()


@router.get("/analysis/correlation/{symbol}")
async def get_correlation_analysis(
    symbol: str,
    lookback_days: int = Query(90, ge=7, le=365, description="Lookback window in days"),
    db_path: str = Depends(get_db_path),
):
    """
    Corey-bias × bot-signal win-rate correlation for a symbol.

    Joins discord_bot_signals with corey_session_bias on date to answer:
    does Corey's LLM-extracted directional bias compound with signal win rate?

    Returns alignment breakdown, session-type performance, and conviction-threshold
    analysis. Requires commentary processor to have run at least once.
    """
    try:
        from analysis.discord_correlation import get_corey_alignment_summary

        return get_corey_alignment_summary(
            symbol.upper(), lookback_days=lookback_days, db_path=db_path
        )
    except Exception as exc:
        logger.exception("correlation analysis failed for %s", symbol)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/analysis/time-patterns/{symbol}")
async def get_time_patterns(
    symbol: str,
    db_path: str = Depends(get_db_path),
):
    """
    Hour-of-day, day-of-week, and monthly win-rate patterns for a symbol's
    Discord bot signals. Surfaces optimal trading windows and hours to avoid.
    """
    from analysis.discord_time_patterns import compute_time_patterns

    try:
        return compute_time_patterns(symbol.upper(), db_path=db_path)
    except Exception as exc:
        logger.exception("time-patterns analysis failed for %s", symbol)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/briefing")
async def get_briefing(
    symbol: str = Query(..., description="JARVIS or Discord symbol (MCL, CL, MES, ES, ...)"),
    lookback_hours: int = Query(24, ge=1, le=168),
    for_date: Optional[str] = Query(None, description="YYYY-MM-DD (defaults to today)"),
    enriched: bool = Query(
        False,
        description="Attach advisory curated-knowledge hits (gbrain) as knowledge_context",
    ),
):
    """
    Unified Discord briefing: Corey session bias + IB levels + keyword sentiment
    + most-recent bot signal, aggregated through discord.briefing.get_discord_briefing.

    With `enriched=true`, also attaches `knowledge_context`: the top curated gbrain
    knowledge hits for a query derived from the session bias. That field is ADVISORY
    (prompt context only) and fallback-safe — never an input to gate-v2/sizing. The
    default (`enriched=false`) response is byte-identical to the pre-enrichment shape.

    5-minute TTL cache at the facade layer.
    """
    from datetime import date as _date

    from discord.briefing import get_discord_briefing

    parsed_date = None
    if for_date:
        try:
            parsed_date = _date.fromisoformat(for_date)
        except ValueError as exc:
            raise HTTPException(
                status_code=422, detail=f"for_date must be YYYY-MM-DD: {exc}"
            ) from exc

    try:
        briefing = await get_discord_briefing(
            symbol=symbol,
            lookback_hours=lookback_hours,
            for_date=parsed_date,
            enriched_with_knowledge=enriched,
        )
        return briefing.to_dict()
    except Exception as exc:
        logger.exception("discord briefing failed for %s", symbol)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/knowledge")
async def get_knowledge(
    q: str = Query(..., description="Free-text query, e.g. 'how do we size risk on a breakout'"),
    limit: int = Query(8, ge=1, le=20),
    min_score: float = Query(0.2, ge=0.0, le=1.0, description="Reranker relevance floor"),
):
    """
    Free-text retrieval over the curated KNOWLEDGE brain (gbrain daemon + rerank).

    A thin reusable HTTP surface over discord.knowledge.search_knowledge_core — the
    same reranked Voyage path as the search_knowledge MCP tool, but callable by any
    HTTP consumer (the Master-Jarvis CommandChat, Hermes briefs, etc.) for an
    arbitrary question. Returns {query, source, rerank (tier), results:[{slug,
    similarity, type, title, content}]}; never raises (an unreachable daemon yields
    an `error` key with empty results).
    """
    from discord.knowledge import search_knowledge_core

    try:
        return await search_knowledge_core(q, limit=limit, min_score=min_score)
    except Exception as exc:
        logger.exception("knowledge search failed for %r", q)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
