"""
IB Gateway Health Monitor
=========================
Monitors IB Gateway connection status during market hours.
Sends WhatsApp alert if connection is lost during trading hours.
"""

import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# Module-level state
_last_alert_time: float = 0.0
_IB_ALERT_COOLDOWN = 3600  # 1 hour cooldown between alerts

CT = ZoneInfo("America/Chicago")


def is_market_hours() -> bool:
    """Check if current time is within market hours (Mon-Fri 8:30am-4:15pm CT)."""
    now = datetime.now(CT)

    # Monday=0, Sunday=6
    if now.weekday() >= 5:  # Saturday or Sunday
        return False

    # Check time: 08:30 to 16:15
    time_minutes = now.hour * 60 + now.minute
    start_minutes = 8 * 60 + 30  # 08:30
    end_minutes = 16 * 60 + 15   # 16:15

    return start_minutes <= time_minutes <= end_minutes


async def check_ib_health(ib_connector) -> bool:
    """
    Check IB Gateway health status.

    Args:
        ib_connector: IB connector instance (or None if not configured)

    Returns:
        True if connected, False if disconnected during market hours

    Raises:
        Exception only if logic errors occur; catches all connector errors
    """
    global _last_alert_time

    try:
        # If no connector configured, assume all is well
        if ib_connector is None:
            logger.debug("[IB Monitor] No IB connector configured")
            return True

        # Check connection status
        is_connected = ib_connector.is_connected()

        # If connected, return immediately
        if is_connected:
            logger.debug("[IB Monitor] IB Gateway connected")
            return True

        # If disconnected during non-market hours, just log and return False
        if not is_market_hours():
            logger.debug("[IB Monitor] IB Gateway disconnected but outside market hours")
            return False

        # Disconnected during market hours — check cooldown and alert
        now_ts = datetime.now().timestamp()
        if now_ts - _last_alert_time > _IB_ALERT_COOLDOWN:
            logger.error("[IB Monitor] IB Gateway disconnected during market hours")
            _last_alert_time = now_ts

            # Send WhatsApp alert asynchronously (non-blocking)
            try:
                from notifications.openclaw_notifier import notify_ib_disconnect
                asyncio.create_task(notify_ib_disconnect())
            except Exception as e:
                logger.warning(f"[IB Monitor] Failed to schedule IB disconnect alert: {e}")
        else:
            logger.debug("[IB Monitor] IB disconnect alert on cooldown")

        return False

    except Exception as e:
        logger.warning(f"[IB Monitor] Health check failed (assuming connected): {e}")
        return True  # Assume connected on exception to avoid false alerts
