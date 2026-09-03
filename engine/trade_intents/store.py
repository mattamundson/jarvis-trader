"""SQLite-backed paper trade-intent lifecycle store.

A preview is immutable once persisted. Submission is idempotent and concurrency
safe: an intent must be atomically claimed (PREVIEWED -> SUBMITTING) before any
broker call. A partial unique index also prevents identical active intents from
coexisting under different idempotency keys.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from trade_intents.core import TradeIntentPreview


class TradeIntentStoreError(ValueError):
    """Raised for invalid trade-intent lifecycle operations."""


_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS manual_trade_intents (
    intent_id TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    request_hash TEXT NOT NULL,
    preview_json TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    submitted_at TEXT,
    order_id TEXT,
    broker_result_json TEXT,
    terminal_reason TEXT
)
"""


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def request_fingerprint(payload: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


class TradeIntentStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(_CREATE_SQL)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_manual_trade_intents_status "
                "ON manual_trade_intents(status, expires_at)"
            )
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS ux_manual_trade_intents_active_hash "
                "ON manual_trade_intents(request_hash) "
                "WHERE status IN ('PREVIEWED', 'SUBMITTING')"
            )
            conn.commit()

    def _row(self, intent_id: str) -> dict[str, Any] | None:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM manual_trade_intents WHERE intent_id = ?", (intent_id,)
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["preview"] = json.loads(result.pop("preview_json"))
        raw_result = result.pop("broker_result_json")
        result["broker_result"] = json.loads(raw_result) if raw_result else None
        return result

    def get(self, intent_id: str) -> dict[str, Any] | None:
        return self._row(intent_id)

    def get_by_idempotency_key(self, key: str) -> dict[str, Any] | None:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT intent_id FROM manual_trade_intents WHERE idempotency_key = ?", (key,)
            ).fetchone()
        return self._row(row["intent_id"]) if row else None

    def get_active_by_request_hash(self, request_hash: str) -> dict[str, Any] | None:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT intent_id
                  FROM manual_trade_intents
                 WHERE request_hash = ?
                   AND status IN ('PREVIEWED', 'SUBMITTING')
                 ORDER BY created_at DESC
                 LIMIT 1
                """,
                (request_hash,),
            ).fetchone()
        return self._row(row["intent_id"]) if row else None

    def create_preview(
        self,
        *,
        idempotency_key: str,
        request_payload: dict[str, Any],
        preview: TradeIntentPreview,
        ttl_seconds: int = 90,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        key = idempotency_key.strip()
        if len(key) < 8:
            raise TradeIntentStoreError("idempotency_key must contain at least 8 characters")
        if not 15 <= ttl_seconds <= 300:
            raise TradeIntentStoreError("ttl_seconds must be between 15 and 300")
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None or current.utcoffset() is None:
            raise TradeIntentStoreError("now must be timezone-aware")

        fingerprint = request_fingerprint(request_payload)
        existing = self.get_by_idempotency_key(key)
        if existing is not None:
            if existing["request_hash"] != fingerprint:
                raise TradeIntentStoreError(
                    "idempotency_key already exists for a different request payload"
                )
            return existing

        active_duplicate = self.get_active_by_request_hash(fingerprint)
        if active_duplicate is not None:
            return active_duplicate

        intent_id = str(uuid.uuid4())
        expires = current + timedelta(seconds=ttl_seconds)
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO manual_trade_intents
                        (intent_id, idempotency_key, request_hash, preview_json, status,
                         created_at, expires_at)
                    VALUES (?, ?, ?, ?, 'PREVIEWED', ?, ?)
                    """,
                    (
                        intent_id,
                        key,
                        fingerprint,
                        _canonical(asdict(preview)),
                        current.isoformat(),
                        expires.isoformat(),
                    ),
                )
                conn.commit()
        except sqlite3.IntegrityError as exc:
            # Two simultaneous requests with different idempotency keys but the
            # same payload can race past the application-level lookup above.
            # The partial unique index is authoritative and closes that race.
            active_duplicate = self.get_active_by_request_hash(fingerprint)
            if active_duplicate is not None:
                return active_duplicate
            raise TradeIntentStoreError(f"trade-intent uniqueness conflict: {exc}") from exc
        created = self.get(intent_id)
        assert created is not None
        return created

    def require_submittable(
        self,
        intent_id: str,
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        record = self.get(intent_id)
        if record is None:
            raise TradeIntentStoreError(f"intent not found: {intent_id}")
        if record["status"] == "SUBMITTED":
            return record
        if record["status"] != "PREVIEWED":
            raise TradeIntentStoreError(
                f"intent status {record['status']} is not submittable"
            )
        current = now or datetime.now(timezone.utc)
        expires = datetime.fromisoformat(record["expires_at"])
        if current >= expires:
            self.mark_terminal(intent_id, status="EXPIRED", reason="intent TTL expired")
            raise TradeIntentStoreError("intent expired")
        return record

    def claim_for_submission(
        self,
        intent_id: str,
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Atomically claim a PREVIEWED intent before any broker call.

        SUBMITTED is returned idempotently. Any other state, including an
        already-SUBMITTING concurrent request, fails closed.
        """
        current = now or datetime.now(timezone.utc)
        record = self.get(intent_id)
        if record is None:
            raise TradeIntentStoreError(f"intent not found: {intent_id}")
        if record["status"] == "SUBMITTED":
            return record
        if record["status"] != "PREVIEWED":
            raise TradeIntentStoreError(
                f"intent status {record['status']} is not claimable"
            )
        expires = datetime.fromisoformat(record["expires_at"])
        if current >= expires:
            self.mark_terminal(intent_id, status="EXPIRED", reason="intent TTL expired")
            raise TradeIntentStoreError("intent expired")

        with sqlite3.connect(self.db_path, timeout=5) as conn:
            cur = conn.execute(
                """
                UPDATE manual_trade_intents
                   SET status='SUBMITTING'
                 WHERE intent_id=? AND status='PREVIEWED'
                """,
                (intent_id,),
            )
            conn.commit()
        if cur.rowcount != 1:
            latest = self.get(intent_id)
            if latest is not None and latest["status"] == "SUBMITTED":
                return latest
            latest_status = latest["status"] if latest is not None else "missing"
            raise TradeIntentStoreError(
                f"intent could not be claimed; current status is {latest_status}"
            )
        claimed = self.get(intent_id)
        assert claimed is not None
        return claimed

    def mark_submitted(
        self,
        intent_id: str,
        *,
        broker_result: dict[str, Any],
        order_id: str | None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        current = now or datetime.now(timezone.utc)
        record = self.get(intent_id)
        if record is None:
            raise TradeIntentStoreError(f"intent not found: {intent_id}")
        if record["status"] == "SUBMITTED":
            return record
        if record["status"] != "SUBMITTING":
            raise TradeIntentStoreError(
                f"cannot submit intent from status {record['status']}"
            )
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                """
                UPDATE manual_trade_intents
                   SET status='SUBMITTED', submitted_at=?, order_id=?, broker_result_json=?
                 WHERE intent_id=? AND status='SUBMITTING'
                """,
                (current.isoformat(), order_id, _canonical(broker_result), intent_id),
            )
            conn.commit()
        if cur.rowcount != 1:
            raise TradeIntentStoreError("intent submission state changed unexpectedly")
        updated = self.get(intent_id)
        assert updated is not None
        return updated

    def mark_terminal(self, intent_id: str, *, status: str, reason: str) -> dict[str, Any]:
        if status not in {"BLOCKED", "EXPIRED", "REJECTED"}:
            raise TradeIntentStoreError("invalid terminal status")
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                """
                UPDATE manual_trade_intents
                   SET status=?, terminal_reason=?
                 WHERE intent_id=? AND status IN ('PREVIEWED', 'SUBMITTING')
                """,
                (status, reason, intent_id),
            )
            conn.commit()
        if cur.rowcount == 0:
            record = self.get(intent_id)
            if record is None:
                raise TradeIntentStoreError(f"intent not found: {intent_id}")
            return record
        updated = self.get(intent_id)
        assert updated is not None
        return updated
