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


def _approved_watchlist_symbols() -> set[str]:
    return {s.upper() for s in (settings.FUTURES_WATCHLIST or [])}


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


def _extract_attribution(snap: dict[str, Any]) -> dict[str, Any]:
    """Extract trade attribution fields from pipeline_snapshot for journal entry."""
    if not isinstance(snap, dict):
        return {}

    # Extract from debate stage
    debate = snap.get("debate") or {}
    if not isinstance(debate, dict):
        debate = {}

    # Extract from technical stage
    tech = snap.get("technical") or {}
    if not isinstance(tech, dict):
        tech = {}

    # Build attribution dict - all fields optional (nullable in DB)
    attribution = {
        "regime_tier": snap.get("regime_tier"),  # could be at root or in technical
        "deciding_stage": snap.get("deciding_stage"),  # which pipeline stage drove the decision
        "bull_score": debate.get("bull_score"),
        "bear_score": debate.get("bear_score"),
        "debate_confidence": debate.get("debate_confidence"),
    }

    # Filter out None values for cleaner update
    return {k: v for k, v in attribution.items() if v is not None}


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

    # Re-entry lockout check
    if _safety_layer is not None:
        lockout = _safety_layer.get_lockout_status(sym)
        if lockout.get("locked"):
            raise HTTPException(
                409,
                detail=f"{sym} locked out for {lockout['remaining_minutes']} more minutes after stop-out",
            )

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

    # Create trade journal entry with attribution metadata
    try:
        attribution = _extract_attribution(snap)
        # Extract timeframe from pipeline result (set at root level, not in technical)
        timeframe = snap.get("timeframe") if isinstance(snap, dict) else None
        if attribution:
            # Create journal entry with attribution fields
            _db_manager.add_journal_entry(
                trade_id=trade_id,
                note="Trade approved via pipeline",
                timestamp=None,  # Use server time
                timeframe=timeframe,
                **attribution,  # Include attribution fields
            )
            logger.info(
                "Journal entry created for trade %s with attribution (timeframe=%s)",
                trade_id[:8],
                timeframe or "unknown",
            )
    except Exception as exc:
        # Non-fatal if journal entry creation fails
        logger.warning(
            "Could not create journal entry with attribution for %s: %s",
            trade_id[:8],
            exc,
        )

    # Submit order to IB Gateway via OrderRouter (non-fatal if unavailable)
    execution_result = None
    if _order_router is not None:
        try:
            execution_result = await _order_router.route_order(
                {
                    "symbol": sym,
                    "action": action,
                    "quantity": int(qty),
                    "order_type": "MKT",
                    "limit_price": float(price) if action.upper() == "SELL" else None,
                }
            )
            logger.info(
                "Order routed for approved trade %s | symbol=%s result=%s",
                trade_id[:8],
                sym,
                execution_result.get("status"),
            )
        except RuntimeError as exc:
            logger.warning(
                "Order routing unavailable for %s (trade still approved): %s",
                trade_id[:8],
                exc,
            )
            execution_result = {"status": "broker_unavailable", "reason": str(exc)}
        except Exception as exc:
            logger.exception("Order routing failed for %s", trade_id[:8])
            execution_result = {"status": "error", "reason": str(exc)}
    else:
        logger.info("No OrderRouter injected — trade %s approved without execution", trade_id[:8])

    return {
        "status": "approved",
        "approval_id": approval_id,
        "paper_trade_id": trade_id,
        "symbol": sym,
        "action": action,
        "quantity": qty,
        "entry_price": float(price),
        "execution": execution_result,
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
        logger.error("resolve_pending_approval failed for rejection id=%s", approval_id[:8])
        raise HTTPException(409, detail="Could not mark approval resolved (race?)")

    return {
        "status": "rejected",
        "approval_id": approval_id,
        "reason": reason,
    }
