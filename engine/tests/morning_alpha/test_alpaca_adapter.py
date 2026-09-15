from datetime import UTC, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from morning_alpha.models import Session
from morning_alpha.providers.alpaca_market_data import (
    AlpacaMarketDataProvider,
    classify_session,
    normalize_alpaca_bar,
)


def raw(ts, close=100):
    return SimpleNamespace(
        timestamp=ts,
        open=close - 1,
        high=close + 1,
        low=close - 2,
        close=close,
        volume=1000,
    )


class FakeClient:
    def __init__(self, rows):
        self.rows = rows

    def get_bars(self, **kwargs):
        return self.rows


def test_session_classification_preserves_premarket():
    ts = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)  # 08:00 ET
    assert classify_session(ts) is Session.PREMARKET
    assert normalize_alpaca_bar("XYZ", raw(ts)).session is Session.PREMARKET


def test_vendor_future_rows_are_filtered_after_normalization():
    as_of = datetime(2026, 9, 15, 14, 0, tzinfo=UTC)
    client = FakeClient(
        [
            raw(datetime(2026, 9, 15, 13, 59, tzinfo=UTC), 100),
            raw(datetime(2026, 9, 15, 14, 1, tzinfo=UTC), 101),
        ]
    )
    provider = AlpacaMarketDataProvider(client=client)
    bars = provider.bars("XYZ", as_of=as_of, limit=10)
    assert [bar.close for bar in bars] == [100]
    assert all(bar.timestamp <= as_of for bar in bars)


def test_normalized_vendor_timestamp_is_utc():
    ts = datetime(2026, 9, 15, 9, 35, tzinfo=ZoneInfo("America/New_York"))
    bar = normalize_alpaca_bar("XYZ", raw(ts))
    assert bar.timestamp.tzinfo == UTC
