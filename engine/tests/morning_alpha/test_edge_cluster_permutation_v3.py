from datetime import UTC, datetime, timedelta

from morning_alpha.research.permutation import evaluate_date_cluster_placebo
from morning_alpha.research.statistical_models import MatchedEdgeObservation


def _row(i: int, *, day: int, control: float, edge: float = 0.10):
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


def _rows():
    return (
        _row(0, day=0, control=0.01),
        _row(1, day=0, control=0.02),
        _row(2, day=1, control=0.03),
        _row(3, day=1, control=0.04),
        _row(4, day=2, control=0.05),
        _row(5, day=2, control=0.06),
    )


def test_date_cluster_placebo_preserves_marginal_and_cluster_sizes_but_breaks_pairing():
    result = evaluate_date_cluster_placebo(_rows(), seed=41)

    assert result.n == 6
    assert result.n_clusters == 3
    assert result.original_cluster_sizes == (2, 2, 2)
    assert result.placebo_cluster_sizes == (2, 2, 2)
    assert sorted(result.placebo_control_returns) == sorted(result.original_control_returns)
    assert result.placebo_control_returns != result.original_control_returns


def test_date_cluster_placebo_is_seed_deterministic():
    first = evaluate_date_cluster_placebo(_rows(), seed=77)
    second = evaluate_date_cluster_placebo(_rows(), seed=77)
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
