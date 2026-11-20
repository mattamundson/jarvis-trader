from datetime import UTC, datetime, timedelta

from morning_alpha.research.permutation import (
    date_cluster_edge_permutation,
    evaluate_date_label_placebo,
    paired_edge_permutation,
)
from morning_alpha.research.statistical_models import MatchedEdgeObservation


def _row(i: int, edge: float, *, day: int, control: float = 0.0):
    ts = datetime(2024, 7, 10, 13, 0, tzinfo=UTC) + timedelta(days=day)
    return MatchedEdgeObservation(
        candidate_id=f"c-{i}",
        decision_timestamp=ts,
        trading_date=ts.date(),
        symbol=f"S{i}",
        sector="Technology" if day % 2 == 0 else "Energy",
        strategy_return=control + edge,
        control_return=control,
    )


def _clustered_rows():
    rows = []
    idx = 0
    for day, edge in enumerate((0.20, -0.05, -0.05, -0.05)):
        for _ in range(10):
            rows.append(_row(idx, edge, day=day))
            idx += 1
    return tuple(rows)


def test_date_cluster_permutation_flips_whole_dates_together():
    result = date_cluster_edge_permutation(_clustered_rows(), seed=11, permutations=1000)
    assert result.cluster_unit == "date"
    assert result.n_clusters == 4
    assert result.n == 40


def test_cluster_permutation_differs_from_iid_on_same_day_clustered_fixture():
    rows = _clustered_rows()
    iid = paired_edge_permutation(rows, seed=5, permutations=5000, exact_max_n=0)
    clustered = date_cluster_edge_permutation(rows, seed=5, permutations=5000, exact_max_clusters=0)
    assert clustered.two_sided_p != iid.two_sided_p
    assert clustered.two_sided_p > iid.two_sided_p


def test_cluster_permutation_is_seed_deterministic():
    rows = _clustered_rows()
    first = date_cluster_edge_permutation(rows, seed=19, permutations=500)
    second = date_cluster_edge_permutation(rows, seed=19, permutations=500)
    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def test_placebo_preserves_control_marginal_but_breaks_pairing():
    rows = tuple(_row(i, 0.10 + i * 0.01, day=i, control=float(i)) for i in range(6))
    result = evaluate_date_label_placebo(rows, seed=9)
    assert sorted(result.placebo_control_returns) == sorted(result.original_control_returns)
    assert result.placebo_control_returns != result.original_control_returns
    assert result.placebo_mean_edge != result.original_mean_edge


def test_placebo_is_seed_deterministic():
    rows = tuple(_row(i, 0.1, day=i, control=float(i)) for i in range(6))
    first = evaluate_date_label_placebo(rows, seed=21)
    second = evaluate_date_label_placebo(rows, seed=21)
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
