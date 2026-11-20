from __future__ import annotations

import json
import random
from collections import defaultdict
from enum import StrEnum
from hashlib import sha256
from statistics import fmean, median

from pydantic import BaseModel, ConfigDict, Field

from morning_alpha.research.statistical_models import MatchedEdgeObservation


class PlaceboKind(StrEnum):
    WITHIN_DATE_CONTROL_REASSIGNMENT = "within_date_control_reassignment"
    DATE_BLOCK_ROTATION = "date_block_rotation"
    DATE_LABEL_SHUFFLE = "date_label_shuffle"
    SIGNAL_DATE_SHIFT = "signal_date_shift"
    RANDOM_UNIVERSE = "random_universe"
    RANDOM_SAME_SECTOR = "random_same_sector"
    IRRELEVANT_FEATURE = "irrelevant_feature"


class PlaceboRun(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: PlaceboKind
    iteration: int = Field(ge=0)
    seed: int
    mean_edge: float
    median_edge: float
    win_rate: float = Field(ge=0, le=1)
    strategy_returns: tuple[float, ...]
    control_returns: tuple[float, ...]
    cluster_sizes: tuple[int, ...]
    run_id: str = Field(min_length=64, max_length=64)


class PlaceboBatteryResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    seed: int
    n: int = Field(gt=1)
    real_mean_edge: float
    real_median_edge: float
    real_win_rate: float = Field(ge=0, le=1)
    real_median_edge_percentile: float = Field(ge=0, le=1)
    real_win_rate_percentile: float = Field(ge=0, le=1)
    fixture_hash: str = Field(min_length=64, max_length=64)
    runs: tuple[PlaceboRun, ...]
    battery_id: str = Field(min_length=64, max_length=64)

    def first(self, kind: PlaceboKind) -> PlaceboRun:
        for run in self.runs:
            if run.kind is kind:
                return run
        raise KeyError(kind)


def _hash(payload: object) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return sha256(raw).hexdigest()


def _cluster_sizes(rows: tuple[MatchedEdgeObservation, ...]) -> tuple[int, ...]:
    groups: dict[object, int] = defaultdict(int)
    for row in rows:
        groups[row.trading_date] += 1
    return tuple(groups[key] for key in sorted(groups, key=str))


def _run(
    kind: PlaceboKind,
    iteration: int,
    seed: int,
    strategy_returns: tuple[float, ...],
    control_returns: tuple[float, ...],
    cluster_sizes: tuple[int, ...],
) -> PlaceboRun:
    edges = tuple(s - c for s, c in zip(strategy_returns, control_returns))
    mean_edge = fmean(edges)
    median_edge = median(edges)
    win_rate = sum(value > 0 for value in edges) / len(edges)
    identity = {
        "kind": kind.value,
        "iteration": iteration,
        "seed": seed,
        "strategy_returns": strategy_returns,
        "control_returns": control_returns,
        "cluster_sizes": cluster_sizes,
    }
    return PlaceboRun(
        kind=kind,
        iteration=iteration,
        seed=seed,
        mean_edge=mean_edge,
        median_edge=median_edge,
        win_rate=win_rate,
        strategy_returns=strategy_returns,
        control_returns=control_returns,
        cluster_sizes=cluster_sizes,
        run_id=_hash(identity),
    )


def _rotate(values: tuple[float, ...], offset: int) -> tuple[float, ...]:
    n = len(values)
    if n < 2:
        return values
    k = offset % n
    if k == 0:
        k = 1
    return values[k:] + values[:k]


def _within_date_controls(rows: tuple[MatchedEdgeObservation, ...]) -> tuple[float, ...]:
    indices: dict[object, list[int]] = defaultdict(list)
    for idx, row in enumerate(rows):
        indices[row.trading_date].append(idx)
    controls = [row.control_return for row in rows]
    out = list(controls)
    for key in sorted(indices, key=str):
        idxs = indices[key]
        if len(idxs) < 2:
            continue
        vals = [controls[i] for i in idxs]
        vals = vals[1:] + vals[:1]
        for i, value in zip(idxs, vals):
            out[i] = value
    return tuple(out)


def _external_run(
    kind: PlaceboKind,
    edges: tuple[float, ...] | list[float] | None,
    *,
    n: int,
    seed: int,
    cluster_sizes: tuple[int, ...],
) -> PlaceboRun | None:
    if edges is None:
        return None
    values = tuple(float(x) for x in edges)
    if len(values) != n:
        raise ValueError(f"{kind.value} placebo length must equal observation count")
    return _run(kind, 0, seed, values, tuple(0.0 for _ in values), cluster_sizes)


def run_placebo_battery(
    observations: tuple[MatchedEdgeObservation, ...] | list[MatchedEdgeObservation],
    *,
    seed: int = 20260915,
    rotations: int = 16,
    random_universe_edges: tuple[float, ...] | list[float] | None = None,
    same_sector_edges: tuple[float, ...] | list[float] | None = None,
    irrelevant_feature_edges: tuple[float, ...] | list[float] | None = None,
) -> PlaceboBatteryResult:
    rows = tuple(observations)
    if len(rows) < 2:
        raise ValueError("placebo battery requires at least two observations")
    if rotations < 1:
        raise ValueError("rotations must be positive")

    strategy = tuple(row.strategy_return for row in rows)
    controls = tuple(row.control_return for row in rows)
    cluster_sizes = _cluster_sizes(rows)
    runs: list[PlaceboRun] = []

    runs.append(
        _run(
            PlaceboKind.WITHIN_DATE_CONTROL_REASSIGNMENT,
            0,
            seed,
            strategy,
            _within_date_controls(rows),
            cluster_sizes,
        )
    )

    for i in range(rotations):
        offset = i + 1
        runs.append(
            _run(
                PlaceboKind.DATE_BLOCK_ROTATION,
                i,
                seed,
                _rotate(strategy, offset),
                controls,
                cluster_sizes,
            )
        )
        runs.append(
            _run(
                PlaceboKind.SIGNAL_DATE_SHIFT,
                i,
                seed,
                _rotate(strategy, offset * max(1, cluster_sizes[0])),
                controls,
                cluster_sizes,
            )
        )

    rng = random.Random(seed)
    shuffled_controls = list(controls)
    rng.shuffle(shuffled_controls)
    if tuple(shuffled_controls) == controls:
        shuffled_controls = list(_rotate(controls, 1))
    runs.append(
        _run(
            PlaceboKind.DATE_LABEL_SHUFFLE,
            0,
            seed,
            strategy,
            tuple(shuffled_controls),
            cluster_sizes,
        )
    )

    for item in (
        _external_run(PlaceboKind.RANDOM_UNIVERSE, random_universe_edges, n=len(rows), seed=seed, cluster_sizes=cluster_sizes),
        _external_run(PlaceboKind.RANDOM_SAME_SECTOR, same_sector_edges, n=len(rows), seed=seed, cluster_sizes=cluster_sizes),
        _external_run(PlaceboKind.IRRELEVANT_FEATURE, irrelevant_feature_edges, n=len(rows), seed=seed, cluster_sizes=cluster_sizes),
    ):
        if item is not None:
            runs.append(item)

    real_edges = tuple(row.edge for row in rows)
    real_mean = fmean(real_edges)
    real_median = median(real_edges)
    real_win_rate = sum(value > 0 for value in real_edges) / len(real_edges)
    placebo_medians = [run.median_edge for run in runs]
    placebo_win_rates = [run.win_rate for run in runs]
    median_percentile = sum(value <= real_median for value in placebo_medians) / len(placebo_medians)
    win_rate_percentile = sum(value <= real_win_rate for value in placebo_win_rates) / len(placebo_win_rates)
    fixture_hash = _hash([row.model_dump(mode="json") for row in rows])
    identity = {
        "seed": seed,
        "fixture_hash": fixture_hash,
        "real_mean_edge": real_mean,
        "real_median_edge": real_median,
        "real_win_rate": real_win_rate,
        "runs": [run.model_dump(mode="json") for run in runs],
    }
    return PlaceboBatteryResult(
        seed=seed,
        n=len(rows),
        real_mean_edge=real_mean,
        real_median_edge=real_median,
        real_win_rate=real_win_rate,
        real_median_edge_percentile=median_percentile,
        real_win_rate_percentile=win_rate_percentile,
        fixture_hash=fixture_hash,
        runs=tuple(runs),
        battery_id=_hash(identity),
    )
