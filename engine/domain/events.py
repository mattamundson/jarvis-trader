"""M-01 canonical event/audit envelope.

This module is intentionally inert. It provides immutable identity, correlation,
causation, actor, environment, and payload-integrity fields for future audit/event
migration but does not publish events or authorize runtime mutations.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from .contracts import ActorKind, ExecutionEnvironment


class EventKind(str, Enum):
    INTENT_CREATED = "INTENT_CREATED"
    AUTHORIZATION_DECISION = "AUTHORIZATION_DECISION"
    RISK_DECISION = "RISK_DECISION"
    OMS_TRANSITION = "OMS_TRANSITION"
    BROKER_OBSERVATION = "BROKER_OBSERVATION"
    RECONCILIATION = "RECONCILIATION"
    STRATEGY_DECISION = "STRATEGY_DECISION"
    OPERATOR_ACTION = "OPERATOR_ACTION"
    SYSTEM_HEALTH = "SYSTEM_HEALTH"


def _canonical_json(value: Mapping[str, Any]) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    except (TypeError, ValueError) as exc:
        raise ValueError("payload must be JSON serializable") from exc


def payload_sha256(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AuditEventEnvelope:
    event_id: str
    event_kind: EventKind
    aggregate_type: str
    aggregate_id: str
    occurred_at_utc: dt.datetime
    recorded_at_utc: dt.datetime
    actor_kind: ActorKind
    environment: ExecutionEnvironment
    correlation_id: str
    causation_id: str | None = None
    idempotency_key: str | None = None
    evidence_ids: tuple[str, ...] = ()
    payload_schema: str = "v1"
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("event_id", "aggregate_type", "aggregate_id", "correlation_id", "payload_schema"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} is required")
            object.__setattr__(self, name, value.strip())
        if self.occurred_at_utc.tzinfo is None or self.recorded_at_utc.tzinfo is None:
            raise ValueError("event timestamps must be timezone-aware")
        occurred = self.occurred_at_utc.astimezone(dt.timezone.utc)
        recorded = self.recorded_at_utc.astimezone(dt.timezone.utc)
        if recorded < occurred - dt.timedelta(minutes=5):
            raise ValueError("recorded_at_utc cannot materially precede occurred_at_utc")
        if self.idempotency_key is not None and len(self.idempotency_key.strip()) < 8:
            raise ValueError("idempotency_key must be at least 8 characters when supplied")
        frozen_payload = json.loads(_canonical_json(dict(self.payload)))
        object.__setattr__(self, "occurred_at_utc", occurred)
        object.__setattr__(self, "recorded_at_utc", recorded)
        object.__setattr__(self, "payload", frozen_payload)
        object.__setattr__(self, "evidence_ids", tuple(str(value) for value in self.evidence_ids))

    @property
    def payload_hash(self) -> str:
        return payload_sha256(self.payload)

    @property
    def can_authorize_execution(self) -> bool:
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_kind": self.event_kind.value,
            "aggregate_type": self.aggregate_type,
            "aggregate_id": self.aggregate_id,
            "occurred_at_utc": self.occurred_at_utc.isoformat(),
            "recorded_at_utc": self.recorded_at_utc.isoformat(),
            "actor_kind": self.actor_kind.value,
            "environment": self.environment.value,
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id,
            "idempotency_key": self.idempotency_key,
            "evidence_ids": list(self.evidence_ids),
            "payload_schema": self.payload_schema,
            "payload": dict(self.payload),
            "payload_sha256": self.payload_hash,
            "can_authorize_execution": False,
        }
