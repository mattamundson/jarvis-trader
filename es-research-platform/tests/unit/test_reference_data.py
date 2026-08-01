from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from es_research.configuration.reference_data import load_instrument_map, load_session_calendars
from es_research.contracts import SessionCalendar


def _session(session_id: str, start: datetime) -> SessionCalendar:
    return SessionCalendar(
        session_id=session_id,
        trade_date=date(2026, 1, 5),
        session_open=start,
        session_close=start + timedelta(hours=8),
        regular_trading_hours_open=start + timedelta(hours=1),
        regular_trading_hours_close=start + timedelta(hours=7),
        timezone="America/Chicago",
    )


def test_reference_inputs_are_validated_sorted_and_hashed(tmp_path: Path) -> None:
    instrument_path = tmp_path / "instruments.json"
    instrument_path.write_text('{"12345":"ESH6"}', encoding="utf-8")
    mapping, first_hash = load_instrument_map(instrument_path)
    instrument_path.write_text('{ "12345": "ESH6" }\n', encoding="utf-8")
    _, second_hash = load_instrument_map(instrument_path)
    assert mapping == {12345: "ESH6"}
    assert first_hash == second_hash

    start = datetime(2026, 1, 5, tzinfo=UTC)
    sessions_path = tmp_path / "sessions.json"
    sessions_path.write_text(
        json.dumps(
            [
                _session("second", start + timedelta(hours=9)).model_dump(mode="json"),
                _session("first", start).model_dump(mode="json"),
            ]
        ),
        encoding="utf-8",
    )
    sessions, calendar_hash = load_session_calendars(sessions_path)
    assert [session.session_id for session in sessions] == ["first", "second"]
    assert len(calendar_hash) == 64


def test_reference_loader_rejects_overlapping_sessions(tmp_path: Path) -> None:
    start = datetime(2026, 1, 5, tzinfo=UTC)
    path = tmp_path / "sessions.json"
    path.write_text(
        json.dumps(
            [
                _session("first", start).model_dump(mode="json"),
                _session("overlap", start + timedelta(hours=7)).model_dump(mode="json"),
            ]
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="overlap"):
        load_session_calendars(path)
