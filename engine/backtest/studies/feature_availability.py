"""Research-only point-in-time feature availability contracts.

This module prevents a strategy/research consumer from using a feature before the
information was actually available. It is intentionally isolated from live
execution paths while the feature-integrity work is validated.

Core invariant:
    event_at <= available_at <= known_at <= decision_at

where ``known_at`` is max(available_at, computed_at). ``available_at`` is the
earliest time the source information could legitimately be known; ``computed_at``
is when JARVIS actually materialized the feature.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable


class FeatureAvailabilityError(ValueError):
    """Base error for invalid point-in-time feature observations."""


class FeatureUnavailableError(FeatureAvailabilityError):
    """Raised when a feature is requested before it was actually known."""


def _require_aware(timestamp: datetime, field_name: str) -> None:
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise FeatureAvailabilityError(f"{field_name} must be timezone-aware")


@dataclass(frozen=True)
class FeatureObservation:
    """One versioned feature value with explicit point-in-time availability.

    ``event_at``
        Time of the underlying market/information event represented by the
        feature (for example, the end of an ORB window or a news release time).

    ``available_at``
        Earliest time the information could legitimately be known by the system.
        This may be later than ``event_at`` for delayed-confirmation features.

    ``computed_at``
        Time JARVIS actually materialized the value. A feature cannot be used
        before this even when its source information was theoretically available.
    """

    feature_id: str
    value: Any
    event_at: datetime
    available_at: datetime
    computed_at: datetime
    version: str = "1"

    def __post_init__(self) -> None:
        if not self.feature_id.strip():
            raise FeatureAvailabilityError("feature_id must be non-empty")
        if not self.version.strip():
            raise FeatureAvailabilityError("version must be non-empty")

        for field_name in ("event_at", "available_at", "computed_at"):
            _require_aware(getattr(self, field_name), field_name)

        if self.available_at < self.event_at:
            raise FeatureAvailabilityError("available_at cannot precede event_at")
        if self.computed_at < self.event_at:
            raise FeatureAvailabilityError("computed_at cannot precede event_at")

    @property
    def known_at(self) -> datetime:
        """First timestamp at which this exact observation was usable by JARVIS."""
        return max(self.available_at, self.computed_at)

    def is_available(self, decision_at: datetime) -> bool:
        _require_aware(decision_at, "decision_at")
        return self.known_at <= decision_at

    def require_available(self, decision_at: datetime) -> "FeatureObservation":
        """Return self if usable at ``decision_at``; otherwise fail closed."""
        if not self.is_available(decision_at):
            raise FeatureUnavailableError(
                f"{self.feature_id}@{self.version} known_at={self.known_at.isoformat()} "
                f"is unavailable for decision_at={decision_at.isoformat()}"
            )
        return self


def point_in_time_snapshot(
    observations: Iterable[FeatureObservation],
    decision_at: datetime,
) -> dict[str, FeatureObservation]:
    """Return the latest known observation per feature as of ``decision_at``.

    Observations that are not yet known are ignored. When multiple versions of a
    feature are supplied, the latest *known observation timestamp* wins; callers
    should normally query one approved feature version at a time.
    """
    _require_aware(decision_at, "decision_at")
    snapshot: dict[str, FeatureObservation] = {}
    for observation in observations:
        if not observation.is_available(decision_at):
            continue
        current = snapshot.get(observation.feature_id)
        if current is None or observation.known_at > current.known_at:
            snapshot[observation.feature_id] = observation
    return snapshot
