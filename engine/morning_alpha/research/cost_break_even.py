from __future__ import annotations

from statistics import fmean

from pydantic import BaseModel, ConfigDict, Field

from morning_alpha.research.statistical_models import MatchedEdgeObservation


class CostBreakEvenReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    available: bool
    n: int = Field(ge=0)
    gross_mean_r: float | None = None
    mean_cost_r_per_bps: float | None = None
    break_even_bps: float | None = None
    realistic_bps: float
    safety_margin_bps: float | None = None
    net_expectancy_realistic_r: float | None = None
    reason: str | None = None


def analyze_cost_break_even(
    observations: tuple[MatchedEdgeObservation, ...] | list[MatchedEdgeObservation],
    *,
    realistic_bps: float = 5.0,
) -> CostBreakEvenReport:
    rows = tuple(observations)
    if not rows:
        raise ValueError("cost break-even requires observations")
    if realistic_bps < 0:
        raise ValueError("realistic_bps must be non-negative")
    if any(row.gross_r is None for row in rows):
        return CostBreakEvenReport(
            available=False, n=len(rows), realistic_bps=realistic_bps, reason="GROSS_R_MISSING"
        )
    if any(row.cost_r_per_bps is None for row in rows):
        return CostBreakEvenReport(
            available=False,
            n=len(rows),
            realistic_bps=realistic_bps,
            reason="COST_COEFFICIENT_MISSING",
        )
    if any(float(row.cost_r_per_bps) <= 0 for row in rows):
        return CostBreakEvenReport(
            available=False,
            n=len(rows),
            realistic_bps=realistic_bps,
            reason="COST_COEFFICIENT_NON_POSITIVE",
        )

    gross_mean = fmean(float(row.gross_r) for row in rows)
    coefficient = fmean(float(row.cost_r_per_bps) for row in rows)
    break_even = max(0.0, gross_mean / coefficient)
    net_realistic = fmean(
        float(row.gross_r) - float(row.cost_r_per_bps) * realistic_bps for row in rows
    )
    return CostBreakEvenReport(
        available=True,
        n=len(rows),
        gross_mean_r=gross_mean,
        mean_cost_r_per_bps=coefficient,
        break_even_bps=break_even,
        realistic_bps=realistic_bps,
        safety_margin_bps=break_even - realistic_bps,
        net_expectancy_realistic_r=net_realistic,
    )
