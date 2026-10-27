from datetime import UTC, datetime

import pytest

from morning_alpha.providers.fake import FakeMarketDataProvider, PointInTimeViolation


def test_fake_provider_never_returns_future_bars():
    as_of = datetime(2026, 9, 15, 14, 0, tzinfo=UTC)
    provider = FakeMarketDataProvider.from_rows(
        "XYZ",
        [
            (datetime(2026, 9, 15, 13, 59, tzinfo=UTC), 100, 101, 99, 100, 1000),
            (datetime(2026, 9, 15, 14, 1, tzinfo=UTC), 100, 102, 99, 101, 1200),
        ],
    )
    bars = provider.bars("XYZ", as_of=as_of, limit=100)
    assert len(bars) == 1
    assert all(bar.timestamp <= as_of for bar in bars)


def test_fake_provider_rejects_naive_as_of():
    provider = FakeMarketDataProvider.from_rows("XYZ", [])
    with pytest.raises(ValueError, match="timezone-aware"):
        provider.bars("XYZ", as_of=datetime(2026, 9, 15, 14, 0), limit=100)


def test_fake_provider_explicit_future_exposure_guard():
    as_of = datetime(2026, 9, 15, 14, 0, tzinfo=UTC)
    provider = FakeMarketDataProvider.from_rows(
        "XYZ",
        [(datetime(2026, 9, 15, 14, 1, tzinfo=UTC), 100, 102, 99, 101, 1200)],
    )
    with pytest.raises(PointInTimeViolation):
        provider.bars("XYZ", as_of=as_of, limit=100, allow_future=True)


def test_batch_snapshot_respects_as_of():
    as_of = datetime(2026, 9, 15, 14, 0, tzinfo=UTC)
    provider = FakeMarketDataProvider.from_rows(
        "XYZ",
        [(datetime(2026, 9, 15, 13, 59, tzinfo=UTC), 100, 101, 99, 100, 1000)],
    )
    snapshots = provider.batch_snapshots(["XYZ"], as_of=as_of)
    assert snapshots["XYZ"].as_of == as_of
    assert snapshots["XYZ"].price == 100
