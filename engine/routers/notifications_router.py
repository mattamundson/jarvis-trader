"""Notification utility endpoints (WhatsApp test, VIX alert)."""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["notifications"])


@router.post("/notifications/whatsapp/test")
async def test_whatsapp():
    """Test WhatsApp notification config."""
    from notifications.whatsapp import get_notifier

    notifier = get_notifier()
    ts = datetime.now(timezone.utc).isoformat()
    if not notifier.enabled:
        return {
            "status": "not_configured",
            "sent": False,
            "timestamp": ts,
            "message": "Add TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM, WHATSAPP_TO to .env",
        }
    ok = await notifier.test()
    return {"status": "sent" if ok else "failed", "sent": bool(ok), "timestamp": ts}


@router.post("/notifications/vix-alert-check")
async def check_vix_alert():
    """Check VIX and send WhatsApp alert if above key thresholds.

    Cooldown-gated per severity level (shared with the hourly
    ``eod_scheduler.run_vix_alert_check`` job via
    ``notifications.vix_alert_cooldown``). This endpoint is polled by the
    dashboard's ``VIXRegimeCard`` every 5 minutes purely to *read* the
    current VIX value for display — without the cooldown, that read-looking
    poll had a live side effect of re-sending a real WhatsApp alert every
    5 minutes for as long as VIX stayed elevated and the tab was open.
    """
    try:
        from analytics.vix_overlay import VIXOverlay
        from notifications.vix_alert_cooldown import (
            get_last_vix_alert_sent,
            mark_vix_alert_sent,
            vix_alert_decision,
        )
        from notifications.whatsapp import send_whatsapp_message

        vix = VIXOverlay()
        state = vix.get_state()

        thresholds = [
            (40, "EXTREME VIX", "Consider halting all trading"),
            (30, "ELEVATED VIX", "Reduce position size, widen stops"),
            (20, "CAUTION VIX", "Monitor closely, use regime filter"),
        ]

        alert_level = None
        guidance = None
        for level, label, advice in thresholds:
            if state.vix_value >= level:
                alert_level = label
                guidance = advice
                break

        if alert_level is None:
            return {
                "sent": False,
                "vix": state.vix_value,
                "regime": state.regime,
                "reason": "VIX normal — no alert needed",
            }

        # Cooldown is keyed by the numeric threshold (40/30/20), not the label
        # text, so it stays shared with schedulers/eod_scheduler.py's hourly
        # run_vix_alert_check even though the two call sites use slightly
        # different label strings ("EXTREME VIX" here vs. "EXTREME" there).
        cooldown_key = str(level)
        now = datetime.now(timezone.utc)
        decision = vix_alert_decision(
            level=cooldown_key,
            last_sent=get_last_vix_alert_sent(cooldown_key),
            now=now,
        )
        if decision == "suppressed_cooldown":
            return {
                "sent": False,
                "vix": state.vix_value,
                "regime": state.regime,
                "alert_level": alert_level,
                "guidance": guidance,
                "reason": "cooldown_active",
            }

        msg = (
            "JARVIS TRADER - VIX Alert\n\n"
            f"VIX: {state.vix_value:.1f} - {alert_level}\n"
            f"Classification: {state.classification}\n\n"
            f"{guidance}\n\n"
            f"Source: {state.source}"
        )

        success = await send_whatsapp_message(msg)
        if success:
            mark_vix_alert_sent(cooldown_key, now)
        return {
            "sent": success,
            "vix": state.vix_value,
            "regime": state.regime,
            "alert_level": alert_level,
            "guidance": guidance,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
