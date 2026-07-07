"""
JARVIS TRADER — Macro Calendar Service (Phase 6.4)
==================================================
Tracks major economic catalysts (Fed, CPI, NFP, PCE) and provides
gating logic to block trade entries during high-volatility releases.

Implements Roadmap P6.4.
"""

import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("jarvis_trader.data.macro_calendar")

# ── Configuration ─────────────────────────────────────────────────────────────

# Windows around releases (minutes)
BLOCK_BEFORE_MINS = 30
BLOCK_AFTER_MINS = 60

# Major 2026 Catalysts (Known dates)
# Note: In a production system, these would be fetched via an API (e.g. FRED, FinancialModelingPrep)
# For P6.4 we use a hardcoded registry for reliability on known dates.
CATALYSTS = [
    # Non-Farm Payrolls (NFP) - 8:30am ET
    {"name": "NFP", "date": date(2026, 5, 1), "time_et": time(8, 30)},
    {"name": "NFP", "date": date(2026, 6, 5), "time_et": time(8, 30)},
    {"name": "NFP", "date": date(2026, 7, 3), "time_et": time(8, 30)},
    {"name": "NFP", "date": date(2026, 8, 7), "time_et": time(8, 30)},

    # Consumer Price Index (CPI) - 8:30am ET
    {"name": "CPI", "date": date(2026, 5, 13), "time_et": time(8, 30)},
    {"name": "CPI", "date": date(2026, 6, 10), "time_et": time(8, 30)},
    {"name": "CPI", "date": date(2026, 7, 14), "time_et": time(8, 30)},

    # FOMC Meetings (Interest Rate Decisions) - 2:00pm ET + 2:30pm Presser
    {"name": "FOMC", "date": date(2026, 5, 6), "time_et": time(14, 0)},
    {"name": "FOMC", "date": date(2026, 6, 17), "time_et": time(14, 0)},
    {"name": "FOMC", "date": date(2026, 7, 29), "time_et": time(14, 0)},
    {"name": "FOMC", "date": date(2026, 9, 23), "time_et": time(14, 0)},
]

class MacroCalendar:
    """
    Manages economic event gating logic.
    """

    def is_blackout(self, dt: Optional[datetime] = None) -> bool:
        """
        Check if the given time (default now) falls within an event blackout window.
        """
        now = dt or datetime.now(timezone.utc)

        for event in CATALYSTS:
            # Construct event datetime in ET then convert to UTC
            # For simplicity, we'll assume ET is UTC-4 (Summer 2026)
            # In a real system, use zoneinfo 'America/New_York'
            event_dt_et = datetime.combine(event["date"], event["time_et"])
            event_dt_utc = event_dt_et + timedelta(hours=4) # ET -> UTC

            start_block = event_dt_utc - timedelta(minutes=BLOCK_BEFORE_MINS)
            end_block = event_dt_utc + timedelta(minutes=BLOCK_AFTER_MINS)

            if start_block <= now <= end_block:
                logger.info(
                    "[MacroCalendar] Blackout active for %s (%s to %s)",
                    event["name"], start_block.isoformat(), end_block.isoformat()
                )
                return True

        return False

    def get_upcoming_events(self, days: int = 7) -> List[Dict[str, Any]]:
        """
        List events occurring in the next N days.
        """
        now = date.today()
        horizon = now + timedelta(days=days)

        return [
            e for e in CATALYSTS
            if now <= e["date"] <= horizon
        ]

_calendar_instance: Optional[MacroCalendar] = None

def get_macro_calendar() -> MacroCalendar:
    global _calendar_instance
    if _calendar_instance is None:
        _calendar_instance = MacroCalendar()
    return _calendar_instance
