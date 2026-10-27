from __future__ import annotations

import json
from datetime import date
from hashlib import sha256
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field, model_validator


def _hash(value: Any) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


class WalkForwardRecord(BaseModel):
    model_config = ConfigDict(frozen=True)
    observation_id: str = Field(min_length=1)
    trading_date: date
    payload: dict[str, Any] = Field(default_factory=dict)


class WalkForwardSpec(BaseModel):
    model_config = ConfigDict(frozen=True)
    train_sessions: int = Field(gt=0)
    test_sessions: int = Field(gt=0)
    step_sessions: int = Field(gt=0)
    purge_sessions: int = Field(default=0, ge=0)
    embargo_sessions: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_spec(self) -> "WalkForwardSpec":
        if self.purge_sessions >= self.train_sessions:
            raise ValueError("purge_sessions must be smaller than train_sessions")
        if self.embargo_sessions >= self.test_sessions:
            raise ValueError("embargo_sessions must be smaller than test_sessions")
        return self


class WalkForwardFold(BaseModel):
    model_config = ConfigDict(frozen=True)
    fold_index: int
    train_records: tuple[WalkForwardRecord, ...]
    test_records: tuple[WalkForwardRecord, ...]
    purged_train_ids: tuple[str, ...] = ()
    embargoed_test_ids: tuple[str, ...] = ()
    selected_params: dict[str, Any] = Field(default_factory=dict)
    parameter_hash: str = ""
    metrics: dict[str, Any] = Field(default_factory=dict)
    fold_hash: str = ""


class WalkForwardSummary(BaseModel):
    model_config = ConfigDict(frozen=True)
    folds: tuple[WalkForwardFold, ...]
    unique_test_observation_ids: tuple[str, ...]


class WalkForwardRunner:
    def __init__(self, spec: WalkForwardSpec) -> None:
        self.spec = spec

    def folds(self, records: tuple[WalkForwardRecord, ...] | list[WalkForwardRecord]) -> tuple[WalkForwardFold, ...]:
        ordered = tuple(sorted(records, key=lambda r: (r.trading_date, r.observation_id)))
        dates = tuple(sorted({r.trading_date for r in ordered}))
        by_date: dict[date, list[WalkForwardRecord]] = {}
        for row in ordered:
            by_date.setdefault(row.trading_date, []).append(row)
        result: list[WalkForwardFold] = []
        cursor = 0
        index = 0
        while cursor + self.spec.train_sessions + self.spec.test_sessions <= len(dates):
            train_dates_raw = dates[cursor : cursor + self.spec.train_sessions]
            test_start = cursor + self.spec.train_sessions
            test_dates_raw = dates[test_start : test_start + self.spec.test_sessions]
            purge = train_dates_raw[-self.spec.purge_sessions :] if self.spec.purge_sessions else ()
            embargo = test_dates_raw[: self.spec.embargo_sessions] if self.spec.embargo_sessions else ()
            train_dates = train_dates_raw[: len(train_dates_raw) - self.spec.purge_sessions] if self.spec.purge_sessions else train_dates_raw
            test_dates = test_dates_raw[self.spec.embargo_sessions :]
            train = tuple(r for d in train_dates for r in by_date[d])
            test = tuple(r for d in test_dates for r in by_date[d])
            purged = tuple(r.observation_id for d in purge for r in by_date[d])
            embargoed = tuple(r.observation_id for d in embargo for r in by_date[d])
            result.append(
                WalkForwardFold(
                    fold_index=index,
                    train_records=train,
                    test_records=test,
                    purged_train_ids=purged,
                    embargoed_test_ids=embargoed,
                )
            )
            index += 1
            cursor += self.spec.step_sessions
        return tuple(result)

    def run(
        self,
        records: tuple[WalkForwardRecord, ...] | list[WalkForwardRecord],
        selector: Callable[[tuple[WalkForwardRecord, ...]], dict[str, Any]],
        evaluator: Callable[[tuple[WalkForwardRecord, ...], dict[str, Any]], dict[str, Any]],
    ) -> WalkForwardSummary:
        completed: list[WalkForwardFold] = []
        unique_ids: dict[str, None] = {}
        for raw in self.folds(records):
            params = dict(selector(raw.train_records))
            metrics = dict(evaluator(raw.test_records, params))
            parameter_hash = _hash(params)
            payload = {
                "fold_index": raw.fold_index,
                "train_ids": [r.observation_id for r in raw.train_records],
                "test_ids": [r.observation_id for r in raw.test_records],
                "purged": raw.purged_train_ids,
                "embargoed": raw.embargoed_test_ids,
                "parameter_hash": parameter_hash,
                "metrics": metrics,
            }
            fold = raw.model_copy(
                update={
                    "selected_params": params,
                    "parameter_hash": parameter_hash,
                    "metrics": metrics,
                    "fold_hash": _hash(payload),
                }
            )
            completed.append(fold)
            for row in fold.test_records:
                unique_ids.setdefault(row.observation_id, None)
        return WalkForwardSummary(folds=tuple(completed), unique_test_observation_ids=tuple(unique_ids))
