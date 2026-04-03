"""LLM cost tracking and summary endpoints."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException

logger = logging.getLogger("jarvis_trader.routers.cost")

router = APIRouter(prefix="/pipeline", tags=["pipeline", "costs"])

_db_manager = None


def inject_dependencies(db_manager) -> None:
    """Inject database manager dependency."""
    global _db_manager
    _db_manager = db_manager


@router.get("/cost-summary")
async def get_cost_summary() -> dict[str, Any]:
    """
    Get a summary of LLM costs across different time windows.

    Returns
    -------
    {
        "today_usd": float,                  # Total cost for today (UTC)
        "this_week_usd": float,              # Total cost for past 7 days
        "all_time_usd": float,               # Total cost across all calls
        "cost_per_trade_usd": float,         # Average cost per pipeline run
        "top_expensive_stages": [            # Top 5 stages by avg tokens
            {"stage": str, "avg_tokens": float},
            ...
        ]
    }
    """
    if _db_manager is None:
        raise HTTPException(503, detail="Database not available")

    try:
        summary = _db_manager.get_cost_summary()
        return summary
    except Exception as e:
        logger.error(f"Error retrieving cost summary: {e}")
        raise HTTPException(500, detail="Failed to retrieve cost summary") from e
