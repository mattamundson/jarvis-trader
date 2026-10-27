from datetime import UTC, datetime, timedelta

from morning_alpha.research.statistical_models import MatchedEdgeObservation
from morning_alpha.research.statistical_validation import (
    StatisticalEvidenceStatus,
    StatisticalValidationSpec,
    build_statistical_validation_bundle,
)


def _row(i, *, edge, symbol=None, sector=None, regime="bull", gross=0.45, cost=0.008, slip=0.6, delay=0.015):
    ts = datetime(2024, 1, 2, 13, 0, tzinfo=UTC) + timedelta(days=i)
    control = 0.005 * ((i % 3) - 1)
    return MatchedEdgeObservation(
        candidate_id=f"c-{i}-{symbol or i}",
        decision_timestamp=ts,
        trading_date=ts.date(),
        symbol=symbol or f"S{i}",
        sector=sector or ("Technology", "Energy", "Healthcare")[i % 3],
        regime=regime,
        strategy_return=control + edge,
        control_return=control,
        gross_r=gross,
        cost_r_per_bps=cost,
        slippage_r_per_atr_fraction=slip,
        delay_penalty_r={"5s": delay / 2, "30s": delay, "1m": delay * 2, "5m": delay * 4},
        entry_gap_penalty_r=0.005,
        stop_gap_penalty_r=0.01,
    )


def _spec(**updates):
    values = dict(
        min_observations=8,
        min_date_clusters=8,
        min_sector_clusters=3,
        bootstrap_resamples=500,
        permutation_resamples=500,
        realistic_bps=5.0,
        realistic_atr_slippage_fraction=0.02,
        realistic_delay_scenario="30s",
    )
    values.update(updates)
    return StatisticalValidationSpec(**values)


def _bundle(rows, **updates):
    return build_statistical_validation_bundle(
        observations=tuple(rows),
        candidate_population_identity="p" * 64,
        data_manifest_hash="d" * 64,
        control_version="same_sector@1.0.0",
        sample_start=datetime(2024, 1, 1, tzinfo=UTC),
        sample_end=datetime(2024, 12, 31, tzinfo=UTC),
        trial_ids=("trial-a", "trial-b"),
        spec=_spec(**updates),
        seed=101,
    )


def test_positive_synthetic_evidence_survives_l3_l4_l5_diagnostics_without_promoting():
    rows = [_row(i, edge=0.03 + (i % 3) * 0.002) for i in range(12)]
    bundle = _bundle(rows)
    assert bundle.status is StatisticalEvidenceStatus.EVIDENCE_COMPLETE
    assert bundle.date_cluster_bootstrap is not None
    assert bundle.date_cluster_bootstrap.lower > 0
    assert bundle.date_cluster_permutation is not None
    assert bundle.date_cluster_permutation.two_sided_p < 0.05
    assert bundle.concentration is not None
    assert bundle.concentration.symbol_stress.mean_after_remove_strongest > 0
    assert bundle.execution_stress is not None
    assert bundle.execution_stress.combined_realistic_r > 0


def test_null_fixture_does_not_look_unusually_different_from_zero():
    edges = (0.03, -0.03, 0.02, -0.02, 0.01, -0.01, 0.015, -0.015, 0.005, -0.005, 0.025, -0.025)
    bundle = _bundle([_row(i, edge=edge) for i, edge in enumerate(edges)])
    assert bundle.date_cluster_bootstrap is not None
    assert bundle.date_cluster_bootstrap.lower <= 0 <= bundle.date_cluster_bootstrap.upper
    assert bundle.date_cluster_permutation is not None
    assert bundle.date_cluster_permutation.two_sided_p > 0.20


def test_concentration_fragile_fixture_loses_edge_after_dominant_symbol_removed():
    rows = [
        _row(0, edge=0.8, symbol="BIG", sector="Technology"),
        _row(1, edge=0.7, symbol="BIG", sector="Technology"),
    ]
    rows.extend(_row(i, edge=-0.04, symbol=f"S{i}") for i in range(2, 12))
    bundle = _bundle(rows)
    assert bundle.concentration is not None
    assert bundle.concentration.mean_edge > 0
    assert bundle.concentration.symbol_stress.strongest_group == "BIG"
    assert bundle.concentration.symbol_stress.mean_after_remove_strongest < 0
    assert bundle.concentration.symbol_stress.mean_retention_ratio < 0


def test_execution_fragile_fixture_turns_negative_after_realistic_combined_stress():
    rows = [
        _row(i, edge=0.02, gross=0.12, cost=0.015, slip=2.0, delay=0.04)
        for i in range(12)
    ]
    bundle = _bundle(rows)
    assert bundle.execution_stress is not None
    assert bundle.execution_stress.gross_mean_r > 0
    assert bundle.execution_stress.combined_realistic_r is not None
    assert bundle.execution_stress.combined_realistic_r < 0
    assert bundle.execution_stress.break_even_bps is not None
    assert bundle.execution_stress.break_even_atr_fraction is not None
