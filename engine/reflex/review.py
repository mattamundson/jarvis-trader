"""
JARVIS TRADER -- Reflex session review
======================================
Scores a session's reflex decisions after the fact: Brier on directional
confidence, a reliability table by confidence bucket, and counts of what the
policy did and why.

This produces a REPORT. It deliberately does not rewrite the judge, the
schema, or any threshold. Nightly auto-rewriting a live decision layer on one
session of fills is the in-sample, self-fulfilling loop this project has
already been burned by (DSR contamination; see
``analytics/calibration.py`` point-in-time notes). Changes suggested by a
review go through a PR and the existing pre-registration / forward-test gates.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Sequence

from reflex.policy import PolicyOutcome
from reflex.schema import Direction, ReflexDecision

__all__ = ["ReviewRecord", "review_session", "RELIABILITY_EDGES"]

RELIABILITY_EDGES = (0.5, 0.6, 0.7, 0.8, 0.9, 1.0)


@dataclass(frozen=True)
class ReviewRecord:
    as_of: datetime
    decision: Optional[ReflexDecision]
    outcome: PolicyOutcome
    # Was the judged direction right over the labelling horizon? None = not yet
    # labelled or the decision was neutral.
    direction_correct: Optional[bool] = None
    label_ts: Optional[datetime] = None  # when the label became knowable; must be > as_of


def _scored(records: Sequence[ReviewRecord]) -> list[tuple[float, float]]:
    pairs = []
    for r in records:
        if r.decision is None or r.decision.direction == Direction.NEUTRAL or r.direction_correct is None:
            continue
        if r.label_ts is None or r.label_ts <= r.as_of:
            raise ValueError(f"label for {r.as_of.isoformat()} is not strictly after the decision (look-ahead)")
        pairs.append((r.decision.direction_confidence, 1.0 if r.direction_correct else 0.0))
    return pairs


def _reliability(pairs: Sequence[tuple[float, float]]) -> list[dict]:
    rows = []
    for lo, hi in zip(RELIABILITY_EDGES[:-1], RELIABILITY_EDGES[1:], strict=True):
        last = hi == RELIABILITY_EDGES[-1]
        bucket = [(p, y) for p, y in pairs if lo <= p < hi or (last and p == hi)]
        if not bucket:
            rows.append({"bucket": f"{lo:.1f}-{hi:.1f}", "n": 0, "mean_conf": None, "hit_rate": None})
            continue
        rows.append({
            "bucket": f"{lo:.1f}-{hi:.1f}",
            "n": len(bucket),
            "mean_conf": round(sum(p for p, _ in bucket) / len(bucket), 4),
            "hit_rate": round(sum(y for _, y in bucket) / len(bucket), 4),
        })
    return rows


def review_session(records: Sequence[ReviewRecord]) -> dict:
    """Summarize one session. Brier is ``None`` when nothing is labelled --
    never a default number that could be mistaken for a measurement."""
    pairs = _scored(records)
    brier = round(sum((p - y) ** 2 for p, y in pairs) / len(pairs), 6) if pairs else None
    reasons: Counter = Counter()
    for r in records:
        reasons.update(r.outcome.reasons)
    n = len(records)
    actions = Counter(r.outcome.action.value for r in records)
    return {
        "n_decisions": n,
        "n_scored": len(pairs),
        "brier": brier,
        "brier_coinflip_reference": 0.25,
        "reliability": _reliability(pairs),
        "actions": dict(actions),
        "escalation_rate": round(actions.get("escalate", 0) / n, 4) if n else None,
        "invalid_decisions": sum(1 for r in records if r.decision is None),
        "block_reasons": dict(reasons.most_common()),
    }
