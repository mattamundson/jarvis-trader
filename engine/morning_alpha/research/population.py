from __future__ import annotations

import json
from collections import Counter
from datetime import date, datetime, time
from enum import StrEnum
from hashlib import sha256
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, SerializeAsAny, model_validator

from morning_alpha.config import MorningAlphaConfig
from morning_alpha.models import MarketBar, SetupCandidate, StrategyKey
from morning_alpha.research.campaign import DataReadinessReport, require_research_ready
from morning_alpha.research.feature_builder import HistoricalFeatureBuilder, HistoricalFeatureSnapshot
from morning_alpha.setups.relative_strength_breakout import RelativeStrengthBreakout


NEW_YORK = ZoneInfo("America/New_York")


class PopulationDecisionClock:
    """Canonical historical Morning Alpha decision clock: 09:00 America/New_York."""

    timezone = NEW_YORK
    hour = 9
    minute = 0

    def at(self, trading_date: date) -> datetime:
        if trading_date.weekday() >= 5:
            raise ValueError("decision date must be a trading day")
        return datetime.combine(trading_date, time(self.hour, self.minute), tzinfo=self.timezone)

    @property
    def canonical(self) -> str:
        return "09:00 America/New_York"


class CandidateDecisionState(StrEnum):
    QUALIFIED = "qualified"
    REJECTED = "rejected"


def _require_aware(ts: datetime, name: str) -> None:
    if ts.tzinfo is None or ts.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def _hash_payload(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(encoded.encode("utf-8")).hexdigest()


def candidate_identity(strategy: StrategyKey, stable_security_id: str, decision_timestamp: datetime) -> str:
    _require_aware(decision_timestamp, "decision_timestamp")
    if not stable_security_id:
        raise ValueError("stable_security_id cannot be empty")
    payload = f"{strategy.canonical}|{stable_security_id}|{decision_timestamp.isoformat()}"
    return sha256(payload.encode("utf-8")).hexdigest()


class CandidateObservation(BaseModel):
    model_config = ConfigDict(frozen=True)

    candidate_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    campaign_id: str = Field(min_length=1)
    strategy: StrategyKey
    stable_security_id: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    decision_timestamp: datetime
    trading_date: date
    sector: str | None = None
    sector_etf: str | None = None
    decision_state: CandidateDecisionState
    rejection_reason: str | None = None
    feature_hash: str = Field(pattern=r"^.{64}$")
    universe_hash: str = Field(pattern=r"^.{64}$")
    data_manifest_hash: str = Field(pattern=r"^.{64}$")
    source_lineage_hash: str = Field(pattern=r"^.{64}$")
    feature_snapshot: dict[str, Any] = Field(default_factory=dict)
    detector_candidate: SerializeAsAny[SetupCandidate] | None = None
    listing_timestamp: datetime | None = None
    delisting_timestamp: datetime | None = None
    sector_effective_from: datetime | None = None
    sector_effective_to: datetime | None = None
    market_data_timestamp: datetime | None = None

    @model_validator(mode="after")
    def validate_observation(self) -> "CandidateObservation":
        _require_aware(self.decision_timestamp, "decision_timestamp")
        if self.trading_date != self.decision_timestamp.date():
            raise ValueError("trading_date must match decision_timestamp date")
        expected = candidate_identity(self.strategy, self.stable_security_id, self.decision_timestamp)
        if self.candidate_id != expected:
            raise ValueError("candidate_id does not match immutable identity")
        if self.decision_state is CandidateDecisionState.QUALIFIED and self.detector_candidate is None:
            raise ValueError("qualified observation requires detector_candidate")
        if self.decision_state is CandidateDecisionState.REJECTED and not self.rejection_reason:
            raise ValueError("rejected observation requires rejection_reason")
        for name in ("listing_timestamp", "delisting_timestamp", "sector_effective_from", "sector_effective_to", "market_data_timestamp"):
            value = getattr(self, name)
            if value is not None:
                _require_aware(value, name)
        return self


class PopulationBuildResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    decision_timestamp: datetime
    observations: tuple[CandidateObservation, ...]
    input_universe_count: int = Field(ge=0)
    qualified_count: int = Field(ge=0)
    rejected_count: int = Field(ge=0)
    rejection_counts: dict[str, int]
    universe_hash: str = Field(pattern=r"^.{64}$")
    population_hash: str = Field(pattern=r"^.{64}$")

    @model_validator(mode="after")
    def validate_population(self) -> "PopulationBuildResult":
        _require_aware(self.decision_timestamp, "decision_timestamp")
        ids = [row.candidate_id for row in self.observations]
        if len(ids) != len(set(ids)):
            raise ValueError("DUPLICATE_CANDIDATE")
        if self.input_universe_count != len(self.observations):
            raise ValueError("ACCOUNTING_MISMATCH: input universe count does not equal observations")
        if self.qualified_count + self.rejected_count != self.input_universe_count:
            raise ValueError("ACCOUNTING_MISMATCH: qualified + rejected does not equal universe")
        if self.qualified_count != sum(
            row.decision_state is CandidateDecisionState.QUALIFIED for row in self.observations
        ):
            raise ValueError("ACCOUNTING_MISMATCH: qualified count")
        if self.rejected_count != sum(
            row.decision_state is CandidateDecisionState.REJECTED for row in self.observations
        ):
            raise ValueError("ACCOUNTING_MISMATCH: rejected count")
        if sum(self.rejection_counts.values()) != self.rejected_count:
            raise ValueError("ACCOUNTING_MISMATCH: rejection reasons")
        return self


class HistoricalUniverseMember(BaseModel):
    model_config = ConfigDict(frozen=True)

    stable_security_id: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    sector: str = Field(min_length=1)
    sector_etf: str = Field(min_length=1)
    listing_timestamp: datetime
    delisting_timestamp: datetime | None = None
    security_type: str = "common_stock"
    primary_exchange: str | None = None
    sector_effective_from: datetime | None = None
    sector_effective_to: datetime | None = None
    market_data_timestamp: datetime | None = None

    @model_validator(mode="after")
    def validate_membership(self) -> "HistoricalUniverseMember":
        _require_aware(self.listing_timestamp, "listing_timestamp")
        if self.delisting_timestamp is not None:
            _require_aware(self.delisting_timestamp, "delisting_timestamp")
            if self.delisting_timestamp <= self.listing_timestamp:
                raise ValueError("delisting_timestamp must be after listing_timestamp")
        for name in ("sector_effective_from", "sector_effective_to", "market_data_timestamp"):
            value = getattr(self, name)
            if value is not None:
                _require_aware(value, name)
        start = self.sector_effective_from or self.listing_timestamp
        if self.sector_effective_to is not None and self.sector_effective_to <= start:
            raise ValueError("sector_effective_to must be after sector_effective_from")
        return self

    def active_at(self, decision_timestamp: datetime) -> bool:
        _require_aware(decision_timestamp, "decision_timestamp")
        return self.listing_timestamp <= decision_timestamp and (
            self.delisting_timestamp is None or self.delisting_timestamp > decision_timestamp
        )

    def sector_active_at(self, decision_timestamp: datetime) -> bool:
        _require_aware(decision_timestamp, "decision_timestamp")
        start = self.sector_effective_from or self.listing_timestamp
        return start <= decision_timestamp and (
            self.sector_effective_to is None or self.sector_effective_to > decision_timestamp
        )

    def eligible_at(self, decision_timestamp: datetime) -> bool:
        _require_aware(decision_timestamp, "decision_timestamp")
        if not self.active_at(decision_timestamp) or not self.sector_active_at(decision_timestamp):
            return False
        if self.market_data_timestamp is not None and self.market_data_timestamp > decision_timestamp:
            return False
        return True


HistoricalSecurityRecord = HistoricalUniverseMember


class HistoricalCandidatePopulationBuilder:
    def __init__(
        self,
        *,
        config: MorningAlphaConfig | None = None,
        feature_builder: HistoricalFeatureBuilder | None = None,
        detector: RelativeStrengthBreakout | None = None,
    ) -> None:
        self.config = config or MorningAlphaConfig()
        self.feature_builder = feature_builder or HistoricalFeatureBuilder()
        self.detector = detector or RelativeStrengthBreakout()

    @staticmethod
    def _universe_hash(members: list[HistoricalUniverseMember]) -> str:
        return _hash_payload(sorted(member.stable_security_id for member in members))

    @staticmethod
    def _rejection_hash(member: HistoricalUniverseMember, reason: str, manifest_hash: str) -> str:
        return _hash_payload(
            {
                "stable_security_id": member.stable_security_id,
                "symbol": member.symbol,
                "reason": reason,
                "manifest": manifest_hash,
            }
        )

    def _observation_from_feature(
        self,
        *,
        member: HistoricalUniverseMember,
        campaign_id: str,
        decision_timestamp: datetime,
        universe_hash: str,
        data_manifest_hash: str,
        feature: HistoricalFeatureSnapshot,
        rejection_reason: str | None,
        detector_candidate: SetupCandidate | None,
    ) -> CandidateObservation:
        state = (
            CandidateDecisionState.QUALIFIED
            if detector_candidate is not None and rejection_reason is None
            else CandidateDecisionState.REJECTED
        )
        return CandidateObservation(
            candidate_id=candidate_identity(self.detector.strategy, member.stable_security_id, decision_timestamp),
            campaign_id=campaign_id,
            strategy=self.detector.strategy,
            stable_security_id=member.stable_security_id,
            symbol=member.symbol,
            decision_timestamp=decision_timestamp,
            trading_date=decision_timestamp.date(),
            sector=member.sector,
            sector_etf=member.sector_etf,
            decision_state=state,
            rejection_reason=rejection_reason,
            feature_hash=feature.feature_hash,
            universe_hash=universe_hash,
            data_manifest_hash=data_manifest_hash,
            source_lineage_hash=feature.source_lineage_hash,
            feature_snapshot=feature.model_dump(mode="json"),
            detector_candidate=detector_candidate,
            listing_timestamp=member.listing_timestamp,
            delisting_timestamp=member.delisting_timestamp,
            sector_effective_from=member.sector_effective_from or member.listing_timestamp,
            sector_effective_to=member.sector_effective_to,
            market_data_timestamp=member.market_data_timestamp,
        )

    def _observation_without_feature(
        self,
        *,
        member: HistoricalUniverseMember,
        campaign_id: str,
        decision_timestamp: datetime,
        universe_hash: str,
        data_manifest_hash: str,
        reason: str,
    ) -> CandidateObservation:
        rejection_hash = self._rejection_hash(member, reason, data_manifest_hash)
        return CandidateObservation(
            candidate_id=candidate_identity(self.detector.strategy, member.stable_security_id, decision_timestamp),
            campaign_id=campaign_id,
            strategy=self.detector.strategy,
            stable_security_id=member.stable_security_id,
            symbol=member.symbol,
            decision_timestamp=decision_timestamp,
            trading_date=decision_timestamp.date(),
            sector=member.sector,
            sector_etf=member.sector_etf,
            decision_state=CandidateDecisionState.REJECTED,
            rejection_reason=reason,
            feature_hash=rejection_hash,
            universe_hash=universe_hash,
            data_manifest_hash=data_manifest_hash,
            source_lineage_hash=rejection_hash,
            feature_snapshot={},
            detector_candidate=None,
            listing_timestamp=member.listing_timestamp,
            delisting_timestamp=member.delisting_timestamp,
            sector_effective_from=member.sector_effective_from or member.listing_timestamp,
            sector_effective_to=member.sector_effective_to,
            market_data_timestamp=member.market_data_timestamp,
        )

    def build_session(
        self,
        *,
        readiness: DataReadinessReport,
        campaign_id: str,
        decision_timestamp: datetime,
        data_manifest_hash: str,
        universe: tuple[HistoricalUniverseMember, ...] | list[HistoricalUniverseMember],
        bars_by_symbol: dict[str, list[MarketBar]],
        spy_bars: list[MarketBar],
        sector_bars_by_etf: dict[str, list[MarketBar]],
    ) -> PopulationBuildResult:
        require_research_ready(readiness)
        _require_aware(decision_timestamp, "decision_timestamp")
        active = sorted(
            (member for member in universe if member.eligible_at(decision_timestamp)),
            key=lambda member: member.stable_security_id,
        )
        universe_hash = self._universe_hash(active)
        observations: list[CandidateObservation] = []

        for member in active:
            stock_bars = bars_by_symbol.get(member.symbol, [])
            sector_bars = sector_bars_by_etf.get(member.sector_etf)
            if sector_bars is None:
                observations.append(
                    self._observation_without_feature(
                        member=member,
                        campaign_id=campaign_id,
                        decision_timestamp=decision_timestamp,
                        universe_hash=universe_hash,
                        data_manifest_hash=data_manifest_hash,
                        reason="BENCHMARK_MISSING",
                    )
                )
                continue
            try:
                feature = self.feature_builder.build(
                    stable_security_id=member.stable_security_id,
                    symbol=member.symbol,
                    sector=member.sector,
                    sector_etf=member.sector_etf,
                    decision_timestamp=decision_timestamp,
                    data_manifest_hash=data_manifest_hash,
                    stock_bars=stock_bars,
                    spy_bars=spy_bars,
                    sector_bars=sector_bars,
                )
            except ValueError as exc:
                message = str(exc)
                if message.startswith("INSUFFICIENT_HISTORY"):
                    reason = "INSUFFICIENT_HISTORY"
                elif message.startswith("BENCHMARK_ALIGNMENT_FAILED"):
                    reason = "BENCHMARK_ALIGNMENT_FAILED"
                else:
                    raise
                observations.append(
                    self._observation_without_feature(
                        member=member,
                        campaign_id=campaign_id,
                        decision_timestamp=decision_timestamp,
                        universe_hash=universe_hash,
                        data_manifest_hash=data_manifest_hash,
                        reason=reason,
                    )
                )
                continue

            if (
                feature.price_as_of < self.config.min_price
                or feature.avg_daily_shares_20d < self.config.min_avg_daily_shares
                or feature.avg_dollar_volume_20d < self.config.min_avg_dollar_volume_20d
            ):
                observations.append(
                    self._observation_from_feature(
                        member=member,
                        campaign_id=campaign_id,
                        decision_timestamp=decision_timestamp,
                        universe_hash=universe_hash,
                        data_manifest_hash=data_manifest_hash,
                        feature=feature,
                        rejection_reason="LIQUIDITY_REJECTED",
                        detector_candidate=None,
                    )
                )
                continue

            detector_candidate = self.detector.evaluate(
                feature.to_instrument_snapshot(), feature.to_setup_context()
            )
            observations.append(
                self._observation_from_feature(
                    member=member,
                    campaign_id=campaign_id,
                    decision_timestamp=decision_timestamp,
                    universe_hash=universe_hash,
                    data_manifest_hash=data_manifest_hash,
                    feature=feature,
                    rejection_reason=None if detector_candidate is not None else "DETECTOR_REJECTED",
                    detector_candidate=detector_candidate,
                )
            )

        rejection_counts = Counter(
            row.rejection_reason
            for row in observations
            if row.decision_state is CandidateDecisionState.REJECTED and row.rejection_reason is not None
        )
        qualified_count = sum(
            row.decision_state is CandidateDecisionState.QUALIFIED for row in observations
        )
        population_payload = {
            "decision_timestamp": decision_timestamp.isoformat(),
            "universe_hash": universe_hash,
            "data_manifest_hash": data_manifest_hash,
            "observations": [
                row.model_dump(mode="json") for row in sorted(observations, key=lambda row: row.candidate_id)
            ],
        }
        population_hash = _hash_payload(population_payload)
        return PopulationBuildResult(
            decision_timestamp=decision_timestamp,
            observations=tuple(sorted(observations, key=lambda row: row.candidate_id)),
            input_universe_count=len(active),
            qualified_count=qualified_count,
            rejected_count=len(active) - qualified_count,
            rejection_counts=dict(sorted(rejection_counts.items())),
            universe_hash=universe_hash,
            population_hash=population_hash,
        )
