from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from es_research.contracts import SessionCalendar
from es_research.features.bars import build_time_bars
from es_research.ingestion.synthetic import SyntheticTradeConfig, generate_synthetic_trades
from es_research.normalization.events import (
    NORMALIZED_TRADE_SCHEMA_VERSION,
    normalize_trade_events,
    read_normalized_trades_parquet,
    write_normalized_trades_parquet,
)
from es_research.sessionization.calendar import SessionAssignmentError, assign_sessions
from es_research.validation.pipeline import validate_bars, validate_normalized_trade_rows

START = datetime(2026, 1, 5, 14, 30, tzinfo=UTC)


def _config(seed: int = 11) -> SyntheticTradeConfig:
    return SyntheticTradeConfig(
        instrument_id="ESH6",
        symbol="/ES",
        venue="CME",
        start_timestamp=START,
        event_count=6,
        interval_seconds=60,
        start_price=Decimal("5000.00"),
        quantity=Decimal("1"),
        random_seed=seed,
    )


def _session() -> SessionCalendar:
    return SessionCalendar(
        session_id="2026-01-05_RTH",
        trade_date=START.date(),
        session_open=START,
        session_close=START + timedelta(hours=7),
        regular_trading_hours_open=START,
        regular_trading_hours_close=START + timedelta(hours=6, minutes=45),
        timezone="America/Chicago",
    )


def test_synthetic_trades_are_deterministic_and_utc() -> None:
    first = generate_synthetic_trades(_config())
    second = generate_synthetic_trades(_config())
    assert first == second
    assert all(event.event_timestamp.tzinfo is not None for event in first)
    assert [event.sequence_number for event in first] == [1, 2, 3, 4, 5, 6]


def test_normalization_sorts_rows_and_validates() -> None:
    events = generate_synthetic_trades(_config())
    rows = normalize_trade_events(tuple(reversed(events)))
    validate_normalized_trade_rows(rows)
    assert [row["sequence_number"] for row in rows] == [1, 2, 3, 4, 5, 6]


def test_session_assignment_and_5_minute_bars() -> None:
    rows = normalize_trade_events(generate_synthetic_trades(_config()))
    assigned = assign_sessions(rows, (_session(),))
    bars = build_time_bars(assigned)
    validate_bars(bars)
    assert len(bars) == 2
    assert bars[0].bar_start == START
    assert bars[0].bar_end == START + timedelta(minutes=5)
    assert bars[0].volume == Decimal("5")
    assert bars[0].trade_count == 5
    assert bars[1].volume == Decimal("1")


def test_session_assignment_rejects_out_of_session_event() -> None:
    rows = normalize_trade_events(generate_synthetic_trades(_config()))
    closed_session = SessionCalendar(
        session_id="closed",
        trade_date=START.date(),
        session_open=START - timedelta(hours=2),
        session_close=START - timedelta(hours=1),
        regular_trading_hours_open=START - timedelta(hours=2),
        regular_trading_hours_close=START - timedelta(hours=1),
        timezone="America/Chicago",
    )
    with pytest.raises(SessionAssignmentError, match="outside all sessions"):
        assign_sessions(rows, (closed_session,))


def test_parquet_writer_requires_pyarrow_when_unavailable(tmp_path) -> None:  # type: ignore[no-untyped-def]
    rows = normalize_trade_events(generate_synthetic_trades(_config()))
    pytest.importorskip("pyarrow")
    write_normalized_trades_parquet(rows, tmp_path / "trades.parquet")
    path = tmp_path / "trades.parquet"
    assert path.exists()
    assert read_normalized_trades_parquet(path) == rows


def test_parquet_reader_rejects_unversioned_schema(tmp_path) -> None:  # type: ignore[no-untyped-def]
    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")
    path = tmp_path / "wrong-schema.parquet"
    pq.write_table(pa.table({"event_timestamp": []}), path)
    with pytest.raises(ValueError, match="schema version mismatch"):
        read_normalized_trades_parquet(path)


def test_normalized_schema_version_is_explicit() -> None:
    assert NORMALIZED_TRADE_SCHEMA_VERSION == "es.normalized_trades.v1"
