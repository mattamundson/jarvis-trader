from __future__ import annotations

from enum import StrEnum
from typing import Any, Callable, Iterable

from pydantic import BaseModel, ConfigDict, Field

from morning_alpha.models import StrategyKey


class AblationKind(StrEnum):
    FULL = "full"
    FULL_MINUS_SECTOR_FILTER = "full_minus_sector_filter"
    FULL_MINUS_VOLUME_CONFIRMATION = "full_minus_volume_confirmation"
    FULL_MINUS_REGIME_FILTER = "full_minus_regime_filter"
    FULL_MINUS_ENTRY_CONFIRMATION = "full_minus_entry_confirmation"


class AblationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    strategy_key: str
    kind: AblationKind
    evidence: dict[str, Any] = Field(default_factory=dict)


AblationEvaluator = Callable[[StrategyKey, AblationKind], dict[str, Any]]


class AblationRunner:
    def run(
        self,
        strategy: StrategyKey,
        evaluator: AblationEvaluator,
        *,
        kinds: Iterable[AblationKind] = tuple(AblationKind),
    ) -> tuple[AblationResult, ...]:
        results: list[AblationResult] = []
        for kind in tuple(kinds):
            evidence = evaluator(strategy, kind)
            results.append(
                AblationResult(
                    strategy_key=strategy.canonical,
                    kind=kind,
                    evidence=dict(evidence),
                )
            )
        return tuple(results)
