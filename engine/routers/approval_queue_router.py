"""
JARVIS TRADER — Autonomous Pipeline Approval Queue Router
==========================================================

HTTP surface for the human-in-the-loop approval queue produced by the
autonomous pipeline scheduler (engine/scheduler/pipeline_autonomous.py).

Prefix: /approvals

All routes require X-API-Key authentication (enforced by the global
APIKeyMiddleware wired in main.py — no per-route Depends() needed).

All non-GET operations log to JSONL at data/approval_audit.jsonl and
re-verify safety gates before executing anything that touches an order.

Design invariants (safety-review scope):
  - Approve endpoint re-checks kill-switch and LIVE_TRADING_ENABLED before
    submitting — these are NOT cached; they are read fresh on every call.
  - Approval only routes through safety_layer.submit_paper_order() — the same
    path used by the existing /pipeline/pending-approvals approve flow.
  - Expired candidates (status=pending AND expires_at <= now) are excluded from
    /pending and blocked from approval.
  - No route auto-starts the scheduler or modifies env vars.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from execution.submission_dedup import SubmissionDedup

logger = logging.getLogger("jarvis_trader.routers.approval_queue")

router = APIRouter(prefix="/approvals", tags=["approvals", "autonomous-queue"])

# ---------------------------------------------------------------------------
# Injected dependencies (set from main.py)
# ---------------------------------------------------------------------------

_safety_layer = None
_db_path: Optional[str] = None
# PaperTradeTracker injected at startup so an approved candidate writes its
# ledger row (paper_trades) alongside the broker submission. Without this the
# queue-approve path routed orders to IB but the dashboard ledger never saw
# them (386 approved queue rows with order_ids matched ZERO paper_trades rows,
# 2026-08-16 audit). The scanner path already does this via add_paper_trade.
_paper_tracker = None
# Shared cross-path submission dedup: this queue and the systematic bridge
# consult the SAME ledger so the same (symbol, action, trading_date) is never
# submitted twice when both paths are armed. Lazily created; overridable for tests.
_dedup: Optional[SubmissionDedup] = None

_AUDIT_LOG_PATH = Path("data/approval_audit.jsonl")


def _get_dedup() -> SubmissionDedup:
    """Return the shared submission-dedup ledger (default path), created lazily."""
    global _dedup
    if _dedup is None:
        _dedup = SubmissionDedup()
    return _dedup


def inject_approval_queue_deps(
    safety_layer, db_path: str, dedup: Optional[SubmissionDedup] = None, paper_tracker=None
) -> None:
    """Called from main.py during lifespan startup."""
    global _safety_layer, _db_path, _dedup, _paper_tracker
    _safety_layer = safety_layer
    _db_path = db_path
    if dedup is not None:
        _dedup = dedup
    _paper_tracker = paper_tracker
    # Ensure the approval queue table exists when the router is first wired.
    _ensure_schema(db_path)
    logger.info("ApprovalQueueRouter: dependencies injected (db=%s)", db_path)


# ---------------------------------------------------------------------------
# Schema bootstrap (idempotent)
# ---------------------------------------------------------------------------

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS pipeline_approval_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    symbol TEXT NOT NULL,
    direction TEXT NOT NULL,
    confidence REAL,
    verdict_json TEXT,
    expires_at TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    reviewed_at TEXT,
    reviewer_notes TEXT,
    order_id TEXT
);
"""

_CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_approval_queue_status_symbol
    ON pipeline_approval_queue(status, symbol, expires_at);
"""


def _ensure_schema(db_path: str) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(_CREATE_TABLE_SQL)
        conn.execute(_CREATE_INDEX_SQL)
        conn.commit()


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    # Parse verdict_json if present
    if d.get("verdict_json"):
        try:
            d["verdict"] = json.loads(d["verdict_json"])
        except Exception:
            d["verdict"] = None
    else:
        d["verdict"] = None
    # Surface the strategy name and its quarantine status so dashboard readers
    # (the /signals feed) don't have to duplicate VALIDATION_ONLY_STRATEGIES
    # client-side, where it would silently drift from the engine's gate.
    stark_signal = ""
    try:
        stark_signal = (
            (((d.get("verdict") or {}).get("analyst_reports") or {}).get("technical") or {})
            .get("indicators", {})
            .get("stark_signal", "")
            or ""
        ).upper()
    except Exception:
        pass
    d["stark_signal"] = stark_signal or None
    try:
        from agents.pipeline import VALIDATION_ONLY_STRATEGIES

        d["validation_only"] = bool(stark_signal) and stark_signal in VALIDATION_ONLY_STRATEGIES
    except Exception:
        d["validation_only"] = False
    return d


def _get_candidate(db_path: str, candidate_id: int) -> Optional[dict[str, Any]]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM pipeline_approval_queue WHERE id = ?",
            (candidate_id,),
        ).fetchone()
    return _row_to_dict(row) if row else None


def _list_pending(db_path: str) -> list[dict[str, Any]]:
    now_iso = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT * FROM pipeline_approval_queue
            WHERE status = 'pending' AND expires_at > ?
            ORDER BY created_at DESC
            """,
            (now_iso,),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def _list_history(db_path: str, days: int) -> list[dict[str, Any]]:
    from datetime import timedelta

    cutoff = (datetime.now(timezone.utc) - timedelta(days=max(1, days))).isoformat()
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT * FROM pipeline_approval_queue
            WHERE status IN ('approved', 'rejected', 'expired')
              AND created_at >= ?
            ORDER BY created_at DESC
            """,
            (cutoff,),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def _update_status(
    db_path: str,
    candidate_id: int,
    status: str,
    reviewer_notes: Optional[str] = None,
    order_id: Optional[str] = None,
) -> None:
    now_iso = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            UPDATE pipeline_approval_queue
               SET status = ?,
                   reviewed_at = ?,
                   reviewer_notes = ?,
                   order_id = ?
             WHERE id = ?
            """,
            (status, now_iso, reviewer_notes, order_id, candidate_id),
        )
        conn.commit()


def _expire_stale(db_path: str) -> int:
    """Mark all pending candidates past their expires_at as expired. Returns count."""
    now_iso = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(db_path) as conn:
        cur = conn.execute(
            """
            UPDATE pipeline_approval_queue
               SET status = 'expired', reviewed_at = ?
             WHERE status = 'pending' AND expires_at <= ?
            """,
            (now_iso, now_iso),
        )
        conn.commit()
        return cur.rowcount


# ---------------------------------------------------------------------------
# Audit logging
# ---------------------------------------------------------------------------


def _audit(event: str, candidate_id: int, extra: dict[str, Any]) -> None:
    """Append a JSONL audit record (best-effort, never raises)."""
    try:
        _AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "candidate_id": candidate_id,
            **extra,
        }
        with _AUDIT_LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    except Exception as exc:
        logger.warning("audit log write failed (non-fatal): %s", exc)


# ---------------------------------------------------------------------------
# Safety guard (re-checked on every approve call)
# ---------------------------------------------------------------------------


def _get_live_trading_enabled() -> bool:
    """Return settings.LIVE_TRADING_ENABLED (isolated for test-patching)."""
    try:
        from config import settings as _cfg

        return bool(_cfg.LIVE_TRADING_ENABLED)
    except Exception:
        return False


def _insert_candidate_direct(
    db_path: str,
    symbol: str,
    direction: str,
    confidence: float,
    verdict_json: str,
    ttl_seconds: int,
) -> int:
    """Thin wrapper around the scheduler's _insert_candidate for test convenience."""
    from scheduler.pipeline_autonomous import _insert_candidate

    return _insert_candidate(
        db_path=db_path,
        symbol=symbol,
        direction=direction,
        confidence=confidence,
        verdict_json=verdict_json,
        ttl_seconds=ttl_seconds,
    )


def _safety_guard_for_approve() -> tuple[bool, str]:
    """
    Re-verify that it is safe to submit a paper order right now.

    Returns (ok, reason).  ok=False → caller should raise HTTP 409.
    """
    # Belt-and-suspenders: always read LIVE_TRADING_ENABLED from config fresh
    if _get_live_trading_enabled():
        return (
            False,
            "LIVE_TRADING_ENABLED=True — approval queue refuses to submit in live mode",
        )

    if _safety_layer is None:
        return False, "safety_layer not injected"

    try:
        status = _safety_layer.get_status()
    except Exception as exc:
        return False, f"safety_layer.get_status() raised: {exc}"

    if status.get("kill_switch_active"):
        return False, "kill switch active"

    return True, "ok"


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class ApproveBody(BaseModel):
    entry_price: Optional[float] = Field(
        default=None,
        description="Override entry price (uses pipeline snapshot price if absent)",
    )


class RejectBody(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=2000)


class CandidateResponse(BaseModel):
    id: int
    created_at: str
    symbol: str
    direction: str
    confidence: Optional[float]
    expires_at: str
    status: str
    reviewed_at: Optional[str] = None
    reviewer_notes: Optional[str] = None
    order_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


def _require_db() -> str:
    if _db_path is None:
        raise HTTPException(503, detail="Approval queue DB not configured")
    return _db_path


@router.get("/pending", summary="List pending (non-expired) approval candidates")
async def list_pending() -> dict[str, Any]:
    db = _require_db()
    expired = _expire_stale(db)
    if expired:
        logger.info("ApprovalQueue: expired %d stale candidates on list_pending", expired)
    candidates = _list_pending(db)
    return {"count": len(candidates), "candidates": candidates}


@router.get("/history", summary="Historical approved/rejected/expired candidates")
async def get_history(days: int = 7) -> dict[str, Any]:
    # NOTE: must be registered BEFORE the parameterized /{candidate_id} route —
    # FastAPI matches routes in declaration order, so with this below it,
    # GET /approvals/history 422'd trying to parse "history" as an int
    # (found 2026-07-16; the route was unreachable dead code until then).
    db = _require_db()
    rows = _list_history(db, days)
    return {"days": days, "count": len(rows), "history": rows}


@router.get("/{candidate_id}", summary="Get single candidate detail")
async def get_candidate(candidate_id: int) -> dict[str, Any]:
    db = _require_db()
    row = _get_candidate(db, candidate_id)
    if row is None:
        raise HTTPException(404, detail=f"Candidate {candidate_id} not found")
    return row


@router.post("/{candidate_id}/approve", summary="Approve candidate — submits paper order")
async def approve_candidate(
    candidate_id: int, body: ApproveBody = ApproveBody()  # noqa: B008 (FastAPI default body)
) -> dict[str, Any]:
    db = _require_db()

    # Re-check safety gates (live-trading + kill-switch) every time
    ok, reason = _safety_guard_for_approve()
    if not ok:
        _audit("approve_refused", candidate_id, {"reason": reason})
        raise HTTPException(409, detail=f"Approval refused: {reason}")

    row = _get_candidate(db, candidate_id)
    if row is None:
        raise HTTPException(404, detail=f"Candidate {candidate_id} not found")

    if row["status"] != "pending":
        raise HTTPException(
            409,
            detail=f"Candidate {candidate_id} is already {row['status']} — cannot approve",
        )

    now_iso = datetime.now(timezone.utc).isoformat()
    if row["expires_at"] <= now_iso:
        _update_status(db, candidate_id, "expired")
        _audit("approve_refused_expired", candidate_id, {})
        raise HTTPException(410, detail=f"Candidate {candidate_id} has expired")

    # Validation-only strategies gate (BLOCKER 5 / §6.3): mirrors ensure_approval_allowed()
    # in approval.service so this queue path cannot bypass the scanner's strategy block.
    try:
        from agents.pipeline import VALIDATION_ONLY_STRATEGIES

        _verdict = row.get("verdict") or {}
        _stark_signal = (
            ((_verdict.get("analyst_reports") or {}).get("technical") or {})
            .get("indicators", {})
            .get("stark_signal", "")
            or ""
        ).upper()
        if _stark_signal and _stark_signal in VALIDATION_ONLY_STRATEGIES:
            _audit("approve_refused_validation_only", candidate_id, {"strategy": _stark_signal})
            raise HTTPException(
                409,
                detail=(
                    f"Strategy {_stark_signal} is in VALIDATION_ONLY_STRATEGIES — "
                    "manual approval is blocked until WFO validation + gate v2 PASS."
                ),
            )
    except HTTPException:
        raise
    except Exception as _vos_exc:
        logger.warning(
            "ApprovalQueue: VALIDATION_ONLY_STRATEGIES check raised (non-blocking): %s", _vos_exc
        )

    symbol = row["symbol"]

    # Gate v2 verdict authorization (PRB-22 sibling gap, found 2026-08-01): this
    # autonomous-scheduler approve path never called gate_v2_policy.is_strategy_authorized(),
    # unlike the manual/messaging-bot path in approval.service.ensure_approval_allowed(). PRB-22
    # (2026-07-29) closed the "enabled=False but still trades" half of this gap by adding an
    # enabled-boolean check to safety_layer.check_order(), but that check only reads the
    # PAPER_CONFIGS[symbol]["enabled"] flag -- it does not re-derive whether the specific
    # strategy's gate v2 verdict is a fresh PASS. A symbol can have enabled=True (as MES's
    # sma_trend config does, deliberately, per its own comment) while its verdict file is
    # INSUFFICIENT_SAMPLE/FAIL/stale, and this path would submit the order anyway. Mirrors the
    # exact check approval.service.ensure_approval_allowed() already runs for the manual path.
    try:
        from backtest.gate_v2_policy import is_strategy_authorized

        _authorized, _reason = is_strategy_authorized(symbol)
        if not _authorized:
            _audit("approve_refused_gate_v2", candidate_id, {"symbol": symbol, "reason": _reason})
            raise HTTPException(
                409,
                detail=f"{symbol} is not authorized for paper orders: {_reason}",
            )
    except HTTPException:
        raise
    except Exception as _gate_exc:
        logger.warning(
            "ApprovalQueue: gate_v2_policy.is_strategy_authorized check raised (non-blocking): %s",
            _gate_exc,
        )

    direction = row["direction"]

    # Derive entry price: caller override > pipeline snapshot > reject
    entry_price = body.entry_price
    if entry_price is None:
        verdict = row.get("verdict") or {}
        trade_dec = verdict.get("trade_decision") or {}
        entry_price = (
            trade_dec.get("limit_price")
            or trade_dec.get("entry_price")
            or trade_dec.get("stop_price")
        )
    if entry_price is None:
        raise HTTPException(
            422,
            detail=(
                "No entry_price in pipeline snapshot; supply one in the request body. "
                'Example: {"entry_price": 2150.50}'
            ),
        )
    entry_price = float(entry_price)

    action = "BUY" if direction == "LONG" else "SELL"

    # Cross-path dedup: if the systematic bridge (or a prior approve) already
    # submitted this (symbol, action, trading_date) today, skip to avoid a 2x
    # double-fill across the two armed paper paths. First-submission-wins.
    dedup = _get_dedup()
    trading_date = datetime.now(timezone.utc).date()
    dkey = dedup.make_key(symbol, action, trading_date)
    if dedup.already_submitted(dkey):
        _audit("approve_skipped_cross_path", candidate_id, {"key": dkey})
        raise HTTPException(
            409,
            detail=(
                f"Another path already submitted {symbol} {action} for "
                f"{trading_date.isoformat()} (cross-path dedup) — not re-submitting."
            ),
        )

    # Submit via the existing safety_layer.submit_paper_order path
    try:
        result = await _safety_layer.submit_paper_order(
            symbol=symbol,
            action=action,
            quantity=1,
            price=entry_price,
            order_type="MKT",
            limit_price=None,
        )
    except Exception as exc:
        _audit("approve_submit_error", candidate_id, {"error": str(exc)})
        raise HTTPException(502, detail=f"Paper order submission raised: {exc}") from exc

    if not result.get("approved", False):
        reason_from_result = str(result.get("reason", "safety layer blocked order"))
        _audit("approve_submit_rejected", candidate_id, {"reason": reason_from_result})
        raise HTTPException(
            409,
            detail=f"Safety layer rejected order: {reason_from_result}",
        )

    order_id = str(result.get("order_id") or result.get("fill_id") or "")
    _update_status(db, candidate_id, "approved", order_id=order_id)

    # ── Ledger write: the queue-approve path previously routed the order to IB
    # but never recorded the paper_trades row, so the dashboard/validation
    # ledger never saw queue-approved trades (386 approved rows matched ZERO
    # paper_trades, 2026-08-16 audit). Mirror the scanner path: write the ledger
    # row with stop/target lifted from the pipeline snapshot. Best-effort — a
    # ledger failure must not fail the already-submitted order (the queue row is
    # the audit record of the broker submission).
    if _paper_tracker is not None:
        try:
            _snap = row.get("verdict") or {}
            _td = _snap.get("trade_decision") or {}
            _stop = _td.get("stop_price") or _td.get("stop_loss") or None
            _tgt = (
                _td.get("target_1")
                or _td.get("target_price")
                or _td.get("take_profit")
                or _td.get("target_2")
                or None
            )
            _ledger_trade_id = _paper_tracker.add_paper_trade(
                symbol=symbol,
                side=action.lower(),
                quantity=1.0,
                entry_price=float(entry_price),
                stop_loss=float(_stop) if _stop is not None else None,
                take_profit=float(_tgt) if _tgt is not None else None,
                strategy_params={
                    "source": "approval_queue",
                    "candidate_id": candidate_id,
                    "direction": direction.upper(),
                },
            )
            _audit("ledger_written", candidate_id, {"trade_id": _ledger_trade_id})
        except Exception as _ledger_exc:
            logger.warning(
                "ApprovalQueue: ledger write failed for approved candidate %d "
                "(order already submitted): %s",
                candidate_id,
                _ledger_exc,
            )

    # Claim the shared cross-path slot only on an APPROVED submit, so a rejected
    # order never blocks the other path. Idempotent (no-op if already recorded).
    dedup.record(
        dkey,
        source="queue",
        native_id=str(candidate_id),
        extra={"order_id": order_id, "symbol": symbol, "action": action},
    )
    _audit(
        "approved",
        candidate_id,
        {
            "symbol": symbol,
            "direction": direction,
            "entry_price": entry_price,
            "order_id": order_id,
        },
    )
    logger.info(
        "ApprovalQueue: candidate %d APPROVED — %s %s @ %.2f → order_id=%s",
        candidate_id,
        symbol,
        direction,
        entry_price,
        order_id,
    )

    # Fire-and-forget Discord notification — never blocks the approve response
    try:
        import asyncio as _asyncio

        from notifications.discord_webhook import post_approval_result as _post_result

        _asyncio.create_task(
            _post_result(
                candidate_id,
                "approved",
                order_id=order_id or None,
                symbol=symbol,
                direction=direction,
            )
        )
    except Exception as _wh_exc:
        logger.warning(
            "ApprovalQueue: Discord webhook task creation failed (non-fatal): %s", _wh_exc
        )

    return {
        "status": "approved",
        "candidate_id": candidate_id,
        "symbol": symbol,
        "direction": direction,
        "entry_price": entry_price,
        "order_id": order_id,
        "order_result": result,
    }


@router.post("/{candidate_id}/reject", summary="Reject a pending candidate")
async def reject_candidate(
    candidate_id: int, body: RejectBody = RejectBody()  # noqa: B008 (FastAPI default body)
) -> dict[str, Any]:
    db = _require_db()
    row = _get_candidate(db, candidate_id)
    if row is None:
        raise HTTPException(404, detail=f"Candidate {candidate_id} not found")
    if row["status"] != "pending":
        raise HTTPException(
            409,
            detail=f"Candidate {candidate_id} is already {row['status']} — cannot reject",
        )
    _update_status(db, candidate_id, "rejected", reviewer_notes=body.reason)
    _audit("rejected", candidate_id, {"reason": body.reason})
    logger.info(
        "ApprovalQueue: candidate %d REJECTED — reason=%s",
        candidate_id,
        body.reason,
    )

    # Fire-and-forget Discord notification — never blocks the reject response
    try:
        import asyncio as _asyncio

        from notifications.discord_webhook import post_approval_result as _post_result

        _asyncio.create_task(
            _post_result(
                candidate_id,
                "rejected",
                notes=body.reason or "",
                symbol=row.get("symbol") or "",
                direction=row.get("direction") or "",
            )
        )
    except Exception as _wh_exc:
        logger.warning(
            "ApprovalQueue: Discord webhook task creation failed (non-fatal): %s", _wh_exc
        )

    return {
        "status": "rejected",
        "candidate_id": candidate_id,
        "reason": body.reason,
    }


# ---------------------------------------------------------------------------
# Extend endpoint — for Discord ⏸ reaction (adds TTL without approving/rejecting)
# ---------------------------------------------------------------------------

_EXTEND_MIN_MINUTES = 5
_EXTEND_MAX_MINUTES = 120


def _extend_candidate_ttl(db_path: str, candidate_id: int, minutes: int) -> str:
    """
    Push the expires_at timestamp forward by `minutes` from now.

    Returns the new ISO-format expires_at string.
    """
    from datetime import timedelta

    now = datetime.now(timezone.utc)
    new_expiry = now + timedelta(minutes=minutes)
    new_expiry_iso = new_expiry.isoformat()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE pipeline_approval_queue SET expires_at = ? WHERE id = ?",
            (new_expiry_iso, candidate_id),
        )
        conn.commit()
    return new_expiry_iso


@router.post(
    "/{candidate_id}/extend",
    summary="Extend TTL of a pending candidate (Discord ⏸ reaction)",
)
async def extend_candidate(candidate_id: int, minutes: int = 30) -> dict[str, Any]:
    """
    Extend the expiry of a *pending* approval candidate.

    Query parameter:
      minutes (int, 5–120): how many minutes to add from now. Default 30.
                            Values outside [5, 120] are clamped silently.

    Cannot extend a candidate that has already been approved, rejected, or expired.

    Requires X-API-Key authentication (enforced by APIKeyMiddleware in main.py).
    """
    db = _require_db()

    # Clamp extension window
    clamped = max(_EXTEND_MIN_MINUTES, min(minutes, _EXTEND_MAX_MINUTES))
    if clamped != minutes:
        logger.info(
            "ApprovalQueue: extend candidate %d — minutes=%d clamped to %d",
            candidate_id,
            minutes,
            clamped,
        )

    row = _get_candidate(db, candidate_id)
    if row is None:
        raise HTTPException(404, detail=f"Candidate {candidate_id} not found")

    if row["status"] != "pending":
        raise HTTPException(
            409,
            detail=(
                f"Candidate {candidate_id} is already {row['status']} — "
                "can only extend pending candidates"
            ),
        )

    new_expiry = _extend_candidate_ttl(db, candidate_id, clamped)
    _audit(
        "extended",
        candidate_id,
        {
            "minutes_requested": minutes,
            "minutes_applied": clamped,
            "new_expires_at": new_expiry,
            "symbol": row.get("symbol"),
            "direction": row.get("direction"),
        },
    )
    logger.info(
        "ApprovalQueue: candidate %d EXTENDED by %d min — new expiry %s",
        candidate_id,
        clamped,
        new_expiry,
    )
    return {
        "status": "extended",
        "candidate_id": candidate_id,
        "minutes_applied": clamped,
        "expires_at": new_expiry,
        "symbol": row.get("symbol"),
        "direction": row.get("direction"),
    }
