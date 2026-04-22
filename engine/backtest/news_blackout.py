"""
News/Event Blackout Filter
Blocks trade entries within 30 minutes of major scheduled economic events.
Uses a hardcoded calendar of recurring high-impact events (FOMC, CPI, NFP, GDP).
For backtesting: uses historical event calendar embedded here.

Usage:
    from backtest.news_blackout import EconomicCalendar

    cal = EconomicCalendar()
    is_blocked = cal.is_blackout(some_timestamp, window_minutes=30)
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import List, Optional, Tuple

import pandas as pd

# ── Event type definitions ──────────────────────────────────────────────────
EVENT_FOMC = "FOMC_DECISION"
EVENT_CPI = "CPI_RELEASE"
EVENT_NFP = "NFP_JOBS"
EVENT_GDP = "GDP_ADVANCE"
EVENT_FED_SPEECH = "FED_SPEECH"

# Impact levels: 1 = moderate, 2 = high, 3 = extreme
IMPACT_EXTREME = 3
IMPACT_HIGH = 2
IMPACT_MODERATE = 1


def _fomc_dates() -> List[Tuple[datetime, str, int]]:
    """
    FOMC rate decisions — 8 per year (2024-2026).
    Announcement time: 14:00 ET = 19:00 UTC.
    """
    # 2024 FOMC dates
    dates_2024 = [
        datetime(2024, 1, 31, 19, 0),
        datetime(2024, 3, 20, 19, 0),
        datetime(2024, 5, 1, 19, 0),
        datetime(2024, 6, 12, 19, 0),
        datetime(2024, 7, 31, 19, 0),
        datetime(2024, 9, 18, 19, 0),
        datetime(2024, 11, 7, 19, 0),
        datetime(2024, 12, 18, 19, 0),
    ]
    # 2025 FOMC dates
    dates_2025 = [
        datetime(2025, 1, 29, 19, 0),
        datetime(2025, 3, 19, 19, 0),
        datetime(2025, 5, 7, 19, 0),
        datetime(2025, 6, 18, 19, 0),
        datetime(2025, 7, 30, 19, 0),
        datetime(2025, 9, 17, 19, 0),
        datetime(2025, 11, 5, 19, 0),
        datetime(2025, 12, 17, 19, 0),
    ]
    # 2026 FOMC dates (known so far)
    dates_2026 = [
        datetime(2026, 1, 28, 19, 0),
        datetime(2026, 3, 18, 19, 0),
    ]
    return [(d, EVENT_FOMC, IMPACT_EXTREME) for d in dates_2024 + dates_2025 + dates_2026]


def _cpi_dates() -> List[Tuple[datetime, str, int]]:
    """
    CPI releases — monthly, typically 2nd/3rd week.
    Release time: 08:30 ET = 13:30 UTC.
    Approximated as 12th-13th of each month (close enough for backtesting).
    """
    events = []
    # Known actual CPI release dates (approximate: 12th or 13th of each month)
    for year in (2024, 2025, 2026):
        for month in range(1, 13):
            if year == 2026 and month > 3:
                break  # only through March 2026
            # CPI typically falls on the 12th or 13th; use 12th as approximation
            day = 12
            try:
                dt = datetime(year, month, day, 13, 30)  # 08:30 ET = 13:30 UTC
                events.append((dt, EVENT_CPI, IMPACT_HIGH))
            except ValueError:
                pass
    return events


def _nfp_dates() -> List[Tuple[datetime, str, int]]:
    """
    Non-Farm Payrolls — first Friday of each month.
    Release time: 08:30 ET = 13:30 UTC.
    """
    events = []
    for year in (2024, 2025, 2026):
        for month in range(1, 13):
            if year == 2026 and month > 3:
                break
            # Find first Friday: day 1 of month, advance to Friday
            first_day = datetime(year, month, 1)
            # weekday(): 0=Mon, 4=Fri
            days_until_friday = (4 - first_day.weekday()) % 7
            first_friday = first_day + timedelta(days=days_until_friday)
            dt = datetime(year, month, first_friday.day, 13, 30)  # 08:30 ET = 13:30 UTC
            events.append((dt, EVENT_NFP, IMPACT_HIGH))
    return events


def _gdp_dates() -> List[Tuple[datetime, str, int]]:
    """
    GDP advance estimates — quarterly, last Thursday of Jan/Apr/Jul/Oct.
    Release time: 08:30 ET = 13:30 UTC.
    """
    events = []
    gdp_months = [1, 4, 7, 10]
    for year in (2024, 2025, 2026):
        for month in gdp_months:
            if year == 2026 and month > 3:
                break
            # Find last Thursday of the month
            # Start from the last day and walk backward
            if month == 12:
                last_day = datetime(year + 1, 1, 1) - timedelta(days=1)
            else:
                last_day = datetime(year, month + 1, 1) - timedelta(days=1)
            # Walk back to Thursday (weekday 3)
            days_back = (last_day.weekday() - 3) % 7
            last_thursday = last_day - timedelta(days=days_back)
            dt = datetime(year, month, last_thursday.day, 13, 30)
            events.append((dt, EVENT_GDP, IMPACT_HIGH))
    return events


class EconomicCalendar:
    """
    Calendar of known high-impact economic events (2024-2026).
    Used to block trade entries near volatile macro releases.
    """

    def __init__(self):
        self._events: List[Tuple[datetime, str, int]] = []
        self._events.extend(_fomc_dates())
        self._events.extend(_cpi_dates())
        self._events.extend(_nfp_dates())
        self._events.extend(_gdp_dates())
        # Sort chronologically
        self._events.sort(key=lambda x: x[0])

    @property
    def events(self) -> List[Tuple[datetime, str, int]]:
        return self._events

    def is_blackout(
        self,
        timestamp: datetime | pd.Timestamp,
        window_minutes: int = 30,
        min_impact: int = IMPACT_HIGH,
    ) -> bool:
        """
        Check if a timestamp falls within the blackout window of any event.

        Parameters
        ----------
        timestamp : datetime or pd.Timestamp
            The bar timestamp to check.
        window_minutes : int, default 30
            Minutes before AND after the event to block entries.
            For daily bars, use 480 (8 hours) to block the entire day.
        min_impact : int, default IMPACT_HIGH (2)
            Minimum impact level to trigger blackout.
            IMPACT_MODERATE=1, IMPACT_HIGH=2, IMPACT_EXTREME=3.

        Returns
        -------
        bool
            True if timestamp is within the blackout window of any qualifying event.
        """
        if isinstance(timestamp, pd.Timestamp):
            timestamp = timestamp.to_pydatetime()

        # Strip timezone if present
        if hasattr(timestamp, "tzinfo") and timestamp.tzinfo is not None:
            timestamp = timestamp.replace(tzinfo=None)

        window = timedelta(minutes=window_minutes)

        for event_dt, _event_name, impact in self._events:
            if impact < min_impact:
                continue
            if abs(timestamp - event_dt) <= window:
                return True

        return False

    def get_blackout_event(
        self,
        timestamp: datetime | pd.Timestamp,
        window_minutes: int = 30,
        min_impact: int = IMPACT_HIGH,
    ) -> Optional[Tuple[datetime, str, int]]:
        """
        Like is_blackout() but returns the triggering event details,
        or None if no blackout.
        """
        if isinstance(timestamp, pd.Timestamp):
            timestamp = timestamp.to_pydatetime()

        if hasattr(timestamp, "tzinfo") and timestamp.tzinfo is not None:
            timestamp = timestamp.replace(tzinfo=None)

        window = timedelta(minutes=window_minutes)

        for event_dt, event_name, impact in self._events:
            if impact < min_impact:
                continue
            if abs(timestamp - event_dt) <= window:
                return (event_dt, event_name, impact)

        return None

    def get_events_in_range(
        self,
        start: datetime | pd.Timestamp | str,
        end: datetime | pd.Timestamp | str,
        min_impact: int = IMPACT_MODERATE,
    ) -> List[dict]:
        """
        Return all events between start and end dates.

        Returns
        -------
        List[dict]
            Each dict has keys: datetime, event_name, impact_level.
        """
        if isinstance(start, str):
            start = pd.Timestamp(start)
        if isinstance(end, str):
            end = pd.Timestamp(end)
        if isinstance(start, pd.Timestamp):
            start = start.to_pydatetime()
        if isinstance(end, pd.Timestamp):
            end = end.to_pydatetime()

        # Strip tz
        if hasattr(start, "tzinfo") and start.tzinfo is not None:
            start = start.replace(tzinfo=None)
        if hasattr(end, "tzinfo") and end.tzinfo is not None:
            end = end.replace(tzinfo=None)

        results = []
        for event_dt, event_name, impact in self._events:
            if impact < min_impact:
                continue
            if start <= event_dt <= end:
                results.append(
                    {
                        "datetime": event_dt,
                        "event_name": event_name,
                        "impact_level": impact,
                    }
                )
        return results

    def summary(self) -> str:
        """Print a summary of the calendar contents."""
        from collections import Counter

        counts = Counter(name for _, name, _ in self._events)
        lines = [
            f"EconomicCalendar: {len(self._events)} total events",
        ]
        for name, count in counts.most_common():
            lines.append(f"  {name}: {count}")
        if self._events:
            lines.append(f"  Range: {self._events[0][0].date()} -> {self._events[-1][0].date()}")
        return "\n".join(lines)
