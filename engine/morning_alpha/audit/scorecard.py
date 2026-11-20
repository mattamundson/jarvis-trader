from __future__ import annotations

from statistics import fmean
from typing import Iterable

from pydantic import BaseModel, ConfigDict, Field

from morning_alpha.models import OutcomeClassification, SignalOutcome


class SignalScorecard(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_candidates: int = Field(ge=0)
    triggers_fired: int = Field(ge=0)
    wins: int = Field(ge=0)
    losses: int = Field(ge=0)
    open_or_unfinished: int = Field(ge=0)
    filtered_losers: int = Field(ge=0)
    filtered_winners: int = Field(ge=0)
    unverified: int = Field(ge=0)
    cumulative_r: float
    average_mfe_r: float | None = None
    average_mae_r: float | None = None
    trigger_rate: float
    filter_protection_rate: float | None = None
    missed_opportunity_rate: float | None = None


class ScorecardBuilder:
    def build(self, outcomes: Iterable[SignalOutcome]) -> SignalScorecard:
        rows = list(outcomes)
        total = len(rows)
        triggers = sum(1 for row in rows if row.triggered)

        def count(classification: OutcomeClassification) -> int:
            return sum(1 for row in rows if row.classification is classification)

        filtered_losers = count(OutcomeClassification.FILTERED_LOSER)
        filtered_winners = count(OutcomeClassification.FILTERED_WINNER)
        filtered_total = filtered_losers + filtered_winners
        mfe = [row.mfe_r for row in rows if row.mfe_r is not None]
        mae = [row.mae_r for row in rows if row.mae_r is not None]
        cumulative_r = sum(row.close_r or 0.0 for row in rows if row.triggered)

        return SignalScorecard(
            total_candidates=total,
            triggers_fired=triggers,
            wins=count(OutcomeClassification.WIN),
            losses=count(OutcomeClassification.LOSS),
            open_or_unfinished=count(OutcomeClassification.OPEN),
            filtered_losers=filtered_losers,
            filtered_winners=filtered_winners,
            unverified=count(OutcomeClassification.UNVERIFIED),
            cumulative_r=cumulative_r,
            average_mfe_r=fmean(mfe) if mfe else None,
            average_mae_r=fmean(mae) if mae else None,
            trigger_rate=(triggers / total) if total else 0.0,
            filter_protection_rate=(filtered_losers / filtered_total if filtered_total else None),
            missed_opportunity_rate=(filtered_winners / filtered_total if filtered_total else None),
        )
