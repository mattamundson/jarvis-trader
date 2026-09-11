#!/usr/bin/env python3
"""
Nightly DiscordChatExporter (DCE) Refresh → Import Chain.

Runs DCE against the two Corey channels that drive `discord_corey_commentary`,
then calls the existing `nightly_discord.py` importer to ingest whatever JSON
freshened. Incremental: uses `--after` so we only fetch the last 7 days.

Prereqs (user action, see docs/incident-notes/2026-04-17-t2.1-discord-staleness.md):
    1. Install DiscordChatExporter.Cli to DCE_CLI_PATH (default below).
    2. Confirm DISCORD_TOKEN is valid in process env, engine .env, or the
       fallback C:\\Users\\mattm\\discord-export\\.token file.
    3. If DCE reports "Authentication token is invalid", rotate the token before
       rerunning; stale futures_sentiment is then a credential-freshness blocker.

Security: never pass Discord credentials via DCE --token/-t command-line args.
This helper injects DISCORD_TOKEN into the subprocess environment only.

Usage:
    python -m scripts.nightly_discord_export              # full chain: export + ingest
    python -m scripts.nightly_discord_export --no-ingest  # export only
    python -m scripts.nightly_discord_export --dry-run    # print commands, run nothing

Scheduled via PM2 cron at 02:00 America/Chicago (engine/ecosystem.config.js).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

ENGINE_DIR = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ENGINE_DIR))

LOGS_DIR = ENGINE_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)

# Consecutive-failure streak file. Tracks how many consecutive days DCE has
# failed so we can fire a WhatsApp alert after 2+ days of silence.
STREAK_FILE = LOGS_DIR / "dce_failure_streak.txt"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(str(LOGS_DIR / "nightly_discord_export.log"), mode="a"),
    ],
)
logger = logging.getLogger(__name__)

DCE_CLI_PATH = Path(
    os.environ.get(
        "DCE_CLI_PATH",
        r"C:\Users\mattm\tools\DiscordChatExporter.Cli\DiscordChatExporter.Cli.exe",
    )
)
EXPORT_DIR = Path(
    os.environ.get("DISCORD_EXPORT_DIR", r"C:\Users\mattm\discord-export")
)
TOKEN_FILE = EXPORT_DIR / ".token"

# Only two channels actually feed live agent decisions. See T2.1 note:
# discord_corey_commentary ← these channels; other 40+ channels are
# archival/reference and don't need nightly refresh.
CHANNELS = {
    "741484321142997086": "general",
    "806343100435660801": "market-updates",
}

# Lookback window: 7 days covers any missed runs without a full re-download.
LOOKBACK_DAYS = 7


def _read_token() -> str:
    token = os.environ.get("DISCORD_TOKEN", "").strip()
    if not token:
        env_file = ENGINE_DIR / ".env"
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.startswith("DISCORD_TOKEN="):
                    token = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    if not token and TOKEN_FILE.exists():
        token = TOKEN_FILE.read_text(encoding="utf-8").strip()
    if not token:
        raise ValueError(
            f"Discord token missing: set DISCORD_TOKEN, populate {TOKEN_FILE}, "
            "or add DISCORD_TOKEN to engine/.env before running."
        )
    return token


def _export_channel(channel_id: str, label: str, token: str, after: str, dry_run: bool) -> int:
    """Returns the subprocess exit code (0 = success)."""
    cmd = [
        str(DCE_CLI_PATH),
        "export",
        "--channel", channel_id,
        "--output", str(EXPORT_DIR) + "/",
        "--format", "Json",
        "--after", after,
    ]
    # Never pass the token on the command line. DiscordChatExporter reads
    # DISCORD_TOKEN from the subprocess environment, avoiding process-list leaks.
    redacted = cmd[:]
    logger.info("Export %s (%s): %s", label, channel_id, " ".join(redacted))
    if dry_run:
        return 0

    env = os.environ.copy()
    env["DISCORD_TOKEN"] = token
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=600,
        env=env,
    )
    if result.returncode != 0:
        stderr_tail = (result.stderr or "")[-500:]
        logger.error("DCE export failed for %s: rc=%s stderr=%s",
                     label, result.returncode, stderr_tail)
    else:
        stdout_tail = (result.stdout or "")[-300:]
        logger.info("DCE export ok for %s: %s", label, stdout_tail)
    return result.returncode


def _run_ingest(dry_run: bool) -> int:
    logger.info("Chaining into nightly_discord.py for ingest + sentiment ETL")
    if dry_run:
        return 0
    result = subprocess.run(
        [sys.executable, "-m", "scripts.nightly_discord"],
        cwd=str(ENGINE_DIR),
        capture_output=True,
        text=True,
        timeout=900,
    )
    if result.returncode != 0:
        logger.error("nightly_discord ingest failed: rc=%s stderr=%s",
                     result.returncode, (result.stderr or "")[-500:])
    return result.returncode


def _get_failure_streak() -> int:
    """Return the number of consecutive days DCE has failed (0 = no streak)."""
    try:
        return int(STREAK_FILE.read_text(encoding="utf-8").strip())
    except Exception:
        return 0


def _set_failure_streak(count: int) -> None:
    """Persist the consecutive failure count to disk."""
    try:
        STREAK_FILE.write_text(str(count), encoding="utf-8")
    except Exception as exc:
        logger.warning("Could not write streak file: %s", exc)


def _fire_stale_alert(streak: int) -> None:
    """Dispatch WhatsApp alert via openclaw_notifier (one per calendar day)."""
    try:
        from notifications.openclaw_notifier import notify_corey_stale

        asyncio.run(
            notify_corey_stale(
                days_stale=streak,
                last_message_date="unknown — DCE export failed",
            )
        )
        logger.info("WhatsApp stale-feed alert dispatched (streak=%d)", streak)
    except Exception as exc:
        logger.warning("WhatsApp stale-feed alert failed to dispatch: %s", exc)


def main() -> int:
    parser = argparse.ArgumentParser(description="DCE nightly export + ingest chain")
    parser.add_argument("--no-ingest", action="store_true",
                        help="Only run DCE export; skip the nightly_discord ingest step.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print intended commands; make no DCE or ingest calls.")
    args = parser.parse_args()

    start = time.time()
    logger.info("=== DCE nightly refresh started %s ===", datetime.now().isoformat())

    if not DCE_CLI_PATH.exists() and not args.dry_run:
        logger.error("DiscordChatExporter CLI not found at %s. "
                     "Install or set DCE_CLI_PATH. Aborting.", DCE_CLI_PATH)
        return 2

    try:
        token = _read_token() if not args.dry_run else "***dry-run***"
    except Exception as exc:
        logger.error("Token read failed: %s", exc)
        return 3

    after = (datetime.now() - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    failures = 0
    for cid, label in CHANNELS.items():
        rc = _export_channel(cid, label, token, after, args.dry_run)
        if rc != 0:
            failures += 1

    if failures == len(CHANNELS):
        logger.error("All DCE exports failed; skipping ingest.")
        # Track consecutive-failure days and alert on day 2+.
        if not args.dry_run:
            streak = _get_failure_streak() + 1
            _set_failure_streak(streak)
            logger.warning("DCE failure streak: %d consecutive day(s)", streak)
            if streak >= 2:
                logger.warning("Streak >= 2 — dispatching WhatsApp staleness alert")
                _fire_stale_alert(streak)
        return 4

    # ── Ingest fresh JSON into SQLite + run sentiment ETL ──────────────────────
    ingest_rc = 0
    if not args.no_ingest:
        ingest_rc = _run_ingest(args.dry_run)

    overall_rc = 1 if (failures or ingest_rc) else 0

    # ── Update failure streak ──────────────────────────────────────────────────
    if not args.dry_run:
        if overall_rc == 0:
            # Clean run — reset streak so a future failure starts counting fresh.
            _set_failure_streak(0)
        else:
            # Partial failure (some channels ok, some failed, or ingest failed).
            streak = _get_failure_streak() + 1
            _set_failure_streak(streak)
            logger.warning("DCE partial-failure streak: %d consecutive day(s)", streak)
            if streak >= 2:
                logger.warning("Streak >= 2 — dispatching WhatsApp staleness alert")
                _fire_stale_alert(streak)

    elapsed = time.time() - start
    logger.info("=== DCE refresh done in %.1fs — export_failures=%d ingest_rc=%d rc=%d ===",
                elapsed, failures, ingest_rc, overall_rc)
    return overall_rc


if __name__ == "__main__":
    sys.exit(main())
