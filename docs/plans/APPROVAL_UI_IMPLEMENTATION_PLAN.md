# Trade Approval UI — Implementation Plan
**Priority:** P0 — Blocks all real paper trading**
**Estimated Effort:** 4–6 hours total
**Date:** 2026-04-02

---

## The Problem (Exact Code State)

`engine/agents/pipeline.py` returns `requires_human: True` and `final_action: "pending_human_approval"` but:

1. **No approval store exists** — approvals are not persisted anywhere
2. **Pipeline router auto-logs trades immediately** (`pipeline_router.py` line ~316) without checking the approval flag
3. **No backend endpoints exist** for listing or acting on pending approvals
4. **No dashboard UI** for Matt to confirm or reject

Every signal that clears all 5 pipeline stages is either silently discarded or auto-executed — neither is correct.

---

## Architecture Decision

**Approach: SQLite-backed approval store + polling dashboard panel**

Why not WebSocket push? The approval flow is low-frequency (a few signals per day). SWR polling every 5 seconds is simpler, requires no new WebSocket channel, and matches every other component in the dashboard. Add push later if latency becomes an issue.

Why SQLite and not in-memory? Engine restarts (which happen often — `restart_engine.ps1`) would wipe in-memory state. A SQLite table survives restarts and gives an audit trail automatically.

---

## Implementation Map

```
Phase 1 — Backend (engine/)           ~2.5 hrs
  Step 1.1  ApprovalStore class       engine/approval/store.py
  Step 1.2  Pydantic models           engine/approval/models.py
  Step 1.3  Approvals router          engine/routers/pipeline/pending-approvals_router.py
  Step 1.4  Wire router into main.py  engine/main.py  (1 import, 1 include_router)
  Step 1.5  Patch pipeline_router     engine/routers/pipeline_router.py  (gate auto-log)

Phase 2 — Frontend (dashboard/)       ~1.5 hrs
  Step 2.1  Add types to api.ts       dashboard/lib/api.ts
  Step 2.2  ApprovalPanel component   dashboard/components/ApprovalPanel.tsx
  Step 2.3  Mount on command-center   dashboard/app/command-center/page.tsx

Phase 3 — Tests                       ~1 hr
  Step 3.1  Backend unit tests        engine/tests/test_approvals.py
  Step 3.2  Manual smoke test         (checklist at end of this doc)
```

---

## Phase 1 — Backend

### Step 1.1 — Create `engine/approval/store.py`

Create a new directory `engine/approval/` with an `__init__.py` and `store.py`.

**`engine/approval/__init__.py`** — empty file.

**`engine/approval/store.py`:**

```python
"""
Approval store — SQLite-backed persistence for pending trade approvals.

Design:
- Single table: trade_approvals
- Status enum: pending | approved | rejected | expired
- Approvals older than APPROVAL_TTL_SECONDS auto-expire on read
- Thread-safe via asyncio.Lock
"""

import asyncio
import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Approvals expire after 4 hours if not acted on (covers RTH session)
APPROVAL_TTL_SECONDS = 4 * 60 * 60

DB_PATH = Path("data/jarvis_trader.db")


class ApprovalStore:
    """Persistent store for trade approvals backed by SQLite."""

    _lock: asyncio.Lock

    def __init__(self, db_path: Path = DB_PATH) -> None:
        self._db_path = db_path
        self._lock = asyncio.Lock()
        self._init_table()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _init_table(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS trade_approvals (
                    approval_id     TEXT PRIMARY KEY,
                    symbol          TEXT NOT NULL,
                    action          TEXT NOT NULL,   -- buy | sell
                    quantity        INTEGER NOT NULL,
                    confidence      REAL,
                    rationale       TEXT,
                    regime          TEXT,
                    stc_value       REAL,
                    pipeline_result TEXT,            -- full JSON blob
                    status          TEXT NOT NULL DEFAULT 'pending',
                    created_at      TEXT NOT NULL,
                    decided_at      TEXT,
                    decision_note   TEXT
                )
            """)
            conn.commit()
        logger.info("ApprovalStore initialised at %s", self._db_path)

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    async def create(
        self,
        symbol: str,
        action: str,
        quantity: int,
        pipeline_result: dict,
    ) -> str:
        """Persist a new pending approval. Returns the approval_id (UUID)."""
        import json

        approval_id = str(uuid.uuid4())
        trade = pipeline_result.get("trade_decision", {})
        tech = pipeline_result.get("analyst_reports", {}).get("technical", {})

        async with self._lock:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO trade_approvals
                        (approval_id, symbol, action, quantity, confidence,
                         rationale, regime, stc_value, pipeline_result,
                         status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
                    """,
                    (
                        approval_id,
                        symbol,
                        action,
                        quantity,
                        trade.get("confidence"),
                        trade.get("rationale"),
                        tech.get("regime"),
                        tech.get("stc_value"),
                        json.dumps(pipeline_result),
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )
                conn.commit()

        logger.info("Approval created: %s %s %s x%d", approval_id[:8], action, symbol, quantity)
        return approval_id

    async def decide(
        self,
        approval_id: str,
        status: str,   # "approved" | "rejected"
        note: Optional[str] = None,
    ) -> bool:
        """Record a human decision. Returns False if approval not found or not pending."""
        async with self._lock:
            with sqlite3.connect(self._db_path) as conn:
                row = conn.execute(
                    "SELECT status FROM trade_approvals WHERE approval_id = ?",
                    (approval_id,),
                ).fetchone()

                if not row:
                    logger.warning("Approval %s not found", approval_id)
                    return False
                if row[0] != "pending":
                    logger.warning("Approval %s already %s", approval_id, row[0])
                    return False

                conn.execute(
                    """
                    UPDATE trade_approvals
                    SET status = ?, decided_at = ?, decision_note = ?
                    WHERE approval_id = ?
                    """,
                    (
                        status,
                        datetime.now(timezone.utc).isoformat(),
                        note,
                        approval_id,
                    ),
                )
                conn.commit()

        logger.info("Approval %s → %s", approval_id[:8], status)
        return True

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def get_pending(self) -> list[dict]:
        """Return all non-expired pending approvals, newest first."""
        import json
        from datetime import timedelta

        cutoff = (
            datetime.now(timezone.utc) - timedelta(seconds=APPROVAL_TTL_SECONDS)
        ).isoformat()

        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT * FROM trade_approvals
                WHERE status = 'pending' AND created_at > ?
                ORDER BY created_at DESC
                """,
                (cutoff,),
            ).fetchall()

        return [dict(r) for r in rows]

    async def get_history(self, limit: int = 50) -> list[dict]:
        """Return recent approval decisions (all statuses), newest first."""
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT approval_id, symbol, action, quantity, confidence,
                       regime, status, created_at, decided_at, decision_note
                FROM trade_approvals
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        return [dict(r) for r in rows]

    async def get_one(self, approval_id: str) -> Optional[dict]:
        """Return a single approval record by ID."""
        import json

        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM trade_approvals WHERE approval_id = ?",
                (approval_id,),
            ).fetchone()

        if not row:
            return None
        result = dict(row)
        # Deserialise the heavy pipeline blob only when explicitly requested
        if result.get("pipeline_result"):
            result["pipeline_result"] = json.loads(result["pipeline_result"])
        return result


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_approval_store: Optional[ApprovalStore] = None


def get_approval_store() -> ApprovalStore:
    global _approval_store
    if _approval_store is None:
        _approval_store = ApprovalStore()
    return _approval_store
```

---

### Step 1.2 — Create `engine/approval/models.py`

```python
"""Pydantic v2 models for the approval API surface."""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class PendingApproval(BaseModel):
    approval_id: str
    symbol: str
    action: str                     # "buy" | "sell"
    quantity: int
    confidence: Optional[float]
    rationale: Optional[str]
    regime: Optional[str]
    stc_value: Optional[float]
    status: str                     # always "pending" in this context
    created_at: str
    age_seconds: Optional[float] = None


class ApprovalHistoryItem(BaseModel):
    approval_id: str
    symbol: str
    action: str
    quantity: int
    confidence: Optional[float]
    regime: Optional[str]
    status: str                     # pending | approved | rejected | expired
    created_at: str
    decided_at: Optional[str]
    decision_note: Optional[str]


class ApprovalDecisionRequest(BaseModel):
    note: Optional[str] = Field(None, description="Optional reason for this decision")


class ApprovalDetailResponse(BaseModel):
    """Full detail including heavy pipeline_result blob."""
    approval_id: str
    symbol: str
    action: str
    quantity: int
    confidence: Optional[float]
    rationale: Optional[str]
    regime: Optional[str]
    stc_value: Optional[float]
    pipeline_result: Optional[dict]
    status: str
    created_at: str
    decided_at: Optional[str]
    decision_note: Optional[str]
```

---

### Step 1.3 — Create `engine/routers/pipeline/pending-approvals_router.py`

```python
"""
Approval router — human-in-the-loop trade confirmation endpoints.

Endpoints
---------
GET  /pipeline/pending-approvals              List all pending approvals
GET  /pipeline/pending-approvals/{id}         Full detail (includes pipeline_result)
POST /pipeline/pending-approvals/{id}/approve         Approve a pending trade
POST /pipeline/pending-approvals/{id}/reject          Reject a pending trade
GET  /pipeline/pending-approvals/history              Audit trail (last 50)
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from approval.models import (
    ApprovalDecisionRequest,
    ApprovalDetailResponse,
    ApprovalHistoryItem,
    PendingApproval,
)
from approval.store import get_approval_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/pipeline/pending-approvals", tags=["approvals"])


# ---------------------------------------------------------------------------
# GET /pipeline/pending-approvals
# ---------------------------------------------------------------------------

@router.get("/pending", response_model=list[PendingApproval])
async def list_pending_approvals():
    """Return all non-expired pending trade approvals."""
    store = get_approval_store()
    rows = await store.get_pending()

    now = datetime.now(timezone.utc)
    result = []
    for r in rows:
        created = datetime.fromisoformat(r["created_at"])
        age = (now - created).total_seconds()
        result.append(PendingApproval(**r, age_seconds=age))

    return result


# ---------------------------------------------------------------------------
# GET /pipeline/pending-approvals/{approval_id}
# ---------------------------------------------------------------------------

@router.get("/pending/{approval_id}", response_model=ApprovalDetailResponse)
async def get_pending_approval(approval_id: str):
    """Full detail for a single pending approval, including the pipeline result."""
    store = get_approval_store()
    record = await store.get_one(approval_id)

    if not record:
        raise HTTPException(status_code=404, detail=f"Approval {approval_id} not found")
    if record["status"] != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"Approval {approval_id} is already {record['status']}",
        )

    return ApprovalDetailResponse(**record)


# ---------------------------------------------------------------------------
# POST /pipeline/pending-approvals/{approval_id}/approve
# ---------------------------------------------------------------------------

@router.post("/{approval_id}/approve")
async def approve_trade(approval_id: str, body: ApprovalDecisionRequest = ApprovalDecisionRequest()):
    """
    Approve a pending trade. The execution layer will pick this up and
    route the order to IB Gateway paper account.
    """
    store = get_approval_store()
    ok = await store.decide(approval_id, "approved", note=body.note)

    if not ok:
        raise HTTPException(
            status_code=404,
            detail=f"Approval {approval_id} not found or already decided",
        )

    # TODO Sprint 12+: trigger actual IB order submission here
    # For now, approval is recorded — the execution wiring will read it
    logger.info("Trade APPROVED by human: %s (note: %s)", approval_id[:8], body.note)

    return {
        "approval_id": approval_id,
        "status": "approved",
        "decided_at": datetime.now(timezone.utc).isoformat(),
        "message": "Trade approved. Execution wiring will route to IB Gateway.",
    }


# ---------------------------------------------------------------------------
# POST /pipeline/pending-approvals/{approval_id}/reject
# ---------------------------------------------------------------------------

@router.post("/{approval_id}/reject")
async def reject_trade(approval_id: str, body: ApprovalDecisionRequest = ApprovalDecisionRequest()):
    """Reject a pending trade. No order will be placed."""
    store = get_approval_store()
    ok = await store.decide(approval_id, "rejected", note=body.note)

    if not ok:
        raise HTTPException(
            status_code=404,
            detail=f"Approval {approval_id} not found or already decided",
        )

    logger.info("Trade REJECTED by human: %s (note: %s)", approval_id[:8], body.note)

    return {
        "approval_id": approval_id,
        "status": "rejected",
        "decided_at": datetime.now(timezone.utc).isoformat(),
        "message": "Trade rejected. No order will be placed.",
    }


# ---------------------------------------------------------------------------
# GET /pipeline/pending-approvals/history
# ---------------------------------------------------------------------------

@router.get("/history", response_model=list[ApprovalHistoryItem])
async def get_approval_history(limit: int = 50):
    """Return the last N approval decisions for audit purposes."""
    store = get_approval_store()
    rows = await store.get_history(limit=limit)
    return [ApprovalHistoryItem(**r) for r in rows]
```

---

### Step 1.4 — Wire into `engine/main.py`

Find the router registration block (the cluster of `app.include_router(...)` calls). Add two lines:

**Import** (with the other router imports, alphabetically):
```python
from routers.approvals_router import router as approvals_router
```

**Register** (with the other `include_router` calls):
```python
app.include_router(approvals_router)
```

That's it — two lines. The prefix `/pipeline/pending-approvals` is already set in the router itself.

---

### Step 1.5 — Patch `engine/routers/pipeline_router.py`

The current code auto-logs a paper trade as soon as `final_action` is LONG or SHORT, without checking `requires_human`. This is the root of the problem.

**Find the block** around line 295–355 that logs paper trades. It looks approximately like:

```python
# CURRENT (auto-logs immediately — WRONG)
if final_action in ("buy", "sell", "long", "short"):
    # ... log the trade to paper trades table
```

**Replace the condition** to gate on `requires_human`:

```python
# PATCHED — only auto-log if human approval is NOT required
requires_human = result.get("requires_human", True)   # default True = safe

if final_action in ("buy", "sell", "long", "short") and not requires_human:
    # ... existing auto-log code unchanged ...
    pass

elif final_action in ("buy", "sell", "long", "short") and requires_human:
    # Store pending approval instead of executing
    from approval.store import get_approval_store
    store = get_approval_store()
    approval_id = await store.create(
        symbol=symbol,
        action=final_action,
        quantity=result.get("final_quantity", 1),
        pipeline_result=result,
    )
    logger.info(
        "Trade pending human approval: %s → approval_id=%s",
        symbol, approval_id[:8]
    )
    result["approval_id"] = approval_id
    result["approval_status"] = "pending"
```

**Also patch the return** at the end of the route handler to include the `approval_id` when present:

```python
return {
    "status": "complete",
    "symbol": symbol,
    "final_action": final_action,
    "requires_human": requires_human,
    "approval_id": result.get("approval_id"),          # NEW
    "approval_status": result.get("approval_status"),  # NEW
    # ... rest of existing fields unchanged ...
}
```

---

## Phase 2 — Frontend

### Step 2.1 — Add types to `dashboard/lib/api.ts`

Append these types to the existing type block. Do NOT redefine `fetchEngine` or `postEngine`.

```typescript
// ─── Trade Approvals ──────────────────────────────────────────────────────

export interface PendingApproval {
  approval_id: string;
  symbol: string;
  action: "buy" | "sell";
  quantity: number;
  confidence: number | null;
  rationale: string | null;
  regime: string | null;
  stc_value: number | null;
  status: "pending";
  created_at: string;
  age_seconds: number | null;
}

export interface ApprovalHistoryItem {
  approval_id: string;
  symbol: string;
  action: string;
  quantity: number;
  confidence: number | null;
  regime: string | null;
  status: "pending" | "approved" | "rejected" | "expired";
  created_at: string;
  decided_at: string | null;
  decision_note: string | null;
}

export interface ApprovalDecisionResult {
  approval_id: string;
  status: "approved" | "rejected";
  decided_at: string;
  message: string;
}
```

---

### Step 2.2 — Create `dashboard/components/ApprovalPanel.tsx`

Create a new file. This is the entire component — copy exactly.

```tsx
"use client";

/**
 * ApprovalPanel — human-in-the-loop trade confirmation widget.
 *
 * Polls /pipeline/pending-approvals every 5 seconds.
 * Shows a card per pending approval with Approve / Reject buttons.
 * Shows the last 10 decided approvals in a compact history table.
 */

import { useState, useCallback } from "react";
import useSWR from "swr";
import { CheckCircle, XCircle, Clock, AlertTriangle, TrendingUp, TrendingDown } from "lucide-react";
import { fetchEngine, postEngine } from "@/lib/api";
import type { PendingApproval, ApprovalHistoryItem, ApprovalDecisionResult } from "@/lib/api";

// ── SWR fetchers ─────────────────────────────────────────────────────────────

const fetchPending = (url: string) =>
  fetchEngine<PendingApproval[]>(url).then((r) => r ?? []);

const fetchHistory = (url: string) =>
  fetchEngine<ApprovalHistoryItem[]>(url).then((r) => r ?? []);

// ── Helpers ───────────────────────────────────────────────────────────────────

function ageLabel(seconds: number | null): string {
  if (seconds === null) return "—";
  if (seconds < 60) return `${Math.round(seconds)}s ago`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
  return `${Math.round(seconds / 3600)}h ago`;
}

function confidenceColor(c: number | null): string {
  if (c === null) return "text-zinc-400";
  if (c >= 0.75) return "text-emerald-400";
  if (c >= 0.55) return "text-yellow-400";
  return "text-red-400";
}

// ── Main component ────────────────────────────────────────────────────────────

export default function ApprovalPanel() {
  const [deciding, setDeciding] = useState<Record<string, boolean>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});

  const {
    data: pending = [],
    mutate: mutatePending,
  } = useSWR("/pipeline/pending-approvals", fetchPending, {
    refreshInterval: 5000,
    revalidateOnFocus: true,
  });

  const {
    data: history = [],
    mutate: mutateHistory,
  } = useSWR("/pipeline/pending-approvals/history?limit=10", fetchHistory, {
    refreshInterval: 10000,
  });

  const decide = useCallback(
    async (approvalId: string, decision: "approve" | "reject") => {
      setDeciding((d) => ({ ...d, [approvalId]: true }));
      setErrors((e) => ({ ...e, [approvalId]: "" }));

      try {
        await postEngine<ApprovalDecisionResult>(
          `/pipeline/pending-approvals/${approvalId}/${decision}`,
          {}
        );
        await mutatePending();
        await mutateHistory();
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : "Request failed";
        setErrors((e) => ({ ...e, [approvalId]: msg }));
      } finally {
        setDeciding((d) => ({ ...d, [approvalId]: false }));
      }
    },
    [mutatePending, mutateHistory]
  );

  // ── Render ──────────────────────────────────────────────────────────────────

  return (
    <div className="space-y-4">

      {/* ── Header ── */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 text-amber-400" />
          <span className="text-sm font-semibold text-zinc-100 uppercase tracking-wider">
            Pending Approvals
          </span>
          {pending.length > 0 && (
            <span className="bg-amber-500 text-black text-xs font-bold px-2 py-0.5 rounded-full">
              {pending.length}
            </span>
          )}
        </div>
      </div>

      {/* ── Pending cards ── */}
      {pending.length === 0 ? (
        <div className="text-xs text-zinc-500 py-3 text-center border border-zinc-800 rounded-lg">
          No pending approvals
        </div>
      ) : (
        <div className="space-y-3">
          {pending.map((appr) => (
            <div
              key={appr.approval_id}
              className="border border-amber-500/40 bg-amber-950/20 rounded-lg p-4 space-y-3"
            >
              {/* Symbol + direction */}
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  {appr.action === "buy" ? (
                    <TrendingUp className="w-5 h-5 text-emerald-400" />
                  ) : (
                    <TrendingDown className="w-5 h-5 text-red-400" />
                  )}
                  <span className="font-bold text-lg text-zinc-100">
                    {appr.symbol}
                  </span>
                  <span
                    className={`text-sm font-semibold uppercase px-2 py-0.5 rounded ${
                      appr.action === "buy"
                        ? "bg-emerald-900/50 text-emerald-400"
                        : "bg-red-900/50 text-red-400"
                    }`}
                  >
                    {appr.action}
                  </span>
                  <span className="text-zinc-400 text-sm">
                    × {appr.quantity}
                  </span>
                </div>
                <div className="flex items-center gap-1 text-xs text-zinc-500">
                  <Clock className="w-3 h-3" />
                  {ageLabel(appr.age_seconds)}
                </div>
              </div>

              {/* Signal details */}
              <div className="grid grid-cols-3 gap-2 text-xs">
                <div>
                  <div className="text-zinc-500">Confidence</div>
                  <div className={`font-mono font-semibold ${confidenceColor(appr.confidence)}`}>
                    {appr.confidence !== null
                      ? `${(appr.confidence * 100).toFixed(0)}%`
                      : "—"}
                  </div>
                </div>
                <div>
                  <div className="text-zinc-500">Regime</div>
                  <div className="font-mono text-zinc-300">
                    {appr.regime ?? "—"}
                  </div>
                </div>
                <div>
                  <div className="text-zinc-500">STC</div>
                  <div className="font-mono text-zinc-300">
                    {appr.stc_value !== null
                      ? appr.stc_value.toFixed(1)
                      : "—"}
                  </div>
                </div>
              </div>

              {/* Rationale */}
              {appr.rationale && (
                <p className="text-xs text-zinc-400 leading-relaxed border-t border-zinc-800 pt-2">
                  {appr.rationale.slice(0, 280)}
                  {appr.rationale.length > 280 ? "…" : ""}
                </p>
              )}

              {/* Error message */}
              {errors[appr.approval_id] && (
                <p className="text-xs text-red-400">
                  {errors[appr.approval_id]}
                </p>
              )}

              {/* Action buttons */}
              <div className="flex gap-2 pt-1">
                <button
                  onClick={() => decide(appr.approval_id, "approve")}
                  disabled={deciding[appr.approval_id]}
                  className="flex-1 flex items-center justify-center gap-2 bg-emerald-700 hover:bg-emerald-600 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-semibold py-2 rounded-lg transition-colors"
                >
                  <CheckCircle className="w-4 h-4" />
                  {deciding[appr.approval_id] ? "…" : "Approve"}
                </button>
                <button
                  onClick={() => decide(appr.approval_id, "reject")}
                  disabled={deciding[appr.approval_id]}
                  className="flex-1 flex items-center justify-center gap-2 bg-red-800 hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-semibold py-2 rounded-lg transition-colors"
                >
                  <XCircle className="w-4 h-4" />
                  {deciding[appr.approval_id] ? "…" : "Reject"}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* ── History ── */}
      {history.length > 0 && (
        <div className="mt-4">
          <div className="text-xs text-zinc-500 uppercase tracking-wider mb-2">
            Recent Decisions
          </div>
          <div className="space-y-1">
            {history.map((h) => (
              <div
                key={h.approval_id}
                className="flex items-center justify-between text-xs py-1 border-b border-zinc-800/50"
              >
                <div className="flex items-center gap-2">
                  {h.status === "approved" ? (
                    <CheckCircle className="w-3 h-3 text-emerald-400" />
                  ) : h.status === "rejected" ? (
                    <XCircle className="w-3 h-3 text-red-400" />
                  ) : (
                    <Clock className="w-3 h-3 text-zinc-500" />
                  )}
                  <span className="text-zinc-300 font-mono">{h.symbol}</span>
                  <span className="text-zinc-500 uppercase">{h.action}</span>
                  <span className="text-zinc-600">×{h.quantity}</span>
                </div>
                <div className="flex items-center gap-2">
                  <span
                    className={`uppercase font-semibold ${
                      h.status === "approved"
                        ? "text-emerald-400"
                        : h.status === "rejected"
                        ? "text-red-400"
                        : "text-zinc-500"
                    }`}
                  >
                    {h.status}
                  </span>
                  <span className="text-zinc-600">
                    {h.decided_at
                      ? new Date(h.decided_at).toLocaleTimeString([], {
                          hour: "2-digit",
                          minute: "2-digit",
                        })
                      : "—"}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
```

---

### Step 2.3 — Mount on `dashboard/app/command-center/page.tsx`

The command center is already the trading operations hub — this is the right home. Make two changes:

**Add the import** near the top of the file (with other component imports):
```tsx
import ApprovalPanel from "@/components/ApprovalPanel";
```

**Mount it** in the JSX. Find the grid or column layout — add the panel as a full-width card in a prominent position, ideally above the positions list or alongside the kill switch. Something like:

```tsx
{/* Trade Approvals — REQUIRE_HUMAN_APPROVAL gate */}
<Card className="border-amber-500/30 bg-zinc-900/50">
  <CardHeader className="pb-2">
    <CardTitle className="text-sm">Trade Approvals</CardTitle>
  </CardHeader>
  <CardContent>
    <ApprovalPanel />
  </CardContent>
</Card>
```

The exact placement depends on the current grid. The important rule: **it must be above the fold** — Matt should see pending approvals the moment the command center loads, not have to scroll.

---

## Phase 3 — Tests

### Step 3.1 — Create `engine/tests/test_approvals.py`

```python
"""Tests for the trade approval store and API endpoints."""

import asyncio
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from approval.store import ApprovalStore


# ── Store unit tests ──────────────────────────────────────────────────────────

@pytest.fixture
def store(tmp_path):
    """Fresh in-memory store backed by a temp SQLite file."""
    return ApprovalStore(db_path=tmp_path / "test.db")


@pytest.mark.asyncio
async def test_create_and_get_pending(store):
    approval_id = await store.create(
        symbol="MCL",
        action="buy",
        quantity=1,
        pipeline_result={"trade_decision": {"confidence": 0.82, "rationale": "Test"}},
    )
    assert approval_id

    pending = await store.get_pending()
    assert len(pending) == 1
    assert pending[0]["symbol"] == "MCL"
    assert pending[0]["status"] == "pending"


@pytest.mark.asyncio
async def test_approve(store):
    approval_id = await store.create("MCL", "buy", 1, {})
    ok = await store.decide(approval_id, "approved", note="looks good")
    assert ok is True

    pending = await store.get_pending()
    assert len(pending) == 0   # no longer pending

    history = await store.get_history()
    assert history[0]["status"] == "approved"
    assert history[0]["decision_note"] == "looks good"


@pytest.mark.asyncio
async def test_reject(store):
    approval_id = await store.create("MNQ", "sell", 2, {})
    ok = await store.decide(approval_id, "rejected", note="regime unfavourable")
    assert ok is True

    history = await store.get_history()
    assert history[0]["status"] == "rejected"


@pytest.mark.asyncio
async def test_double_decide_returns_false(store):
    approval_id = await store.create("MCL", "buy", 1, {})
    await store.decide(approval_id, "approved")
    ok = await store.decide(approval_id, "rejected")   # already decided
    assert ok is False


@pytest.mark.asyncio
async def test_nonexistent_id_returns_false(store):
    ok = await store.decide("does-not-exist", "approved")
    assert ok is False


# ── API endpoint tests ────────────────────────────────────────────────────────
# NOTE: These require a running engine or TestClient fixture.
# Add to your existing conftest.py test_client fixture pattern.

def test_pending_endpoint_empty(test_client: TestClient):
    """With no approvals in store, /pipeline/pending-approvals returns []."""
    resp = test_client.get("/pipeline/pending-approvals", headers={"X-API-Key": "test"})
    assert resp.status_code == 200
    assert resp.json() == []


def test_approve_nonexistent_returns_404(test_client: TestClient):
    resp = test_client.post(
        "/pipeline/pending-approvals/fake-id/approve",
        json={},
        headers={"X-API-Key": "test"},
    )
    assert resp.status_code == 404


def test_reject_nonexistent_returns_404(test_client: TestClient):
    resp = test_client.post(
        "/pipeline/pending-approvals/fake-id/reject",
        json={},
        headers={"X-API-Key": "test"},
    )
    assert resp.status_code == 404
```

---

## Smoke Test Checklist (Manual — after implementation)

Run through this after coding is complete. Check each box before calling it done.

### Backend
- [ ] `restart_engine.ps1` — engine starts, health check passes
- [ ] `GET /pipeline/pending-approvals` → `[]` (empty on fresh start)
- [ ] `GET /pipeline/pending-approvals/history` → `[]`
- [ ] POST a pipeline run with `REQUIRE_HUMAN_APPROVAL=True` (default)
- [ ] `GET /pipeline/pending-approvals` → shows the pending trade with correct symbol, action, quantity, confidence
- [ ] `POST /pipeline/pending-approvals/{id}/approve` → `{"status": "approved"}`
- [ ] `GET /pipeline/pending-approvals` → `[]` (approval consumed)
- [ ] `GET /pipeline/pending-approvals/history` → shows approved entry
- [ ] Run another pipeline → `POST /pipeline/pending-approvals/{id}/reject` → `{"status": "rejected"}`
- [ ] `GET /pipeline/pending-approvals/history` → shows both approved + rejected entries
- [ ] Swagger docs at `/docs` show all 5 new endpoints

### Frontend
- [ ] Dashboard loads without TypeScript errors (`pnpm run build` passes)
- [ ] ApprovalPanel renders on command center page
- [ ] "No pending approvals" shows when queue is empty
- [ ] After triggering a pipeline run, amber card appears within 5 seconds (SWR poll)
- [ ] Card shows symbol, direction, confidence, regime, STC, truncated rationale
- [ ] Approve button → card disappears → history row appears with "APPROVED"
- [ ] Reject button → card disappears → history row appears with "REJECTED"
- [ ] Multiple pending approvals show as stacked cards
- [ ] Disabled state on buttons during API call in flight

---

## What This Does NOT Do Yet (Sprint 12+)

This plan deliberately stops at the approval gate. The execution wiring (approved approval → IB Gateway order) is a separate Sprint 12 task. Here's the stub you'll need:

```python
# Future: engine/routers/pipeline/pending-approvals_router.py — inside approve_trade()
# After store.decide(approval_id, "approved"):

from execution.ib_order_manager import get_order_manager
record = await store.get_one(approval_id)
if record and record.get("pipeline_result"):
    order_manager = get_order_manager()
    await order_manager.submit_approved_trade(
        symbol=record["symbol"],
        action=record["action"],
        quantity=record["quantity"],
        pipeline_result=record["pipeline_result"],
    )
```

That `submit_approved_trade` method needs to be added to `IBOrderManager`. Leave a `# TODO Sprint 12` comment in the approval endpoint now so it's findable.

---

## File Summary

| File | Action | Est. Lines |
|------|--------|-----------|
| `engine/approval/__init__.py` | CREATE | 1 |
| `engine/approval/store.py` | CREATE | ~130 |
| `engine/approval/models.py` | CREATE | ~50 |
| `engine/routers/pipeline/pending-approvals_router.py` | CREATE | ~100 |
| `engine/main.py` | EDIT (2 lines) | +2 |
| `engine/routers/pipeline_router.py` | EDIT (~15 lines) | +15 |
| `dashboard/lib/api.ts` | EDIT (append) | +30 |
| `dashboard/components/ApprovalPanel.tsx` | CREATE | ~180 |
| `dashboard/app/command-center/page.tsx` | EDIT (2 insertions) | +10 |
| `engine/tests/test_approvals.py` | CREATE | ~90 |
| **Total** | | **~610 lines** |

---

## Implementation Order (Strict)

1. `engine/approval/__init__.py` + `store.py` + `models.py` — foundation, no dependencies
2. `engine/routers/pipeline/pending-approvals_router.py` — depends on step 1
3. `engine/main.py` — wire router, 2 lines
4. `engine/routers/pipeline_router.py` — gate the auto-log, depends on store
5. Run engine: `GET /pipeline/pending-approvals` should return `[]` — verify backend works
6. `dashboard/lib/api.ts` — add types
7. `dashboard/components/ApprovalPanel.tsx` — depends on step 6
8. `dashboard/app/command-center/page.tsx` — mount component
9. Run build: `cd dashboard && pnpm run build` — must be zero TypeScript errors
10. `engine/tests/test_approvals.py` — run full test suite

*Report generated 2026-04-02*
