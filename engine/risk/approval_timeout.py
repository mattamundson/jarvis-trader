"""
JARVIS TRADER — Approval Timeouts (Phase 4.4)
============================================
Logic for determining if a pending approval has expired based on market 
session (RTH vs. Overnight) and trade type.
"""

import logging
from datetime import datetime, time, timezone
from typing import Dict, Any, Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger("jarvis_trader.risk.approval_timeout")

# ── Configuration ─────────────────────────────────────────────────────────────

# Default timeouts in minutes
TIMEOUT_RTH = 5
TIMEOUT_OVERNIGHT = 10

# Exchange timezone — using the IANA zone (not a fixed UTC offset) so the
# EDT/EST daylight-saving transition is handled automatically.
_ET = ZoneInfo("America/New_York")
_RTH_OPEN = time(9, 30)
_RTH_CLOSE = time(16, 0)


def is_rth(now: Optional[datetime] = None) -> bool:
    """
    Return True if the US equity market is in Regular Trading Hours
    (NYSE 09:30-16:00 ET, Monday-Friday).

    Converts to America/New_York so the DST transition is correct year-round
    (the previous fixed 13:30-20:00 UTC heuristic was only right in summer and
    also fired on weekends). Market holidays are intentionally NOT modelled: the
    only consequence here is a holiday getting the shorter RTH approval timeout,
    which is low-stakes — add a market-calendar dependency if holiday precision
    is ever needed.

    Args:
        now: optional reference instant (for testing). Naive datetimes are
            treated as UTC. Defaults to the current time.
    """
    ref = now or datetime.now(timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    now_et = ref.astimezone(_ET)
    if now_et.weekday() >= 5:  # Saturday (5) / Sunday (6)
        return False
    return _RTH_OPEN <= now_et.time() <= _RTH_CLOSE

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
