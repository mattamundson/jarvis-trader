"""Research-only registry-backed point-in-time feature store.

The store is deliberately in-memory for the first integrity phase.  Its purpose
is to make temporal correctness testable before any persistence/database design
is introduced.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Iterable

from backtest.studies.feature_availability import (
    FeatureObservation,
    FeatureUnavailableError,
    _require_aware,
)
from backtest.studies.feature_registry import FeatureRegistry, UnknownFeatureError


class FeatureStore:
    """Append/query feature observations with fail-closed point-in-time semantics."""

    def __init__(self, registry: FeatureRegistry) -> None:
        self.registry = registry
        self._observations: dict[str, list[FeatureObservation]] = defaultdict(list)

    def put(self, observation: FeatureObservation) -> None:
        """Store one observation after confirming the feature is registered."""
        self.registry.get(observation.feature_id)
        bucket = self._observations[observation.feature_id]
        duplicate = any(
            existing.version == observation.version
            and existing.event_at == observation.event_at
            and existing.known_at == observation.known_at
            for existing in bucket
        )
        if duplicate:
            raise ValueError(
                f"duplicate feature observation: {observation.feature_id}@{observation.version}"
            )
        bucket.append(observation)
        bucket.sort(key=lambda item: (item.known_at, item.event_at, item.version))

    def extend(self, observations: Iterable[FeatureObservation]) -> None:
        for observation in observations:
            self.put(observation)

    def as_of(
        self,
        feature_id: str,
        decision_at: datetime,
        *,
        version: str | None = None,
        required: bool = True,
    ) -> FeatureObservation | None:
        """Return the newest observation actually known by ``decision_at``.

        Unknown feature IDs always raise.  A registered-but-not-yet-known feature
        raises ``FeatureUnavailableError`` by default so trading/research callers
        fail closed instead of silently substituting a future or missing value.
        """
        _require_aware(decision_at, "decision_at")
        self.registry.get(feature_id)
        candidates = [
            observation
            for observation in self._observations.get(feature_id, [])
            if observation.is_available(decision_at)
            and (version is None or observation.version == version)
        ]
        if not candidates:
            if required:
                raise FeatureUnavailableError(
                    f"no observation for {feature_id} is known at {decision_at.isoformat()}"
                )
            return None
        return max(candidates, key=lambda item: (item.known_at, item.event_at, item.version))

    def snapshot(
        self,
        decision_at: datetime,
        feature_ids: Iterable[str] | None = None,
        *,
        required: bool = False,
    ) -> dict[str, FeatureObservation]:
        """Return the latest known observations for a governed feature set."""
        _require_aware(decision_at, "decision_at")
        selected = tuple(feature_ids) if feature_ids is not None else self.registry.ids()
        snapshot: dict[str, FeatureObservation] = {}
        for feature_id in selected:
            # Validate IDs even when ``required=False``.  Typos must not disappear.
            try:
                observation = self.as_of(feature_id, decision_at, required=required)
            except UnknownFeatureError:
                raise
            if observation is not None:
                snapshot[feature_id] = observation
        return snapshot
