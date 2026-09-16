from morning_alpha.research.regime_robustness import StructuralObservation,analyze_dimension

def _rows():
    return (StructuralObservation(observation_id="1",edge=.6,dimensions={"regime":"bull"}),StructuralObservation(observation_id="2",edge=.4,dimensions={"regime":"bull"}),StructuralObservation(observation_id="3",edge=.2,dimensions={"regime":"neutral"}),StructuralObservation(observation_id="4",edge=0,dimensions={"regime":"neutral"}),StructuralObservation(observation_id="5",edge=-.3,dimensions={"regime":"bear"}),StructuralObservation(observation_id="6",edge=-.1,dimensions={"regime":"bear"}))

def test_reports_strongest_worst_and_leave_one_out():
    r=analyze_dimension(_rows(),dimension="regime",min_bucket_n=2); assert r.strongest_bucket=="bull"; assert r.worst_bucket=="bear"; assert r.leave_one_out["bull"]<r.overall_mean_edge

def test_removing_strongest_reports_retained_fraction():
    r=analyze_dimension(_rows(),dimension="regime",min_bucket_n=2); assert r.mean_without_strongest==r.leave_one_out["bull"]; assert r.retained_edge_fraction<1

def test_small_bucket_is_flagged_not_used_for_extrema():
    rows=_rows()+(StructuralObservation(observation_id="7",edge=9,dimensions={"regime":"oneoff"}),); r=analyze_dimension(rows,dimension="regime",min_bucket_n=2); assert not r.buckets["oneoff"].eligible; assert r.strongest_bucket=="bull"; assert "oneoff" in r.insufficient_buckets

def test_missing_dimension_counted():
    r=analyze_dimension(_rows()+(StructuralObservation(observation_id="7",edge=.1,dimensions={}),),dimension="regime",min_bucket_n=2); assert r.missing_dimension_count==1
