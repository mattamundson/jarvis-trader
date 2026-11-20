from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram


class MorningAlphaMetrics:
    """Prometheus instruments for scanner/data-quality/audit health."""

    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        self.registry = registry or CollectorRegistry()
        self.scan_duration_seconds = Histogram(
            "morning_alpha_scan_duration_seconds",
            "Morning Alpha scan duration in seconds",
            registry=self.registry,
        )
        self.provider_staleness_seconds = Gauge(
            "morning_alpha_provider_staleness_seconds",
            "Age of the newest provider market timestamp at scan time",
            ["provider"],
            registry=self.registry,
        )
        self.candidates_total = Counter(
            "morning_alpha_candidates_total",
            "Total setup candidates generated",
            registry=self.registry,
        )
        self.qualified_total = Counter(
            "morning_alpha_qualified_total",
            "Total portfolio-qualified trade plans",
            registry=self.registry,
        )
        self.no_trade_total = Counter(
            "morning_alpha_no_trade_total",
            "Total scans ending with NO_TRADE",
            registry=self.registry,
        )
        self.point_in_time_violations_total = Counter(
            "morning_alpha_point_in_time_violations_total",
            "Point-in-time violations blocked by the subsystem",
            registry=self.registry,
        )
        self.audit_unverified_total = Counter(
            "morning_alpha_audit_unverified_total",
            "Outcome audits classified UNVERIFIED due to insufficient sequencing evidence",
            registry=self.registry,
        )

    def record_scan(
        self,
        *,
        duration_seconds: float,
        candidate_count: int,
        qualified_count: int,
        no_trade: bool,
    ) -> None:
        self.scan_duration_seconds.observe(duration_seconds)
        self.candidates_total.inc(candidate_count)
        self.qualified_total.inc(qualified_count)
        if no_trade:
            self.no_trade_total.inc()
