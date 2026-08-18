"""Deterministic /ES calendar fixtures for boundary and DST tests.

These fixtures model representative session shapes and are not an authoritative
exchange holiday calendar. Production ingestion must persist the calendar source
and version supplied by the market-data vendor or exchange.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from es_research.contracts import SessionCalendar


def es_session_fixtures() -> tuple[SessionCalendar, ...]:
    """Return representative winter, DST, Friday, and early-close sessions."""
    return (
        SessionCalendar(
            session_id="2026-01-05_GLOBEX",
            trade_date=date(2026, 1, 5),
            session_open=datetime(2026, 1, 4, 23, 0, tzinfo=UTC),
            session_close=datetime(2026, 1, 5, 22, 0, tzinfo=UTC),
            regular_trading_hours_open=datetime(2026, 1, 5, 14, 30, tzinfo=UTC),
            regular_trading_hours_close=datetime(2026, 1, 5, 21, 15, tzinfo=UTC),
            timezone="America/Chicago",
        ),
        SessionCalendar(
            session_id="2026-03-09_GLOBEX",
            trade_date=date(2026, 3, 9),
            session_open=datetime(2026, 3, 8, 22, 0, tzinfo=UTC),
            session_close=datetime(2026, 3, 9, 21, 0, tzinfo=UTC),
            regular_trading_hours_open=datetime(2026, 3, 9, 13, 30, tzinfo=UTC),
            regular_trading_hours_close=datetime(2026, 3, 9, 20, 15, tzinfo=UTC),
            timezone="America/Chicago",
        ),
        SessionCalendar(
            session_id="2026-03-13_GLOBEX",
            trade_date=date(2026, 3, 13),
            session_open=datetime(2026, 3, 12, 22, 0, tzinfo=UTC),
            session_close=datetime(2026, 3, 13, 21, 0, tzinfo=UTC),
            regular_trading_hours_open=datetime(2026, 3, 13, 13, 30, tzinfo=UTC),
            regular_trading_hours_close=datetime(2026, 3, 13, 20, 15, tzinfo=UTC),
            timezone="America/Chicago",
        ),
        SessionCalendar(
            session_id="2026-11-27_EARLY_CLOSE_FIXTURE",
            trade_date=date(2026, 11, 27),
            session_open=datetime(2026, 11, 26, 23, 0, tzinfo=UTC),
            session_close=datetime(2026, 11, 27, 18, 15, tzinfo=UTC),
            regular_trading_hours_open=datetime(2026, 11, 27, 14, 30, tzinfo=UTC),
            regular_trading_hours_close=datetime(2026, 11, 27, 18, 15, tzinfo=UTC),
            timezone="America/Chicago",
            holiday_name="Representative early-close fixture",
        ),
    )


def closed_trade_dates() -> frozenset[date]:
    """Return representative no-session dates used to test closure handling."""
    return frozenset({date(2026, 1, 1)})
