"""
Per-level cooldown for VIX-threshold WhatsApp alerts.

Mirrors ``notifications/pipeline_alert_cooldown.py``'s pattern (pure decision
function + in-memory time map) rather than inventing a new mechanism. Keyed
by alert *level* (CAUTION/ELEVATED/EXTREME) instead of symbol — VIX is a
single macro instrument, not a per-symbol signal, but an *escalation* to a
more severe level should never be suppressed just because the previous,
milder level alerted recently.

Bug fixed 2026-07-10: two independent call sites fired a real WhatsApp send
on every invocation with no rate limiting —

  * ``schedulers/eod_scheduler.py::run_vix_alert_check`` — hourly cron,
    Mon-Fri 8AM-5PM CT. VIX staying elevated for a session re-sent the same
    alert every hour.
  * ``routers/notifications_router.py::check_vix_alert`` (``POST
    /notifications/vix-alert-check``) — polled every 5 minutes by the
    dashboard's ``VIXRegimeCard`` (``dashboard/components/VIXRegimeCard.tsx``)
    purely to *read* the current VIX value for display. The read-looking poll
    had a live side effect: it re-sent the WhatsApp alert every 5 minutes
    whenever VIX was elevated, for as long as the watchlist tab stayed open.

Both call sites now share this module's in-memory state so a send from
either path counts against the same cooldown window.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, Literal, Optional

_last_sent: Dict[str, datetime] = {}

# VIX alert checks run as often as every 5 minutes (dashboard poll); a 60-minute
# cooldown per level keeps a sustained elevated regime from spamming while still
# re-notifying well within the same trading session.
DEFAULT_VIX_ALERT_COOLDOWN_MINUTES = 60

Decision = Literal["send", "suppressed_cooldown"]


def reset_vix_alert_cooldown_for_tests() -> None:
    """Clear in-memory cooldown map (pytest only)."""
    _last_sent.clear()


def get_last_vix_alert_sent(level: str) -> Optional[datetime]:
    return _last_sent.get(level)


def mark_vix_alert_sent(level: str, when: datetime) -> None:
    _last_sent[level] = when


def vix_alert_cooldown_timedelta(minutes: int) -> timedelta:
    return timedelta(minutes=max(1, minutes))


def vix_alert_decision(
    *,
    level: str,
    last_sent: Optional[datetime],
    now: datetime,
    cooldown_minutes: int = DEFAULT_VIX_ALERT_COOLDOWN_MINUTES,
) -> Decision:
    """Pure helper for unit tests and the two call sites.

    ``level`` keys the cooldown independently per severity (CAUTION /
    ELEVATED / EXTREME) so an escalation always sends even if a milder level
    alerted moments ago.
    """
    td = vix_alert_cooldown_timedelta(cooldown_minutes)
    if last_sent is not None and (now - last_sent) < td:
        return "suppressed_cooldown"
    return "send"
