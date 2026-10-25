"""Point-in-time feature snapshot manifests for trading decisions."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping, Optional, Sequence


class FeatureComponentType(str, Enum):
    """Canonical feature categories that may feed a trading decision."""

    MARKET_BARS = "market_bars"
    PRICE_MARK = "price_mark"
    GATE_VERDICT = "gate_verdict"
    FUTURES_SENTIMENT = "futures_sentiment"
    EQUITY_SENTIMENT = "equity_sentiment"
    MACRO_CONTEXT = "macro_context"
    OPTIONS_CONTEXT = "options_context"
    ACCOUNT_STATE = "account_state"
    POSITION_STATE = "position_state"
    LLM_PROMPT = "llm_prompt"


class FeatureFreshnessStatus(str, Enum):
    """Machine-readable freshness status for one feature component."""

    FRESH = "fresh"
    STALE = "stale"
    MISSING = "missing"
    UNKNOWN = "unknown"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_time(value: datetime | str | int | float | None) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
    return None


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


@dataclass(frozen=True)
class FeatureComponent:
    """One point-in-time feature input with source and freshness metadata."""

    component_type: FeatureComponentType
    source: str
    as_of: datetime | str | int | float | None
    stale_after_s: float | None
    quality: str = "unknown"
    metadata: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))

    def age_seconds(self, *, now: datetime | None = None) -> Optional[float]:
        observed_at = _parse_time(self.as_of)
        if observed_at is None:
            return None
        current = now or _utc_now()
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        return max(0.0, (current - observed_at).total_seconds())

    def freshness_status(self, *, now: datetime | None = None) -> FeatureFreshnessStatus:
        if not self.source or self.source == "unavailable":
            return FeatureFreshnessStatus.MISSING
        if self.quality.lower() in {"none", "unavailable", "missing"}:
            return FeatureFreshnessStatus.MISSING

        age = self.age_seconds(now=now)
        if age is None or self.stale_after_s is None:
            return FeatureFreshnessStatus.UNKNOWN
        if age > self.stale_after_s:
            return FeatureFreshnessStatus.STALE
        return FeatureFreshnessStatus.FRESH

    def to_record(self, *, now: datetime | None = None) -> dict[str, Any]:
        as_of = _parse_time(self.as_of)
        status = self.freshness_status(now=now)
        return {
            "component_type": self.component_type.value,
            "source": self.source,
            "as_of": as_of.isoformat() if as_of else None,
            "stale_after_s": self.stale_after_s,
            "quality": self.quality,
            "freshness_status": status.value,
            "age_seconds": self.age_seconds(now=now),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class FeatureSnapshotManifest:
    """Hashable manifest for the feature inputs behind one decision."""

    symbol: str
    components: Sequence[FeatureComponent]
    decision_id: Optional[str] = None
    created_at: datetime | str | int | float | None = field(default_factory=_utc_now)
    schema_version: int = 1

    def to_record(self, *, now: datetime | None = None, include_snapshot_id: bool = True) -> dict:
        created_at = _parse_time(self.created_at)
        record = {
            "schema_version": self.schema_version,
            "symbol": self.symbol.upper(),
            "decision_id": self.decision_id,
            "created_at": created_at.isoformat() if created_at else None,
            "components": [component.to_record(now=now) for component in self.components],
        }
        if include_snapshot_id:
            record["snapshot_id"] = self.snapshot_id(now=now)
        return record

    def snapshot_id(self, *, now: datetime | None = None) -> str:
        payload = self.to_record(now=now, include_snapshot_id=False)
        return hashlib.sha256(_canonical_json(payload).encode()).hexdigest()

    def freshness_statuses(self, *, now: datetime | None = None) -> dict[str, str]:
        return {
            component.component_type.value: component.freshness_status(now=now).value
            for component in self.components
        }

    def blocking_reasons(
        self,
        *,
        now: datetime | None = None,
        required_components: set[FeatureComponentType] | None = None,
    ) -> list[str]:
        present = {component.component_type for component in self.components}
        reasons: list[str] = []
        for required in sorted(required_components or set(), key=lambda item: item.value):
            if required not in present:
                reasons.append(f"missing_required_component:{required.value}")

        for component in self.components:
            status = component.freshness_status(now=now)
            if status in {FeatureFreshnessStatus.MISSING, FeatureFreshnessStatus.STALE}:
                reasons.append(f"{status.value}:{component.component_type.value}")
        return reasons


def component_from_data_provenance(
    provenance: Mapping[str, Any] | None,
    *,
    now: datetime | None = None,
    stale_after_s: float = 60.0,
) -> FeatureComponent:
    """Build a market-bars component from existing decision data provenance."""
    provenance = provenance or {}
    serve_age_s = provenance.get("serve_age_s")
    current = now or _utc_now()
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    try:
        age = float(serve_age_s)
        as_of: datetime | None = datetime.fromtimestamp(
            current.timestamp() - max(0.0, age),
            tz=timezone.utc,
        )
    except (TypeError, ValueError):
        as_of = None

    return FeatureComponent(
        component_type=FeatureComponentType.MARKET_BARS,
        source=str(provenance.get("last_bar_source") or "unavailable"),
        as_of=as_of,
        stale_after_s=stale_after_s,
        quality=str(provenance.get("data_quality") or "unknown"),
        metadata=dict(provenance),
    )


def data_provenance_from_decision(decision: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    """Extract data provenance from a pipeline/approval decision shape."""
    if not isinstance(decision, Mapping):
        return None

    provenance = decision.get("data_provenance")
    if isinstance(provenance, Mapping):
        return provenance

    signal_data = decision.get("signal_data")
    if isinstance(signal_data, Mapping):
        provenance = signal_data.get("data_provenance")
        if isinstance(provenance, Mapping):
            return provenance

    return None


def manifest_from_decision_provenance(
    decision: Mapping[str, Any] | None,
    *,
    symbol: str,
    decision_id: str | None = None,
    now: datetime | None = None,
    market_bars_stale_after_s: float = 60.0,
) -> FeatureSnapshotManifest:
    """Build the required market-data snapshot manifest for authorization."""
    current = now or _utc_now()
    provenance = data_provenance_from_decision(decision)
    return FeatureSnapshotManifest(
        symbol=symbol,
        decision_id=decision_id,
        created_at=current,
        components=[
            component_from_data_provenance(
                provenance,
                now=current,
                stale_after_s=market_bars_stale_after_s,
            )
        ],
    )


def required_feature_blocking_reasons(
    decision: Mapping[str, Any] | None,
    *,
    symbol: str,
    decision_id: str | None = None,
    now: datetime | None = None,
    market_bars_stale_after_s: float = 60.0,
) -> list[str]:
    """Return fail-closed reasons for required decision feature freshness."""
    manifest = manifest_from_decision_provenance(
        decision,
        symbol=symbol,
        decision_id=decision_id,
        now=now,
        market_bars_stale_after_s=market_bars_stale_after_s,
    )
    reasons = manifest.blocking_reasons(
        now=now,
        required_components={FeatureComponentType.MARKET_BARS},
    )
    statuses = manifest.freshness_statuses(now=now)
    if statuses.get(FeatureComponentType.MARKET_BARS.value) == FeatureFreshnessStatus.UNKNOWN.value:
        reasons.append(f"unknown:{FeatureComponentType.MARKET_BARS.value}")
    return reasons
