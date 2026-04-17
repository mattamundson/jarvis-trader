#!/usr/bin/env python3
"""
Nightly DiscordChatExporter (DCE) Refresh → Import Chain.

Runs DCE against the two Corey channels that drive `discord_corey_commentary`,
then calls the existing `nightly_discord.py` importer to ingest whatever JSON
freshened. Incremental: uses `--after` so we only fetch the last 7 days.

Prereqs (user action, see docs/incident-notes/2026-04-17-t2.1-discord-staleness.md):
    1. Install DiscordChatExporter.Cli to DCE_CLI_PATH (default below).
    2. Confirm C:\\Users\\mattm\\discord-export\\.token exists and is valid.

Usage:
    python -m scripts.nightly_discord_export              # full chain: export + ingest
    python -m scripts.nightly_discord_export --no-ingest  # export only
    python -m scripts.nightly_discord_export --dry-run    # print commands, run nothing

Scheduled via PM2 cron at 02:00 America/Chicago (engine/ecosystem.config.js).
"""

from __future__ import annotations

import argparse
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
    if not TOKEN_FILE.exists():
        raise FileNotFoundError(
            f"Discord token file missing: {TOKEN_FILE}. "
            "Save the user/bot token (one line, no quotes) before running."
        )
    token = TOKEN_FILE.read_text(encoding="utf-8").strip()
    if not token:
        raise ValueError(f"Token file is empty: {TOKEN_FILE}")
    return token


def _export_channel(channel_id: str, label: str, token: str, after: str, dry_run: bool) -> int:
    """Returns the subprocess exit code (0 = success)."""
    cmd = [
        str(DCE_CLI_PATH),
        "export",
        "--channel", channel_id,
        "--token", token,
        "--output", str(EXPORT_DIR) + "/",
        "--format", "Json",
        "--after", after,
    ]
    # Never echo the token to stdout/logs.
    redacted = [x if x != token else "***REDACTED***" for x in cmd]
    logger.info("Export %s (%s): %s", label, channel_id, " ".join(redacted))
    if dry_run:
        return 0

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=600,
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
        return 4

    ingest_rc = 0
    if not args.no_ingest:
        ingest_rc = _run_ingest(args.dry_run)

    elapsed = time.time() - start
    logger.info("=== DCE refresh done in %.1fs — export_failures=%d ingest_rc=%d ===",
                elapsed, failures, ingest_rc)
    return 1 if (failures or ingest_rc) else 0


if __name__ == "__main__":
    sys.exit(main())
