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

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    sql = f"""
        SELECT * FROM discord_bot_signals
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

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    sql = f"""
        SELECT * FROM discord_ib_reports
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

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    sql = f"""
        SELECT * FROM discord_corey_alerts
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

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    sql = f"""
        SELECT * FROM discord_corey_commentary
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
        raise HTTPException(status_code=400, detail="jarvis_bias must be LONG, SHORT, or NEUTRAL") from None

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


@router.get("/briefing")
async def get_briefing(
    symbol: str = Query(..., description="JARVIS or Discord symbol (MCL, CL, MES, ES, ...)"),
    lookback_hours: int = Query(24, ge=1, le=168),
    for_date: Optional[str] = Query(None, description="YYYY-MM-DD (defaults to today)"),
):
    """
    Unified Discord briefing: Corey session bias + IB levels + keyword sentiment
    + most-recent bot signal, aggregated through discord.briefing.get_discord_briefing.

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
            symbol=symbol, lookback_hours=lookback_hours, for_date=parsed_date
        )
        return briefing.to_dict()
    except Exception as exc:
        logger.exception("discord briefing failed for %s", symbol)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
