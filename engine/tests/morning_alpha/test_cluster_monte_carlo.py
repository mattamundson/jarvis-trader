from datetime import date
from morning_alpha.research.monte_carlo import MonteCarloObservation,MonteCarloSpec,draw_cluster_path,run_cluster_monte_carlo

def _rows():
    return (MonteCarloObservation(observation_id="a1",trading_date=date(2024,1,2),return_r=.5),MonteCarloObservation(observation_id="a2",trading_date=date(2024,1,2),return_r=-.2),MonteCarloObservation(observation_id="b1",trading_date=date(2024,1,3),return_r=.3),MonteCarloObservation(observation_id="b2",trading_date=date(2024,1,3),return_r=.1),MonteCarloObservation(observation_id="c1",trading_date=date(2024,1,4),return_r=-.4))

def test_cluster_path_preserves_same_day_members():
    p=draw_cluster_path(_rows(),seed=7)
    for day,ids in p.sampled_clusters: assert ids==tuple(r.observation_id for r in _rows() if r.trading_date==day)

def test_deterministic_under_seed():
    s=MonteCarloSpec(n_paths=500,seed=42,loss_thresholds_r=(-1,-2)); assert run_cluster_monte_carlo(_rows(),s)==run_cluster_monte_carlo(_rows(),s)

def test_reports_drawdown_streak_and_loss_probabilities():
    r=run_cluster_monte_carlo(_rows(),MonteCarloSpec(n_paths=500,seed=3,loss_thresholds_r=(-.5,-1))); assert r.p99_max_drawdown_r>=r.p95_max_drawdown_r>=r.median_max_drawdown_r>=0; assert 0<=r.probability_negative_terminal_r<=1; assert set(r.probability_loss_threshold)=={-.5,-1}

def test_negative_fixture_increases_negative_terminal_probability():
    n=tuple(r.model_copy(update={"return_r":r.return_r-.6}) for r in _rows()); s=MonteCarloSpec(n_paths=1000,seed=9); assert run_cluster_monte_carlo(n,s).probability_negative_terminal_r>run_cluster_monte_carlo(_rows(),s).probability_negative_terminal_r
