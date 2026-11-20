from __future__ import annotations

from statistics import fmean

from pydantic import BaseModel, ConfigDict, Field


class StructuralObservation(BaseModel):
    model_config = ConfigDict(frozen=True)
    observation_id: str = Field(min_length=1)
    edge: float
    dimensions: dict[str, str] = Field(default_factory=dict)


class BucketEvidence(BaseModel):
    model_config = ConfigDict(frozen=True)
    n: int
    mean_edge: float
    eligible: bool


class StructuralRobustnessReport(BaseModel):
    model_config = ConfigDict(frozen=True)
    dimension: str
    overall_mean_edge: float
    buckets: dict[str, BucketEvidence]
    strongest_bucket: str | None
    worst_bucket: str | None
    leave_one_out: dict[str, float]
    mean_without_strongest: float | None
    retained_edge_fraction: float | None
    insufficient_buckets: tuple[str, ...]
    missing_dimension_count: int


def analyze_dimension(
    observations: tuple[StructuralObservation, ...] | list[StructuralObservation],
    *,
    dimension: str,
    min_bucket_n: int = 10,
) -> StructuralRobustnessReport:
    if min_bucket_n < 1:
        raise ValueError("min_bucket_n must be >= 1")
    rows = tuple(observations)
    if not rows:
        raise ValueError("observations cannot be empty")
    grouped: dict[str, list[StructuralObservation]] = {}
    missing = 0
    for row in rows:
        key = row.dimensions.get(dimension)
        if key is None:
            missing += 1
            continue
        grouped.setdefault(key, []).append(row)
    buckets = {
        key: BucketEvidence(
            n=len(group),
            mean_edge=fmean(row.edge for row in group),
            eligible=len(group) >= min_bucket_n,
        )
        for key, group in sorted(grouped.items())
    }
    eligible = {key: evidence for key, evidence in buckets.items() if evidence.eligible}
    strongest = max(eligible, key=lambda k: eligible[k].mean_edge) if eligible else None
    worst = min(eligible, key=lambda k: eligible[k].mean_edge) if eligible else None
    overall = fmean(row.edge for row in rows)
    leave_one: dict[str, float] = {}
    for key in eligible:
        remaining = [row.edge for row in rows if row.dimensions.get(dimension) != key]
        if remaining:
            leave_one[key] = fmean(remaining)
    without = leave_one.get(strongest) if strongest else None
    if without is None or overall == 0:
        retained = None
    else:
        retained = without / overall
    return StructuralRobustnessReport(
        dimension=dimension,
        overall_mean_edge=overall,
        buckets=buckets,
        strongest_bucket=strongest,
        worst_bucket=worst,
        leave_one_out=leave_one,
        mean_without_strongest=without,
        retained_edge_fraction=retained,
        insufficient_buckets=tuple(k for k, v in buckets.items() if not v.eligible),
        missing_dimension_count=missing,
    )
