"""Alert history and statistics endpoints."""

import logging
import sqlite3

from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["alerts"])

_db_manager = None


def inject_dependencies(db_manager=None):
    global _db_manager
    if db_manager is not None:
        _db_manager = db_manager


@router.get("/alerts/history")
async def get_alert_history(limit: int = 100, alert_type: str | None = None):
    """Return recent alert log entries."""
    if _db_manager is None:
        raise HTTPException(status_code=503, detail="DB not initialized")
    try:
        rows = _db_manager.get_alert_history(limit=min(limit, 500), alert_type=alert_type)
        return {"alerts": rows, "count": len(rows)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/alerts/stats")
async def get_alert_stats():
    """Return alert counts grouped by type and status."""
    if _db_manager is None:
        raise HTTPException(status_code=503, detail="DB not initialized")
    try:
        with _db_manager._lock:
            conn = sqlite3.connect(str(_db_manager._db_path))
            try:
                cursor = conn.execute(
                    """
                    SELECT alert_type, status, COUNT(*) as count
                    FROM alert_log
                    GROUP BY alert_type, status
                    ORDER BY count DESC
                """
                )
                rows = [
                    {"alert_type": r[0], "status": r[1], "count": r[2]} for r in cursor.fetchall()
                ]
                total_cursor = conn.execute("SELECT COUNT(*) FROM alert_log")
                total = total_cursor.fetchone()[0]
            finally:
                conn.close()
        return {"stats": rows, "total": total}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
