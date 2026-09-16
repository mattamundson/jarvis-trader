from __future__ import annotations

import json
import math
from datetime import date, datetime
from hashlib import sha256

from pydantic import BaseModel, ConfigDict, Field, model_validator


def _canonical_hash(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return sha256(raw).hexdigest()


class MatchedEdgeObservation(BaseModel):
    model_config = ConfigDict(frozen=True)

    candidate_id: str = Field(min_length=1)
    decision_timestamp: datetime
    trading_date: date
    symbol: str = Field(min_length=1)
    sector: str = Field(min_length=1)
    regime: str | None = None
    strategy_return: float
    control_return: float
    gross_r: float | None = None
    cost_r_per_bps: float | None = None
    slippage_r_per_atr_fraction: float | None = None
    delay_penalty_r: dict[str, float] = Field(default_factory=dict)
    entry_gap_penalty_r: float | None = None
    stop_gap_penalty_r: float | None = None

    @model_validator(mode="after")
    def validate_observation(self) -> "MatchedEdgeObservation":
        if self.decision_timestamp.tzinfo is None or self.decision_timestamp.utcoffset() is None:
            raise ValueError("decision_timestamp must be timezone-aware")
        if self.trading_date != self.decision_timestamp.date():
            raise ValueError("trading_date must match decision_timestamp date")
        for field_name in (
            "strategy_return",
            "control_return",
            "gross_r",
            "cost_r_per_bps",
            "slippage_r_per_atr_fraction",
            "entry_gap_penalty_r",
            "stop_gap_penalty_r",
        ):
            value = getattr(self, field_name)
            if value is not None and not math.isfinite(value):
                raise ValueError(f"{field_name} must be finite")
        for key, value in self.delay_penalty_r.items():
            if not key:
                raise ValueError("delay_penalty_r key cannot be blank")
            if not math.isfinite(value):
                raise ValueError("delay_penalty_r values must be finite")
        return self

    @property
    def edge(self) -> float:
        return self.strategy_return - self.control_return

    @property
    def observation_hash(self) -> str:
        return _canonical_hash(self.model_dump(mode="json"))
