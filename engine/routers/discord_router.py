"""FastAPI router for Discord intelligence data."""

import logging
import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

logger = logging.getLogger("jarvis_trader.discord")

router = APIRouter(prefix="/discord", tags=["discord"])


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
