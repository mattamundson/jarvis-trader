from datetime import date

from morning_alpha.research.monte_carlo import MonteCarloObservation, MonteCarloSpec, draw_cluster_path, run_cluster_monte_carlo


def _rows():
    return (
        MonteCarloObservation(observation_id='a1', trading_date=date(2024,1,2), return_r=0.5),
        MonteCarloObservation(observation_id='a2', trading_date=date(2024,1,2), return_r=-0.2),
        MonteCarloObservation(observation_id='b1', trading_date=date(2024,1,3), return_r=0.3),
        MonteCarloObservation(observation_id='b2', trading_date=date(2024,1,3), return_r=0.1),
        MonteCarloObservation(observation_id='c1', trading_date=date(2024,1,4), return_r=-0.4),
    )


def test_cluster_path_preserves_same_day_observations_together():
    path = draw_cluster_path(_rows(), seed=7)
    # Each sampled date contributes all original members of that date contiguously.
    for sampled_date, ids in path.sampled_clusters:
        original = tuple(r.observation_id for r in _rows() if r.trading_date == sampled_date)
        assert ids == original


def test_monte_carlo_is_deterministic_under_seed():
    spec = MonteCarloSpec(n_paths=500, seed=42, loss_thresholds_r=(-1.0, -2.0))
    one = run_cluster_monte_carlo(_rows(), spec)
    two = run_cluster_monte_carlo(_rows(), spec)
    assert one == two


def test_monte_carlo_reports_drawdown_losing_streak_and_negative_terminal_probability():
    report = run_cluster_monte_carlo(_rows(), MonteCarloSpec(n_paths=500, seed=3, loss_thresholds_r=(-0.5, -1.0)))
    assert report.median_max_drawdown_r >= 0
    assert report.p95_max_drawdown_r >= report.median_max_drawdown_r
    assert report.p99_max_drawdown_r >= report.p95_max_drawdown_r
    assert report.p95_max_losing_streak >= 0
    assert 0 <= report.probability_negative_terminal_r <= 1
    assert set(report.probability_loss_threshold) == {-0.5, -1.0}


def test_more_negative_fixture_increases_negative_terminal_probability():
    positive = _rows()
    negative = tuple(row.model_copy(update={'return_r': row.return_r - 0.6}) for row in _rows())
    spec = MonteCarloSpec(n_paths=1000, seed=9)
    assert run_cluster_monte_carlo(negative, spec).probability_negative_terminal_r > run_cluster_monte_carlo(positive, spec).probability_negative_terminal_r
