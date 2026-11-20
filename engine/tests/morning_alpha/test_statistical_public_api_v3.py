def test_cluster_placebo_is_public_research_evidence():
    from morning_alpha.research import ClusterPlaceboResult, evaluate_date_cluster_placebo

    assert ClusterPlaceboResult.__name__ == "ClusterPlaceboResult"
    assert callable(evaluate_date_cluster_placebo)
