from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from hashlib import sha256

from pydantic import BaseModel, ConfigDict, Field, model_validator

from morning_alpha.models import SetupCandidate, StrategyKey


class CandidateDecisionState(StrEnum):
    QUALIFIED = "qualified"
    REJECTED = "rejected"


def _require_aware(ts: datetime, name: str) -> None:
    if ts.tzinfo is None or ts.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def candidate_identity(strategy: StrategyKey, stable_security_id: str, decision_timestamp: datetime) -> str:
    _require_aware(decision_timestamp, "decision_timestamp")
    if not stable_security_id:
        raise ValueError("stable_security_id cannot be empty")
    payload = f"{strategy.canonical}|{stable_security_id}|{decision_timestamp.isoformat()}"
    return sha256(payload.encode("utf-8")).hexdigest()


class CandidateObservation(BaseModel):
    model_config = ConfigDict(frozen=True)

    candidate_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    campaign_id: str = Field(min_length=1)
    strategy: StrategyKey
    stable_security_id: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    decision_timestamp: datetime
    trading_date: date
    sector: str | None = None
    sector_etf: str | None = None
    decision_state: CandidateDecisionState
    rejection_reason: str | None = None
    feature_hash: str = Field(pattern=r"^.{64}$")
    universe_hash: str = Field(pattern=r"^.{64}$")
    data_manifest_hash: str = Field(pattern=r"^.{64}$")
    source_lineage_hash: str = Field(pattern=r"^.{64}$")
    detector_candidate: SetupCandidate | None = None

    @model_validator(mode="after")
    def validate_observation(self) -> "CandidateObservation":
        _require_aware(self.decision_timestamp, "decision_timestamp")
        if self.trading_date != self.decision_timestamp.date():
            raise ValueError("trading_date must match decision_timestamp date")
        expected = candidate_identity(self.strategy, self.stable_security_id, self.decision_timestamp)
        if self.candidate_id != expected:
            raise ValueError("candidate_id does not match immutable identity")
        if self.decision_state is CandidateDecisionState.QUALIFIED and self.detector_candidate is None:
            raise ValueError("qualified observation requires detector_candidate")
        if self.decision_state is CandidateDecisionState.REJECTED and not self.rejection_reason:
            raise ValueError("rejected observation requires rejection_reason")
        return self


class PopulationBuildResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    decision_timestamp: datetime
    observations: tuple[CandidateObservation, ...]
    input_universe_count: int = Field(ge=0)
    qualified_count: int = Field(ge=0)
    rejected_count: int = Field(ge=0)
    rejection_counts: dict[str, int]
    universe_hash: str = Field(pattern=r"^.{64}$")
    population_hash: str = Field(pattern=r"^.{64}$")

    @model_validator(mode="after")
    def validate_population(self) -> "PopulationBuildResult":
        _require_aware(self.decision_timestamp, "decision_timestamp")
        ids = [row.candidate_id for row in self.observations]
        if len(ids) != len(set(ids)):
            raise ValueError("DUPLICATE_CANDIDATE")
        if self.input_universe_count != len(self.observations):
            raise ValueError("ACCOUNTING_MISMATCH: input universe count does not equal observations")
        if self.qualified_count + self.rejected_count != self.input_universe_count:
            raise ValueError("ACCOUNTING_MISMATCH: qualified + rejected does not equal universe")
        if self.qualified_count != sum(
            row.decision_state is CandidateDecisionState.QUALIFIED for row in self.observations
        ):
            raise ValueError("ACCOUNTING_MISMATCH: qualified count")
        if self.rejected_count != sum(
            row.decision_state is CandidateDecisionState.REJECTED for row in self.observations
        ):
            raise ValueError("ACCOUNTING_MISMATCH: rejected count")
        if sum(self.rejection_counts.values()) != self.rejected_count:
            raise ValueError("ACCOUNTING_MISMATCH: rejection reasons")
        return self
