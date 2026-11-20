from __future__ import annotations

from statistics import fmean, median
from typing import Iterable

from pydantic import BaseModel, ConfigDict

from morning_alpha.models import OutcomeClassification, SignalOutcome, TradePlan


class StrategyMetrics(BaseModel):
    model_config = ConfigDict(frozen=True)

    n: int
    expectancy_r: float | None
    median_r: float | None
    win_rate: float | None
    profit_factor: float | None
    average_mfe_r: float | None
    median_mfe_r: float | None
    average_mae_r: float | None
    median_mae_r: float | None
    filtered_loser_rate: float | None
    filtered_winner_rate: float | None
    cost_sensitivity_r: dict[int, float | None]


def compute_strategy_metrics(
    outcomes: Iterable[SignalOutcome],
    plans: Iterable[TradePlan] = (),
    *,
    cost_bps: tuple[int, ...] = (0, 2, 5, 10, 20),
) -> StrategyMetrics:
    rows = list(outcomes)
    plan_rows = list(plans)
    realized = [
        row.close_r
        for row in rows
        if row.triggered
        and row.close_r is not None
        and row.classification is not OutcomeClassification.UNVERIFIED
    ]
    mfe = [row.mfe_r for row in rows if row.mfe_r is not None]
    mae = [row.mae_r for row in rows if row.mae_r is not None]
    wins = [r for r in realized if r > 0]
    losses = [r for r in realized if r < 0]
    filtered_losers = sum(
        1 for r in rows if r.classification is OutcomeClassification.FILTERED_LOSER
    )
    filtered_winners = sum(
        1 for r in rows if r.classification is OutcomeClassification.FILTERED_WINNER
    )
    filtered_total = filtered_losers + filtered_winners

    pf = None
    if losses:
        pf = sum(wins) / abs(sum(losses)) if wins else 0.0
    elif wins:
        pf = float("inf")

    cost_map: dict[int, float | None] = {}
    for bps in cost_bps:
        adjusted: list[float] = []
        for outcome, plan in zip(rows, plan_rows):
            if (
                not outcome.triggered
                or outcome.close_r is None
                or outcome.classification is OutcomeClassification.UNVERIFIED
            ):
                continue
            risk_pct = plan.risk_per_share / plan.entry
            cost_r = ((2 * bps) / 10_000) / risk_pct if risk_pct > 0 else 0.0
            adjusted.append(outcome.close_r - cost_r)
        cost_map[bps] = fmean(adjusted) if adjusted else None

    return StrategyMetrics(
        n=len(rows),
        expectancy_r=fmean(realized) if realized else None,
        median_r=median(realized) if realized else None,
        win_rate=(len(wins) / len(realized)) if realized else None,
        profit_factor=pf,
        average_mfe_r=fmean(mfe) if mfe else None,
        median_mfe_r=median(mfe) if mfe else None,
        average_mae_r=fmean(mae) if mae else None,
        median_mae_r=median(mae) if mae else None,
        filtered_loser_rate=(filtered_losers / filtered_total) if filtered_total else None,
        filtered_winner_rate=(filtered_winners / filtered_total) if filtered_total else None,
        cost_sensitivity_r=cost_map,
    )
