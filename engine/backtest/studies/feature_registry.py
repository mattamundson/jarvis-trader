"""Research-only loader for FEATURE_REGISTRY_V2.yaml.

The registry is governance metadata, not a source of trading signals.  It keeps
engineering state (source/parity/causality) separate from statistical evidence
and deployment eligibility.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml


class FeatureRegistryError(ValueError):
    """Raised when registry content is malformed or internally inconsistent."""


class UnknownFeatureError(KeyError):
    """Raised when a consumer requests a feature that is not registered."""


@dataclass(frozen=True)
class FeatureDefinition:
    id: str
    family: str
    role: str
    priority: str
    availability: str
    source_integrity: str
    causal_integrity: str
    parity: str
    statistical_evidence: str
    deployment: str
    raw: dict[str, Any]

    @classmethod
    def from_mapping(cls, mapping: dict[str, Any]) -> "FeatureDefinition":
        required = {
            "id",
            "family",
            "role",
            "priority",
            "availability",
            "source_integrity",
            "causal_integrity",
            "parity",
            "statistical_evidence",
            "deployment",
        }
        missing = sorted(required - mapping.keys())
        if missing:
            raise FeatureRegistryError(
                f"feature {mapping.get('id', '<unknown>')} missing fields: {missing}"
            )
        feature_id = str(mapping["id"]).strip()
        if not feature_id:
            raise FeatureRegistryError("feature id must be non-empty")
        return cls(
            id=feature_id,
            family=str(mapping["family"]),
            role=str(mapping["role"]),
            priority=str(mapping["priority"]),
            availability=str(mapping["availability"]),
            source_integrity=str(mapping["source_integrity"]),
            causal_integrity=str(mapping["causal_integrity"]),
            parity=str(mapping["parity"]),
            statistical_evidence=str(mapping["statistical_evidence"]),
            deployment=str(mapping["deployment"]),
            raw=dict(mapping),
        )

    @property
    def live_eligible(self) -> bool:
        return (
            self.deployment == "live_allowed"
            and self.causal_integrity in {"safe", "safe_core", "safe_formula"}
            and self.parity == "passed"
            and self.statistical_evidence in {"paper_pass", "live_pass"}
        )


class FeatureRegistry:
    """Immutable indexed view of registry-v2 feature definitions."""

    def __init__(self, definitions: Iterable[FeatureDefinition]) -> None:
        indexed: dict[str, FeatureDefinition] = {}
        for definition in definitions:
            if definition.id in indexed:
                raise FeatureRegistryError(f"duplicate feature id: {definition.id}")
            indexed[definition.id] = definition
        if not indexed:
            raise FeatureRegistryError("registry contains no features")
        self._definitions = indexed

    @classmethod
    def from_yaml(cls, path: str | Path) -> "FeatureRegistry":
        registry_path = Path(path)
        payload = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("version") != 2:
            raise FeatureRegistryError("expected FEATURE_REGISTRY_V2 version 2")
        features = payload.get("features")
        if not isinstance(features, list):
            raise FeatureRegistryError("registry features must be a list")
        return cls(FeatureDefinition.from_mapping(item) for item in features)

    def get(self, feature_id: str) -> FeatureDefinition:
        try:
            return self._definitions[feature_id]
        except KeyError as exc:
            raise UnknownFeatureError(feature_id) from exc

    def __contains__(self, feature_id: object) -> bool:
        return feature_id in self._definitions

    def __len__(self) -> int:
        return len(self._definitions)

    def ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._definitions))
