"""Command Center V2 RT-3 risk-reducing paper operations.

Initial scope is intentionally narrow:
- read broker positions and open orders,
- classify broker orders by JARVIS manual-intent provenance,
- cancel only still-open RT-2 manual-intent *entry* orders,
- emergency flatten-all + latch the SafetyLayer halt.

Protective STP/TP children, external/unmanaged broker orders, arbitrary stop
modification, and position increases are never mutation targets here.
"""

from __future__ import annotations

import math
import sqlite3
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from config import settings

router = APIRouter(tags=["paper-ops"])

_OPEN_STATUSES = frozenset(
    {
        "PENDINGSUBMIT",
        "PRESUBMITTED",
        "SUBMITTED",
        "PENDINGCANCEL",
        "APIPENDING",
        "INACTIVE",
    }
)


class FlattenAllRequest(BaseModel):
    confirmation: Literal["FLATTEN ALL"]


def _parent_state():
    from routers import orders_router

    return orders_router


def _deps():
    state = _parent_state()
    safety = getattr(state, "_safety_layer", None)
    if safety is None:
        raise HTTPException(503, "Safety layer not initialized")
    gateway = getattr(safety, "_ib_gateway", None)
    if gateway is None:
        raise HTTPException(503, "Paper execution gateway unavailable")
    return safety, gateway


def _require_real_ib_paper() -> None:
    if bool(getattr(settings, "LIVE_TRADING_ENABLED", False)):
        raise HTTPException(409, "Paper operations are disabled in live mode")
    if not bool(getattr(settings, "PAPER_TRADING", True)):
        raise HTTPException(409, "Paper trading is not enabled")
    if not bool(getattr(settings, "IB_PAPER_BROKER_ENABLED", False)):
        raise HTTPException(
            409,
            "Risk-reducing operator mutations require the real IB paper gateway; simulator mode is read-only",
        )


def _connected(gateway) -> bool:
    try:
        attr = getattr(gateway, "is_connected", False)
        return bool(attr() if callable(attr) else attr)
    except Exception:
        return False


def _submitted_manual_entry_ids(safety) -> set[str]:
    db_path = getattr(safety, "_db_path", None)
    if not db_path:
        return set()
    try:
        with sqlite3.connect(str(db_path), timeout=5) as conn:
            # Table may not exist before RT-2 is used; read-only state should
            # degrade to "no controlled manual entries", never fabricate scope.
            rows = conn.execute(
                """
                SELECT order_id
                FROM trade_intents
                WHERE status = 'SUBMITTED' AND order_id IS NOT NULL
                """
            ).fetchall()
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc).lower():
            return set()
        raise HTTPException(503, f"Trade-intent provenance read failed: {exc}") from exc
    except Exception as exc:
        raise HTTPException(503, f"Trade-intent provenance read failed: {exc}") from exc
    return {str(row[0]) for row in rows if row and row[0] is not None}


def _normalize_order(order: dict[str, Any], controlled_entries: set[str], real_ib: bool) -> dict[str, Any]:
    oid = str(order.get("order_id") or "")
    parent_raw = order.get("parent_id")
    parent_id = str(parent_raw) if parent_raw not in (None, "", 0, "0") else None
    status = str(order.get("status") or "UNKNOWN")
    try:
        remaining = float(order.get("remaining") or 0)
    except (TypeError, ValueError):
        remaining = 0.0

    if parent_id is not None and parent_id in controlled_entries:
        role = "PROTECTIVE_CHILD"
    elif parent_id is None and oid in controlled_entries:
        role = "MANUAL_INTENT_ENTRY"
    elif parent_id is None:
        role = "UNMANAGED_ENTRY"
    else:
        role = "EXTERNAL_OR_OTHER_CHILD"

    can_cancel_entry = (
        real_ib
        and role == "MANUAL_INTENT_ENTRY"
        and status.upper() in _OPEN_STATUSES
        and remaining > 0
    )
    return {
        **order,
        "order_id": oid,
        "parent_id": parent_id,
        "control_role": role,
        "can_cancel_entry": can_cancel_entry,
    }


async def _broker_state(safety, gateway) -> tuple[list[dict], list[dict]]:
    if not _connected(gateway):
        raise HTTPException(503, "IB paper execution gateway is not connected")
    try:
        positions = await gateway.get_positions()
        orders = await gateway.get_open_orders()
    except Exception as exc:
        raise HTTPException(503, f"IB paper state could not be read: {exc}") from exc
    if not isinstance(positions, list) or not isinstance(orders, list):
        raise HTTPException(503, "IB paper state returned an invalid response")
    return positions, orders


@router.get("/paper-ops/state")
async def get_paper_ops_state() -> dict[str, Any]:
    safety, gateway = _deps()
    positions, orders = await _broker_state(safety, gateway)
    controlled = _submitted_manual_entry_ids(safety)
    real_ib = bool(getattr(settings, "IB_PAPER_BROKER_ENABLED", False)) and not bool(
        getattr(settings, "LIVE_TRADING_ENABLED", False)
    )
    normalized = [_normalize_order(dict(order), controlled, real_ib) for order in orders]
    return {
        "mode": "REAL_IB_PAPER" if real_ib else "SIMULATOR_READ_ONLY",
        "connected": True,
        "kill_switch_active": bool(safety.is_killed),
        "positions": positions,
        "open_orders": normalized,
        "controlled_entry_ids": sorted(controlled),
        "cancelable_entry_count": sum(1 for order in normalized if order["can_cancel_entry"]),
    }


@router.post("/paper-ops/orders/{order_id}/cancel-entry")
async def cancel_manual_entry(order_id: str) -> dict[str, Any]:
    _require_real_ib_paper()
    safety, gateway = _deps()
    _positions, orders = await _broker_state(safety, gateway)
    controlled = _submitted_manual_entry_ids(safety)

    target = next((dict(order) for order in orders if str(order.get("order_id")) == str(order_id)), None)
    if target is None:
        raise HTTPException(404, "Open broker order not found")
    normalized = _normalize_order(target, controlled, real_ib=True)
    if normalized["control_role"] != "MANUAL_INTENT_ENTRY":
        raise HTTPException(403, f"Order is not a controllable manual-intent entry ({normalized['control_role']})")
    if not normalized["can_cancel_entry"]:
        raise HTTPException(409, "Entry is not currently cancelable")
    if normalized["parent_id"] is not None:
        raise HTTPException(403, "Protective child orders cannot be cancelled from this endpoint")

    try:
        broker_id = int(order_id)
    except ValueError as exc:
        raise HTTPException(409, "Real IB paper order IDs must be numeric") from exc

    try:
        requested = await gateway.cancel_order(broker_id)
    except Exception as exc:
        raise HTTPException(502, f"IB cancellation outcome is ambiguous: {exc}") from exc
    if requested is not True:
        raise HTTPException(502, "IB did not acknowledge the cancel request; verify broker state before retrying")

    # IB cancel is fire-and-forget. Do not claim the order is cancelled until a
    # later state refresh shows it gone / cancelled.
    return {
        "status": "CANCEL_REQUESTED",
        "order_id": str(order_id),
        "symbol": normalized.get("symbol"),
        "message": "Cancel request sent to IB paper. Refresh broker state to confirm.",
    }


@router.post("/paper-ops/flatten-all")
async def emergency_flatten_all(body: FlattenAllRequest) -> dict[str, Any]:
    _require_real_ib_paper()
    safety, gateway = _deps()
    if not _connected(gateway):
        raise HTTPException(503, "IB paper execution gateway is not connected")
    if body.confirmation != "FLATTEN ALL":
        raise HTTPException(422, "Exact confirmation text required")

    try:
        result = await safety.emergency_flatten_and_halt(
            reason="Command Center V2 RT-3 operator flatten-all"
        )
    except Exception as exc:
        raise HTTPException(502, f"Emergency flatten outcome is ambiguous: {exc}") from exc

    return {
        "status": "EMERGENCY_FLATTEN_REQUESTED",
        "kill_switch_activated": bool(result.get("kill_switch_activated", True)),
        "halt_level": result.get("halt_level"),
        "flattened": result.get("flattened", 0),
        "order_ids": result.get("order_ids", []),
        "errors": result.get("errors", []),
    }
