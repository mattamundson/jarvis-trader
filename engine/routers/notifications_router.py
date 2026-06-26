"""
Notifications Router — auto-generated scaffold.
Full WhatsApp/alert implementation pending Twilio configuration.
"""
from fastapi import APIRouter

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.post("/notifications/whatsapp/test")
async def test_whatsapp():
    """Test WhatsApp notification config."""
    return {
        "status": "not_configured",
        "sent": False,
        "message": "Add TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM, WHATSAPP_TO to .env",
    }


@router.post("/notifications/vix-alert-check")
async def check_vix_alert():
    """Check VIX and send WhatsApp alert if above key thresholds."""
    return {
        "status": "not_implemented",
        "message": "VIX alert notifications pending Twilio configuration.",
    }


@router.post("/notifications/thinkscript")
async def generate_thinkscript(symbol: str = "SPY", timeframe: str = "15m", is_futures: bool = False):
    """Generate a ThinkScript indicator (not yet implemented)."""
    return {
        "status": "not_implemented",
        "message": "ThinkScript generation pending full implementation.",
    }
