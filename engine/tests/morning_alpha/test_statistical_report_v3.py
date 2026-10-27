from datetime import UTC, datetime, timedelta

from morning_alpha.research.statistical_models import MatchedEdgeObservation
from morning_alpha.research.statistical_report import render_statistical_validation_report
from morning_alpha.research.statistical_validation import StatisticalValidationSpec, build_statistical_validation_bundle


def _bundle():
    rows = []
    for i in range(9):
        ts = datetime(2024, 1, 2, 13, 0, tzinfo=UTC) + timedelta(days=i)
        rows.append(
            MatchedEdgeObservation(
                candidate_id=f"c-{i}",
                decision_timestamp=ts,
                trading_date=ts.date(),
                symbol="BIG" if i < 2 else f"S{i}",
                sector=("Technology", "Energy", "Healthcare")[i % 3],
                regime="bull" if i < 5 else "neutral",
                strategy_return=0.04 + i * 0.001,
                control_return=0.01,
                gross_r=0.40 + i * 0.01,
                cost_r_per_bps=0.01,
                slippage_r_per_atr_fraction=1.0,
                delay_penalty_r={"5s": 0.01, "30s": 0.02, "1m": 0.04, "5m": 0.08},
                entry_gap_penalty_r=0.01,
                stop_gap_penalty_r=0.02,
            )
        )
    spec = StatisticalValidationSpec(
        min_observations=6,
        min_date_clusters=4,
        min_sector_clusters=3,
        bootstrap_resamples=200,
        permutation_resamples=200,
    )
    return build_statistical_validation_bundle(
        observations=tuple(rows),
        candidate_population_identity="p" * 64,
        data_manifest_hash="d" * 64,
        control_version="same_sector@1.0.0",
        sample_start=datetime(2024, 1, 1, tzinfo=UTC),
        sample_end=datetime(2024, 12, 31, tzinfo=UTC),
        trial_ids=("trial-1", "trial-2"),
        spec=spec,
        seed=29,
    )


def test_report_surfaces_l3_l4_l5_hardening_evidence():
    report = render_statistical_validation_report(_bundle())
    assert "placebo_date_clusters:" in report
    assert "sector_mean_retention_ratio:" in report
    assert "year_mean_retention_ratio:" in report
    assert "regime_mean_retention_ratio:" in report
    assert "gap_penalties_included: true" in report.lower()
    assert "NOT A STRATEGY PROMOTION VERDICT" in report


def test_report_keeps_trial_and_data_identity_visible():
    report = render_statistical_validation_report(_bundle())
    assert "population_identity:" in report
    assert "data_manifest_hash:" in report
    assert "control_version:" in report
    assert "trial_ids: trial-1, trial-2" in report
