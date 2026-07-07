"""CRUD for pending_trade_approvals (human-gated pipeline executions)."""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from typing import Any, Dict, List, Optional

from ._helpers import _utcnow

logger = logging.getLogger("jarvis_trader.database")


class PendingApprovalsMixin:
    """Methods for ``pending_trade_approvals``."""

    def insert_pending_approval(
        self,
        *,
        symbol: str,
        action: str,
        quantity: float,
        entry_price: Optional[float],
        pipeline_snapshot: dict,
        timeframe: Optional[str] = None,
    ) -> str:
        """Insert a pending row; returns ``approval_id`` (UUID string)."""
        approval_id = str(uuid.uuid4())
        created_at = _utcnow()
        payload = json.dumps(pipeline_snapshot, default=str)
        sql = """
            INSERT INTO pending_trade_approvals
                (approval_id, symbol, action, quantity, entry_price, status,
                 pipeline_snapshot_json, created_at, timeframe)
            VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?)
        """
        params = (
            approval_id,
            symbol.upper(),
            action.lower(),
            float(quantity),
            float(entry_price) if entry_price is not None else None,
            payload,
            created_at,
            timeframe,
        )
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(sql, params)
                conn.commit()
                logger.debug(
                    "[DB] insert_pending_approval approval_id=%s symbol=%s",
                    approval_id[:8],
                    symbol,
                )
            finally:
                conn.close()
        return approval_id

    def list_pending_approvals(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return rows with status=pending, newest first."""
        limit = min(max(1, limit), 200)
        sql = """
            SELECT id, approval_id, symbol, action, quantity, entry_price, status,
                   pipeline_snapshot_json, created_at, resolved_at, resolved_by,
                   rejection_reason, paper_trade_id, ib_order_id, timeframe
            FROM pending_trade_approvals
            WHERE status = 'pending'
            ORDER BY created_at DESC, id DESC
            LIMIT ?
        """
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(sql, (limit,)).fetchall()
                return [self._row_to_dict(r) for r in rows]  # type: ignore[arg-type]
            finally:
                conn.close()

    def get_pending_approval_stats(self) -> Dict[str, Any]:
        """Lightweight aggregate for /health: number of pending approvals and the
        created_at of the oldest one (status='pending'). A growing count / age
        means candidates are queued but not being approved (e.g. outbound
        notifications are failing) — the live-fill path is stalled."""
        sql = """
            SELECT COUNT(*), MIN(created_at)
            FROM pending_trade_approvals
            WHERE status = 'pending'
        """
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(sql).fetchone()
            finally:
                conn.close()
        if not row:
            return {"count": 0, "oldest_created_at": None}
        return {"count": int(row[0] or 0), "oldest_created_at": row[1]}

    def get_recent_approvals_all_statuses(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Return recent pipeline decisions (all statuses) ordered by created_at DESC."""
        limit = min(max(1, limit), 50)
        sql = """
            SELECT id, approval_id, symbol, action, quantity, entry_price, status,
                   pipeline_snapshot_json, created_at, resolved_at, resolved_by,
                   rejection_reason, paper_trade_id, ib_order_id, timeframe
            FROM pending_trade_approvals
            ORDER BY created_at DESC, id DESC
            LIMIT ?
        """
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(sql, (limit,)).fetchall()
                return [self._row_to_dict(r) for r in rows]  # type: ignore[arg-type]
            finally:
                conn.close()

    def get_pending_approval(self, approval_id: str) -> Optional[Dict[str, Any]]:
        """Fetch one row by approval_id or None."""
        sql = """
            SELECT id, approval_id, symbol, action, quantity, entry_price, status,
                   pipeline_snapshot_json, created_at, resolved_at, resolved_by,
                   rejection_reason, paper_trade_id, ib_order_id, timeframe
            FROM pending_trade_approvals
            WHERE approval_id = ?
        """
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(sql, (approval_id,)).fetchone()
                return self._row_to_dict(row) if row else None  # type: ignore[arg-type]
            finally:
                conn.close()

    def resolve_pending_approval(
        self,
        approval_id: str,
        *,
        new_status: str,
        resolved_by: str,
        rejection_reason: Optional[str] = None,
        paper_trade_id: Optional[str] = None,
        ib_order_id: Optional[str] = None,
    ) -> bool:
        """
        Set status from pending → approved/rejected/error. Returns True if one row updated.
        """
        resolved_at = _utcnow()
        sql = """
            UPDATE pending_trade_approvals
            SET status = ?, resolved_at = ?, resolved_by = ?,
                rejection_reason = ?, paper_trade_id = ?, ib_order_id = ?
            WHERE approval_id = ? AND status = 'pending'
        """
        params = (
            new_status,
            resolved_at,
            resolved_by,
            rejection_reason,
            paper_trade_id,
            ib_order_id,
            approval_id,
        )
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(sql, params)
                conn.commit()
                return cur.rowcount > 0
            finally:
                conn.close()

    def _row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        d = dict(row)
        raw = d.pop("pipeline_snapshot_json", None)
        if isinstance(raw, str):
            try:
                d["pipeline_snapshot"] = json.loads(raw)
            except json.JSONDecodeError:
                d["pipeline_snapshot"] = {}
        else:
            d["pipeline_snapshot"] = {}
        return d
