from __future__ import annotations

import json
from datetime import datetime
from hashlib import sha256
from statistics import fmean

from pydantic import BaseModel, ConfigDict, Field, model_validator


def _hash(payload: dict) -> str:
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


class PaperSignal(BaseModel):
    model_config = ConfigDict(frozen=True)
    strategy_key: str = Field(min_length=1)
    generated_at: datetime
    symbol: str = Field(min_length=1)
    entry: float
    stop: float
    targets: tuple[float, ...]
    feature_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    regime: str | None = None
    expected_cost_r: float
    expected_slippage_r: float
    signal_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_time(self) -> "PaperSignal":
        if self.generated_at.tzinfo is None or self.generated_at.utcoffset() is None:
            raise ValueError("generated_at must be timezone-aware")
        return self

    @classmethod
    def create(cls, **kwargs) -> "PaperSignal":
        payload = dict(kwargs)
        payload["signal_hash"] = _hash(kwargs)
        return cls(**payload)


class PaperOutcome(BaseModel):
    model_config = ConfigDict(frozen=True)
    signal_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    realized_r: float
    actual_slippage_r: float
    filled: bool


class ForwardComparison(BaseModel):
    model_config = ConfigDict(frozen=True)
    status: str
    outcome_count: int
    historical_expectancy_r: float
    paper_expectancy_r: float | None
    expectancy_delta_r: float | None
    fill_rate: float | None
    average_actual_slippage_r: float | None


class PaperForwardRegistry:
    def __init__(self) -> None:
        self._signals: list[PaperSignal] = []
        self._outcomes: list[PaperOutcome] = []

    @property
    def signals(self) -> tuple[PaperSignal, ...]:
        return tuple(self._signals)

    @property
    def outcomes(self) -> tuple[PaperOutcome, ...]:
        return tuple(self._outcomes)

    def append_signal(self, signal: PaperSignal) -> None:
        if any(row.signal_hash == signal.signal_hash for row in self._signals):
            raise ValueError("DUPLICATE_PAPER_SIGNAL")
        self._signals.append(signal)

    def append_outcome(self, *, signal_hash: str, realized_r: float, actual_slippage_r: float, filled: bool) -> None:
        if not any(row.signal_hash == signal_hash for row in self._signals):
            raise ValueError("UNKNOWN_PAPER_SIGNAL")
        if any(row.signal_hash == signal_hash for row in self._outcomes):
            raise ValueError("DUPLICATE_PAPER_OUTCOME")
        self._outcomes.append(
            PaperOutcome(
                signal_hash=signal_hash,
                realized_r=realized_r,
                actual_slippage_r=actual_slippage_r,
                filled=filled,
            )
        )


def compare_forward_to_historical(
    registry: PaperForwardRegistry,
    *,
    historical_expectancy_r: float,
    min_outcomes: int = 50,
) -> ForwardComparison:
    outcomes = registry.outcomes
    if len(outcomes) < min_outcomes:
        return ForwardComparison(
            status="insufficient_data",
            outcome_count=len(outcomes),
            historical_expectancy_r=historical_expectancy_r,
            paper_expectancy_r=None,
            expectancy_delta_r=None,
            fill_rate=None,
            average_actual_slippage_r=None,
        )
    paper = fmean(row.realized_r for row in outcomes)
    return ForwardComparison(
        status="complete",
        outcome_count=len(outcomes),
        historical_expectancy_r=historical_expectancy_r,
        paper_expectancy_r=paper,
        expectancy_delta_r=paper - historical_expectancy_r,
        fill_rate=sum(row.filled for row in outcomes) / len(outcomes),
        average_actual_slippage_r=fmean(row.actual_slippage_r for row in outcomes),
    )
