"""
JARVIS TRADER — Approval Timeouts (Phase 4.4)
============================================
Logic for determining if a pending approval has expired based on market 
session (RTH vs. Overnight) and trade type.
"""

import logging
from datetime import datetime, time, timezone
from typing import Dict, Any

logger = logging.getLogger("jarvis_trader.risk.approval_timeout")

# ── Configuration ─────────────────────────────────────────────────────────────

# Default timeouts in minutes
TIMEOUT_RTH = 5
TIMEOUT_OVERNIGHT = 10

def is_rth() -> bool:
    """
    Check if currently in Regular Trading Hours (NYSE: 09:30 - 16:00 ET).
    For simplicity, we use UTC offset for ET (currently -4 or -5).
    """
    # TODO: Use a proper market calendar for robust RTH detection
    # For now, heuristic: 13:30 - 20:00 UTC (9:30 - 16:00 ET in Summer)
    now_utc = datetime.now(timezone.utc).time()
    return time(13, 30) <= now_utc <= time(20, 0)

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
