"""Shared approval flow for API and OpenClaw approval paths."""

from __future__ import annotations

import logging
from typing import Any, Optional

from approval.snapshot import entry_price_from_snapshot
from config import settings

logger = logging.getLogger("jarvis_trader.approval.service")


class ApprovalFlowError(Exception):
    """Structured approval flow error that routers can map to HTTP responses."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def approved_watchlist_symbols() -> set[str]:
    """Approved futures symbols that may pass through the human approval gate."""
    return {s.upper() for s in (settings.FUTURES_WATCHLIST or [])}


def extract_attribution(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Extract journal attribution metadata from a pipeline snapshot."""
    if not isinstance(snapshot, dict):
        return {}

    debate = snapshot.get("debate") or {}
    if not isinstance(debate, dict):
        debate = {}

    return {
        k: v
        for k, v in {
            "regime_tier": snapshot.get("regime_tier"),
            "deciding_stage": snapshot.get("deciding_stage"),
            "bull_score": debate.get("bull_score"),
            "bear_score": debate.get("bear_score"),
            "debate_confidence": debate.get("debate_confidence"),
        }.items()
        if v is not None
    }


def get_pending_approval_row(db_manager, approval_id: str) -> dict[str, Any]:
    """Load and validate a pending approval row."""
    if db_manager is None:
        raise ApprovalFlowError(503, "Database not available")

    row = db_manager.get_pending_approval(approval_id)
    if not row:
        raise ApprovalFlowError(404, "Approval not found")
    if row.get("status") != "pending":
        raise ApprovalFlowError(409, f"Already resolved: {row.get('status')}")
    return row


def get_latest_pending_approval_row(db_manager) -> dict[str, Any]:
    """Return the most recent pending approval row."""
    if db_manager is None:
        raise ApprovalFlowError(503, "Database not available")

    rows = db_manager.list_pending_approvals(limit=1)
    if not rows:
        raise ApprovalFlowError(404, "No pending approvals")
    return rows[0]


def resolve_entry_price(
    approval_row: dict[str, Any],
    *,
    entry_price_override: Optional[float] = None,
) -> float:
    """Resolve an entry price from override, row, or snapshot."""
    snapshot = approval_row.get("pipeline_snapshot") or {}
    price = (
        entry_price_override
        if entry_price_override is not None
        else approval_row.get("entry_price")
    )
    if price is None:
        price = entry_price_from_snapshot(snapshot)
    if price is None:
        raise ApprovalFlowError(400, "No entry price in snapshot; pass entry_price in request body")
    return float(price)


def ensure_approval_allowed(approval_row: dict[str, Any], safety_layer) -> None:
    """Validate approval-time safety gates before execution."""
    symbol = str(approval_row["symbol"]).upper()

    if safety_layer and safety_layer.get_status().get("kill_switch_active"):
        raise ApprovalFlowError(409, "Kill switch active — cannot approve")

    if symbol not in approved_watchlist_symbols():
        raise ApprovalFlowError(400, f"Symbol {symbol} not on approved futures watchlist")

    if safety_layer is not None and hasattr(safety_layer, "get_lockout_status"):
        lockout = safety_layer.get_lockout_status(symbol)
        if lockout.get("locked"):
            raise ApprovalFlowError(
                409,
                f"{symbol} locked out for {lockout['remaining_minutes']} more minutes after stop-out",
            )


async def execute_approved_trade(
    *,
    safety_layer,
    symbol: str,
    action: str,
    quantity: float,
    entry_price: float,
) -> dict[str, Any]:
    """
    Route an approved futures trade through the hard safety wrapper.

    The approval surface is futures-only today, so canonical execution goes through
    SafetyLayer.submit_paper_order() instead of directly calling the broker connector.
    """
    if safety_layer is None:
        raise ApprovalFlowError(503, "Safety layer not available")

    result = await safety_layer.submit_paper_order(
        symbol=symbol,
        action=action.upper(),
        quantity=max(1, int(round(quantity))),
        price=float(entry_price),
        order_type="MKT",
        limit_price=None,
    )
    if not result.get("approved", False):
        raise ApprovalFlowError(
            409,
            str(result.get("reason") or "Safety layer blocked approved trade execution"),
        )
    return result


def write_trade_journal_entry(db_manager, trade_id: str, snapshot: dict[str, Any]) -> None:
    """Best-effort journal entry creation with attribution metadata."""
    if db_manager is None or not isinstance(snapshot, dict):
        return

    attribution = extract_attribution(snapshot)
    if not attribution:
        return

    timeframe = snapshot.get("timeframe")
    db_manager.add_journal_entry(
        trade_id=trade_id,
        note="Trade approved via pipeline",
        timestamp=None,
        timeframe=timeframe,
        **attribution,
    )


async def approve_pending_trade(
    *,
    approval_id: str,
    db_manager,
    paper_tracker,
    safety_layer,
    resolved_by: str,
    entry_price_override: Optional[float] = None,
) -> dict[str, Any]:
    """Approve a pending trade via the canonical shared control path."""
    if paper_tracker is None:
        raise ApprovalFlowError(503, "Paper tracker not available")

    row = get_pending_approval_row(db_manager, approval_id)
    ensure_approval_allowed(row, safety_layer)

    symbol = str(row["symbol"]).upper()
    action = str(row["action"]).lower()
    quantity = float(row["quantity"])
    snapshot = row.get("pipeline_snapshot") or {}
    entry_price = resolve_entry_price(row, entry_price_override=entry_price_override)

    execution_result = await execute_approved_trade(
        safety_layer=safety_layer,
        symbol=symbol,
        action=action,
        quantity=quantity,
        entry_price=entry_price,
    )

    notes = str(snapshot.get("summary") or "")[:2000] if isinstance(snapshot, dict) else ""
    try:
        trade_id = paper_tracker.open_trade(
            symbol=symbol,
            action=action,
            quantity=quantity,
            price=entry_price,
            notes=notes,
        )
    except Exception as exc:
        logger.exception("approve_pending_trade open_trade failed for %s", approval_id[:8])
        raise ApprovalFlowError(500, str(exc)) from exc

    ok = db_manager.resolve_pending_approval(
        approval_id,
        new_status="approved",
        resolved_by=resolved_by,
        paper_trade_id=trade_id,
    )
    if not ok:
        logger.error("resolve_pending_approval failed after open_trade id=%s", trade_id[:8])
        raise ApprovalFlowError(409, "Could not mark approval resolved (race?)")

    try:
        write_trade_journal_entry(db_manager, trade_id, snapshot)
    except Exception as exc:
        logger.warning("Could not create journal entry with attribution for %s: %s", trade_id[:8], exc)

    return {
        "status": "approved",
        "approval_id": approval_id,
        "paper_trade_id": trade_id,
        "symbol": symbol,
        "action": action,
        "quantity": quantity,
        "entry_price": entry_price,
        "execution": execution_result,
    }


def reject_pending_trade(
    *,
    approval_id: str,
    db_manager,
    resolved_by: str,
    reason: Optional[str] = None,
) -> dict[str, Any]:
    """Reject a pending trade via the canonical shared control path."""
    row = get_pending_approval_row(db_manager, approval_id)
    rejection_reason = reason or "rejected_by_user"
    ok = db_manager.resolve_pending_approval(
        approval_id,
        new_status="rejected",
        resolved_by=resolved_by,
        rejection_reason=rejection_reason,
    )
    if not ok:
        logger.error("resolve_pending_approval failed for rejection id=%s", approval_id[:8])
        raise ApprovalFlowError(409, "Could not mark approval resolved (race?)")

    return {
        "status": "rejected",
        "approval_id": approval_id,
        "symbol": row["symbol"],
        "reason": rejection_reason,
    }

