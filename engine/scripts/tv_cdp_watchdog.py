"""
JARVIS TRADER — TV CDP Port Watchdog
======================================
Polls TCP port 9222 (TradingView CDP remote-debugging port) on a configurable
interval (default 30 minutes).  If the port is unreachable, triggers the
JARVIS-TV-CDP-AtLogon scheduled task to restart TradingView Desktop.
Sends a Discord alert when port recovers (failure → success transition).

Logs every check to ~/.claude/logs/tv-cdp-watchdog.csv.

Designed to run as a daemon or be invoked by Windows Task Scheduler.

Usage (from jarvis-trader root):
    engine/.venv/Scripts/python engine/scripts/tv_cdp_watchdog.py
    engine/.venv/Scripts/python engine/scripts/tv_cdp_watchdog.py --dry-run
    engine/.venv/Scripts/python engine/scripts/tv_cdp_watchdog.py --once
    engine/.venv/Scripts/python engine/scripts/tv_cdp_watchdog.py --interval-minutes 15

Flags:
    --dry-run            Print intended actions without executing schtasks.
    --once               Run a single check and exit (no loop).
    --interval-minutes N Polling interval in minutes (default 30).
    --no-discord         Suppress Discord POSTs (log to stdout only).
    --debounce-minutes N Minimum minutes between recovery alerts (default 60).
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import socket
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("tv_cdp_watchdog")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_CDP_HOST = "127.0.0.1"
_CDP_PORT = 9222
_CONNECT_TIMEOUT = 3  # seconds

_SCHTASKS_TASK_NAME = "JARVIS-TV-CDP-AtLogon"

_LOG_DIR = Path.home() / ".claude" / "logs"
_LOG_CSV = _LOG_DIR / "tv-cdp-watchdog.csv"

_CSV_HEADERS = ["timestamp_utc", "port_reachable", "action_taken", "dry_run", "note"]

_DISCORD_WEBHOOK = (
    os.getenv("JARVIS_DISCORD_APPROVAL_WEBHOOK") or os.getenv("DISCORD_WEBHOOK_URL") or ""
).strip()


# ---------------------------------------------------------------------------
# Port check
# ---------------------------------------------------------------------------


def _check_port(
    host: str = _CDP_HOST, port: int = _CDP_PORT, timeout: float = _CONNECT_TIMEOUT
) -> bool:
    """Return True if the TCP port accepts a connection."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Recovery action
# ---------------------------------------------------------------------------


def _trigger_recovery(dry_run: bool) -> str:
    """
    Run JARVIS-TV-CDP-AtLogon via schtasks.

    Returns a short description of what was done.
    """
    cmd = ["schtasks", "/Run", "/TN", _SCHTASKS_TASK_NAME]
    if dry_run:
        logger.info("[DRY-RUN] Would execute: %s", " ".join(cmd))
        return "schtasks_skipped_dry_run"

    logger.info("Port 9222 unreachable — triggering recovery task: %s", _SCHTASKS_TASK_NAME)
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0:
            logger.info("Recovery task triggered successfully.")
            return "schtasks_triggered"
        else:
            logger.warning(
                "schtasks returned %d: %s %s",
                result.returncode,
                result.stdout.strip(),
                result.stderr.strip(),
            )
            return f"schtasks_error_rc{result.returncode}"
    except subprocess.TimeoutExpired:
        logger.warning("schtasks timed out after 15s")
        return "schtasks_timeout"
    except Exception as exc:
        logger.warning("schtasks failed: %s", exc)
        return f"schtasks_exception: {exc}"


# ---------------------------------------------------------------------------
# Discord alert
# ---------------------------------------------------------------------------


def _send_discord_alert(message: str, no_discord: bool) -> None:
    logger.info("ALERT: %s", message)
    if no_discord:
        return
    if not _DISCORD_WEBHOOK:
        logger.debug("JARVIS_DISCORD_APPROVAL_WEBHOOK not set — Discord alert skipped")
        return
    payload = json.dumps(
        {
            "content": f":tv: **JARVIS TV-CDP WATCHDOG** — {message}",
            "username": "JARVIS",
        }
    )
    try:
        req = urllib.request.Request(
            _DISCORD_WEBHOOK,
            data=payload.encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status not in (200, 204):
                logger.warning("Discord webhook returned %s", resp.status)
    except Exception as exc:
        logger.warning("Discord webhook POST failed: %s", exc)


# ---------------------------------------------------------------------------
# CSV logging
# ---------------------------------------------------------------------------


def _log_csv(
    timestamp_utc: str,
    port_reachable: bool,
    action_taken: str,
    dry_run: bool,
    note: str = "",
) -> None:
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    write_header = not _LOG_CSV.exists()
    try:
        with _LOG_CSV.open("a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=_CSV_HEADERS)
            if write_header:
                writer.writeheader()
            writer.writerow(
                {
                    "timestamp_utc": timestamp_utc,
                    "port_reachable": port_reachable,
                    "action_taken": action_taken,
                    "dry_run": dry_run,
                    "note": note,
                }
            )
    except Exception as exc:
        logger.warning("CSV log write failed: %s", exc)


# ---------------------------------------------------------------------------
# Single poll cycle
# ---------------------------------------------------------------------------


def poll_once(
    dry_run: bool = False,
    no_discord: bool = False,
    prev_reachable: bool | None = None,
    last_alert_ts: float | None = None,
    debounce_seconds: float = 3600,
) -> dict:
    """
    Check port 9222.  Trigger recovery and/or Discord alert as appropriate.

    Returns:
        {
            "reachable": bool,
            "action": str,
            "last_alert_ts": float | None,
        }
    """
    ts_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    reachable = _check_port()
    action = "none"
    note = ""

    logger.info(
        "Port %s:%d — %s",
        _CDP_HOST,
        _CDP_PORT,
        "reachable" if reachable else "UNREACHABLE",
    )

    if not reachable:
        action = _trigger_recovery(dry_run=dry_run)
        note = "recovery_triggered"
    elif prev_reachable is not None and not prev_reachable and reachable:
        # Transition: failure → success
        now_ts = time.monotonic()
        debounce_ok = last_alert_ts is None or (now_ts - last_alert_ts) >= debounce_seconds
        if debounce_ok:
            _send_discord_alert(
                "TV CDP port 9222 recovered — TradingView Desktop is reachable again.",
                no_discord=no_discord,
            )
            last_alert_ts = now_ts
            action = "discord_recovery_alert"
            note = "port_recovered"
        else:
            action = "recovery_debounced"
            note = "within_debounce_window"

    _log_csv(ts_utc, reachable, action, dry_run, note)

    return {
        "reachable": reachable,
        "action": action,
        "last_alert_ts": last_alert_ts,
        "ts_utc": ts_utc,
    }


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def run_loop(
    interval_seconds: float,
    dry_run: bool = False,
    no_discord: bool = False,
    debounce_seconds: float = 3600,
) -> None:
    """Poll indefinitely on interval_seconds cadence."""
    prev_reachable: bool | None = None
    last_alert_ts: float | None = None

    logger.info(
        "TV CDP watchdog started — polling port %d every %.0fs (dry_run=%s)",
        _CDP_PORT,
        interval_seconds,
        dry_run,
    )

    while True:
        result = poll_once(
            dry_run=dry_run,
            no_discord=no_discord,
            prev_reachable=prev_reachable,
            last_alert_ts=last_alert_ts,
            debounce_seconds=debounce_seconds,
        )
        prev_reachable = result["reachable"]
        last_alert_ts = result["last_alert_ts"]

        logger.debug("Sleeping %.0fs until next check.", interval_seconds)
        time.sleep(interval_seconds)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="JARVIS TV CDP watchdog — port 9222 health check")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print intended actions without executing schtasks or writing Discord.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single check and exit (no loop).",
    )
    parser.add_argument(
        "--interval-minutes",
        type=float,
        default=30.0,
        help="Polling interval in minutes (default: 30).",
    )
    parser.add_argument(
        "--no-discord",
        action="store_true",
        help="Suppress Discord POSTs.",
    )
    parser.add_argument(
        "--debounce-minutes",
        type=float,
        default=60.0,
        help="Minimum minutes between recovery Discord alerts (default: 60).",
    )
    args = parser.parse_args()

    interval_seconds = args.interval_minutes * 60
    debounce_seconds = args.debounce_minutes * 60

    if args.once:
        result = poll_once(
            dry_run=args.dry_run,
            no_discord=args.no_discord,
            prev_reachable=None,
            last_alert_ts=None,
            debounce_seconds=debounce_seconds,
        )
        logger.info("Single check result: %s", result)
        return 0

    run_loop(
        interval_seconds=interval_seconds,
        dry_run=args.dry_run,
        no_discord=args.no_discord,
        debounce_seconds=debounce_seconds,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
