from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from morning_alpha.journal.repository import JournalCandidateRecord, JournalEvent
from morning_alpha.models import SetupCandidate, SignalOutcome, TradePlan
from morning_alpha.risk import TradeRejection


class PostgresSignalJournal:
    """Append-only PostgreSQL signal journal with explicit transactions."""

    def __init__(self, connection: Any) -> None:
        self.connection = connection

    @classmethod
    def connect(cls, dsn: str) -> "PostgresSignalJournal":
        try:
            import psycopg2
        except ImportError as exc:  # pragma: no cover - runtime dependency path
            raise RuntimeError("psycopg2 is required for PostgreSQL journaling") from exc
        return cls(psycopg2.connect(dsn))

    def initialize_schema(self) -> None:
        schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
        with self.connection:
            with self.connection.cursor() as cur:
                cur.execute(schema)

    @staticmethod
    def _json(value: dict[str, Any]) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"))

    def append_candidate(
        self,
        candidate: SetupCandidate,
        *,
        recorded_at: datetime,
        provider_lineage: dict[str, Any] | None = None,
    ) -> UUID:
        candidate_id = uuid4()
        payload = candidate.model_dump(mode="json")
        with self.connection:
            with self.connection.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO morning_alpha_strategy_versions(strategy_id, version, first_seen_at)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (strategy_id, version) DO NOTHING
                    """,
                    (candidate.strategy.strategy_id, candidate.strategy.version, recorded_at),
                )
                cur.execute(
                    """
                    INSERT INTO morning_alpha_signal_candidates
                    (candidate_id, recorded_at, as_of, symbol, strategy_id, strategy_version,
                     payload, provider_lineage)
                    VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb)
                    """,
                    (
                        str(candidate_id),
                        recorded_at,
                        candidate.as_of,
                        candidate.symbol,
                        candidate.strategy.strategy_id,
                        candidate.strategy.version,
                        self._json(payload),
                        self._json(provider_lineage or {}),
                    ),
                )
        return candidate_id

    def _append_event(
        self,
        candidate_id: UUID,
        event_type: str,
        payload: dict[str, Any],
        *,
        recorded_at: datetime,
    ) -> UUID:
        event_id = uuid4()
        with self.connection:
            with self.connection.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO morning_alpha_signal_events
                    (event_id, candidate_id, event_type, recorded_at, payload)
                    VALUES (%s,%s,%s,%s,%s::jsonb)
                    """,
                    (str(event_id), str(candidate_id), event_type, recorded_at, self._json(payload)),
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
        with self.connection.cursor() as cur:
            cur.execute(
                """
                SELECT candidate_id, recorded_at, strategy_id, strategy_version, payload, provider_lineage
                FROM morning_alpha_signal_candidates WHERE candidate_id=%s
                """,
                (str(candidate_id),),
            )
            row = cur.fetchone()
        if row is None:
            raise KeyError(candidate_id)
        return JournalCandidateRecord(
            candidate_id=row[0],
            recorded_at=row[1],
            strategy_id=row[2],
            strategy_version=row[3],
            payload=row[4],
            provider_lineage=row[5],
        )

    def events(self, candidate_id: UUID) -> tuple[JournalEvent, ...]:
        with self.connection.cursor() as cur:
            cur.execute(
                """
                SELECT event_id, candidate_id, event_type, recorded_at, payload
                FROM morning_alpha_signal_events WHERE candidate_id=%s ORDER BY recorded_at, event_id
                """,
                (str(candidate_id),),
            )
            rows = cur.fetchall()
        return tuple(
            JournalEvent(
                event_id=r[0], candidate_id=r[1], event_type=r[2], recorded_at=r[3], payload=r[4]
            )
            for r in rows
        )
