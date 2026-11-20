from __future__ import annotations

import json
from datetime import datetime
from enum import StrEnum
from hashlib import sha256

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TrialStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


_IDENTITY_FIELDS = (
    "campaign_id",
    "strategy_key",
    "control_version",
    "trigger_version",
    "exit_version",
    "ablation_kind",
    "parameter_fingerprint",
    "cost_bps",
    "data_manifest_hash",
    "sample_start",
    "sample_end",
)


class ResearchTrial(BaseModel):
    model_config = ConfigDict(frozen=True)

    trial_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    campaign_id: str = Field(min_length=1)
    strategy_key: str = Field(min_length=1)
    control_version: str = Field(min_length=1)
    trigger_version: str = Field(min_length=1)
    exit_version: str = Field(min_length=1)
    ablation_kind: str = Field(min_length=1)
    parameter_fingerprint: str = Field(min_length=1)
    cost_bps: int = Field(ge=0)
    data_manifest_hash: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    sample_start: datetime
    sample_end: datetime
    status: TrialStatus
    sample_size: int = Field(ge=0)
    output_hash: str | None = None
    output_path: str | None = None
    error: str | None = None

    @model_validator(mode="after")
    def validate_interval(self) -> "ResearchTrial":
        for name in ("sample_start", "sample_end"):
            value = getattr(self, name)
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name} must be timezone-aware")
        if self.sample_end < self.sample_start:
            raise ValueError("sample_end must be on or after sample_start")
        return self

    @classmethod
    def build(cls, **values) -> "ResearchTrial":
        identity = {
            field: values[field].isoformat() if isinstance(values[field], datetime) else values[field]
            for field in _IDENTITY_FIELDS
        }
        payload = json.dumps(identity, sort_keys=True, separators=(",", ":"))
        trial_id = sha256(payload.encode("utf-8")).hexdigest()
        return cls(trial_id=trial_id, **values)


class InMemoryTrialLedger:
    def __init__(self) -> None:
        self._rows: dict[str, ResearchTrial] = {}
        self._order: list[str] = []

    def append(self, trial: ResearchTrial) -> None:
        if trial.trial_id in self._rows:
            raise ValueError(f"trial already recorded: {trial.trial_id}")
        self._rows[trial.trial_id] = trial
        self._order.append(trial.trial_id)

    def get(self, trial_id: str) -> ResearchTrial:
        return self._rows[trial_id]

    def all(self) -> tuple[ResearchTrial, ...]:
        return tuple(self._rows[trial_id] for trial_id in self._order)
