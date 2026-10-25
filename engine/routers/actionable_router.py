"""
JARVIS TRADER — Actionable-Now board router.

GET /pipeline/actionable — the pipeline's recent directional decisions as a
live board: status chip (awaiting_entry / triggerable / triggered /
target_reached / invalidated / expired / unknown), distance-to-entry in % and
ATR, planned reward:risk, and current R-multiple, derived from the latest
cached price. Read-only and display-only: derivation is the pure
``analytics.actionable`` module; approval/execution stay in the existing
human-gated flow. Fails open (200 with ``available: false``) — a board outage
must never look like "no opportunities".
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Query

from analytics.actionable import derive_actionable_board

logger = logging.getLogger("jarvis_trader.routers.actionable")

router = APIRouter(prefix="/pipeline", tags=["pipeline", "actionable"])

_db_manager = None


def inject_dependencies(db_manager) -> None:
    global _db_manager
    _db_manager = db_manager


@router.get("/actionable")
async def get_actionable_board(limit: int = Query(25, ge=1, le=50)) -> dict[str, Any]:
    """Live actionable view over recent pipeline decisions."""
    if _db_manager is None:
        return {"items": [], "count": 0, "available": False, "note": "Database not available."}

    try:
        rows = _db_manager.get_recent_approvals_all_statuses(limit=limit)
    except Exception as exc:
        logger.warning("[Actionable] approvals read failed: %s", exc)
        return {"items": [], "count": 0, "available": False, "note": f"Approvals read failed: {exc}"}

    # Only fetch prices for rows that can survive actionable-board filtering.
    # Rejected/error/hold rows are diagnostic history, not live candidates; asking
    # the live price router about those symbols can stall the operator card even
    # though the final board would be empty. Keep the route fail-open and fast.
    actionable_rows = [
        r
        for r in rows
        if str(r.get("final_decision") or "").lower() in {"buy", "sell", "long", "short"}
        and str(r.get("status") or "").lower() not in {"rejected", "error"}
    ]
    symbols = sorted({(r.get("symbol") or "").upper() for r in actionable_rows if r.get("symbol")})
    prices: dict[str, dict] = {}
    if symbols:
        try:
            # Reuse the cached snapshot path (60s TTL) — no new data dependency.
            from routers.prices_router import get_price_snapshot

            prices = await get_price_snapshot(",".join(symbols))
        except Exception as exc:
            # Pure derivation degrades every item to status "unknown" — honest.
            logger.warning("[Actionable] price snapshot failed: %s", exc)
            prices = {}

    try:
        return derive_actionable_board(rows, prices)
    except Exception as exc:  # defensive — the board must never 500
        logger.error("[Actionable] derivation failed: %s", exc)
        return {"items": [], "count": 0, "available": False, "note": f"Derivation failed: {exc}"}
