"""Append-only order lifecycle ledger for paper-order observability."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Optional

_HERE = Path(__file__).resolve().parent
_DEFAULT_LEDGER = _HERE.parent / "data" / "order_lifecycle" / "events.jsonl"


class OrderLifecycleType(str, Enum):
    """Known order lifecycle event names."""

    INTENT_CREATED = "intent_created"
    RISK_CHECKED = "risk_checked"
    AUTHORIZATION_FAILED = "authorization_failed"
    AUTHORIZED = "authorized"
    SUBMITTED = "submitted"
    ACCEPTED = "accepted"
    PARTIAL_FILL = "partial_fill"
    FILLED = "filled"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    RECONCILED = "reconciled"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


@dataclass(frozen=True)
class OrderLifecycleEvent:
    """One immutable order lifecycle event."""

    event_type: OrderLifecycleType
    idempotency_key: str
    source: str
    symbol: str
    account_mode: str = "paper"
    timestamp: str = field(default_factory=_utc_now_iso)
    strategy_id: Optional[str] = None
    decision_id: Optional[str] = None
    safety_state_hash: Optional[str] = None
    feature_snapshot_id: Optional[str] = None
    broker_order_id: Optional[str] = None
    raw_broker_status: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))

    @property
    def event_id(self) -> str:
        return hashlib.sha256(_canonical_json(self.to_record(include_event_id=False)).encode()).hexdigest()

    def to_record(self, *, include_event_id: bool = True) -> dict[str, Any]:
        record: dict[str, Any] = {
            "event_type": self.event_type.value,
            "idempotency_key": self.idempotency_key,
            "source": self.source,
            "symbol": self.symbol.upper(),
            "account_mode": self.account_mode.lower(),
            "timestamp": self.timestamp,
        }
        optional = {
            "strategy_id": self.strategy_id,
            "decision_id": self.decision_id,
            "safety_state_hash": self.safety_state_hash,
            "feature_snapshot_id": self.feature_snapshot_id,
            "broker_order_id": self.broker_order_id,
            "raw_broker_status": self.raw_broker_status,
        }
        record.update({key: value for key, value in optional.items() if value is not None})
        if self.metadata:
            record["metadata"] = dict(self.metadata)
        if include_event_id:
            record["event_id"] = self.event_id
        return record


class OrderLifecycleLedger:
    """Append-only JSONL ledger for order lifecycle events."""

    def __init__(self, ledger_path: Optional[Path | str] = None) -> None:
        self._path = Path(ledger_path) if ledger_path else _DEFAULT_LEDGER

    def read_events(self) -> list[dict[str, Any]]:
        """Read all well-formed events, skipping malformed JSONL lines."""
        if not self._path.exists():
            return []
        events: list[dict[str, Any]] = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                events.append(record)
        return events

    def event_ids(self) -> set[str]:
        return {
            str(record["event_id"])
            for record in self.read_events()
            if record.get("event_id")
        }

    def append(self, event: OrderLifecycleEvent) -> bool:
        """Append ``event`` unless an identical event_id already exists."""
        record = event.to_record()
        if record["event_id"] in self.event_ids():
            return False
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, default=str) + "\n")
        return True

    def events_for_idempotency_key(self, idempotency_key: str) -> list[dict[str, Any]]:
        return [
            record
            for record in self.read_events()
            if record.get("idempotency_key") == idempotency_key
        ]
