from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict

from morning_alpha.research.campaign import DataReadinessReport
from morning_alpha.research.population import CandidateDecisionState, PopulationBuildResult


NEW_YORK = ZoneInfo("America/New_York")


class ValidationSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


class ValidationCode(StrEnum):
    DATA_NOT_CERTIFIED = "DATA_NOT_CERTIFIED"
    TEMPORAL_LEAKAGE = "TEMPORAL_LEAKAGE"
    BENCHMARK_ALIGNMENT_FAILED = "BENCHMARK_ALIGNMENT_FAILED"
    DUPLICATE_CANDIDATE = "DUPLICATE_CANDIDATE"
    ACCOUNTING_MISMATCH = "ACCOUNTING_MISMATCH"
    MANIFEST_IDENTITY_MISMATCH = "MANIFEST_IDENTITY_MISMATCH"
    NON_DETERMINISTIC_RESEARCH = "NON_DETERMINISTIC_RESEARCH"
    ARTIFACT_HASH_MISMATCH = "ARTIFACT_HASH_MISMATCH"


class ValidationIssue(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: ValidationCode
    severity: ValidationSeverity
    message: str
    candidate_id: str | None = None


class PopulationValidationReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    valid: bool
    issues: tuple[ValidationIssue, ...]


def _parse_timestamp(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


class PopulationValidator:
    def validate(
        self,
        result: PopulationBuildResult,
        *,
        readiness: DataReadinessReport | None = None,
        expected_manifest_hash: str | None = None,
        repeat_reference: PopulationBuildResult | None = None,
    ) -> PopulationValidationReport:
        issues: list[ValidationIssue] = []

        def error(code: ValidationCode, message: str, candidate_id: str | None = None) -> None:
            issues.append(
                ValidationIssue(
                    code=code,
                    severity=ValidationSeverity.ERROR,
                    message=message,
                    candidate_id=candidate_id,
                )
            )

        if readiness is not None and not readiness.ready:
            error(
                ValidationCode.DATA_NOT_CERTIFIED,
                "research readiness is not certified: " + ",".join(readiness.reasons),
            )

        ids = [row.candidate_id for row in result.observations]
        if len(ids) != len(set(ids)):
            error(ValidationCode.DUPLICATE_CANDIDATE, "duplicate candidate IDs detected")

        observed_qualified = sum(
            row.decision_state is CandidateDecisionState.QUALIFIED for row in result.observations
        )
        observed_rejected = sum(
            row.decision_state is CandidateDecisionState.REJECTED for row in result.observations
        )
        if (
            result.input_universe_count != len(result.observations)
            or result.qualified_count != observed_qualified
            or result.rejected_count != observed_rejected
            or result.qualified_count + result.rejected_count != result.input_universe_count
            or sum(result.rejection_counts.values()) != result.rejected_count
        ):
            error(ValidationCode.ACCOUNTING_MISMATCH, "population accounting does not reconcile")

        for row in result.observations:
            for name in ("listing_timestamp", "sector_effective_from", "market_data_timestamp"):
                value = getattr(row, name, None)
                if value is not None and value > row.decision_timestamp:
                    error(ValidationCode.TEMPORAL_LEAKAGE, f"{name} is after decision timestamp", row.candidate_id)
            delisting = getattr(row, "delisting_timestamp", None)
            if delisting is not None and delisting <= row.decision_timestamp:
                error(ValidationCode.TEMPORAL_LEAKAGE, "security is delisted at decision timestamp", row.candidate_id)
            sector_end = getattr(row, "sector_effective_to", None)
            if sector_end is not None and sector_end <= row.decision_timestamp:
                error(ValidationCode.TEMPORAL_LEAGE, "sector classification is not effective at decision timestamp", row.candidate_id)
            if expected_manifest_hash is not None and row.data_manifest_hash != expected_manifest_hash:
                error(
                    ValidationCode.MANIFEST_IDENTITY_MISMATCH,
                    f"candidate manifest {row.data_manifest_hash} != expected {expected_manifest_hash}",
                    row.candidate_id,
                )

            snapshot = row.feature_snapshot
            if not snapshot:
                continue
            latest = _parse_timestamp(snapshot.get("latest_source_timestamp"))
            if latest is not None and latest >= row.decision_timestamp:
                error(
                    ValidationCode.TEMPORAL_LEAKAGE,
                    "feature source timestamp reaches or exceeds decision timestamp",
                    row.candidate_id,
                )

            lineage = snapshot.get("lineage") if isinstance(snapshot, dict) else None
            if isinstance(lineage, dict):
                endpoints = [
                    _parse_timestamp(lineage.get("stock_endpoint")),
                    _parse_timestamp(lineage.get("spy_endpoint")),
                    _parse_timestamp(lineage.get("sector_endpoint")),
                ]
                parsed = [endpoint for endpoint in endpoints if endpoint is not None]
                if len(parsed) == 3:
                    endpoint_dates = {endpoint.astimezone(NEW_YORK).date() for endpoint in parsed}
                    if len(endpoint_dates) != 1:
                        error(
                            ValidationCode.BENCHMARK_ALIGNMENT_FAILED,
                            "stock/SPY/sector feature endpoints do not match",
                            row.candidate_id,
                        )

        if expected_manifest_hash is not None and any(
            row.data_manifest_hash != expected_manifest_hash for row in result.observations
        ):
            pass

        if repeat_reference is not None:
            current_signature = (
                result.population_hash,
                result.universe_hash,
                tuple((row.candidate_id, row.feature_hash) for row in result.observations),
            )
            reference_signature = (
                repeat_reference.population_hash,
                repeat_reference.universe_hash,
                tuple((row.candidate_id, row.feature_hash) for row in repeat_reference.observations),
            )
            if current_signature != reference_signature:
                error(
                    ValidationCode.NON_DETERMINISTIC_RESEARCH,
                    "repeat run differs under unchanged research identity",
                )

        return PopulationValidationReport(
            valid=not any(issue.severity is ValidationSeverity.ERROR for issue in issues),
            issues=tuple(issues),
        )
