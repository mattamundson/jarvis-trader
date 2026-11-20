from prometheus_client import CollectorRegistry, generate_latest

from morning_alpha.observability import MorningAlphaMetrics


def test_required_prometheus_metrics_are_exposed():
    registry = CollectorRegistry()
    metrics = MorningAlphaMetrics(registry)
    metrics.record_scan(duration_seconds=1.2, candidate_count=3, qualified_count=1, no_trade=False)
    metrics.provider_staleness_seconds.labels(provider="alpaca").set(12)
    metrics.point_in_time_violations_total.inc()
    metrics.audit_unverified_total.inc(2)
    text = generate_latest(registry).decode()
    for name in (
        "morning_alpha_scan_duration_seconds",
        "morning_alpha_provider_staleness_seconds",
        "morning_alpha_candidates_total",
        "morning_alpha_qualified_total",
        "morning_alpha_no_trade_total",
        "morning_alpha_point_in_time_violations_total",
        "morning_alpha_audit_unverified_total",
    ):
        assert name in text


def test_no_trade_counter_increments_only_when_flagged():
    registry = CollectorRegistry()
    metrics = MorningAlphaMetrics(registry)
    metrics.record_scan(duration_seconds=0.1, candidate_count=0, qualified_count=0, no_trade=True)
    text = generate_latest(registry).decode()
    assert "morning_alpha_no_trade_total 1.0" in text
