from __future__ import annotations

import itertools
import random
from collections import defaultdict
from enum import StrEnum
from statistics import fmean, median, pstdev

from pydantic import BaseModel, ConfigDict, Field

from morning_alpha.research.statistical_models import MatchedEdgeObservation


class PermutationMode(StrEnum):
    EXACT = "exact"
    MONTE_CARLO = "monte_carlo"


class PairedPermutationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    n: int = Field(gt=0)
    observed_mean_edge: float
    observed_median_edge: float
    null_mean: float
    null_std: float
    one_sided_p: float = Field(ge=0, le=1)
    two_sided_p: float = Field(ge=0, le=1)
    percentile_rank: float = Field(ge=0, le=1)
    mode: PermutationMode
    seed: int
    permutations: int = Field(gt=0)


def _mean_signed(edges: list[float], signs: tuple[int, ...] | list[int]) -> float:
    return fmean(edge * sign for edge, sign in zip(edges, signs))


def paired_edge_permutation(
    observations: tuple[MatchedEdgeObservation, ...] | list[MatchedEdgeObservation],
    *,
    seed: int = 1729,
    permutations: int = 10_000,
    exact_max_n: int = 20,
) -> PairedPermutationResult:
    rows = tuple(observations)
    if not rows:
        raise ValueError("paired permutation requires at least one observation")
    edges = [row.edge for row in rows]
    observed = fmean(edges)

    if len(rows) <= exact_max_n:
        null = [
            _mean_signed(edges, signs)
            for signs in itertools.product((-1, 1), repeat=len(rows))
        ]
        mode = PermutationMode.EXACT
        one_sided = sum(value >= observed for value in null) / len(null)
        two_sided = sum(abs(value) >= abs(observed) for value in null) / len(null)
        count = len(null)
    else:
        if permutations <= 0:
            raise ValueError("permutations must be positive")
        rng = random.Random(seed)
        null = []
        for _ in range(permutations):
            signs = [1 if rng.getrandbits(1) else -1 for _ in edges]
            null.append(_mean_signed(edges, signs))
        mode = PermutationMode.MONTE_CARLO
        one_extreme = sum(value >= observed for value in null)
        two_extreme = sum(abs(value) >= abs(observed) for value in null)
        one_sided = (one_extreme + 1) / (permutations + 1)
        two_sided = (two_extreme + 1) / (permutations + 1)
        count = permutations

    percentile_rank = sum(value <= observed for value in null) / len(null)
    return PairedPermutationResult(
        n=len(rows),
        observed_mean_edge=observed,
        observed_median_edge=median(edges),
        null_mean=fmean(null),
        null_std=pstdev(null) if len(null) > 1 else 0.0,
        one_sided_p=one_sided,
        two_sided_p=two_sided,
        percentile_rank=percentile_rank,
        mode=mode,
        seed=seed,
        permutations=count,
    )


def date_label_placebo(
    observations: tuple[MatchedEdgeObservation, ...] | list[MatchedEdgeObservation],
    *,
    seed: int = 1729,
) -> tuple[MatchedEdgeObservation, ...]:
    rows = tuple(observations)
    if len(rows) < 2:
        raise ValueError("date-label placebo requires at least two observations")
    controls = [row.control_return for row in rows]
    rng = random.Random(seed)
    rng.shuffle(controls)
    if all(control == row.control_return for control, row in zip(controls, rows)):
        controls = controls[1:] + controls[:1]
    return tuple(row.model_copy(update={"control_return": control}) for row, control in zip(rows, controls))


class ClusterPermutationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    n: int = Field(gt=0)
    n_clusters: int = Field(gt=1)
    cluster_unit: str = "date"
    observed_mean_edge: float
    null_mean: float
    null_std: float
    one_sided_p: float = Field(ge=0, le=1)
    two_sided_p: float = Field(ge=0, le=1)
    percentile_rank: float = Field(ge=0, le=1)
    mode: PermutationMode
    seed: int
    permutations: int = Field(gt=0)


class PlaceboResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    n: int = Field(gt=1)
    seed: int
    original_mean_edge: float
    placebo_mean_edge: float
    original_control_returns: tuple[float, ...]
    placebo_control_returns: tuple[float, ...]


def date_cluster_edge_permutation(
    observations: tuple[MatchedEdgeObservation, ...] | list[MatchedEdgeObservation],
    *,
    seed: int = 1729,
    permutations: int = 10_000,
    exact_max_clusters: int = 20,
) -> ClusterPermutationResult:
    rows = tuple(observations)
    if not rows:
        raise ValueError("date-cluster permutation requires at least one observation")
    groups: dict[object, list[MatchedEdgeObservation]] = defaultdict(list)
    for row in rows:
        groups[row.trading_date].append(row)
    keys = sorted(groups, key=str)
    if len(keys) < 2:
        raise ValueError("date-cluster permutation requires at least 2 date clusters")

    observed = fmean(row.edge for row in rows)

    def signed_mean(signs: tuple[int, ...] | list[int]) -> float:
        signed_edges: list[float] = []
        for key, sign in zip(keys, signs):
            signed_edges.extend(row.edge * sign for row in groups[key])
        return fmean(signed_edges)

    if len(keys) <= exact_max_clusters:
        null = [signed_mean(signs) for signs in itertools.product((-1, 1), repeat=len(keys))]
        mode = PermutationMode.EXACT
        one_sided = sum(value >= observed for value in null) / len(null)
        two_sided = sum(abs(value) >= abs(observed) for value in null) / len(null)
        count = len(null)
    else:
        if permutations <= 0:
            raise ValueError("permutations must be positive")
        rng = random.Random(seed)
        null = []
        for _ in range(permutations):
            signs = [1 if rng.getrandbits(1) else -1 for _ in keys]
            null.append(signed_mean(signs))
        one_extreme = sum(value >= observed for value in null)
        two_extreme = sum(abs(value) >= abs(observed) for value in null)
        one_sided = (one_extreme + 1) / (permutations + 1)
        two_sided = (two_extreme + 1) / (permutations + 1)
        count = permutations
        mode = PermutationMode.MONTE_CARLO

    return ClusterPermutationResult(
        n=len(rows),
        n_clusters=len(keys),
        observed_mean_edge=observed,
        null_mean=fmean(null),
        null_std=pstdev(null) if len(null) > 1 else 0.0,
        one_sided_p=one_sided,
        two_sided_p=two_sided,
        percentile_rank=sum(value <= observed for value in null) / len(null),
        mode=mode,
        seed=seed,
        permutations=count,
    )


def evaluate_date_label_placebo(
    observations: tuple[MatchedEdgeObservation, ...] | list[MatchedEdgeObservation],
    *,
    seed: int = 1729,
) -> PlaceboResult:
    rows = tuple(observations)
    placebo = date_label_placebo(rows, seed=seed)
    return PlaceboResult(
        n=len(rows),
        seed=seed,
        original_mean_edge=fmean(row.edge for row in rows),
        placebo_mean_edge=fmean(row.edge for row in placebo),
        original_control_returns=tuple(row.control_return for row in rows),
        placebo_control_returns=tuple(row.control_return for row in placebo),
    )
