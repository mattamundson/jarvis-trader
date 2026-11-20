from datetime import UTC, datetime, timedelta

from morning_alpha.research.bootstrap import BootstrapClusterUnit, bootstrap_edge_ci
from morning_alpha.research.statistical_models import MatchedEdgeObservation


def _row(i: int, *, day: int, sector: str = "Technology", edge: float = 0.1):
    ts = datetime(2024, 7, 10, 13, 0, tzinfo=UTC) + timedelta(days=day)
    return MatchedEdgeObservation(
        candidate_id=f"c-{i}",
        decision_timestamp=ts,
        trading_date=ts.date(),
        symbol=f"S{i}",
        sector=sector,
        strategy_return=edge,
        control_return=0.0,
    )


def test_date_cluster_bootstrap_reports_true_cluster_sizes_not_row_count():
    rows = tuple(
        [_row(i, day=0, edge=0.2) for i in range(10)]
        + [_row(10 + i, day=1, edge=-0.1) for i in range(2)]
        + [_row(12 + i, day=2, edge=0.05) for i in range(3)]
    )
    result = bootstrap_edge_ci(rows, cluster_unit=BootstrapClusterUnit.DATE, seed=7, resamples=200)
    assert result.n == 15
    assert result.n_clusters == 3
    assert result.effective_cluster_count == 3
    assert result.cluster_sizes == (10, 2, 3)


def test_sector_cluster_bootstrap_reports_sector_cluster_sizes():
    rows = (
        _row(0, day=0, sector="Technology"),
        _row(1, day=1, sector="Technology"),
        _row(2, day=2, sector="Energy"),
        _row(3, day=3, sector="Healthcare"),
    )
    result = bootstrap_edge_ci(rows, cluster_unit=BootstrapClusterUnit.SECTOR, seed=11, resamples=100)
    assert result.n_clusters == 3
    assert result.cluster_sizes == (1, 1, 2)


def test_cluster_bootstrap_can_require_more_distinct_clusters():
    rows = (_row(0, day=0), _row(1, day=1))
    try:
        bootstrap_edge_ci(
            rows,
            cluster_unit=BootstrapClusterUnit.DATE,
            seed=1,
            resamples=20,
            min_clusters=3,
        )
    except ValueError as exc:
        assert "at least 3 distinct clusters" in str(exc)
    else:
        raise AssertionError("expected minimum cluster validation to fail")
