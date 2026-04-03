"""Human-gated trade approvals — list / approve / reject pending pipeline trades."""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from approval.snapshot import entry_price_from_snapshot
from config import settings

logger = logging.getLogger("jarvis_trader.routers.approval")

router = APIRouter(prefix="/pipeline", tags=["pipeline", "approvals"])

_safety_layer = None
_paper_tracker = None
_db_manager = None


def inject_dependencies(safety_layer, paper_tracker, db_manager) -> None:
    global _safety_layer, _paper_tracker, _db_manager
    _safety_layer = safety_layer
    _paper_tracker = paper_tracker
    _db_manager = db_manager


class ApprovePendingBody(BaseModel):
    """Optional overrides when approving."""

    entry_price: Optional[float] = Field(
        default=None,
        description="Override entry price when snapshot has none",
    )


class RejectPendingBody(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=2000)


def _approved_watchlist_symbols() -> set[str]:
    return {s.upper() for s in (settings.FUTURES_WATCHLIST or [])}


@router.get("/pending-approvals")
async def list_pending_approvals(limit: int = 50) -> dict[str, Any]:
    if _db_manager is None:
        raise HTTPException(503, detail="Database not available")
    rows = _db_manager.list_pending_approvals(limit=limit)
    return {"pending": rows, "count": len(rows)}


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
    if _db_manager is None:
        raise HTTPException(503, detail="Database not available")
    if _paper_tracker is None:
        raise HTTPException(503, detail="Paper tracker not available")

    row = _db_manager.get_pending_approval(approval_id)
    if not row:
        raise HTTPException(404, detail="Approval not found")
    if row.get("status") != "pending":
        raise HTTPException(409, detail=f"Already resolved: {row.get('status')}")

    if _safety_layer and _safety_layer.get_status().get("kill_switch_active"):
        raise HTTPException(409, detail="Kill switch active — cannot approve")

    sym = row["symbol"]
    if sym.upper() not in _approved_watchlist_symbols():
        raise HTTPException(400, detail=f"Symbol {sym} not on approved futures watchlist")

    snap = row.get("pipeline_snapshot") or {}
    price = body.entry_price if body and body.entry_price is not None else row.get("entry_price")
    if price is None:
        price = entry_price_from_snapshot(snap)
    if price is None:
        raise HTTPException(
            400,
            detail="No entry price in snapshot; pass entry_price in request body",
        )

    action = row["action"]
    qty = float(row["quantity"])
    notes = ""
    if isinstance(snap, dict):
        notes = str(snap.get("summary") or "")[:2000]

    try:
        trade_id = _paper_tracker.open_trade(
            symbol=sym,
            action=action,
            quantity=qty,
            price=float(price),
            notes=notes,
        )
    except Exception as exc:
        logger.exception("approve_pending open_trade failed")
        raise HTTPException(500, detail=str(exc)) from exc

    ok = _db_manager.resolve_pending_approval(
        approval_id,
        new_status="approved",
        resolved_by="api",
        paper_trade_id=trade_id,
    )
    if not ok:
        logger.error("resolve_pending_approval failed after open_trade id=%s", trade_id[:8])
        raise HTTPException(409, detail="Could not mark approval resolved (race?)")

    return {
        "status": "approved",
        "approval_id": approval_id,
        "paper_trade_id": trade_id,
        "symbol": sym,
        "action": action,
        "quantity": qty,
        "entry_price": float(price),
    }


@router.post("/pending-approvals/{approval_id}/reject")
async def reject_pending(
    approval_id: str,
    body: RejectPendingBody | None = None,
) -> dict[str, Any]:
    if _db_manager is None:
        raise HTTPException(503, detail="Database not available")

    row = _db_manager.get_pending_approval(approval_id)
    if not row:
        raise HTTPException(404, detail="Approval not found")
    if row.get("status") != "pending":
        raise HTTPException(409, detail=f"Already resolved: {row.get('status')}")

    reason = (body.reason if body else None) or "rejected_by_user"
    ok = _db_manager.resolve_pending_approval(
        approval_id,
        new_status="rejected",
        resolved_by="api",
        rejection_reason=reason,
    )
    if not ok:
        raise HTTPException(409, detail="Could not reject approval")

    return {
        "status": "rejected",
        "approval_id": approval_id,
        "symbol": row["symbol"],
        "action": row["action"],
        "quantity": row["quantity"],
        "reason": reason,
    }
