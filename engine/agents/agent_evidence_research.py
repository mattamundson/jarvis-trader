"""Read-only, point-in-time evaluation of JARVIS debate versus deterministic baseline.

Research-only: never imports broker, execution, trading pipeline, or risk modules.
Signed forward returns must be supplied by a separately audited outcome pipeline.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from statistics import fmean
from typing import Iterable

DIRECTIONS = frozenset({"long", "short", "hold"})


@dataclass(frozen=True)
class AgentObservation:
    event_id: str
    symbol: str
    decided_at: datetime
    available_at: datetime
    bull: str
    bear: str
    baseline: str
    agent: str
    # Forward return of the underlying over a fixed, externally defined horizon;
    # entered only after the complete horizon has elapsed.
    forward_return: float
    outcome_available_at: datetime


@dataclass(frozen=True)
class ArmMetrics:
    arm: str
    observations: int
    participation: int
    mean_signed_return: float
    directional_accuracy: float | None


@dataclass(frozen=True)
class ResearchComparison:
    count: int
    disagreement_count: int
    baseline: ArmMetrics
    agent: ArmMetrics
    signed_return_increment: float


def _aware(t: datetime) -> bool:
    return isinstance(t, datetime) and t.tzinfo is not None and t.utcoffset() is not None


def _validate(row: AgentObservation, evaluation_at: datetime) -> None:
    if not row.event_id.strip() or not row.symbol.strip():
        raise ValueError("event_id and symbol are required")
    for label in ("bull", "bear", "baseline", "agent"):
        if getattr(row, label) not in DIRECTIONS:
            raise ValueError(f"invalid {label} direction")
    for label in ("decided_at", "available_at", "outcome_available_at"):
        if not _aware(getattr(row, label)):
            raise ValueError(f"{label} must be timezone-aware")
    if row.available_at > row.decided_at:
        raise ValueError("LOOKAHEAD: input was not available at decision time")
    if row.outcome_available_at <= row.decided_at:
        raise ValueError("outcome must follow decision")
    if row.outcome_available_at > evaluation_at:
        raise ValueError("LOOKAHEAD: outcome not yet available")
    if not isfinite(row.forward_return):
        raise ValueError("forward_return must be finite")


def _metrics(name: str, rows: list[AgentObservation]) -> ArmMetrics:
    signed: list[float] = []
    correct: list[bool] = []
    for row in rows:
        action = getattr(row, name)
        direction = {"long": 1, "short": -1, "hold": 0}[action]
        signed.append(direction * row.forward_return)
        if direction:
            correct.append(direction * row.forward_return > 0)
    return ArmMetrics(
        arm=name,
        observations=len(rows),
        participation=len(correct),
        mean_signed_return=fmean(signed),
        directional_accuracy=fmean(correct) if correct else None,
    )


def compare_agent_to_baseline(
    observations: Iterable[AgentObservation], *, evaluation_at: datetime
) -> ResearchComparison:
    """Paired descriptive comparison; NOT an execution P&L or statistical edge test.

    Both arms use identical events and fixed-horizon underlying returns. The
    0-return HOLD convention is explicit; brokerage fees, option decay, spreads,
    slippage, data leakage, and selection bias require separate evaluation.
    """
    if not _aware(evaluation_at):
        raise ValueError("evaluation_at must be timezone-aware")
    rows = list(observations)
    if not rows:
        raise ValueError("no observations")
    ids: set[str] = set()
    for row in rows:
        _validate(row, evaluation_at)
        if row.event_id in ids:
            raise ValueError("duplicate event_id")
        ids.add(row.event_id)
    baseline = _metrics("baseline", rows)
    agent = _metrics("agent", rows)
    return ResearchComparison(
        count=len(rows),
        disagreement_count=sum(row.bull != row.bear for row in rows),
        baseline=baseline,
        agent=agent,
        signed_return_increment=agent.mean_signed_return - baseline.mean_signed_return,
    )
