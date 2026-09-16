from morning_alpha.research.regime_robustness import StructuralObservation, analyze_dimension


def _rows():
    return (
        StructuralObservation(observation_id='1', edge=0.6, dimensions={'regime':'bull','sector':'Tech','year':'2024'}),
        StructuralObservation(observation_id='2', edge=0.4, dimensions={'regime':'bull','sector':'Tech','year':'2024'}),
        StructuralObservation(observation_id='3', edge=0.2, dimensions={'regime':'neutral','sector':'Health','year':'2025'}),
        StructuralObservation(observation_id='4', edge=0.0, dimensions={'regime':'neutral','sector':'Health','year':'2025'}),
        StructuralObservation(observation_id='5', edge=-0.3, dimensions={'regime':'bear','sector':'Energy','year':'2025'}),
        StructuralObservation(observation_id='6', edge=-0.1, dimensions={'regime':'bear','sector':'Energy','year':'2025'}),
    )


def test_regime_analysis_reports_strongest_worst_and_leave_one_out():
    report = analyze_dimension(_rows(), dimension='regime', min_bucket_n=2)
    assert report.strongest_bucket == 'bull'
    assert report.worst_bucket == 'bear'
    assert report.buckets['bull'].mean_edge == 0.5
    assert report.buckets['bear'].mean_edge == -0.2
    assert report.leave_one_out['bull'] < report.overall_mean_edge


def test_removing_strongest_bucket_reports_retained_edge_fraction():
    report = analyze_dimension(_rows(), dimension='regime', min_bucket_n=2)
    assert report.mean_without_strongest == report.leave_one_out['bull']
    assert report.retained_edge_fraction < 1.0


def test_buckets_below_minimum_n_are_flagged_not_used_for_extrema():
    rows = _rows() + (StructuralObservation(observation_id='7', edge=9.0, dimensions={'regime':'oneoff'}),)
    report = analyze_dimension(rows, dimension='regime', min_bucket_n=2)
    assert report.buckets['oneoff'].eligible is False
    assert report.strongest_bucket == 'bull'
    assert 'oneoff' in report.insufficient_buckets


def test_missing_dimension_is_explicitly_counted():
    rows = _rows() + (StructuralObservation(observation_id='7', edge=0.1, dimensions={}),)
    report = analyze_dimension(rows, dimension='regime', min_bucket_n=2)
    assert report.missing_dimension_count == 1
