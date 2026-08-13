"""CRUD for pending_trade_approvals (human-gated pipeline executions)."""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from typing import Any, Dict, List, Optional

from ._helpers import _utcnow

try:  # dual-path import (engine.* as package vs bare under engine/ cwd)
    from engine.approval.audit_chain import (
        GENESIS_HASH,
        append_record,
        merkle_root,
        verify_chain,
    )
except ImportError:  # pragma: no cover
    from approval.audit_chain import (
        GENESIS_HASH,
        append_record,
        merkle_root,
        verify_chain,
    )

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
                 pipeline_snapshot_json, created_at, timeframe, prev_hash, audit_hash)
            VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?)
        """
        with self._lock:
            conn = self._connect()
            try:
                # Tamper-evident audit-chain hashes (passive; non-fatal — a hashing
                # failure must never block the approval insert).
                prev_hash, audit_hash = self._compute_audit_link(conn, payload)
                params = (
                    approval_id,
                    symbol.upper(),
                    action.lower(),
                    float(quantity),
                    float(entry_price) if entry_price is not None else None,
                    payload,
                    created_at,
                    timeframe,
                    prev_hash,
                    audit_hash,
                )
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

    def _compute_audit_link(
        self, conn: sqlite3.Connection, payload: str
    ) -> tuple[Optional[str], Optional[str]]:
        """
        Compute (prev_hash, audit_hash) for a new decision row.

        The hash is taken over ``json.loads(payload)`` — exactly the dict that
        will be re-read on verification — so insert-time and verify-time digests
        are identical regardless of any ``default=str`` coercion. ``prev_hash`` is
        the ``audit_hash`` of the most recent hashed row (GENESIS for the first),
        so any NULL gaps left by a prior hashing failure are skipped and the chain
        stays contiguous. Returns ``(None, None)`` on any error — never raises.
        """
        try:
            row = conn.execute(
                "SELECT audit_hash FROM pending_trade_approvals "
                "WHERE audit_hash IS NOT NULL ORDER BY id DESC LIMIT 1"
            ).fetchone()
            prev_hash = row["audit_hash"] if row else GENESIS_HASH
            record = append_record(json.loads(payload), prev_hash)
            return prev_hash, record.audit_hash
        except Exception as exc:  # pragma: no cover — defensive, non-fatal
            logger.warning("[DB] audit-chain hash computation failed (non-fatal): %s", exc)
            return None, None

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

    # ── Audit chain (tamper-evidence) ────────────────────────────────────────

    def get_decision_audit_chain(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Return the hashed decision rows in chain order (oldest first).

        Each item has ``approval_id``, ``created_at``, ``prev_hash``,
        ``audit_hash``, and the parsed ``snapshot``. Only rows written since
        migration 041 carry hashes; earlier rows (audit_hash IS NULL) are excluded.
        """
        sql = (
            "SELECT approval_id, created_at, prev_hash, audit_hash, pipeline_snapshot_json "
            "FROM pending_trade_approvals WHERE audit_hash IS NOT NULL "
            "ORDER BY id ASC"
        )
        if limit is not None:
            sql += f" LIMIT {int(limit)}"
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(sql).fetchall()
            finally:
                conn.close()
        chain: List[Dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            raw = d.pop("pipeline_snapshot_json", None)
            try:
                d["snapshot"] = json.loads(raw) if isinstance(raw, str) else {}
            except json.JSONDecodeError:
                d["snapshot"] = {}
            chain.append(d)
        return chain

    def verify_decision_audit_chain(self) -> Dict[str, Any]:
        """
        Verify the decision-log hash chain end to end.

        Rebuilds each row's hash from its stored snapshot and checks the
        prev_hash links, detecting any mutated, reordered, deleted, or forged
        row. Returns a plain dict (JSON-friendly for the API / verifier script).
        """
        chain = self.get_decision_audit_chain()
        result = verify_chain(chain)
        broken = None
        if result.broken_index is not None and result.broken_index < len(chain):
            broken = chain[result.broken_index].get("approval_id")
        return {
            "ok": result.ok,
            "n_records": result.n_records,
            "broken_index": result.broken_index,
            "broken_approval_id": broken,
            "reason": result.reason,
        }

    def decision_merkle_root(self, day: Optional[str] = None) -> str:
        """
        Merkle root over the day's decision hashes — a single daily integrity anchor.

        ``day`` is a ``YYYY-MM-DD`` UTC date string; when None, roots the entire
        hashed chain. Returns ``GENESIS_HASH`` when no hashed rows match.
        """
        sql = (
            "SELECT audit_hash FROM pending_trade_approvals "
            "WHERE audit_hash IS NOT NULL"
        )
        params: tuple = ()
        if day is not None:
            sql += " AND substr(created_at, 1, 10) = ?"
            params = (day,)
        sql += " ORDER BY id ASC"
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(sql, params).fetchall()
            finally:
                conn.close()
        return merkle_root([r["audit_hash"] for r in rows])

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
