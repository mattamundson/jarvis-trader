from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

pytest.importorskip("pyarrow")

from es_research.features.bars import build_time_bars
from es_research.normalization.databento import normalize_databento_trades
from es_research.normalization.events import (
    read_normalized_trades_parquet,
    write_normalized_trades_parquet,
)
from es_research.sessionization.calendar import assign_sessions
from es_research.sessionization.es_fixtures import es_session_fixtures
from es_research.validation.pipeline import validate_bars, validate_normalized_trade_rows


def test_decoded_vendor_fixture_round_trips_to_silver_and_bars(tmp_path: Path) -> None:
    start_ns = int(datetime(2026, 1, 5, 14, 30, tzinfo=UTC).timestamp() * 1_000_000_000)
    records = tuple(
        {
            "instrument_id": 12345,
            "price": 5_000_000_000_000 + index * 250_000_000,
            "publisher_id": 1,
            "sequence": index + 1,
            "side": "A",
            "size": index + 1,
            "ts_event": start_ns + index * 60_000_000_000,
            "ts_recv": start_ns + index * 60_000_000_000 + 1_000,
        }
        for index in range(6)
    )
    normalized = normalize_databento_trades(records, symbol_by_instrument={12345: "ESH6"})
    path = tmp_path / "silver" / "trades.parquet"
    write_normalized_trades_parquet(normalized, path)
    restored = read_normalized_trades_parquet(path)
    validate_normalized_trade_rows(restored)
    assert restored == normalized

    bars = build_time_bars(assign_sessions(restored, es_session_fixtures()))
    validate_bars(bars)
    assert len(bars) == 2
    assert bars[0].volume == Decimal("15.000000000")
    assert bars[0].high == Decimal("5001.000000000")
    assert bars[1].close == Decimal("5001.250000000")
