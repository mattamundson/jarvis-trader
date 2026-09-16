from __future__ import annotations

import json
from datetime import datetime
from enum import StrEnum
from hashlib import sha256

from pydantic import BaseModel, ConfigDict, Field, model_validator

from morning_alpha.research.bootstrap import BootstrapClusterUnit, BootstrapResult, bootstrap_edge_ci
from morning_alpha.research.concentration import ConcentrationReport, analyze_edge_concentration
from morning_alpha.research.cost_break_even import CostBreakEvenReport, analyze_cost_break_even
from morning_alpha.research.execution_stress import ExecutionStressReport, analyze_execution_stress
from morning_alpha.research.permutation import (
    ClusterPermutationResult,
    PairedPermutationResult,
    PlaceboResult,
    date_cluster_edge_permutation,
    evaluate_date_label_placebo,
    paired_edge_permutation,
)
from morning_alpha.research.statistical_models import MatchedEdgeObservation


class StatisticalValidationSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    min_observations: int = Field(default=200, gt=0)
    min_date_clusters: int = Field(default=30, gt=1)
    min_sector_clusters: int = Field(default=3, gt=1)
    confidence: float = Field(default=0.95, gt=0, lt=1)
    bootstrap_resamples: int = Field(default=10_000, gt=0)
    permutation_resamples: int = Field(default=10_000, gt=0)
    cost_bps: tuple[int, ...] = (0, 2, 5, 10, 20)
    atr_slippage_fractions: tuple[float, ...] = (0.0, 0.02, 0.05, 0.10)
    delay_scenarios: tuple[str, ...] = ("5s", "30s", "1m", "5m")
    realistic_bps: float = Field(default=5.0, ge=0)
    realistic_atr_slippage_fraction: float = Field(default=0.02, ge=0)
    realistic_delay_scenario: str = "30s"

    @model_validator(mode="after")
    def validate_spec(self) -> "StatisticalValidationSpec":
        if len(set(self.cost_bps)) != len(self.cost_bps):
            raise ValueError("cost_bps must be unique")
        if len(set(self.atr_slippage_fractions)) != len(self.atr_slippage_fractions):
            raise ValueError("atr_slippage_fractions must be unique")
        if len(set(self.delay_scenarios)) != len(self.delay_scenarios):
            raise ValueError("delay_scenarios must be unique")
        if self.realistic_delay_scenario not in self.delay_scenarios:
            raise ValueError("realistic_delay_scenario must be one of delay_scenarios")
        return self


class StatisticalEvidenceStatus(StrEnum):
    EVIDENCE_COMPLETE = "evidence_complete"
    INSUFFICIENT_DATA = "insufficient_data"
    INVALID = "invalid"


class StatisticalValidationBundle(BaseModel):
    model_config = ConfigDict(frozen=True)

    bundle_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: StatisticalEvidenceStatus
    reasons: tuple[str, ...] = ()
    candidate_population_identity: str = Field(min_length=1)
    data_manifest_hash: str = Field(min_length=1)
    control_version: str = Field(min_length=1)
    sample_start: datetime
    sample_end: datetime
    trial_ids: tuple[str, ...]
    spec: StatisticalValidationSpec
    n: int = Field(ge=0)
    date_cluster_count: int = Field(ge=0)
    sector_cluster_count: int = Field(ge=0)
    permutation: PairedPermutationResult | None = None
    date_cluster_permutation: ClusterPermutationResult | None = None
    placebo: PlaceboResult | None = None
    iid_bootstrap: BootstrapResult | None = None
    date_cluster_bootstrap: BootstrapResult | None = None
    sector_cluster_bootstrap: BootstrapResult | None = None
    concentration: ConcentrationReport | None = None
    cost_break_even: CostBreakEvenReport | None = None
    execution_stress: ExecutionStressReport | None = None

    @model_validator(mode="after")
    def validate_window(self) -> "StatisticalValidationBundle":
        for name in ("sample_start", "sample_end"):
            value = getattr(self, name)
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name} must be timezone-aware")
        if self.sample_end < self.sample_start:
            raise ValueError("sample_end must be on or after sample_start")
        return self


def _bundle_hash(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return sha256(raw).hexdigest()


def build_statistical_validation_bundle(
    *,
    observations: tuple[MatchedEdgeObservation, ...] | list[MatchedEdgeObservation],
    candidate_population_identity: str,
    data_manifest_hash: str,
    control_version: str,
    sample_start: datetime,
    sample_end: datetime,
    trial_ids: tuple[str, ...],
    spec: StatisticalValidationSpec | None = None,
    seed: int = 1729,
    permutation_resamples: int | None = None,
    bootstrap_resamples: int | None = None,
    realistic_bps: float | None = None,
) -> StatisticalValidationBundle:
    rows = tuple(observations)
    base_spec = spec or StatisticalValidationSpec()
    effective_spec = base_spec.model_copy(
        update={
            **({"permutation_resamples": permutation_resamples} if permutation_resamples is not None else {}),
            **({"bootstrap_resamples": bootstrap_resamples} if bootstrap_resamples is not None else {}),
            **({"realistic_bps": realistic_bps} if realistic_bps is not None else {}),
        }
    )

    reasons: list[str] = []
    invalid_reasons: list[str] = []

    permutation = None
    date_permutation = None
    placebo = None
    iid_bootstrap = None
    date_bootstrap = None
    sector_bootstrap = None
    concentration = None
    cost_report = None
    execution_report = None

    date_cluster_count = len({row.trading_date for row in rows})
    sector_cluster_count = len({row.sector for row in rows})

    if not rows:
        invalid_reasons.append("EMPTY_SAMPLE")
    else:
        if len(rows) < effective_spec.min_observations:
            reasons.append("OBSERVATIONS_BELOW_MINIMUM")
        if date_cluster_count < effective_spec.min_date_clusters:
            reasons.append("DATE_CLUSTERS_BELOW_MINIMUM")
        if sector_cluster_count < effective_spec.min_sector_clusters:
            reasons.append("SECTOR_CLUSTERS_BELOW_MINIMUM")

        permutation = paired_edge_permutation(
            rows,
            seed=seed,
            permutations=effective_spec.permutation_resamples,
        )
        iid_bootstrap = bootstrap_edge_ci(
            rows,
            cluster_unit=BootstrapClusterUnit.IID,
            seed=seed + 1,
            resamples=effective_spec.bootstrap_resamples,
            confidence=effective_spec.confidence,
        )
        concentration = analyze_edge_concentration(rows)

        if date_cluster_count >= 2:
            date_bootstrap = bootstrap_edge_ci(
                rows,
                cluster_unit=BootstrapClusterUnit.DATE,
                seed=seed + 2,
                resamples=effective_spec.bootstrap_resamples,
                confidence=effective_spec.confidence,
            )
            date_permutation = date_cluster_edge_permutation(
                rows,
                seed=seed + 4,
                permutations=effective_spec.permutation_resamples,
            )
        else:
            reasons.append("DATE_CLUSTERS_INSUFFICIENT_FOR_INFERENCE")

        if sector_cluster_count >= 2:
            sector_bootstrap = bootstrap_edge_ci(
                rows,
                cluster_unit=BootstrapClusterUnit.SECTOR,
                seed=seed + 3,
                resamples=effective_spec.bootstrap_resamples,
                confidence=effective_spec.confidence,
            )

        if len(rows) >= 2:
            placebo = evaluate_date_label_placebo(rows, seed=seed + 5)

        gross_presence = [row.gross_r is not None for row in rows]
        execution_declared = any(
            row.gross_r is not None
            or row.cost_r_per_bps is not None
            or row.slippage_r_per_atr_fraction is not None
            or bool(row.delay_penalty_r)
            for row in rows
        )
        if any(gross_presence):
            cost_report = analyze_cost_break_even(rows, realistic_bps=effective_spec.realistic_bps)
        if execution_declared:
            execution_report = analyze_execution_stress(rows, spec=effective_spec)
            invalid_reasons.extend(execution_report.reasons)

    if invalid_reasons:
        status = StatisticalEvidenceStatus.INVALID
    elif reasons:
        status = StatisticalEvidenceStatus.INSUFFICIENT_DATA
    else:
        status = StatisticalEvidenceStatus.EVIDENCE_COMPLETE

    all_reasons = tuple(dict.fromkeys([*reasons, *invalid_reasons]))
    identity_payload = {
        "status": status.value,
        "reasons": all_reasons,
        "candidate_population_identity": candidate_population_identity,
        "data_manifest_hash": data_manifest_hash,
        "control_version": control_version,
        "sample_start": sample_start.isoformat(),
        "sample_end": sample_end.isoformat(),
        "trial_ids": trial_ids,
        "spec": effective_spec.model_dump(mode="json"),
        "date_cluster_count": date_cluster_count,
        "sector_cluster_count": sector_cluster_count,
        "observation_hashes": tuple(row.observation_hash for row in rows),
        "permutation": permutation.model_dump(mode="json") if permutation else None,
        "date_cluster_permutation": (
            date_permutation.model_dump(mode="json") if date_permutation else None
        ),
        "placebo": placebo.model_dump(mode="json") if placebo else None,
        "iid_bootstrap": iid_bootstrap.model_dump(mode="json") if iid_bootstrap else None,
        "date_cluster_bootstrap": date_bootstrap.model_dump(mode="json") if date_bootstrap else None,
        "sector_cluster_bootstrap": sector_bootstrap.model_dump(mode="json") if sector_bootstrap else None,
        "concentration": concentration.model_dump(mode="json") if concentration else None,
        "cost_break_even": cost_report.model_dump(mode="json") if cost_report else None,
        "execution_stress": execution_report.model_dump(mode="json") if execution_report else None,
    }
    bundle_id = _bundle_hash(identity_payload)
    return StatisticalValidationBundle(
        bundle_id=bundle_id,
        status=status,
        reasons=all_reasons,
        candidate_population_identity=candidate_population_identity,
        data_manifest_hash=data_manifest_hash,
        control_version=control_version,
        sample_start=sample_start,
        sample_end=sample_end,
        trial_ids=trial_ids,
        spec=effective_spec,
        n=len(rows),
        date_cluster_count=date_cluster_count,
        sector_cluster_count=sector_cluster_count,
        permutation=permutation,
        date_cluster_permutation=date_permutation,
        placebo=placebo,
        iid_bootstrap=iid_bootstrap,
        date_cluster_bootstrap=date_bootstrap,
        sector_cluster_bootstrap=sector_bootstrap,
        concentration=concentration,
        cost_break_even=cost_report,
        execution_stress=execution_report,
    )
