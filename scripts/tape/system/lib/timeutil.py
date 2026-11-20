"""America/Chicago time helpers for the ES read system."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

CT = ZoneInfo("America/Chicago")
UTC = ZoneInfo("UTC")


def parse_ct(s: str) -> datetime:
    """Parse 'YYYY-MM-DD HH:MM' or ISO with offset into CT-aware datetime."""
    s = s.strip()
    if s.endswith("Z"):
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.astimezone(CT)
    if "T" in s:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=CT)
        return dt.astimezone(CT)
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=CT)
        except ValueError:
            continue
    raise ValueError(f"unparseable CT timestamp: {s!r}")


def to_ct_str(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=CT)
    return dt.astimezone(CT).strftime("%Y-%m-%d %H:%M")


def hour_of_night(dt: datetime) -> str:
    """Bucket overnight hours as labels like '21', '22' (CT hour)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=CT)
    return f"{dt.astimezone(CT).hour:02d}"


def session_date_for(dt: datetime):
    """Futures session date: before 17:00 CT belongs to that calendar date;
    at/after 17:00 CT belongs to the next calendar date."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=CT)
    local = dt.astimezone(CT)
    if local.hour >= 17:
        return (local + timedelta(days=1)).date()
    return local.date()
