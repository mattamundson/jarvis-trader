from __future__ import annotations

from statistics import fmean
from typing import Iterable

from pydantic import BaseModel, ConfigDict, Field


class ParameterPoint(BaseModel):
    model_config = ConfigDict(frozen=True)

    parameter_value: float
    expectancy_r: float
    sample_size: int = Field(gt=0)


class ParameterStabilityReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    points: tuple[ParameterPoint, ...]
    adjacent_dispersion: float
    max_neighbor_drop: float
    positive_neighbor_fraction: float
    min_sample_size: int
    stability_score: float = Field(ge=0.0, le=1.0)


def analyze_parameter_stability(
    points: Iterable[ParameterPoint],
) -> ParameterStabilityReport:
    ordered = tuple(sorted(points, key=lambda row: row.parameter_value))
    if not ordered:
        return ParameterStabilityReport(
            points=(),
            adjacent_dispersion=0.0,
            max_neighbor_drop=0.0,
            positive_neighbor_fraction=0.0,
            min_sample_size=0,
            stability_score=0.0,
        )

    min_sample = min(row.sample_size for row in ordered)
    if len(ordered) < 2:
        return ParameterStabilityReport(
            points=ordered,
            adjacent_dispersion=0.0,
            max_neighbor_drop=0.0,
            positive_neighbor_fraction=0.0,
            min_sample_size=min_sample,
            stability_score=0.0,
        )

    expectancies = [row.expectancy_r for row in ordered]
    diffs = [abs(right - left) for left, right in zip(expectancies, expectancies[1:])]
    adjacent_dispersion = fmean(diffs)
    max_neighbor_drop = max(diffs)
    positive_neighbor_fraction = sum(
        1
        for left, right in zip(expectancies, expectancies[1:])
        if left > 0 and right > 0
    ) / (len(ordered) - 1)
    sample_factor = min(1.0, min_sample / 200.0)
    raw_score = positive_neighbor_fraction * sample_factor / (
        1.0 + adjacent_dispersion + max_neighbor_drop
    )
    stability_score = max(0.0, min(1.0, raw_score))

    return ParameterStabilityReport(
        points=ordered,
        adjacent_dispersion=adjacent_dispersion,
        max_neighbor_drop=max_neighbor_drop,
        positive_neighbor_fraction=positive_neighbor_fraction,
        min_sample_size=min_sample,
        stability_score=stability_score,
    )
