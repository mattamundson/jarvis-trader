"""Causal calendar features derived from an explicit exchange-session schedule.

The caller supplies the point-in-time exchange calendar/scheduled closures. No
future price bars or hard-coded year-specific ThinkScript dates are used.

Boundary rule: the module fails closed on partial schedule edges. It only marks
"first sessions" when a prior month is present in the supplied schedule, only
marks "last sessions" when a following month is present, and only marks a
pre-holiday session when the closure is bracketed by supplied sessions.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

import numpy as np
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
    """Flag schedule-confirmed last-N / first-N exchange sessions of each month.

    A month at the left edge of a truncated schedule has no confirmed "first"
    boundary; a month at the right edge has no confirmed "last" boundary. Those
    edge classifications remain False rather than guessing from partial input.
    """
    if last_sessions < 0 or first_sessions < 0:
        raise CalendarFeatureError("session counts must be non-negative")
    index = _normalized_sessions(sessions)
    flags = pd.Series(False, index=index, dtype=bool)
    periods = index.to_period("M")
    unique_periods = list(periods.unique())

    for period_index, period in enumerate(unique_periods):
        positions = [i for i, value in enumerate(periods) if value == period]
        has_prior_month = period_index > 0
        has_next_month = period_index < len(unique_periods) - 1

        if has_prior_month:
            for i in positions[:first_sessions]:
                flags.iloc[i] = True
        if has_next_month and last_sessions:
            for i in positions[-last_sessions:]:
                flags.iloc[i] = True
    return flags


def preholiday_flags(
    sessions: Iterable[pd.Timestamp | date | str],
    scheduled_closures: Iterable[pd.Timestamp | date | str],
) -> pd.Series:
    """Flag the session immediately preceding a bracketed scheduled closure.

    ``scheduled_closures`` must come from a versioned exchange calendar. The
    supplied session schedule must contain at least one session on each side of
    the closure; otherwise the feature remains False rather than inferring from
    a truncated range. Weekends alone never create holiday flags.
    """
    index = _normalized_sessions(sessions)
    closures = pd.DatetimeIndex(pd.to_datetime(list(scheduled_closures))).normalize()
    flags = pd.Series(False, index=index, dtype=bool)

    for closure in closures.unique():
        prior = index[index < closure]
        following = index[index > closure]
        if len(prior) == 0 or len(following) == 0:
            continue
        flags.loc[prior[-1]] = True
    return flags


def calendar_feature_frame(
    sessions: Iterable[pd.Timestamp | date | str],
    scheduled_closures: Iterable[pd.Timestamp | date | str],
) -> pd.DataFrame:
    """Return canonical schedule-derived calendar context for each session."""
    index = _normalized_sessions(sessions)
    periods = index.to_period("M")
    unique_periods = list(periods.unique())

    frame = pd.DataFrame(index=index)
    frame["is_turn_of_month"] = turn_of_month_flags(index)
    frame["is_preholiday"] = preholiday_flags(index, scheduled_closures)
    frame["month_session_number"] = frame.groupby(periods).cumcount() + 1

    remaining = pd.Series(np.nan, index=index, dtype=float)
    for period_index, period in enumerate(unique_periods):
        if period_index == len(unique_periods) - 1:
            continue  # right-edge month may be truncated: leave unknown
        positions = [i for i, value in enumerate(periods) if value == period]
        total = len(positions)
        for within_month, absolute_position in enumerate(positions, start=1):
            remaining.iloc[absolute_position] = total - within_month
    frame["sessions_remaining_in_month"] = remaining
    return frame
