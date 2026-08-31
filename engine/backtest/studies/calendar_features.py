"""Causal calendar features derived from an explicit exchange-session schedule.

The caller supplies the point-in-time exchange calendar/scheduled closures.  No
future price bars or hard-coded year-specific ThinkScript dates are used.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

import pandas as pd


class CalendarFeatureError(ValueError):
    """Raised when exchange-session inputs are malformed."""


def _normalized_sessions(sessions: Iterable[pd.Timestamp | date | str]) -> pd.DatetimeIndex:
    index = pd.DatetimeIndex(pd.to_datetime(list(sessions))).normalize()
    if len(index) == 0:
        raise CalendarFeatureError("sessions must be non-empty")
    if index.has_duplicates:
        raise CalendarFeatureError("sessions must be unique")
    if not index.is_monotonic_increasing:
        raise CalendarFeatureError("sessions must be chronologically sorted")
    return index


def turn_of_month_flags(
    sessions: Iterable[pd.Timestamp | date | str],
    *,
    last_sessions: int = 1,
    first_sessions: int = 3,
) -> pd.Series:
    """Flag the last N and first N exchange sessions around each month boundary.

    This is schedule-based, so the final session of a month is known from the
    exchange calendar rather than inferred from ``GetMonth()[-1]`` or a future
    market bar.
    """
    if last_sessions < 0 or first_sessions < 0:
        raise CalendarFeatureError("session counts must be non-negative")
    index = _normalized_sessions(sessions)
    flags = pd.Series(False, index=index, dtype=bool)
    periods = index.to_period("M")

    for period in periods.unique():
        positions = [i for i, value in enumerate(periods) if value == period]
        for i in positions[:first_sessions]:
            flags.iloc[i] = True
        if last_sessions:
            for i in positions[-last_sessions:]:
                flags.iloc[i] = True
    return flags


def preholiday_flags(
    sessions: Iterable[pd.Timestamp | date | str],
    scheduled_closures: Iterable[pd.Timestamp | date | str],
) -> pd.Series:
    """Flag the exchange session immediately preceding each scheduled closure.

    ``scheduled_closures`` must come from a versioned exchange calendar known
    before the trading session. Weekends are not inferred as holidays: only
    explicit closure dates create a pre-holiday flag.
    """
    index = _normalized_sessions(sessions)
    closures = pd.DatetimeIndex(pd.to_datetime(list(scheduled_closures))).normalize()
    flags = pd.Series(False, index=index, dtype=bool)

    for closure in closures.unique():
        prior = index[index < closure]
        if len(prior) == 0:
            continue
        flags.loc[prior[-1]] = True
    return flags


def calendar_feature_frame(
    sessions: Iterable[pd.Timestamp | date | str],
    scheduled_closures: Iterable[pd.Timestamp | date | str],
) -> pd.DataFrame:
    """Return canonical schedule-derived calendar context for each session."""
    index = _normalized_sessions(sessions)
    frame = pd.DataFrame(index=index)
    frame["is_turn_of_month"] = turn_of_month_flags(index)
    frame["is_preholiday"] = preholiday_flags(index, scheduled_closures)
    frame["month_session_number"] = frame.groupby(index.to_period("M")).cumcount() + 1
    month_counts = frame.groupby(index.to_period("M"))["month_session_number"].transform("max")
    frame["sessions_remaining_in_month"] = month_counts - frame["month_session_number"]
    return frame
