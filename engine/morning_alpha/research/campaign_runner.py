from __future__ import annotations

from enum import StrEnum
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field

from morning_alpha.models import StrategyKey
from morning_alpha.research.campaign import DataReadinessReport, ResearchCampaignSpec


class CampaignRunStatus(StrEnum):
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"


class FamilyRunState(StrEnum):
    PENDING = "pending"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class FamilyResearchResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    strategy_key: str
    state: FamilyRunState
    evidence: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class CampaignRunResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    campaign_id: str
    status: CampaignRunStatus
    families: tuple[FamilyResearchResult, ...]
    stopped_reason: str | None = None


FamilyExecutor = Callable[[StrategyKey, ResearchCampaignSpec], FamilyResearchResult]


class ResearchCampaignRunner:
    """Fail-closed orchestrator for the frozen Morning Alpha research campaign.

    The runner intentionally does not implement family research logic itself. It only
    enforces campaign ordering, data certification, identity matching, and stop-on-failure
    semantics around an injected family executor.
    """

    def __init__(self, spec: ResearchCampaignSpec | None = None) -> None:
        self.spec = spec or ResearchCampaignSpec()

    def run(
        self,
        readiness: DataReadinessReport,
        executor: FamilyExecutor,
    ) -> CampaignRunResult:
        if not readiness.ready:
            reason = ",".join(readiness.reasons) or "DATA_NOT_READY"
            blocked = tuple(
                FamilyResearchResult(
                    strategy_key=strategy.canonical,
                    state=FamilyRunState.BLOCKED,
                    error=reason,
                )
                for strategy in self.spec.strategies
            )
            return CampaignRunResult(
                campaign_id=self.spec.campaign_id,
                status=CampaignRunStatus.BLOCKED,
                families=blocked,
                stopped_reason=reason,
            )

        rows: list[FamilyResearchResult] = []
        for index, strategy in enumerate(self.spec.strategies):
            try:
                result = executor(strategy, self.spec)
                if result.strategy_key != strategy.canonical:
                    raise ValueError(
                        f"mismatched strategy key: expected {strategy.canonical}, "
                        f"got {result.strategy_key}"
                    )
                if result.state is not FamilyRunState.COMPLETED:
                    raise ValueError(
                        f"executor must return COMPLETED for successful family; "
                        f"got {result.state.value}"
                    )
                rows.append(result)
            except Exception as exc:
                rows.append(
                    FamilyResearchResult(
                        strategy_key=strategy.canonical,
                        state=FamilyRunState.FAILED,
                        error=str(exc),
                    )
                )
                for remaining in self.spec.strategies[index + 1 :]:
                    rows.append(
                        FamilyResearchResult(
                            strategy_key=remaining.canonical,
                            state=FamilyRunState.SKIPPED,
                            error="skipped after earlier family failure",
                        )
                    )
                return CampaignRunResult(
                    campaign_id=self.spec.campaign_id,
                    status=CampaignRunStatus.FAILED,
                    families=tuple(rows),
                    stopped_reason=str(exc),
                )

        return CampaignRunResult(
            campaign_id=self.spec.campaign_id,
            status=CampaignRunStatus.COMPLETED,
            families=tuple(rows),
        )
