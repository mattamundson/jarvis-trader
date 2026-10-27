from __future__ import annotations

from collections import Counter

from pydantic import BaseModel, ConfigDict

from morning_alpha.research.population import PopulationBuildResult
from morning_alpha.research.validation import PopulationValidationReport


class PopulationDiagnostics(BaseModel):
    model_config = ConfigDict(frozen=True)

    by_state: dict[str, int]
    by_rejection: dict[str, int]
    by_sector: dict[str, int]
    by_symbol: dict[str, int]
    by_month: dict[str, int]
    by_year: dict[str, int]


def build_population_diagnostics(result: PopulationBuildResult) -> PopulationDiagnostics:
    state = Counter(row.decision_state.value for row in result.observations)
    rejection = Counter(
        row.rejection_reason for row in result.observations if row.rejection_reason is not None
    )
    sector = Counter((row.sector or "UNKNOWN") for row in result.observations)
    symbol = Counter(row.symbol for row in result.observations)
    month = Counter(row.trading_date.strftime("%Y-%m") for row in result.observations)
    year = Counter(row.trading_date.strftime("%Y") for row in result.observations)
    return PopulationDiagnostics(
        by_state=dict(sorted(state.items())),
        by_rejection=dict(sorted(rejection.items())),
        by_sector=dict(sorted(sector.items())),
        by_symbol=dict(sorted(symbol.items())),
        by_month=dict(sorted(month.items())),
        by_year=dict(sorted(year.items())),
    )


def render_population_report(
    result: PopulationBuildResult,
    validation: PopulationValidationReport,
    diagnostics: PopulationDiagnostics,
) -> str:
    status = "POPULATION_VALIDATED" if validation.valid else "POPULATION_INVALID"
    issue_lines = [f"- {issue.code.value}: {issue.message}" for issue in validation.issues]
    if not issue_lines:
        issue_lines = ["- none"]
    return "\n".join(
        [
            "POPULATION IDENTITY",
            f"population_hash: {result.population_hash}",
            f"universe_hash: {result.universe_hash}",
            "",
            "ACCOUNTING",
            f"input_universe: {result.input_universe_count}",
            f"qualified: {result.qualified_count}",
            f"rejected: {result.rejected_count}",
            "",
            "VALIDATION",
            *issue_lines,
            "",
            "DISTRIBUTION",
            f"by_state: {diagnostics.by_state}",
            f"by_rejection: {diagnostics.by_rejection}",
            f"by_sector: {diagnostics.by_sector}",
            f"by_symbol: {diagnostics.by_symbol}",
            f"by_month: {diagnostics.by_month}",
            f"by_year: {diagnostics.by_year}",
            "",
            "RESEARCH STATUS",
            status,
            "Population validation is not an edge verdict.",
            "",
        ]
    )
