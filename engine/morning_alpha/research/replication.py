from __future__ import annotations

from statistics import fmean

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ReplicationCandidate(BaseModel):
    model_config = ConfigDict(frozen=True)
    candidate_id: str = Field(min_length=1)
    features: dict[str, float] = Field(default_factory=dict)
    triggered: bool
    outcome_r: float | None = None


class ReplicationDataset(BaseModel):
    model_config = ConfigDict(frozen=True)
    provider: str = Field(min_length=1)
    lineage_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidates: tuple[ReplicationCandidate, ...]

    @model_validator(mode="after")
    def unique_candidates(self) -> "ReplicationDataset":
        ids=[row.candidate_id for row in self.candidates]
        if len(ids)!=len(set(ids)):
            raise ValueError("duplicate candidate_id in replication dataset")
        return self


class ReplicationReport(BaseModel):
    model_config = ConfigDict(frozen=True)
    status: str
    reasons: tuple[str, ...] = ()
    candidate_overlap_rate: float = 0.0
    missing_from_secondary: tuple[str, ...] = ()
    missing_from_primary: tuple[str, ...] = ()
    trigger_disagreement_rate: float | None = None
    feature_mean_absolute_delta: dict[str, float] = Field(default_factory=dict)
    primary_expectancy_r: float | None = None
    secondary_expectancy_r: float | None = None
    expectancy_delta_r: float | None = None


class ShadowComparisonEvent(BaseModel):
    model_config = ConfigDict(frozen=True)
    primary_signal_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    shadow_signal_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    same_decision: bool
    reason: str = Field(min_length=1)


class ShadowComparisonJournal:
    def __init__(self) -> None:
        self._events: list[ShadowComparisonEvent] = []

    @property
    def events(self) -> tuple[ShadowComparisonEvent, ...]:
        return tuple(self._events)

    def append(self, **kwargs) -> ShadowComparisonEvent:
        event=ShadowComparisonEvent(**kwargs); self._events.append(event); return event


def compare_replication(primary: ReplicationDataset, secondary: ReplicationDataset) -> ReplicationReport:
    if primary.provider==secondary.provider or primary.lineage_hash==secondary.lineage_hash:
        return ReplicationReport(status="invalid", reasons=("INDEPENDENT_LINEAGE_REQUIRED",))
    p={r.candidate_id:r for r in primary.candidates}; s={r.candidate_id:r for r in secondary.candidates}; common=tuple(sorted(set(p)&set(s))); union=set(p)|set(s)
    overlap=len(common)/len(union) if union else 1.0; missing_s=tuple(sorted(set(p)-set(s))); missing_p=tuple(sorted(set(s)-set(p)))
    disagreements=sum(p[k].triggered!=s[k].triggered for k in common)/len(common) if common else None
    keys=sorted({key for k in common for key in set(p[k].features)&set(s[k].features)})
    deltas={key:fmean(abs(p[k].features[key]-s[k].features[key]) for k in common if key in p[k].features and key in s[k].features) for key in keys}
    p_out=[p[k].outcome_r for k in common if p[k].outcome_r is not None]; s_out=[s[k].outcome_r for k in common if s[k].outcome_r is not None]
    p_exp=fmean(p_out) if p_out else None; s_exp=fmean(s_out) if s_out else None; delta=(s_exp-p_exp) if p_exp is not None and s_exp is not None else None
    return ReplicationReport(status="complete", candidate_overlap_rate=overlap, missing_from_secondary=missing_s, missing_from_primary=missing_p, trigger_disagreement_rate=disagreements, feature_mean_absolute_delta=deltas, primary_expectancy_r=p_exp, secondary_expectancy_r=s_exp, expectancy_delta_r=delta)
