"""
Trading decisions endpoints
"""

import logging

from fastapi import APIRouter

from database import repository as db_repository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["decisions"])

# In-memory ring buffer — used as fallback when PostgreSQL is unavailable
_decision_log: list[dict] = []


@router.get("/decisions/recent")
async def get_recent_decisions(limit: int = 20, symbol: str = None, agent: str = None):
    """Return most recent agent decisions from PostgreSQL, falling back to in-memory log"""
    try:
        rows = await db_repository.get_recent_decisions(
            agent_name=agent,
            symbol=symbol.upper() if symbol else None,
            limit=limit,
        )
        if rows:
            return rows
    except Exception as exc:
        logger.warning(f"[DB] get_recent_decisions from PostgreSQL failed: {exc}")
    # Fallback: return in-memory ring buffer
    return _decision_log[-limit:]


@router.post("/decisions/log")
async def log_decision(decision: dict):
    """Internal: agents call this to log decisions to the in-memory fallback buffer"""
    _decision_log.append({**decision, "id": len(_decision_log) + 1})
    if len(_decision_log) > 100:
        _decision_log.pop(0)
    return {"ok": True}


# ── Sentiment feed ────────────────────────────────────────────────────────
