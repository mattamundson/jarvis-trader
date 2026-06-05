"""
JARVIS TRADER — Approval Timeouts (Phase 4.4)
============================================
Logic for determining if a pending approval has expired based on market
session (RTH vs. Overnight) and trade type.
"""

import logging
from datetime import datetime, time, timezone
from typing import Any, Dict
from zoneinfo import ZoneInfo

logger = logging.getLogger("jarvis_trader.risk.approval_timeout")

# ── Configuration ─────────────────────────────────────────────────────────────

# Default timeouts in minutes
TIMEOUT_RTH = 5
TIMEOUT_OVERNIGHT = 10

# NYSE local zone — handles the EDT/EST transition automatically.
_ET = ZoneInfo("America/New_York")


def _is_rth_at(now_et: datetime) -> bool:
    """RTH = NYSE 09:30–16:00 ET on a weekday. `now_et` must be ET-localized."""
    if now_et.weekday() >= 5:  # Saturday / Sunday
        return False
    return time(9, 30) <= now_et.time() <= time(16, 0)


def is_rth() -> bool:
    """
    Check if currently in Regular Trading Hours (NYSE: 09:30 - 16:00 ET, Mon-Fri).

    Converts to America/New_York so the ET window tracks DST correctly. The old
    hardcoded 13:30-20:00 UTC window was right only in EDT; in EST it was an hour
    off — misclassifying 08:30-09:30 ET as RTH and the real 15:00-16:00 ET hour
    as overnight. Holidays are NOT modelled (no market calendar dependency); on a
    holiday this returns the RTH window, which only tightens the approval timeout
    (5m vs 10m), never loosens it.
    """
    return _is_rth_at(datetime.now(_ET))

def get_timeout_for_trade(approval_row: Dict[str, Any]) -> int:
    """
    Determine the allowed lifetime of an approval in minutes.
    """
    # 1. Check if we're in RTH
    rth = is_rth()

    # 2. Base timeout
    timeout = TIMEOUT_RTH if rth else TIMEOUT_OVERNIGHT

    # 3. (Future) Trade-specific overrides
    # e.g. symbol-based or strategy-based adjustments

    return timeout

def is_expired(approval_row: Dict[str, Any]) -> bool:
    """
    Evaluate if a specific approval row has exceeded its permitted lifetime.
    """
    created_at_str = approval_row.get("created_at")
    if not created_at_str:
        return False

    try:
        if isinstance(created_at_str, datetime):
            created_at = created_at_str
        else:
            created_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))

        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)

        now = datetime.now(timezone.utc)
        age_mins = (now - created_at).total_seconds() / 60

        timeout = get_timeout_for_trade(approval_row)

        if age_mins > timeout:
            logger.info(
                "[Timeout] %s expired: age=%.1fm, limit=%dm (rth=%s)",
                approval_row.get("symbol"), age_mins, timeout, is_rth()
            )
            return True

        return False
    except Exception as e:
        logger.error(f"[Timeout] Error evaluating expiry: {e}")
        return False
