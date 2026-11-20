from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from typing import Callable

from pydantic import BaseModel, ConfigDict, Field


class RedTeamStatus(StrEnum):
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class RedTeamCase:
    name: str
    expected_detector: str
    probe: Callable[[], str | None]


class RedTeamCaseResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1)
    expected_detector: str = Field(min_length=1)
    actual_detector: str | None = None
    caught: bool


class RedTeamReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_cases: int = Field(gt=0)
    caught_cases: int = Field(ge=0)
    missed_cases: int = Field(ge=0)
    status: RedTeamStatus
    results: tuple[RedTeamCaseResult, ...]
    report_id: str = Field(min_length=64, max_length=64)


def _hash(payload: object) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return sha256(raw).hexdigest()


def run_red_team(cases: tuple[RedTeamCase, ...] | list[RedTeamCase]) -> RedTeamReport:
    items = tuple(cases)
    if not items:
        raise ValueError("red-team battery requires at least one case")
    results: list[RedTeamCaseResult] = []
    for case in items:
        if not case.name or not case.expected_detector:
            raise ValueError("red-team case name and expected detector are required")
        try:
            actual = case.probe()
        except Exception as exc:  # probes may intentionally trigger validation exceptions
            actual = str(exc).split(":", 1)[0] or type(exc).__name__
        caught = actual == case.expected_detector or (
            isinstance(actual, str) and case.expected_detector in actual
        )
        normalized_actual = case.expected_detector if caught else actual
        results.append(
            RedTeamCaseResult(
                name=case.name,
                expected_detector=case.expected_detector,
                actual_detector=normalized_actual,
                caught=caught,
            )
        )
    caught = sum(result.caught for result in results)
    status = RedTeamStatus.VERIFIED if caught == len(results) else RedTeamStatus.FAILED
    identity = [result.model_dump(mode="json") for result in results]
    return RedTeamReport(
        total_cases=len(results),
        caught_cases=caught,
        missed_cases=len(results) - caught,
        status=status,
        results=tuple(results),
        report_id=_hash(identity),
    )
