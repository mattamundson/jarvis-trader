"""Session assignment for normalized event rows."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from es_research.contracts import SessionCalendar, require_utc


class SessionAssignmentError(ValueError):
    """Raised when an event cannot be mapped to exactly one session."""


def assign_session_id(timestamp: datetime, sessions: tuple[SessionCalendar, ...]) -> str:
    """Return the session_id whose inclusive-open/exclusive-close interval contains timestamp."""
    normalized_timestamp = require_utc(timestamp)
    matches = [
        session.session_id
        for session in sessions
        if session.session_open <= normalized_timestamp < session.session_close
    ]
    if not matches:
        raise SessionAssignmentError(
            f"timestamp {normalized_timestamp.isoformat()} is outside all sessions"
        )
    if len(matches) > 1:
        raise SessionAssignmentError(
            f"timestamp {normalized_timestamp.isoformat()} matched multiple sessions"
        )
    return matches[0]


def assign_sessions(
    rows: tuple[dict[str, Any], ...], sessions: tuple[SessionCalendar, ...]
) -> tuple[dict[str, Any], ...]:
    """Attach session_id to normalized event rows without mutating inputs."""
    assigned: list[dict[str, Any]] = []
    for row in rows:
        if "event_timestamp" not in row:
            raise KeyError("normalized event row missing event_timestamp")
        next_row = dict(row)
        next_row["session_id"] = assign_session_id(row["event_timestamp"], sessions)
        assigned.append(next_row)
    return tuple(assigned)
