from __future__ import annotations

from morning_alpha.research.campaign import DataReadinessReport

RELATIVE_STRENGTH_BREAKOUT_SCOPE = "relative_strength_breakout@1.0.0"

_ALLOWED_OMISSIONS_BY_SCOPE: dict[str, frozenset[str]] = {
    RELATIVE_STRENGTH_BREAKOUT_SCOPE: frozenset(
        {
            "EARNINGS_EVENTS_MISSING",
            "ARTIFACT_KIND_MISSING:earnings_events",
        }
    ),
}


def scope_readiness_report(
    report: DataReadinessReport,
    strategy_key: str,
) -> DataReadinessReport:
    """Narrow full-campaign readiness without weakening unrelated evidence gates.

    Only omissions proven unrelated to an explicitly supported frozen strategy are
    filtered. Unsupported scopes fail closed. Any other manifest, provenance,
    coverage, point-in-time, hash, or artifact failure remains blocking.
    """

    allowed_omissions = _ALLOWED_OMISSIONS_BY_SCOPE.get(strategy_key)
    if allowed_omissions is None:
        reason = f"UNSUPPORTED_STRATEGY_SCOPE:{strategy_key}"
        reasons = report.reasons if reason in report.reasons else (*report.reasons, reason)
        return report.model_copy(update={"ready": False, "reasons": reasons})

    reasons = tuple(reason for reason in report.reasons if reason not in allowed_omissions)
    return report.model_copy(update={"ready": not reasons, "reasons": reasons})
