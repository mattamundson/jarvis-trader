from __future__ import annotations

import math
from collections import defaultdict
from statistics import fmean
from typing import Callable

from pydantic import BaseModel, ConfigDict, Field

from morning_alpha.research.statistical_models import MatchedEdgeObservation


class GroupConcentrationStress(BaseModel):
    model_config = ConfigDict(frozen=True)

    group_name: str
    strongest_group: str | None
    strongest_group_total_edge: float | None
    strongest_positive_share: float = Field(ge=0, le=1)
    mean_after_remove_strongest: float | None
    n_after_remove_strongest: int = Field(ge=0)
    positive_hhi: float = Field(ge=0, le=1)


class ConcentrationReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    n: int = Field(gt=0)
    mean_edge: float
    total_edge: float
    total_positive_edge: float
    top1_positive_share: float = Field(ge=0, le=1)
    top5_positive_share: float | None = Field(default=None, ge=0, le=1)
    top10pct_positive_share: float = Field(ge=0, le=1)
    mean_after_remove_top1: float | None
    mean_after_remove_top5: float | None
    mean_after_remove_top10pct: float | None
    mean_after_remove_top_symbol: float | None
    mean_after_remove_top5_symbols: float | None
    mean_after_remove_top10pct_symbols: float | None
    symbol_hhi: float = Field(ge=0, le=1)
    sector_hhi: float = Field(ge=0, le=1)
    year_hhi: float = Field(ge=0, le=1)
    regime_hhi: float = Field(ge=0, le=1)
    symbol_stress: GroupConcentrationStress
    sector_stress: GroupConcentrationStress
    year_stress: GroupConcentrationStress
    regime_stress: GroupConcentrationStress
    by_symbol: dict[str, float]
    by_sector: dict[str, float]
    by_year: dict[str, float]
    by_regime: dict[str, float]


def _aggregate(rows: tuple[MatchedEdgeObservation, ...], key_fn: Callable[[MatchedEdgeObservation], object]) -> dict[str, float]:
    values: dict[str, float] = defaultdict(float)
    for row in rows:
        values[str(key_fn(row))] += row.edge
    return dict(sorted(values.items()))


def _mean_after_remove(rows: tuple[MatchedEdgeObservation, ...], remove_count: int) -> float | None:
    if remove_count <= 0:
        return fmean(row.edge for row in rows)
    ordered = sorted(range(len(rows)), key=lambda i: rows[i].edge, reverse=True)
    positive = [i for i in ordered if rows[i].edge > 0]
    to_remove = set(positive[:remove_count])
    remaining = [row.edge for i, row in enumerate(rows) if i not in to_remove]
    return fmean(remaining) if remaining else None


def _positive_hhi(aggregates: dict[str, float]) -> float:
    positives = [value for value in aggregates.values() if value > 0]
    total = sum(positives)
    if total <= 0:
        return 0.0
    return sum((value / total) ** 2 for value in positives)


def _mean_after_remove_groups(
    rows: tuple[MatchedEdgeObservation, ...],
    *,
    key_fn: Callable[[MatchedEdgeObservation], object],
    remove_count: int,
) -> float | None:
    aggregates = _aggregate(rows, key_fn)
    positive_groups = [
        key for key, value in sorted(aggregates.items(), key=lambda item: item[1], reverse=True) if value > 0
    ]
    remove = set(positive_groups[:remove_count])
    remaining = [row.edge for row in rows if str(key_fn(row)) not in remove]
    return fmean(remaining) if remaining else None


def _group_stress(
    rows: tuple[MatchedEdgeObservation, ...],
    *,
    group_name: str,
    key_fn: Callable[[MatchedEdgeObservation], object],
) -> GroupConcentrationStress:
    aggregates = _aggregate(rows, key_fn)
    positives = [(key, value) for key, value in aggregates.items() if value > 0]
    positives.sort(key=lambda item: item[1], reverse=True)
    positive_total = sum(value for _, value in positives)
    strongest_group = positives[0][0] if positives else None
    strongest_total = positives[0][1] if positives else None
    strongest_share = (strongest_total / positive_total) if strongest_total is not None and positive_total > 0 else 0.0
    remaining = [row.edge for row in rows if strongest_group is None or str(key_fn(row)) != strongest_group]
    return GroupConcentrationStress(
        group_name=group_name,
        strongest_group=strongest_group,
        strongest_group_total_edge=strongest_total,
        strongest_positive_share=strongest_share,
        mean_after_remove_strongest=fmean(remaining) if remaining else None,
        n_after_remove_strongest=len(remaining),
        positive_hhi=_positive_hhi(aggregates),
    )


def analyze_edge_concentration(
    observations: tuple[MatchedEdgeObservation, ...] | list[MatchedEdgeObservation],
) -> ConcentrationReport:
    rows = tuple(observations)
    if not rows:
        raise ValueError("concentration analysis requires observations")
    edges = [row.edge for row in rows]
    positive = sorted((edge for edge in edges if edge > 0), reverse=True)
    positive_total = sum(positive)

    def share(k: int) -> float:
        if positive_total <= 0:
            return 0.0
        return min(1.0, sum(positive[:k]) / positive_total)

    top10_count = max(1, math.ceil(len(rows) * 0.10))
    top5_share = share(5) if len(positive) >= 5 else None

    symbol_key = lambda row: row.symbol
    sector_key = lambda row: row.sector
    year_key = lambda row: row.trading_date.year
    regime_key = lambda row: row.regime or "UNKNOWN"

    by_symbol = _aggregate(rows, symbol_key)
    by_sector = _aggregate(rows, sector_key)
    by_year = _aggregate(rows, year_key)
    by_regime = _aggregate(rows, regime_key)

    symbol_positive_groups = [key for key, value in by_symbol.items() if value > 0]
    symbol_top10_count = max(1, math.ceil(len(symbol_positive_groups) * 0.10)) if symbol_positive_groups else 0

    symbol_stress = _group_stress(rows, group_name="symbol", key_fn=symbol_key)
    sector_stress = _group_stress(rows, group_name="sector", key_fn=sector_key)
    year_stress = _group_stress(rows, group_name="year", key_fn=year_key)
    regime_stress = _group_stress(rows, group_name="regime", key_fn=regime_key)

    return ConcentrationReport(
        n=len(rows),
        mean_edge=fmean(edges),
        total_edge=sum(edges),
        total_positive_edge=positive_total,
        top1_positive_share=share(1),
        top5_positive_share=top5_share,
        top10pct_positive_share=share(top10_count),
        mean_after_remove_top1=_mean_after_remove(rows, 1),
        mean_after_remove_top5=_mean_after_remove(rows, 5) if len(positive) >= 5 else None,
        mean_after_remove_top10pct=_mean_after_remove(rows, top10_count),
        mean_after_remove_top_symbol=symbol_stress.mean_after_remove_strongest,
        mean_after_remove_top5_symbols=_mean_after_remove_groups(rows, key_fn=symbol_key, remove_count=5),
        mean_after_remove_top10pct_symbols=(
            _mean_after_remove_groups(rows, key_fn=symbol_key, remove_count=symbol_top10_count)
            if symbol_top10_count > 0
            else fmean(edges)
        ),
        symbol_hhi=_positive_hhi(by_symbol),
        sector_hhi=_positive_hhi(by_sector),
        year_hhi=_positive_hhi(by_year),
        regime_hhi=_positive_hhi(by_regime),
        symbol_stress=symbol_stress,
        sector_stress=sector_stress,
        year_stress=year_stress,
        regime_stress=regime_stress,
        by_symbol=by_symbol,
        by_sector=by_sector,
        by_year=by_year,
        by_regime=by_regime,
    )
