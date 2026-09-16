from __future__ import annotations

from statistics import fmean
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from morning_alpha.research.statistical_models import MatchedEdgeObservation


class ExecutionStressSpec(Protocol):
    cost_bps: tuple[int, ...]
    atr_slippage_fractions: tuple[float, ...]
    delay_scenarios: tuple[str, ...]
    realistic_bps: float
    realistic_atr_slippage_fraction: float
    realistic_delay_scenario: str


class ExecutionStressReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    n: int = Field(gt=0)
    gross_mean_r: float | None = None
    cost_curve_r: dict[int, float] = Field(default_factory=dict)
    break_even_bps: float | None = None
    atr_slippage_curve_r: dict[float, float] = Field(default_factory=dict)
    break_even_atr_fraction: float | None = None
    delay_curve_r: dict[str, float] = Field(default_factory=dict)
    combined_realistic_r: float | None = None
    realistic_bps: float
    realistic_atr_slippage_fraction: float
    realistic_delay_scenario: str
    mean_entry_gap_penalty_r: float | None = None
    mean_stop_gap_penalty_r: float | None = None
    reasons: tuple[str, ...] = ()


def _complete(rows: tuple[MatchedEdgeObservation, ...], field: str) -> bool:
    return all(getattr(row, field) is not None for row in rows)


def analyze_execution_stress(
    observations: tuple[MatchedEdgeObservation, ...] | list[MatchedEdgeObservation],
    *,
    spec: ExecutionStressSpec,
) -> ExecutionStressReport:
    rows = tuple(observations)
    if not rows:
        raise ValueError("execution stress requires observations")

    reasons: list[str] = []
    gross_complete = _complete(rows, "gross_r")
    cost_complete = _complete(rows, "cost_r_per_bps")
    slip_complete = _complete(rows, "slippage_r_per_atr_fraction")

    if not gross_complete:
        reasons.append("GROSS_R_MISSING")
    if gross_complete and not cost_complete:
        reasons.append("COST_EVIDENCE_MISSING")
    if gross_complete and not slip_complete:
        reasons.append("SLIPPAGE_EVIDENCE_MISSING")

    gross_mean = fmean(float(row.gross_r) for row in rows) if gross_complete else None

    cost_curve: dict[int, float] = {}
    break_even_bps: float | None = None
    if gross_complete and cost_complete:
        coefficients = [float(row.cost_r_per_bps) for row in rows]
        if any(value <= 0 for value in coefficients):
            reasons.append("COST_COEFFICIENT_NON_POSITIVE")
        else:
            for bps in spec.cost_bps:
                cost_curve[bps] = fmean(
                    float(row.gross_r) - float(row.cost_r_per_bps) * bps for row in rows
                )
            mean_coefficient = fmean(coefficients)
            break_even_bps = max(0.0, float(gross_mean) / mean_coefficient)

    atr_curve: dict[float, float] = {}
    break_even_atr: float | None = None
    if gross_complete and slip_complete:
        coefficients = [float(row.slippage_r_per_atr_fraction) for row in rows]
        if any(value <= 0 for value in coefficients):
            reasons.append("SLIPPAGE_COEFFICIENT_NON_POSITIVE")
        else:
            for fraction in spec.atr_slippage_fractions:
                atr_curve[fraction] = fmean(
                    float(row.gross_r)
                    - float(row.slippage_r_per_atr_fraction) * fraction
                    for row in rows
                )
            break_even_atr = max(0.0, float(gross_mean) / fmean(coefficients))

    delay_curve: dict[str, float] = {}
    for scenario in spec.delay_scenarios:
        if gross_complete and all(scenario in row.delay_penalty_r for row in rows):
            delay_curve[scenario] = fmean(
                float(row.gross_r) - float(row.delay_penalty_r[scenario]) for row in rows
            )
        elif scenario == spec.realistic_delay_scenario:
            reasons.append(f"DELAY_EVIDENCE_MISSING:{scenario}")

    combined: float | None = None
    combined_ready = (
        gross_complete
        and cost_complete
        and slip_complete
        and all(spec.realistic_delay_scenario in row.delay_penalty_r for row in rows)
        and all(float(row.cost_r_per_bps) > 0 for row in rows)
        and all(float(row.slippage_r_per_atr_fraction) > 0 for row in rows)
    )
    if combined_ready:
        combined = fmean(
            float(row.gross_r)
            - float(row.cost_r_per_bps) * spec.realistic_bps
            - float(row.slippage_r_per_atr_fraction) * spec.realistic_atr_slippage_fraction
            - float(row.delay_penalty_r[spec.realistic_delay_scenario])
            for row in rows
        )

    entry_gap = (
        fmean(float(row.entry_gap_penalty_r) for row in rows)
        if _complete(rows, "entry_gap_penalty_r")
        else None
    )
    stop_gap = (
        fmean(float(row.stop_gap_penalty_r) for row in rows)
        if _complete(rows, "stop_gap_penalty_r")
        else None
    )

    return ExecutionStressReport(
        n=len(rows),
        gross_mean_r=gross_mean,
        cost_curve_r=cost_curve,
        break_even_bps=break_even_bps,
        atr_slippage_curve_r=atr_curve,
        break_even_atr_fraction=break_even_atr,
        delay_curve_r=delay_curve,
        combined_realistic_r=combined,
        realistic_bps=spec.realistic_bps,
        realistic_atr_slippage_fraction=spec.realistic_atr_slippage_fraction,
        realistic_delay_scenario=spec.realistic_delay_scenario,
        mean_entry_gap_penalty_r=entry_gap,
        mean_stop_gap_penalty_r=stop_gap,
        reasons=tuple(dict.fromkeys(reasons)),
    )
