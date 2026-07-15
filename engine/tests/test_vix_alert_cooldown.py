"""Tests for VIX-threshold WhatsApp alert cooldown decision logic.

Mirrors test_pipeline_alert_cooldown.py's style for the sibling
notifications.pipeline_alert_cooldown module.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from notifications.vix_alert_cooldown import (
    reset_vix_alert_cooldown_for_tests,
    vix_alert_cooldown_timedelta,
    vix_alert_decision,
)


def test_vix_alert_cooldown_timedelta_clamps_to_one_minute() -> None:
    assert vix_alert_cooldown_timedelta(0) == timedelta(minutes=1)
    assert vix_alert_cooldown_timedelta(60) == timedelta(minutes=60)


def test_decision_send_when_never_sent() -> None:
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    assert (
        vix_alert_decision(level="40", last_sent=None, now=now, cooldown_minutes=60)
        == "send"
    )


def test_decision_suppressed_within_cooldown_same_level() -> None:
    now = datetime(2026, 1, 1, 12, 5, 0, tzinfo=timezone.utc)
    last = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    assert (
        vix_alert_decision(level="40", last_sent=last, now=now, cooldown_minutes=60)
        == "suppressed_cooldown"
    )


def test_decision_send_after_cooldown_elapsed() -> None:
    now = datetime(2026, 1, 1, 13, 5, 0, tzinfo=timezone.utc)
    last = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    assert (
        vix_alert_decision(level="40", last_sent=last, now=now, cooldown_minutes=60)
        == "send"
    )


def test_escalation_to_different_level_is_independent() -> None:
    """A recent CAUTION (level=20) alert must not suppress a fresh EXTREME
    (level=40) alert — each severity level has its own cooldown window."""
    now = datetime(2026, 1, 1, 12, 5, 0, tzinfo=timezone.utc)
    last_caution = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    assert (
        vix_alert_decision(level="20", last_sent=last_caution, now=now, cooldown_minutes=60)
        == "suppressed_cooldown"
    )
    # No prior send recorded for the "40" key -> sends despite "20" being on cooldown.
    assert (
        vix_alert_decision(level="40", last_sent=None, now=now, cooldown_minutes=60)
        == "send"
    )


def test_reset_for_tests_clears_state() -> None:
    from notifications import vix_alert_cooldown as vac

    vac.mark_vix_alert_sent("40", datetime.now(timezone.utc))
    assert vac.get_last_vix_alert_sent("40") is not None
    reset_vix_alert_cooldown_for_tests()
    assert vac.get_last_vix_alert_sent("40") is None
