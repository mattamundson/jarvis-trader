"""
JARVIS TRADER — Proactive Advisor Brief router (Phase 5)
========================================================
Exposes ``GET /brief/session``: a session brief assembled from the reasoning the
pipeline ALREADY produced (stored on recent pending-approval snapshots), turned
into 1-3 concrete recommended actions by the pure ``analytics.session_brief``
module. Never fabricates — a reasoning-less decision surfaces as an honest gap.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException

from analytics.session_brief import DEFAULT_MAX_ACTIONS, build_session_brief

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/brief", tags=["advisor-brief"])

_db_manager: Any = None


def inject_dependencies(db_manager: Any = None) -> None:
    """Wire the DB manager (called from main on startup)."""
    global _db_manager
    _db_manager = db_manager


def _collect_snapshots(limit: int) -> list[dict]:
    """Pull recent pipeline snapshots (newest-first) from pending approvals and
    enrich each with the row's symbol/action/created_at (which the trimmed
    approval snapshot omits). Read-only; degrades to [] when the DB is absent."""
    if _db_manager is None:
        return []
    try:
        rows = _db_manager.get_recent_approvals_all_statuses(limit=limit)
    except Exception:
        logger.exception("[brief] failed to read recent approvals")
        return []

    snapshots: list[dict] = []
    for row in rows or []:
        snap = row.get("pipeline_snapshot")
        snap = dict(snap) if isinstance(snap, dict) else {}
        symbol = row.get("symbol")
        if symbol and not snap.get("symbol"):
            snap["symbol"] = symbol
        if row.get("action") and not snap.get("final_action"):
            snap["final_action"] = row.get("action")
        if row.get("created_at") and not snap.get("completed_at"):
            snap["completed_at"] = row.get("created_at")
        if snap.get("symbol"):
            snapshots.append(snap)
    return snapshots


@router.get("/session")
async def get_session_brief(limit: int = 10, max_actions: int = DEFAULT_MAX_ACTIONS):
    """Return a proactive advisor brief built from existing pipeline reasoning.

    Query params:
        limit       : how many recent decisions to scan (1-50).
        max_actions : cap on recommended actions in the brief (1-5).
    """
    try:
        limit = min(max(1, int(limit)), 50)
        max_actions = min(max(1, int(max_actions)), 5)
        snapshots = _collect_snapshots(limit)
        return build_session_brief(snapshots, max_actions=max_actions)
    except Exception as exc:  # fail honest, never 500 on brief assembly
        logger.exception("[brief] session brief assembly failed")
        raise HTTPException(status_code=500, detail=f"brief assembly failed: {exc}") from exc
