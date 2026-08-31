"""Tests for registry-backed point-in-time feature retrieval."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from backtest.studies.feature_availability import FeatureObservation, FeatureUnavailableError
from backtest.studies.feature_registry import FeatureRegistry, UnknownFeatureError
from backtest.studies.feature_store import FeatureStore


REGISTRY_PATH = Path(__file__).resolve().parents[2] / "thinkorswim-scripts" / "FEATURE_REGISTRY_V2.yaml"


def _time(minutes: int = 0) -> datetime:
    return datetime(2026, 8, 31, 14, 0, tzinfo=timezone.utc) + timedelta(minutes=minutes)


def _store() -> FeatureStore:
    return FeatureStore(FeatureRegistry.from_yaml(REGISTRY_PATH))


def test_registry_loads_v2_and_rejects_unknown_feature() -> None:
    store = _store()
    assert len(store.registry) >= 20
    with pytest.raises(UnknownFeatureError):
        store.as_of("feature_that_does_not_exist", _time())


def test_store_hides_observation_until_known_at() -> None:
    store = _store()
    observation = FeatureObservation(
        feature_id="stc_main_v2",
        value=72.0,
        event_at=_time(),
        available_at=_time(1),
        computed_at=_time(2),
    )
    store.put(observation)

    with pytest.raises(FeatureUnavailableError):
        store.as_of("stc_main_v2", _time(1))
    assert store.as_of("stc_main_v2", _time(2)) == observation


def test_as_of_returns_latest_known_not_latest_future_observation() -> None:
    store = _store()
    earlier = FeatureObservation("stc_main_v2", 55.0, _time(), _time(), _time())
    later = FeatureObservation("stc_main_v2", 78.0, _time(5), _time(5), _time(6))
    store.extend([later, earlier])  # deliberately ingest out of chronological order

    assert store.as_of("stc_main_v2", _time(5)).value == 55.0
    assert store.as_of("stc_main_v2", _time(6)).value == 78.0


def test_version_filter_does_not_cross_feature_versions() -> None:
    store = _store()
    store.extend(
        [
            FeatureObservation("stc_main_v2", 1.0, _time(), _time(), _time(), version="1"),
            FeatureObservation("stc_main_v2", 2.0, _time(1), _time(1), _time(1), version="2"),
        ]
    )

    assert store.as_of("stc_main_v2", _time(2), version="1").value == 1.0
    assert store.as_of("stc_main_v2", _time(2), version="2").value == 2.0


def test_duplicate_point_in_time_observation_is_rejected() -> None:
    store = _store()
    observation = FeatureObservation("stc_main_v2", 55.0, _time(), _time(), _time())
    store.put(observation)
    with pytest.raises(ValueError, match="duplicate feature observation"):
        store.put(observation)


def test_snapshot_can_be_sparse_or_required() -> None:
    store = _store()
    store.put(FeatureObservation("stc_main_v2", 55.0, _time(), _time(), _time()))

    sparse = store.snapshot(_time(), ["stc_main_v2", "kama_next_signal_v2"])
    assert set(sparse) == {"stc_main_v2"}

    with pytest.raises(FeatureUnavailableError):
        store.snapshot(
            _time(),
            ["stc_main_v2", "kama_next_signal_v2"],
            required=True,
        )
