"""
Alerts Router — auto-generated scaffold.
Full alert log implementation pending DB manager wiring.
"""
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/alerts", tags=["alerts"])

# Global references (injected from main.py)
db_manager = None


def inject_dependencies(db=None):
    global db_manager
    if db is not None:
        db_manager = db


@router.get("/alerts/history")
async def get_alert_history(limit: int = 100, alert_type: str | None = None):
    """Return recent alert log entries."""
    if db_manager is None:
        return {"alerts": [], "count": 0, "note": "DB not initialized"}
    try:
        rows = db_manager.get_alert_history(limit=min(limit, 500), alert_type=alert_type)
        return {"alerts": rows, "count": len(rows)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/alerts/stats")
async def get_alert_stats():
    """Return alert counts grouped by type and status."""
    if db_manager is None:
        return {"stats": [], "total": 0, "note": "DB not initialized"}
    try:
        import sqlite3
        with db_manager._lock:
            conn = sqlite3.connect(str(db_manager._db_path))
            try:
                cursor = conn.execute(
                    "SELECT alert_type, status, COUNT(*) as count FROM alert_log "
                    "GROUP BY alert_type, status ORDER BY count DESC"
                )
                rows = [{"alert_type": r[0], "status": r[1], "count": r[2]} for r in cursor.fetchall()]
                total = conn.execute("SELECT COUNT(*) FROM alert_log").fetchone()[0]
            finally:
                conn.close()
        return {"stats": rows, "total": total}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
