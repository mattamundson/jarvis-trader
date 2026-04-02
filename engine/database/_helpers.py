"""
JARVIS TRADER — Database Helpers
==================================
Private utility functions shared across all database mixin modules.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger("jarvis_trader.database")


def _utcnow() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _to_json(value: Any) -> Optional[str]:
    """Serialise a dict/list to a JSON string; pass through strings/None."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, default=str)


def _from_json(value: Optional[str]) -> Any:
    """Deserialise a JSON string; return None/non-string values unchanged."""
    if value is None or not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, ValueError):
        return value  # return raw string if it is not valid JSON
