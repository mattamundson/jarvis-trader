from morning_alpha.research.robustness import ParameterPoint, analyze_parameter_stability


def points(values, sample_size=250):
    return [
        ParameterPoint(parameter_value=float(idx), expectancy_r=value, sample_size=sample_size)
        for idx, value in enumerate(values)
    ]


def test_broad_positive_plateau_scores_more_stable_than_isolated_spike():
    plateau = analyze_parameter_stability(points([0.28, 0.31, 0.34, 0.33, 0.31]))
    spike = analyze_parameter_stability(points([0.02, 0.04, 0.48, -0.01, 0.03]))

    assert plateau.stability_score > spike.stability_score
    assert plateau.adjacent_dispersion < spike.adjacent_dispersion
    assert plateau.positive_neighbor_fraction > spike.positive_neighbor_fraction


def test_points_are_sorted_by_parameter_value_without_selecting_winner():
    rows = [
        ParameterPoint(parameter_value=10, expectancy_r=0.2, sample_size=250),
        ParameterPoint(parameter_value=5, expectancy_r=0.18, sample_size=250),
        ParameterPoint(parameter_value=7, expectancy_r=0.21, sample_size=250),
    ]
    report = analyze_parameter_stability(rows)

    assert [row.parameter_value for row in report.points] == [5, 7, 10]
    assert not hasattr(report, "best_parameter")


def test_small_sample_floor_penalizes_otherwise_identical_plateau():
    large = analyze_parameter_stability(points([0.2, 0.22, 0.21, 0.23], sample_size=250))
    small = analyze_parameter_stability(points([0.2, 0.22, 0.21, 0.23], sample_size=25))

    assert large.stability_score > small.stability_score
    assert small.min_sample_size == 25


def test_single_point_has_zero_stability_because_no_neighborhood_exists():
    report = analyze_parameter_stability(
        [ParameterPoint(parameter_value=5, expectancy_r=0.3, sample_size=300)]
    )
    assert report.stability_score == 0.0
    assert report.positive_neighbor_fraction == 0.0
