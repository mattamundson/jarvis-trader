from datetime import UTC, datetime, timedelta

from morning_alpha.research.statistical_models import MatchedEdgeObservation
from morning_alpha.research.statistical_report import render_statistical_validation_report
from morning_alpha.research.statistical_validation import (
    StatisticalEvidenceStatus,
    StatisticalValidationSpec,
    build_statistical_validation_bundle,
)


def _row(i, *, edge, day, symbol=None, sector=None, gross=None, cost=0.01, slip=1.0, delay=0.02):
    ts = datetime(2024, 1, 2, 13, 0, tzinfo=UTC) + timedelta(days=day)
    kwargs = {}
    if gross is not None:
        kwargs = dict(
            gross_r=gross,
            cost_r_per_bps=cost,
            slippage_r_per_atr_fraction=slip,
            delay_penalty_r={"5s": delay / 2, "30s": delay, "1m": delay * 2, "5m": delay * 4},
        )
    return MatchedEdgeObservation(
        candidate_id=f"c-{i}",
        decision_timestamp=ts,
        trading_date=ts.date(),
        symbol=symbol or f"S{i}",
        sector=sector or ("Technology", "Energy", "Healthcare")[i % 3],
        regime="bull" if day % 2 == 0 else "neutral",
        strategy_return=edge,
        control_return=0.0,
        **kwargs,
    )


def _bundle(rows, *, spec):
    return build_statistical_validation_bundle(
        observations=tuple(rows),
        candidate_population_identity="p" * 64,
        data_manifest_hash="d" * 64,
        control_version="same_sector@1.0.0",
        sample_start=datetime(2024, 1, 1, tzinfo=UTC),
        sample_end=datetime(2024, 12, 31, tzinfo=UTC),
        trial_ids=("trial-a", "trial-b"),
        spec=spec,
        seed=23,
    )


def _spec(**updates):
    data = dict(
        min_observations=6,
        min_date_clusters=4,
        min_sector_clusters=3,
        bootstrap_resamples=300,
        permutation_resamples=300,
        realistic_bps=5.0,
        realistic_atr_slippage_fraction=0.02,
        realistic_delay_scenario="30s",
    )
    data.update(updates)
    return StatisticalValidationSpec(**data)


def test_clustered_false_confidence_is_not_evidence_complete():
    rows = []
    i = 0
    for day, edge in enumerate((0.20, -0.05, -0.05, -0.05)):
        for _ in range(12):
            rows.append(_row(i, edge=edge, day=day))
            i += 1
    bundle = _bundle(rows, spec=_spec(min_date_clusters=5, min_observations=20))
    assert bundle.status is StatisticalEvidenceStatus.INSUFFICIENT_DATA
    assert "DATE_CLUSTERS_BELOW_MINIMUM" in bundle.reasons
    assert bundle.iid_bootstrap is not None
    assert bundle.date_cluster_bootstrap is not None
    assert (bundle.iid_bootstrap.lower, bundle.iid_bootstrap.upper) != (
        bundle.date_cluster_bootstrap.lower,
        bundle.date_cluster_bootstrap.upper,
    )


def test_negative_edge_remains_negative_and_report_is_non_promotional():
    rows = tuple(_row(i, edge=-0.02 - i * 0.001, day=i) for i in range(9))
    bundle = _bundle(rows, spec=_spec())
    assert bundle.date_cluster_bootstrap is not None
    assert bundle.date_cluster_bootstrap.point_estimate < 0
    report = render_statistical_validation_report(bundle).upper()
    assert "EDGE CONFIRMED" not in report
    assert "STRATEGY PASS" not in report
    assert "NOT A STRATEGY PROMOTION VERDICT" in report


def test_positive_raw_edge_can_depend_entirely_on_one_symbol():
    rows = [
        _row(0, edge=1.0, day=0, symbol="BIG", sector="Technology"),
        _row(1, edge=0.8, day=1, symbol="BIG", sector="Technology"),
    ]
    for i in range(2, 11):
        rows.append(_row(i, edge=-0.05, day=i, symbol=f"S{i}"))
    bundle = _bundle(rows, spec=_spec(min_observations=6, min_date_clusters=4))
    assert bundle.concentration is not None
    assert bundle.concentration.mean_edge > 0
    assert bundle.concentration.symbol_stress.strongest_group == "BIG"
    assert bundle.concentration.symbol_stress.mean_after_remove_strongest < 0


def test_positive_gross_expectancy_can_fail_realistic_execution_stress():
    rows = tuple(
        _row(
            i,
            edge=0.02,
            day=i,
            gross=0.12,
            cost=0.015,
            slip=2.0,
            delay=0.04,
        )
        for i in range(9)
    )
    bundle = _bundle(rows, spec=_spec())
    assert bundle.execution_stress is not None
    assert bundle.execution_stress.gross_mean_r > 0
    assert bundle.execution_stress.combined_realistic_r is not None
    assert bundle.execution_stress.combined_realistic_r <= 0
