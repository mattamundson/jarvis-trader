from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "unattended_readiness_probe.py"
SPEC = importlib.util.spec_from_file_location("unattended_readiness_probe", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
PROBE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROBE)


def test_cron_health_detects_missed_cron_and_delivery_failure():
    missed = PROBE.cron_job_health(
        {
            "id": "job",
            "name": "watchdog",
            "enabled": False,
            "state": "paused",
            "last_status": "ok",
            "last_error": None,
            "last_delivery_error": None,
        }
    )
    assert missed["healthy"] is False
    assert "disabled_or_not_scheduled" in missed["reasons"]

    delivery_failure = PROBE.cron_job_health(
        {
            "id": "job",
            "name": "alert bridge",
            "enabled": True,
            "state": "scheduled",
            "last_status": "ok",
            "last_error": None,
            "last_delivery_error": "simulated sink unavailable",
        }
    )
    assert delivery_failure["healthy"] is False
    assert "delivery_error_present" in delivery_failure["reasons"]


def test_cron_health_clears_after_scheduler_and_delivery_recover():
    healthy = PROBE.cron_job_health(
        {
            "id": "job",
            "name": "alert bridge",
            "enabled": True,
            "state": "scheduled",
            "last_status": "ok",
            "last_error": None,
            "last_delivery_error": None,
            "failure_streak": 0,
        }
    )
    assert healthy["healthy"] is True
    assert healthy["reasons"] == []


def test_missing_cron_job_is_not_healthy():
    assert PROBE.cron_job_health(None) == {
        "present": False,
        "healthy": False,
        "reasons": ["missing"],
    }


def test_sample_timing_metrics_detects_duplicate_and_gap():
    start = datetime(2026, 9, 29, tzinfo=timezone.utc)
    expected_end = start + timedelta(hours=24)
    samples = [
        {"timestamp": start.isoformat()},
        {"timestamp": (start + timedelta(minutes=15)).isoformat()},
        {"timestamp": (start + timedelta(minutes=15)).isoformat()},
        {"timestamp": (start + timedelta(minutes=45)).isoformat()},
    ]

    timing = PROBE.sample_timing_metrics(samples, start, expected_end)

    assert timing["valid_timestamp_count"] == 4
    assert timing["duplicate_timestamp_count"] == 1
    assert timing["max_gap_minutes"] == 30.0
    assert timing["first_sample_lag_minutes"] == 0.0
    assert timing["end_shortfall_minutes"] == 1_395.0


def test_sample_timing_metrics_accepts_complete_15_minute_cadence():
    start = datetime(2026, 9, 29, tzinfo=timezone.utc)
    expected_end = start + timedelta(hours=24)
    samples = [
        {"timestamp": (start + timedelta(minutes=15 * index)).isoformat()}
        for index in range(97)
    ]

    timing = PROBE.sample_timing_metrics(samples, start, expected_end)

    assert timing["valid_timestamp_count"] == 97
    assert timing["duplicate_timestamp_count"] == 0
    assert timing["observed_span_hours"] == 24.0
    assert timing["max_gap_minutes"] == 15.0
    assert timing["first_sample_lag_minutes"] == 0.0
    assert timing["end_shortfall_minutes"] == 0.0
