"""Append-only research trial ledger for honest multiple-testing accounting.

Each strategy experiment must be planned before its result is recorded. Records
are hash chained so accidental/manual edits are detectable. This is research
infrastructure only; it has no broker or strategy-execution authority.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal


EventType = Literal["PLAN", "RESULT", "SELECTION"]
GENESIS_HASH = "0" * 64


class TrialLedgerError(ValueError):
    """Base error for invalid or inconsistent research-ledger operations."""


class TrialLedgerIntegrityError(TrialLedgerError):
    """Raised when the persisted hash chain cannot be verified."""


def _require_aware(timestamp: datetime) -> None:
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise TrialLedgerError("created_at must be timezone-aware")


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise TrialLedgerIntegrityError(f"invalid event timestamp: {value}") from exc
    _require_aware(parsed)
    return parsed


@dataclass(frozen=True)
class TrialEvent:
    event_id: str
    trial_id: str
    event_type: EventType
    created_at: str
    payload: dict[str, Any]


class TrialLedger:
    """Single-writer append-only JSONL ledger with SHA-256 chain verification."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def _read_records(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        records: list[dict[str, Any]] = []
        for line_number, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise TrialLedgerIntegrityError(
                    f"invalid JSON on ledger line {line_number}"
                ) from exc
            records.append(record)
        return records

    @staticmethod
    def _event_hash(sequence: int, previous_hash: str, event: dict[str, Any]) -> str:
        material = _canonical_json(
            {"sequence": sequence, "previous_hash": previous_hash, "event": event}
        ).encode("utf-8")
        return hashlib.sha256(material).hexdigest()

    def verify(self) -> bool:
        previous_hash = GENESIS_HASH
        event_ids: set[str] = set()
        plan_times: dict[str, datetime] = {}
        result_times: dict[str, datetime] = {}

        for expected_sequence, record in enumerate(self._read_records(), start=1):
            if record.get("sequence") != expected_sequence:
                raise TrialLedgerIntegrityError(
                    f"sequence mismatch at {expected_sequence}: {record.get('sequence')}"
                )
            if record.get("previous_hash") != previous_hash:
                raise TrialLedgerIntegrityError(
                    f"previous-hash mismatch at sequence {expected_sequence}"
                )
            event = record.get("event")
            if not isinstance(event, dict):
                raise TrialLedgerIntegrityError(
                    f"missing event object at sequence {expected_sequence}"
                )
            expected_hash = self._event_hash(expected_sequence, previous_hash, event)
            if record.get("event_hash") != expected_hash:
                raise TrialLedgerIntegrityError(
                    f"event-hash mismatch at sequence {expected_sequence}"
                )

            try:
                parsed = TrialEvent(**event)
            except TypeError as exc:
                raise TrialLedgerIntegrityError(
                    f"invalid event schema at sequence {expected_sequence}"
                ) from exc
            if not parsed.event_id.strip() or not parsed.trial_id.strip():
                raise TrialLedgerIntegrityError(
                    f"empty event_id/trial_id at sequence {expected_sequence}"
                )
            if parsed.event_id in event_ids:
                raise TrialLedgerIntegrityError(f"duplicate event_id: {parsed.event_id}")
            event_ids.add(parsed.event_id)
            created_at = _parse_timestamp(parsed.created_at)

            if parsed.event_type == "PLAN":
                if parsed.trial_id in plan_times:
                    raise TrialLedgerIntegrityError(f"duplicate PLAN for trial: {parsed.trial_id}")
                plan_times[parsed.trial_id] = created_at
            elif parsed.event_type == "RESULT":
                plan_at = plan_times.get(parsed.trial_id)
                if plan_at is None:
                    raise TrialLedgerIntegrityError(
                        f"RESULT without prior PLAN: {parsed.trial_id}"
                    )
                if created_at < plan_at:
                    raise TrialLedgerIntegrityError(
                        f"RESULT predates PLAN: {parsed.trial_id}"
                    )
                if parsed.trial_id in result_times:
                    raise TrialLedgerIntegrityError(
                        f"duplicate RESULT for trial: {parsed.trial_id}"
                    )
                result_times[parsed.trial_id] = created_at
            elif parsed.event_type == "SELECTION":
                result_at = result_times.get(parsed.trial_id)
                if result_at is None:
                    raise TrialLedgerIntegrityError(
                        f"SELECTION without prior RESULT: {parsed.trial_id}"
                    )
                if created_at < result_at:
                    raise TrialLedgerIntegrityError(
                        f"SELECTION predates RESULT: {parsed.trial_id}"
                    )
            else:
                raise TrialLedgerIntegrityError(
                    f"unknown event_type at sequence {expected_sequence}: {parsed.event_type}"
                )
            previous_hash = expected_hash
        return True

    def _events(self) -> list[TrialEvent]:
        self.verify()
        return [TrialEvent(**record["event"]) for record in self._read_records()]

    def events(self) -> tuple[TrialEvent, ...]:
        """Return a verified immutable snapshot of ledger events."""
        return tuple(self._events())

    @staticmethod
    def _require_identifiers(event_id: str, trial_id: str) -> None:
        if not event_id.strip():
            raise TrialLedgerError("event_id must be non-empty")
        if not trial_id.strip():
            raise TrialLedgerError("trial_id must be non-empty")

    @staticmethod
    def _require_unique_event_id(existing: list[TrialEvent], event_id: str) -> None:
        if any(event.event_id == event_id for event in existing):
            raise TrialLedgerError(f"event_id already exists: {event_id}")

    def _append(self, event: TrialEvent) -> str:
        records = self._read_records()
        self.verify()
        sequence = len(records) + 1
        previous_hash = records[-1]["event_hash"] if records else GENESIS_HASH
        event_dict = asdict(event)
        event_hash = self._event_hash(sequence, previous_hash, event_dict)
        record = {
            "sequence": sequence,
            "previous_hash": previous_hash,
            "event_hash": event_hash,
            "event": event_dict,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(_canonical_json(record) + "\n")
        return event_hash

    def append_plan(
        self,
        *,
        event_id: str,
        trial_id: str,
        created_at: datetime,
        strategy_family: str,
        parameters: dict[str, Any],
        feature_ids: list[str],
        data_fingerprint: str,
        code_commit: str,
        evaluation_plan: dict[str, Any],
    ) -> str:
        _require_aware(created_at)
        self._require_identifiers(event_id, trial_id)
        existing = self._events()
        self._require_unique_event_id(existing, event_id)
        if any(event.trial_id == trial_id and event.event_type == "PLAN" for event in existing):
            raise TrialLedgerError(f"trial already planned: {trial_id}")
        payload = {
            "strategy_family": strategy_family,
            "parameters": parameters,
            "feature_ids": sorted(feature_ids),
            "data_fingerprint": data_fingerprint,
            "code_commit": code_commit,
            "evaluation_plan": evaluation_plan,
        }
        if not strategy_family or not data_fingerprint or not code_commit:
            raise TrialLedgerError("strategy_family, data_fingerprint, and code_commit are required")
        return self._append(
            TrialEvent(event_id, trial_id, "PLAN", created_at.isoformat(), payload)
        )

    def append_result(
        self,
        *,
        event_id: str,
        trial_id: str,
        created_at: datetime,
        metrics: dict[str, Any],
        status: str,
    ) -> str:
        _require_aware(created_at)
        self._require_identifiers(event_id, trial_id)
        existing = self._events()
        self._require_unique_event_id(existing, event_id)
        plans = [
            event for event in existing if event.trial_id == trial_id and event.event_type == "PLAN"
        ]
        if not plans:
            raise TrialLedgerError(f"result has no preregistered plan: {trial_id}")
        if any(event.trial_id == trial_id and event.event_type == "RESULT" for event in existing):
            raise TrialLedgerError(f"trial already has a result: {trial_id}")
        plan_at = _parse_timestamp(plans[0].created_at)
        if created_at < plan_at:
            raise TrialLedgerError(f"result predates plan: {trial_id}")
        return self._append(
            TrialEvent(
                event_id,
                trial_id,
                "RESULT",
                created_at.isoformat(),
                {"metrics": metrics, "status": status},
            )
        )

    def append_selection(
        self,
        *,
        event_id: str,
        trial_id: str,
        created_at: datetime,
        decision: str,
        rationale: str,
    ) -> str:
        _require_aware(created_at)
        self._require_identifiers(event_id, trial_id)
        existing = self._events()
        self._require_unique_event_id(existing, event_id)
        results = [
            event for event in existing if event.trial_id == trial_id and event.event_type == "RESULT"
        ]
        if not results:
            raise TrialLedgerError(f"selection has no completed result: {trial_id}")
        result_at = _parse_timestamp(results[0].created_at)
        if created_at < result_at:
            raise TrialLedgerError(f"selection predates result: {trial_id}")
        return self._append(
            TrialEvent(
                event_id,
                trial_id,
                "SELECTION",
                created_at.isoformat(),
                {"decision": decision, "rationale": rationale},
            )
        )

    def trial_counts(self, *, strategy_family: str | None = None) -> dict[str, int]:
        """Count verified events, optionally restricted to a preregistered family."""
        events = self._events()
        if strategy_family is not None:
            trial_ids = {
                event.trial_id
                for event in events
                if event.event_type == "PLAN"
                and event.payload.get("strategy_family") == strategy_family
            }
            events = [event for event in events if event.trial_id in trial_ids]
        return {
            "planned": sum(event.event_type == "PLAN" for event in events),
            "completed": sum(event.event_type == "RESULT" for event in events),
            "selection_events": sum(event.event_type == "SELECTION" for event in events),
        }
