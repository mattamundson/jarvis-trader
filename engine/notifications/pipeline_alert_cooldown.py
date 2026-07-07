"""
Per-symbol cooldown for WhatsApp pipeline alerts (watchlist scheduler + manual scan).

State lives here so ``main.py`` and ``dependencies.py`` cannot drift.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, Literal, Optional

_last_sent: Dict[str, datetime] = {}

Decision = Literal["send", "suppressed_cooldown", "suppressed_no_channel"]


def reset_pipeline_alert_cooldown_for_tests() -> None:
    """Clear in-memory cooldown map (pytest only)."""
    _last_sent.clear()


def get_last_pipeline_alert_sent(symbol: str) -> Optional[datetime]:
    return _last_sent.get(symbol)


def mark_pipeline_alert_sent(symbol: str, when: datetime) -> None:
    _last_sent[symbol] = when


def pipeline_alert_cooldown_timedelta(minutes: int) -> timedelta:
    return timedelta(minutes=max(1, minutes))


def pipeline_alert_decision(
    *,
    last_sent: Optional[datetime],
    now: datetime,
    cooldown_minutes: int,
    notifier_enabled: bool,
) -> Decision:
    """Pure helper for unit tests and main.py branches."""
    if not notifier_enabled:
        return "suppressed_no_channel"
    td = pipeline_alert_cooldown_timedelta(cooldown_minutes)
    if last_sent is not None and (now - last_sent) < td:
        return "suppressed_cooldown"
    return "send"
