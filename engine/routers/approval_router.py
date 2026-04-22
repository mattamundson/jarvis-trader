"""Human-gated trade approvals — list / approve / reject pending pipeline trades."""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from approval.service import (
    ApprovalFlowError,
    approve_pending_trade,
    reject_pending_trade,
)

logger = logging.getLogger("jarvis_trader.routers.approval")

router = APIRouter(prefix="/pipeline", tags=["pipeline", "approvals"])

_safety_layer = None
_paper_tracker = None
_db_manager = None
_order_router = None


def inject_dependencies(safety_layer, paper_tracker, db_manager, order_router=None) -> None:
    global _safety_layer, _paper_tracker, _db_manager, _order_router
    _safety_layer = safety_layer
    _paper_tracker = paper_tracker
    _db_manager = db_manager
    _order_router = order_router


class ApprovePendingBody(BaseModel):
    """Optional overrides when approving."""

    entry_price: Optional[float] = Field(
        default=None,
        description="Override entry price when snapshot has none",
    )


class RejectPendingBody(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=2000)


def _extract_provenance(approval_row: dict[str, Any]) -> dict[str, Any]:
    """Extract signal provenance fields from pipeline_snapshot and enrich approval row."""
    snap = approval_row.get("pipeline_snapshot") or {}
    if not isinstance(snap, dict):
        return approval_row

    # Try to extract provenance from technical report or root level
    tech = snap.get("technical") or {}
    if not isinstance(tech, dict):
        tech = {}

    # Extract fields with None defaults for missing values
    provenance = {
        "regime": tech.get("regime"),
        "structure_position": tech.get("structure_position"),
        "bias": tech.get("bias"),
        "composite_score": tech.get("composite_score"),
        "stc_contrib": tech.get("stc_contrib"),
        "orb_contrib": tech.get("orb_contrib"),
        "vwap_contrib": tech.get("vwap_contrib"),
        "risk_pct_used": tech.get("risk_pct_used"),
        # Extract timeframe from root level (set by pipeline) or technical report fallback
        "timeframe": snap.get("timeframe") or tech.get("timeframe"),
    }

    # Merge provenance into approval row
    return {**approval_row, **provenance}
@router.get("/pending-approvals")
async def list_pending_approvals(limit: int = 50) -> dict[str, Any]:
    if _db_manager is None:
        raise HTTPException(503, detail="Database not available")
    rows = _db_manager.list_pending_approvals(limit=limit)
    enriched_rows = [_extract_provenance(row) for row in rows]
    return {"pending": enriched_rows, "count": len(enriched_rows)}


@router.get("/recent-with-reasoning")
async def get_recent_pipeline_with_reasoning(limit: int = 10) -> dict[str, Any]:
    """Return recent pipeline decisions (all statuses) with full snapshot for reasoning display."""
    if _db_manager is None:
        raise HTTPException(503, detail="Database not available")
    try:
        rows = _db_manager.get_recent_approvals_all_statuses(limit=min(max(1, limit), 50))
        return {"decisions": rows, "count": len(rows)}
    except Exception as exc:
        logger.error("[ApprovalRouter] recent-with-reasoning failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/pending-approvals/{approval_id}")
async def get_pending_approval(approval_id: str) -> dict[str, Any]:
    if _db_manager is None:
        raise HTTPException(503, detail="Database not available")
    row = _db_manager.get_pending_approval(approval_id)
    if not row:
        raise HTTPException(404, detail="Approval not found")
    return row


@router.post("/pending-approvals/{approval_id}/approve")
async def approve_pending(
    approval_id: str,
    body: ApprovePendingBody | None = None,
) -> dict[str, Any]:
    try:
        return await approve_pending_trade(
            approval_id=approval_id,
            db_manager=_db_manager,
            paper_tracker=_paper_tracker,
            safety_layer=_safety_layer,
            resolved_by="api",
            entry_price_override=(body.entry_price if body else None),
        )
    except ApprovalFlowError as exc:
        raise HTTPException(exc.status_code, detail=exc.detail) from exc


@router.post("/pending-approvals/{approval_id}/reject")
async def reject_pending(
    approval_id: str,
    body: RejectPendingBody | None = None,
) -> dict[str, Any]:
    try:
        return reject_pending_trade(
            approval_id=approval_id,
            db_manager=_db_manager,
            resolved_by="api",
            reason=(body.reason if body else None),
        )
    except ApprovalFlowError as exc:
        raise HTTPException(exc.status_code, detail=exc.detail) from exc
