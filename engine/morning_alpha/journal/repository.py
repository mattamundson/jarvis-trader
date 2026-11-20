from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from morning_alpha.models import SetupCandidate, SignalOutcome, TradePlan
from morning_alpha.risk import TradeRejection


class JournalCandidateRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    candidate_id: UUID
    recorded_at: datetime
    strategy_id: str
    strategy_version: str
    payload: dict[str, Any]
    provider_lineage: dict[str, Any] = Field(default_factory=dict)


class JournalEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: UUID
    candidate_id: UUID
    event_type: str
    recorded_at: datetime
    payload: dict[str, Any]


class SignalJournal(Protocol):
    def append_candidate(
        self,
        candidate: SetupCandidate,
        *,
        recorded_at: datetime,
        provider_lineage: dict[str, Any] | None = None,
    ) -> UUID: ...

    def append_plan(self, candidate_id: UUID, plan: TradePlan, *, recorded_at: datetime) -> UUID: ...

    def append_rejection(
        self, candidate_id: UUID, rejection: TradeRejection, *, recorded_at: datetime
    ) -> UUID: ...

    def append_outcome(
        self, candidate_id: UUID, outcome: SignalOutcome, *, recorded_at: datetime
    ) -> UUID: ...

    def get_candidate(self, candidate_id: UUID) -> JournalCandidateRecord: ...

    def events(self, candidate_id: UUID) -> tuple[JournalEvent, ...]: ...


class InMemorySignalJournal:
    """Append-only journal used by unit tests and deterministic research runs."""

    def __init__(self) -> None:
        self._candidates: dict[UUID, JournalCandidateRecord] = {}
        self._events: list[JournalEvent] = []
        self._strategy_versions: set[tuple[str, str]] = set()

    @staticmethod
    def _ensure_aware(ts: datetime, name: str) -> None:
        if ts.tzinfo is None or ts.utcoffset() is None:
            raise ValueError(f"{name} must be timezone-aware")

    def append_candidate(
        self,
        candidate: SetupCandidate,
        *,
        recorded_at: datetime,
        provider_lineage: dict[str, Any] | None = None,
    ) -> UUID:
        self._ensure_aware(recorded_at, "recorded_at")
        candidate_id = uuid4()
        payload = deepcopy(candidate.model_dump(mode="json"))
        lineage = deepcopy(provider_lineage or {})
        record = JournalCandidateRecord(
            candidate_id=candidate_id,
            recorded_at=recorded_at,
            strategy_id=candidate.strategy.strategy_id,
            strategy_version=candidate.strategy.version,
            payload=payload,
            provider_lineage=lineage,
        )
        self._strategy_versions.add((record.strategy_id, record.strategy_version))
        self._candidates[candidate_id] = record
        return candidate_id

    def _append_event(
        self,
        candidate_id: UUID,
        event_type: str,
        payload: dict[str, Any],
        *,
        recorded_at: datetime,
    ) -> UUID:
        self._ensure_aware(recorded_at, "recorded_at")
        if candidate_id not in self._candidates:
            raise KeyError(candidate_id)
        event_id = uuid4()
        self._events.append(
            JournalEvent(
                event_id=event_id,
                candidate_id=candidate_id,
                event_type=event_type,
                recorded_at=recorded_at,
                payload=deepcopy(payload),
            )
        )
        return event_id

    def append_plan(self, candidate_id: UUID, plan: TradePlan, *, recorded_at: datetime) -> UUID:
        return self._append_event(
            candidate_id, "trade_plan", plan.model_dump(mode="json"), recorded_at=recorded_at
        )

    def append_rejection(
        self, candidate_id: UUID, rejection: TradeRejection, *, recorded_at: datetime
    ) -> UUID:
        return self._append_event(
            candidate_id, "rejection", rejection.model_dump(mode="json"), recorded_at=recorded_at
        )

    def append_outcome(
        self, candidate_id: UUID, outcome: SignalOutcome, *, recorded_at: datetime
    ) -> UUID:
        return self._append_event(
            candidate_id, "outcome", outcome.model_dump(mode="json"), recorded_at=recorded_at
        )

    def get_candidate(self, candidate_id: UUID) -> JournalCandidateRecord:
        try:
            record = self._candidates[candidate_id]
        except KeyError:
            raise KeyError(candidate_id) from None
        return record.model_copy(deep=True)

    def events(self, candidate_id: UUID) -> tuple[JournalEvent, ...]:
        if candidate_id not in self._candidates:
            raise KeyError(candidate_id)
        return tuple(
            event.model_copy(deep=True)
            for event in self._events
            if event.candidate_id == candidate_id
        )

    @property
    def strategy_versions(self) -> frozenset[tuple[str, str]]:
        return frozenset(self._strategy_versions)
