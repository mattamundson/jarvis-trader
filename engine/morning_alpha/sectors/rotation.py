from __future__ import annotations

from datetime import datetime
from typing import Iterable

from pydantic import BaseModel, ConfigDict, Field

from morning_alpha.models import SectorSnapshot
from morning_alpha.sectors.benchmark_policy import sector_benchmark_available

SECTOR_ETFS = ("XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLC", "XLB", "XLU", "XLRE")


class SectorScore(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    sector: str
    as_of: datetime
    score_version: str = "sector_rotation_score@0.1.0-research"
    rank: int = Field(gt=0)
    score: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    raw_features: dict[str, float | None]
    normalized_components: dict[str, float]


_WEIGHTS = {
    "relative_to_spy_20d": 0.30,
    "returns_5d": 0.15,
    "returns_20d": 0.20,
    "returns_50d": 0.10,
    "distance_from_52w_high": 0.15,
    "volume_acceleration": 0.10,
}


def _percentiles(values: list[tuple[str, float]]) -> dict[str, float]:
    """Return deterministic [0,1] percentile ranks; ties share average rank."""
    if not values:
        return {}
    sorted_values = sorted(values, key=lambda item: (item[1], item[0]))
    n = len(sorted_values)
    if n == 1:
        return {sorted_values[0][0]: 1.0}
    result: dict[str, float] = {}
    i = 0
    while i < n:
        j = i + 1
        while j < n and sorted_values[j][1] == sorted_values[i][1]:
            j += 1
        avg_index = (i + (j - 1)) / 2
        pct = avg_index / (n - 1)
        for k in range(i, j):
            result[sorted_values[k][0]] = pct
        i = j
    return result


class SectorRotationEngine:
    version = "sector_rotation_score@0.1.0-research"

    def rank(self, snapshots: Iterable[SectorSnapshot]) -> list[SectorScore]:
        rows = [
            row
            for row in snapshots
            if row.symbol in SECTOR_ETFS and sector_benchmark_available(row.symbol, as_of=row.as_of)
        ]
        if not rows:
            return []
        as_of_values = {row.as_of for row in rows}
        if len(as_of_values) != 1:
            raise ValueError("all sector snapshots must share the same as_of timestamp")

        normalized_by_feature: dict[str, dict[str, float]] = {}
        for feature in _WEIGHTS:
            values = [
                (row.symbol, float(getattr(row, feature)))
                for row in rows
                if getattr(row, feature) is not None
            ]
            normalized_by_feature[feature] = _percentiles(values)

        provisional: list[tuple[SectorSnapshot, float, float, dict[str, float]]] = []
        for row in rows:
            components: dict[str, float] = {}
            present_weight = 0.0
            weighted = 0.0
            for feature, weight in _WEIGHTS.items():
                value = normalized_by_feature[feature].get(row.symbol)
                if value is None:
                    continue
                components[feature] = value
                weighted += weight * value
                present_weight += weight
            score = weighted / present_weight if present_weight else 0.0
            confidence = present_weight / sum(_WEIGHTS.values())
            provisional.append((row, score, confidence, components))

        provisional.sort(key=lambda item: (-item[1], item[0].symbol))
        result: list[SectorScore] = []
        for idx, (row, score, confidence, components) in enumerate(provisional, start=1):
            result.append(
                SectorScore(
                    symbol=row.symbol,
                    sector=row.sector,
                    as_of=row.as_of,
                    rank=idx,
                    score=score,
                    confidence=confidence,
                    raw_features={feature: getattr(row, feature) for feature in _WEIGHTS},
                    normalized_components=components,
                )
            )
        return result
