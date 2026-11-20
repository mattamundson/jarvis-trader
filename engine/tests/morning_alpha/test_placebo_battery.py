from datetime import datetime, timezone

from morning_alpha.research.placebo_battery import PlaceboKind, run_placebo_battery
from morning_alpha.research.statistical_models import MatchedEdgeObservation


def _rows():
    values = [
        (1, "A", 0.30, 0.05),
        (1, "B", 0.20, -0.02),
        (2, "C", 0.35, 0.04),
        (2, "D", 0.25, 0.00),
        (3, "E", 0.40, 0.03),
        (3, "F", 0.15, -0.01),
    ]
    rows = []
    for i, (day, symbol, strategy, control) in enumerate(values):
        ts = datetime(2024, 1, day, 9, tzinfo=timezone.utc)
        rows.append(MatchedEdgeObservation(
            candidate_id=f"C{i}", decision_timestamp=ts, trading_date=ts.date(),
            symbol=symbol, sector="TECH" if i % 2 == 0 else "HEALTH",
            strategy_return=strategy, control_return=control,
        ))
    return tuple(rows)


def test_placebo_battery_preserves_marginals_and_date_cluster_sizes():
    rows = _rows()
    result = run_placebo_battery(rows, seed=77, rotations=8)
    within = result.first(PlaceboKind.WITHIN_DATE_CONTROL_REASSIGNMENT)
    assert sorted(within.control_returns) == sorted(row.control_return for row in rows)
    assert within.cluster_sizes == (2, 2, 2)
    shifted = result.first(PlaceboKind.DATE_BLOCK_ROTATION)
    assert sorted(shifted.strategy_returns) == sorted(row.strategy_return for row in rows)
    assert shifted.cluster_sizes == (2, 2, 2)


def test_placebo_battery_is_deterministic_and_reports_real_edge_percentile():
    rows = _rows()
    a = run_placebo_battery(rows, seed=11, rotations=12)
    b = run_placebo_battery(rows, seed=11, rotations=12)
    assert a == b
    assert a.battery_id == b.battery_id
    assert 0.0 <= a.real_median_edge_percentile <= 1.0
    assert 0.0 <= a.real_win_rate_percentile <= 1.0
    assert a.real_mean_edge > 0
    assert a.real_median_edge > 0


def test_external_random_same_sector_and_irrelevant_placebos_are_included():
    result = run_placebo_battery(
        _rows(),
        seed=3,
        rotations=4,
        random_universe_edges=(0.01, -0.02, 0.00, 0.03, -0.01, 0.01),
        same_sector_edges=(0.02, 0.01, -0.01, 0.00, 0.01, -0.02),
        irrelevant_feature_edges=(-0.01, 0.00, 0.01, -0.02, 0.02, 0.00),
    )
    kinds = {run.kind for run in result.runs}
    assert PlaceboKind.RANDOM_UNIVERSE in kinds
    assert PlaceboKind.RANDOM_SAME_SECTOR in kinds
    assert PlaceboKind.IRRELEVANT_FEATURE in kinds


def test_signal_date_shift_breaks_alignment_without_changing_strategy_marginal():
    rows = _rows()
    result = run_placebo_battery(rows, seed=5, rotations=3)
    run = result.first(PlaceboKind.SIGNAL_DATE_SHIFT)
    assert sorted(run.strategy_returns) == sorted(row.strategy_return for row in rows)
    assert run.strategy_returns != tuple(row.strategy_return for row in rows)


def test_marginal_preserving_placebos_do_not_misrepresent_mean_edge_as_discriminating_statistic():
    result = run_placebo_battery(_rows(), seed=9, rotations=5)
    marginal_runs = [r for r in result.runs if r.kind in {PlaceboKind.WITHIN_DATE_CONTROL_REASSIGNMENT, PlaceboKind.DATE_BLOCK_ROTATION, PlaceboKind.DATE_LABEL_SHUFFLE, PlaceboKind.SIGNAL_DATE_SHIFT}]
    assert all(abs(r.mean_edge - result.real_mean_edge) < 1e-12 for r in marginal_runs)
    assert any(abs(r.median_edge - result.real_median_edge) > 1e-12 for r in marginal_runs)
