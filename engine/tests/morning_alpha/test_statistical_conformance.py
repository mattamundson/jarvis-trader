from datetime import datetime, timezone

from morning_alpha.research.conformance import ConformanceStatus, run_statistical_conformance
from morning_alpha.research.statistical_models import MatchedEdgeObservation


def _rows(edges, *, same_day_pairs=False):
    out = []
    for i, edge in enumerate(edges):
        day = 1 + (i // 2 if same_day_pairs else i)
        ts = datetime(2024, 1, day, 9, tzinfo=timezone.utc)
        out.append(
            MatchedEdgeObservation(
                candidate_id=f"C{i}",
                decision_timestamp=ts,
                trading_date=ts.date(),
                symbol=f"S{i}",
                sector="TECH" if i % 2 == 0 else "HEALTH",
                strategy_return=float(edge),
                control_return=0.0,
                gross_r=0.5 + 0.1 * i,
                cost_r_per_bps=0.01 + 0.001 * i,
            )
        )
    return tuple(out)


def test_exact_paired_permutation_matches_scipy_reference():
    report = run_statistical_conformance(_rows([0.1, 0.2, 0.3, -0.1]), resamples=4000)
    case = report.case("paired_permutation_exact_vs_scipy")
    assert case.status is ConformanceStatus.VERIFIED
    assert case.absolute_difference <= case.tolerance


def test_date_cluster_permutation_matches_exhaustive_reference():
    report = run_statistical_conformance(
        _rows([0.2, 0.1, -0.1, 0.3, 0.4, 0.2], same_day_pairs=True),
        resamples=4000,
    )
    case = report.case("date_cluster_permutation_vs_exhaustive")
    assert case.status is ConformanceStatus.VERIFIED
    assert case.absolute_difference == 0.0


def test_iid_percentile_bootstrap_agrees_with_scipy_within_preregistered_tolerance():
    report = run_statistical_conformance(
        _rows([-0.15, 0.05, 0.10, 0.20, 0.25, 0.30, 0.35, 0.45]),
        resamples=12000,
        bootstrap_tolerance=0.035,
    )
    lower = report.case("iid_bootstrap_lower_vs_scipy")
    upper = report.case("iid_bootstrap_upper_vs_scipy")
    assert lower.status is ConformanceStatus.VERIFIED
    assert upper.status is ConformanceStatus.VERIFIED


def test_cost_break_even_matches_direct_recomputation():
    report = run_statistical_conformance(_rows([0.1, 0.2, 0.3, 0.4]), resamples=2000)
    case = report.case("cost_break_even_closed_form")
    assert case.status is ConformanceStatus.VERIFIED
    assert case.absolute_difference <= 1e-12


def test_negative_and_tied_samples_are_preserved_not_forced_positive():
    negative = run_statistical_conformance(_rows([-0.4, -0.2, -0.1, -0.3]), resamples=2000)
    tied = run_statistical_conformance(_rows([0.0, 0.0, 0.0, 0.0]), resamples=2000)
    assert negative.overall_status is ConformanceStatus.VERIFIED
    assert tied.overall_status is ConformanceStatus.VERIFIED
    assert negative.observed_mean_edge < 0
    assert tied.observed_mean_edge == 0.0


def test_conformance_is_deterministic_for_same_seed_and_fixture():
    rows = _rows([0.1, 0.2, -0.05, 0.4, 0.3, 0.1])
    a = run_statistical_conformance(rows, seed=99, resamples=3000)
    b = run_statistical_conformance(rows, seed=99, resamples=3000)
    assert a.report_id == b.report_id
    assert a == b
