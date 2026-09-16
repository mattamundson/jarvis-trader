from datetime import UTC, datetime, timedelta

from morning_alpha.research.statistical_models import MatchedEdgeObservation
from morning_alpha.research.statistical_validation import (
    StatisticalEvidenceStatus,
    StatisticalValidationSpec,
    build_statistical_validation_bundle,
)


def _row(i: int, *, entry_gap=0.01, stop_gap=0.02):
    ts = datetime(2024, 1, 2, 13, 0, tzinfo=UTC) + timedelta(days=i)
    sectors = ("Technology", "Energy", "Healthcare")
    return MatchedEdgeObservation(
        candidate_id=f"c-{i}",
        decision_timestamp=ts,
        trading_date=ts.date(),
        symbol=f"S{i % 4}",
        sector=sectors[i % 3],
        regime="bull" if i < 4 else "neutral",
        strategy_return=0.04 + i * 0.001,
        control_return=0.01,
        gross_r=0.40 + i * 0.01,
        cost_r_per_bps=0.01 + (i % 2) * 0.002,
        slippage_r_per_atr_fraction=1.0,
        delay_penalty_r={"5s": 0.01, "30s": 0.02, "1m": 0.04, "5m": 0.08},
        entry_gap_penalty_r=entry_gap,
        stop_gap_penalty_r=stop_gap,
    )


def _spec(**updates):
    data = dict(
        min_observations=6,
        min_date_clusters=4,
        min_sector_clusters=3,
        bootstrap_resamples=200,
        permutation_resamples=200,
    )
    data.update(updates)
    return StatisticalValidationSpec(**data)


def _build(rows, **kwargs):
    return build_statistical_validation_bundle(
        observations=tuple(rows),
        candidate_population_identity="p" * 64,
        data_manifest_hash="d" * 64,
        control_version="same_sector@1.0.0",
        sample_start=datetime(2024, 1, 1, tzinfo=UTC),
        sample_end=datetime(2024, 12, 31, tzinfo=UTC),
        trial_ids=("trial-1", "trial-2"),
        spec=kwargs.pop("spec", _spec()),
        seed=23,
        **kwargs,
    )


def test_evidence_complete_contains_cluster_primary_evidence_and_cluster_placebo():
    bundle = _build([_row(i) for i in range(9)])
    assert bundle.status is StatisticalEvidenceStatus.EVIDENCE_COMPLETE
    assert bundle.date_cluster_bootstrap is not None
    assert bundle.date_cluster_permutation is not None
    assert bundle.placebo is not None
    assert bundle.placebo.n_clusters == 9
    assert bundle.concentration is not None
    assert bundle.execution_stress is not None
    assert bundle.execution_stress.gap_penalties_included is True


def test_partial_gap_execution_evidence_makes_bundle_invalid():
    rows = [_row(i) for i in range(9)]
    rows[0] = rows[0].model_copy(update={"entry_gap_penalty_r": None})
    bundle = _build(rows)
    assert bundle.status is StatisticalEvidenceStatus.INVALID
    assert "ENTRY_GAP_EVIDENCE_PARTIAL" in bundle.reasons


def test_insufficient_date_clusters_cannot_be_evidence_complete():
    rows = []
    base = datetime(2024, 1, 2, 13, 0, tzinfo=UTC)
    for i in range(9):
        row = _row(i)
        ts = base + timedelta(days=i % 2)
        rows.append(row.model_copy(update={"decision_timestamp": ts, "trading_date": ts.date()}))
    bundle = _build(rows)
    assert bundle.status is StatisticalEvidenceStatus.INSUFFICIENT_DATA
    assert "DATE_CLUSTERS_BELOW_MINIMUM" in bundle.reasons
