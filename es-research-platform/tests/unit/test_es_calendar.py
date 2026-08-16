from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from es_research.sessionization.calendar import SessionAssignmentError, assign_session_id
from es_research.sessionization.es_fixtures import closed_trade_dates, es_session_fixtures


def test_winter_and_dst_sessions_shift_utc_boundaries() -> None:
    sessions = es_session_fixtures()
    winter, dst = sessions[0], sessions[1]
    assert winter.regular_trading_hours_open.hour == 14
    assert dst.regular_trading_hours_open.hour == 13
    assert assign_session_id(datetime(2026, 1, 4, 23, 0, tzinfo=UTC), sessions) == winter.session_id


def test_session_close_is_exclusive_and_friday_has_no_following_session() -> None:
    sessions = es_session_fixtures()
    friday = sessions[2]
    with pytest.raises(SessionAssignmentError, match="outside all sessions"):
        assign_session_id(friday.session_close, sessions)


def test_representative_early_close_rejects_later_event() -> None:
    sessions = es_session_fixtures()
    early_close = sessions[3]
    with pytest.raises(SessionAssignmentError, match="outside all sessions"):
        assign_session_id(datetime(2026, 11, 27, 19, 0, tzinfo=UTC), sessions)
    assert early_close.holiday_name == "Representative early-close fixture"


def test_closed_trade_date_has_no_session_fixture() -> None:
    sessions = es_session_fixtures()
    assert date(2026, 1, 1) in closed_trade_dates()
    assert all(session.trade_date != date(2026, 1, 1) for session in sessions)
