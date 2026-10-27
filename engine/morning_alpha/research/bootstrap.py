from __future__ import annotations

import math
import random
from collections import defaultdict
from enum import StrEnum
from statistics import fmean

from pydantic import BaseModel, ConfigDict, Field

from morning_alpha.research.statistical_models import MatchedEdgeObservation


class BootstrapClusterUnit(StrEnum):
    IID = "iid"
    DATE = "date"
    SECTOR = "sector"


class BootstrapResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    point_estimate: float
    lower: float
    upper: float
    confidence: float = Field(gt=0, lt=1)
    resamples: int = Field(gt=0)
    seed: int
    cluster_unit: BootstrapClusterUnit
    n: int = Field(gt=0)
    n_clusters: int = Field(gt=0)
    effective_cluster_count: int = Field(gt=0)
    cluster_sizes: tuple[int, ...]
    fraction_non_positive: float = Field(ge=0, le=1)


def _quantile(values: list[float], q: float) -> float:
    if not values:
        raise ValueError("quantile requires values")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def bootstrap_edge_ci(
    observations: tuple[MatchedEdgeObservation, ...] | list[MatchedEdgeObservation],
    *,
    cluster_unit: BootstrapClusterUnit = BootstrapClusterUnit.DATE,
    seed: int = 2718,
    resamples: int = 10_000,
    confidence: float = 0.95,
    min_clusters: int = 2,
) -> BootstrapResult:
    rows = tuple(observations)
    if not rows:
        raise ValueError("bootstrap requires at least one observation")
    if resamples <= 0:
        raise ValueError("resamples must be positive")
    if not 0 < confidence < 1:
        raise ValueError("confidence must be between 0 and 1")
    if min_clusters <= 0:
        raise ValueError("min_clusters must be positive")

    rng = random.Random(seed)
    means: list[float] = []

    if cluster_unit is BootstrapClusterUnit.IID:
        n_clusters = len(rows)
        cluster_sizes = tuple(1 for _ in rows)
        for _ in range(resamples):
            sample = [rows[rng.randrange(len(rows))].edge for _ in rows]
            means.append(fmean(sample))
    else:
        groups: dict[object, list[MatchedEdgeObservation]] = defaultdict(list)
        for row in rows:
            key = row.trading_date if cluster_unit is BootstrapClusterUnit.DATE else row.sector
            groups[key].append(row)
        keys = sorted(groups, key=str)
        if len(keys) < min_clusters:
            raise ValueError(f"cluster bootstrap requires at least {min_clusters} distinct clusters")
        n_clusters = len(keys)
        cluster_sizes = tuple(len(groups[key]) for key in keys)
        for _ in range(resamples):
            sampled_keys = [keys[rng.randrange(len(keys))] for _ in keys]
            sample_edges: list[float] = []
            for key in sampled_keys:
                sample_edges.extend(row.edge for row in groups[key])
            means.append(fmean(sample_edges))

    alpha = (1.0 - confidence) / 2.0
    return BootstrapResult(
        point_estimate=fmean(row.edge for row in rows),
        lower=_quantile(means, alpha),
        upper=_quantile(means, 1.0 - alpha),
        confidence=confidence,
        resamples=resamples,
        seed=seed,
        cluster_unit=cluster_unit,
        n=len(rows),
        n_clusters=n_clusters,
        effective_cluster_count=n_clusters,
        cluster_sizes=cluster_sizes,
        fraction_non_positive=sum(value <= 0 for value in means) / len(means),
    )
