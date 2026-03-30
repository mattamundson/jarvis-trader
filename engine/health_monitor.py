"""
JARVIS TRADER — Health Monitor
================================
Polls the engine health endpoint every 60 seconds.
Sends a WhatsApp alert via Twilio if the engine is down or unresponsive.
Logs status with timestamps to engine/logs/health.log.

Usage (run alongside the engine):
    cd engine
    .venv\Scripts\python health_monitor.py
"""

import logging
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Resolve project paths
# ---------------------------------------------------------------------------
ENGINE_DIR = Path(__file__).resolve().parent
LOGS_DIR = ENGINE_DIR / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOGS_DIR / "health.log"

# ---------------------------------------------------------------------------
# Logging — file + console
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("health_monitor")

# ---------------------------------------------------------------------------
# Config — load from .env without third-party deps
# ---------------------------------------------------------------------------
def _load_env(env_path: Path) -> dict:
    """Minimal .env parser — handles KEY=VALUE and quoted values."""
    env: dict = {}
    if not env_path.exists():
        return env
    with open(env_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            env[key] = value
    return env


_env = _load_env(ENGINE_DIR / ".env")

HEALTH_URL = "http://localhost:8010/health"
POLL_INTERVAL = 60          # seconds between checks
REQUEST_TIMEOUT = 10        # seconds before considering engine dead
ALERT_COOLDOWN = 300        # seconds between repeated DOWN alerts (5 min)

TWILIO_ACCOUNT_SID  = _env.get("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN   = _env.get("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM         = _env.get("TWILIO_WHATSAPP_FROM", "")
WHATSAPP_TO         = _env.get("WHATSAPP_TO", "")

_PLACEHOLDERS = {"", None, "your_account_sid_here", "your_auth_token_here",
                 "your_whatsapp_from_here", "your_whatsapp_to_here"}

WHATSAPP_ENABLED = not any(v in _PLACEHOLDERS for v in [
    TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM, WHATSAPP_TO
])

# ---------------------------------------------------------------------------
# WhatsApp alert (stdlib only — urllib + base64 for Basic Auth)
# ---------------------------------------------------------------------------
import base64
import json as _json


def _send_whatsapp(message: str) -> bool:
    """Send a WhatsApp message via Twilio REST API using only stdlib."""
    if not WHATSAPP_ENABLED:
        logger.warning("WhatsApp not configured — alert suppressed: %s", message)
        return False

    url = f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_ACCOUNT_SID}/Messages.json"
    body = urllib.parse.urlencode({
        "From": TWILIO_FROM,
        "To":   WHATSAPP_TO,
        "Body": message,
    }).encode("utf-8")

    credentials = base64.b64encode(
        f"{TWILIO_ACCOUNT_SID}:{TWILIO_AUTH_TOKEN}".encode()
    ).decode()

    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type":  "application/x-www-form-urlencoded",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8")
            data = _json.loads(raw)
            logger.info("WhatsApp alert sent  SID=%s", data.get("sid"))
            return True
    except urllib.error.HTTPError as exc:
        logger.error("Twilio HTTP %s: %s", exc.code, exc.read().decode("utf-8", errors="replace")[:300])
    except Exception as exc:
        logger.error("WhatsApp send failed: %s", exc)
    return False


# ---------------------------------------------------------------------------
# urllib.parse needed for urlencode — import after definition to keep tidy
# ---------------------------------------------------------------------------
import urllib.parse  # noqa: E402  (stdlib, already available)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
def _check_health() -> tuple[bool, str]:
    """
    Returns (is_healthy: bool, detail: str).
    Healthy = HTTP 200 within REQUEST_TIMEOUT seconds.
    """
    try:
        req = urllib.request.Request(HEALTH_URL, method="GET")
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            if resp.status == 200:
                return True, f"HTTP 200"
            return False, f"HTTP {resp.status}"
    except urllib.error.URLError as exc:
        return False, f"URLError: {exc.reason}"
    except TimeoutError:
        return False, f"Timed out after {REQUEST_TIMEOUT}s"
    except Exception as exc:
        return False, f"Exception: {exc}"


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
def run() -> None:
    logger.info("=" * 60)
    logger.info("JARVIS TRADER Health Monitor started")
    logger.info("Polling : %s", HEALTH_URL)
    logger.info("Interval: %ds  |  Timeout: %ds  |  Alert cooldown: %ds",
                POLL_INTERVAL, REQUEST_TIMEOUT, ALERT_COOLDOWN)
    logger.info("WhatsApp alerts: %s", "ENABLED" if WHATSAPP_ENABLED else "DISABLED (configure .env)")
    logger.info("=" * 60)

    was_down = False
    last_alert_ts: float = 0.0

    while True:
        is_healthy, detail = _check_health()

        if is_healthy:
            logger.info("OK  — Engine is healthy  (%s)", detail)
            if was_down:
                # Engine came back up — send recovery notice
                _send_whatsapp(
                    "JARVIS Engine RECOVERED\n"
                    f"Engine is back online.\n"
                    f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                )
                was_down = False
        else:
            logger.warning("DOWN — Engine not responding  (%s)", detail)
            was_down = True

            now = time.monotonic()
            if now - last_alert_ts >= ALERT_COOLDOWN:
                sent = _send_whatsapp(
                    "JARVIS Engine DOWN — restart required\n\n"
                    f"Health check failed: {detail}\n"
                    f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                    "Run: cd engine && .venv\\Scripts\\python -m uvicorn main:app --port 8010"
                )
                if sent:
                    last_alert_ts = now

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        logger.info("Health monitor stopped by user (KeyboardInterrupt).")
        sys.exit(0)
