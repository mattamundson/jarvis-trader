"""
Market data endpoints
"""

import logging

from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["market"])

# Global references (injected from main.py)


def inject_dependencies():
    """Inject dependencies from main.py"""
    pass


@router.get("/market/earnings")
async def get_upcoming_earnings(days: int = 7):
    """Check for upcoming earnings near our watched symbols.

    Earnings calendar data is not currently available without yfinance.
    Returns an empty list — wire a Finnhub or Polygon earnings endpoint
    to populate this in a future iteration.
    """
    return {
        "upcoming_earnings": [],
        "count": 0,
        "days_lookahead": days,
        "note": "Earnings calendar unavailable — integrate Finnhub /calendar/earnings for live data",
        "source": "unavailable",
    }


@router.get("/market/session")
async def get_market_session():
    """Return current market session status (pre-market, regular, after-hours, closed)."""
    import zoneinfo
    from datetime import datetime

    eastern = zoneinfo.ZoneInfo("America/New_York")
    now = datetime.now(tz=eastern)
    weekday = now.weekday()  # 0=Mon, 6=Sun
    hour, minute = now.hour, now.minute
    time_val = hour * 60 + minute

    if weekday >= 5:  # Saturday or Sunday
        session = "closed"
        description = "Markets closed — weekend"
    elif time_val < 4 * 60:  # before 4:00 AM ET
        session = "closed"
        description = "Markets closed — overnight"
    elif time_val < 9 * 60 + 30:  # 4:00–9:30 AM ET
        session = "pre_market"
        description = "Pre-market session (4:00–9:30 AM ET)"
    elif time_val < 16 * 60:  # 9:30 AM–4:00 PM ET
        session = "regular"
        description = "Regular trading hours (9:30 AM–4:00 PM ET)"
    elif time_val < 20 * 60:  # 4:00–8:00 PM ET
        session = "after_hours"
        description = "After-hours session (4:00–8:00 PM ET)"
    else:
        session = "closed"
        description = "Markets closed — after hours"

    return {
        "session": session,
        "description": description,
        "timestamp": now.isoformat(),
        "is_open": session == "regular",
    }
