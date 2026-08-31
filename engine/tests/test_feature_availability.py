"""Tests for research-only point-in-time feature availability contracts."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backtest.studies.feature_availability import (
    FeatureAvailabilityError,
    FeatureObservation,
    FeatureUnavailableError,
    point_in_time_snapshot,
)


UTC = timezone.utc


def ts(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 8, 31, hour, minute, tzinfo=UTC)


def test_observation_requires_timezone_aware_timestamps() -> None:
    with pytest.raises(FeatureAvailabilityError, match="timezone-aware"):
        FeatureObservation(
            feature_id="orb30",
            value=123.0,
            event_at=datetime(2026, 8, 31, 14, 0),
            available_at=ts(14, 0),
            computed_at=ts(14, 0),
        )


def test_available_at_cannot_precede_event_at() -> None:
    with pytest.raises(FeatureAvailabilityError, match="available_at"):
        FeatureObservation(
            feature_id="confirmed_single",
            value=True,
            event_at=ts(15, 0),
            available_at=ts(14, 59),
            computed_at=ts(15, 1),
        )


def test_known_at_is_later_of_source_availability_and_computation() -> None:
    observation = FeatureObservation(
        feature_id="news_catalyst",
        value="positive",
        event_at=ts(13, 30),
        available_at=ts(13, 30),
        computed_at=ts(13, 32),
    )
    assert observation.known_at == ts(13, 32)
    assert observation.is_available(ts(13, 31)) is False
    assert observation.is_available(ts(13, 32)) is True


def test_require_available_fails_closed_before_known_time() -> None:
    observation = FeatureObservation(
        feature_id="ib60",
        value={"high": 100.0, "low": 98.0},
        event_at=ts(15, 30),
        available_at=ts(15, 30),
        computed_at=ts(15, 30) + timedelta(seconds=2),
    )
    with pytest.raises(FeatureUnavailableError, match="unavailable"):
        observation.require_available(ts(15, 30,))


def test_delayed_confirmation_feature_is_not_visible_early() -> None:
    candidate = FeatureObservation(
        feature_id="singlefinder_confirmed_v2",
        value={"direction": "bull", "level": 100.0},
        event_at=ts(14, 0),
        available_at=ts(14, 5),  # next completed bar confirms the structure
        computed_at=ts(14, 5),
    )
    assert point_in_time_snapshot([candidate], ts(14, 4)) == {}
    assert point_in_time_snapshot([candidate], ts(14, 5))[candidate.feature_id] == candidate


def test_snapshot_uses_latest_known_observation_only() -> None:
    older = FeatureObservation(
        feature_id="vwap",
        value=100.0,
        event_at=ts(14, 0),
        available_at=ts(14, 0),
        computed_at=ts(14, 0),
    )
    newer = FeatureObservation(
        feature_id="vwap",
        value=101.0,
        event_at=ts(14, 5),
        available_at=ts(14, 5),
        computed_at=ts(14, 5),
    )

    assert point_in_time_snapshot([newer, older], ts(14, 4))["vwap"] == older
    assert point_in_time_snapshot([older, newer], ts(14, 5))["vwap"] == newer
