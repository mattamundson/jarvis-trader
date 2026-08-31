"""Tests for exchange-schedule-derived calendar features."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest.studies.calendar_features import (
    CalendarFeatureError,
    calendar_feature_frame,
    preholiday_flags,
    turn_of_month_flags,
)


def test_turn_of_month_uses_confirmed_schedule_boundaries_only() -> None:
    sessions = pd.to_datetime(
        [
            "2026-01-28",
            "2026-01-29",
            "2026-01-30",
            "2026-02-02",
            "2026-02-03",
            "2026-02-04",
            "2026-02-05",
        ]
    )
    flags = turn_of_month_flags(sessions, last_sessions=1, first_sessions=3)

    # January's last session is confirmed by the presence of February.
    assert flags.loc[pd.Timestamp("2026-01-30")]
    # February's first three sessions are confirmed by the presence of January.
    assert flags.loc[pd.Timestamp("2026-02-02")]
    assert flags.loc[pd.Timestamp("2026-02-03")]
    assert flags.loc[pd.Timestamp("2026-02-04")]
    # The right edge may be a truncated month, so its apparent last session is not guessed.
    assert not flags.loc[pd.Timestamp("2026-02-05")]
    # The left-edge January schedule is truncated, so January first-session flags are not guessed.
    assert not flags.loc[pd.Timestamp("2026-01-28")]


def test_preholiday_marks_only_bracketed_explicit_exchange_closure() -> None:
    sessions = pd.to_datetime(["2026-09-03", "2026-09-04", "2026-09-08", "2026-09-09"])
    closures = pd.to_datetime(["2026-09-07"])
    flags = preholiday_flags(sessions, closures)

    assert not flags.loc[pd.Timestamp("2026-09-03")]
    assert flags.loc[pd.Timestamp("2026-09-04")]
    assert not flags.loc[pd.Timestamp("2026-09-08")]


def test_unbracketed_future_closure_does_not_backlabel_old_session() -> None:
    sessions = pd.to_datetime(["2026-02-02", "2026-02-03", "2026-02-04"])
    flags = preholiday_flags(sessions, ["2026-02-16"])
    assert not flags.any()


def test_weekend_gap_alone_does_not_create_preholiday_flag() -> None:
    sessions = pd.to_datetime(["2026-08-28", "2026-08-31"])
    flags = preholiday_flags(sessions, [])
    assert not flags.any()


def test_calendar_frame_marks_unknown_right_edge_month_remaining_as_nan() -> None:
    sessions = pd.to_datetime(
        ["2026-01-29", "2026-01-30", "2026-02-02", "2026-02-03", "2026-02-04"]
    )
    frame = calendar_feature_frame(sessions, [])

    assert frame.loc[pd.Timestamp("2026-02-02"), "month_session_number"] == 1
    assert frame.loc[pd.Timestamp("2026-01-29"), "sessions_remaining_in_month"] == 1
    assert np.isnan(frame.loc[pd.Timestamp("2026-02-04"), "sessions_remaining_in_month"])


def test_sessions_must_be_unique_and_sorted() -> None:
    with pytest.raises(CalendarFeatureError, match="unique"):
        turn_of_month_flags(["2026-01-02", "2026-01-02"])
    with pytest.raises(CalendarFeatureError, match="sorted"):
        turn_of_month_flags(["2026-01-05", "2026-01-02"])
