from __future__ import annotations

import json
from datetime import date, datetime
from hashlib import sha256
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field, model_validator


def _hash(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return sha256(raw).hexdigest()


class OOSIdentity(BaseModel):
    model_config = ConfigDict(frozen=True)

    strategy_key: str = Field(min_length=1)
    parameter_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    data_manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_population_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    trial_ledger_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    trial_count: int = Field(ge=0)
    code_commit: str = Field(min_length=1)


class OOSLockSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    campaign_id: str = Field(min_length=1)
    strategy_key: str = Field(min_length=1)
    parameter_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    trigger_version: str = Field(min_length=1)
    exit_version: str = Field(min_length=1)
    data_manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_population_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    trial_ledger_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    trial_count: int = Field(ge=0)
    development_start: date
    development_end: date
    validation_start: date
    validation_end: date
    oos_start: date
    oos_end: date
    purge_sessions: int = Field(ge=0)
    embargo_sessions: int = Field(ge=0)
    code_commit: str = Field(min_length=1)
    locked_at: datetime

    @model_validator(mode="after")
    def validate_spec(self) -> "OOSLockSpec":
        if self.locked_at.tzinfo is None or self.locked_at.utcoffset() is None:
            raise ValueError("locked_at must be timezone-aware")
        intervals = (
            (self.development_start, self.development_end),
            (self.validation_start, self.validation_end),
            (self.oos_start, self.oos_end),
        )
        if any(start > end for start, end in intervals):
            raise ValueError("OOS_INTERVAL_INVALID")
        if not (
            self.development_end < self.validation_start
            and self.validation_end < self.oos_start
        ):
            raise ValueError("OOS_INTERVAL_OVERLAP")
        return self

    def seal(self) -> "OOSLock":
        payload = self.model_dump(mode="json")
        return OOSLock(**payload, lock_hash=_hash(payload))


class OOSLock(OOSLockSpec):
    lock_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @property
    def identity(self) -> OOSIdentity:
        return OOSIdentity(
            strategy_key=self.strategy_key,
            parameter_hash=self.parameter_hash,
            data_manifest_hash=self.data_manifest_hash,
            candidate_population_hash=self.candidate_population_hash,
            trial_ledger_hash=self.trial_ledger_hash,
            trial_count=self.trial_count,
            code_commit=self.code_commit,
        )


class OOSResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    lock_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    metrics: dict[str, Any]
    evidence_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class LockedOOSEvaluator:
    def __init__(self, lock: OOSLock) -> None:
        self.lock = lock

    def evaluate(self, identity: OOSIdentity, evaluator: Callable[[], dict[str, Any]]) -> OOSResult:
        if identity != self.lock.identity:
            raise ValueError("OOS_IDENTITY_MISMATCH")
        metrics = dict(evaluator())
        evidence_hash = _hash({"lock_hash": self.lock.lock_hash, "metrics": metrics})
        return OOSResult(lock_hash=self.lock.lock_hash, metrics=metrics, evidence_hash=evidence_hash)
