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

Decision source (T8 fix, 2026-08-25): since REQUIRE_HUMAN_APPROVAL=False
(2026-08-11) the pipeline writes its decisions to the AUTONOMOUS queue
(``pipeline_approval_queue``); the legacy human-gated table
(``pending_trade_approvals``) stopped receiving rows 2026-08-11 and its last 25
rows are all rejected — which is why this endpoint returned an empty board for
two weeks while the pipeline ran daily. The router now reads the queue first
and falls back to the legacy table only when the queue has no rows (new/empty
DB). Both shapes feed the SAME pure derivation via ``queue_row_to_board_row``.

Empty-state diagnostics: the response carries ``source`` and
``last_pipeline_run_at`` (newest pipeline_runs row) so the UI can tell
"queue empty — pipeline ran recently and offered nothing directional" apart
from "engine is not running the pipeline at all".
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Query

from analytics.actionable import derive_actionable_board, queue_row_to_board_row

logger = logging.getLogger("jarvis_trader.routers.actionable")

router = APIRouter(prefix="/pipeline", tags=["pipeline", "actionable"])

_db_manager = None


def inject_dependencies(db_manager) -> None:
    global _db_manager
    _db_manager = db_manager


def _load_rows(limit: int) -> tuple[list[dict], str]:
    """Return (board-shaped rows, source label). Queue first, legacy fallback.

    Raises only when BOTH sources are unreadable — the router then fails
    honest (``available: False``) instead of presenting a read failure as a
    legitimately empty board ("no opportunities" would be a false claim).
    """
    queue_rows = None
    try:
        queue_rows = _db_manager.get_recent_queue_decisions(limit=limit)
    except Exception as exc:
        logger.warning("[Actionable] queue read failed: %s", exc)

    if queue_rows:
        return [queue_row_to_board_row(r) for r in queue_rows], "queue"

    try:
        legacy = _db_manager.get_recent_approvals_all_statuses(limit=limit)
    except Exception as exc:
        logger.warning("[Actionable] approvals read failed: %s", exc)
        raise RuntimeError("both decision sources unreadable") from exc

    return legacy, "legacy"


@router.get("/actionable")
async def get_actionable_board(limit: int = Query(25, ge=1, le=50)) -> dict[str, Any]:
    """Live actionable view over recent pipeline decisions."""
    if _db_manager is None:
        return {"items": [], "count": 0, "available": False, "note": "Database not available."}

    try:
        rows, source = _load_rows(limit)
    except Exception as exc:  # defensive — the board must never 500
        logger.error("[Actionable] decision read failed: %s", exc)
        return {"items": [], "count": 0, "available": False, "note": f"Decision read failed: {exc}"}

    symbols = sorted({(r.get("symbol") or "").upper() for r in rows if r.get("symbol")})
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
        board = derive_actionable_board(rows, prices)
    except Exception as exc:  # defensive — the board must never 500
        logger.error("[Actionable] derivation failed: %s", exc)
        return {"items": [], "count": 0, "available": False, "note": f"Derivation failed: {exc}"}

    # Empty-state diagnostics (pure reads; failures degrade to None, never 500).
    try:
        board["last_pipeline_run_at"] = _db_manager.get_last_pipeline_run_at()
    except Exception:
        board["last_pipeline_run_at"] = None
    board["source"] = source
    return board
