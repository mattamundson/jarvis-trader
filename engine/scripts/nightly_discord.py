#!/usr/bin/env python3
"""
Nightly Discord Data Refresh for JARVIS Trader
================================================
Runs two operations in sequence:
1. Discord message import (idempotent via message_id UNIQUE constraint)
2. Sentiment ETL (computes/updates discord_daily_sentiment table)

Usage:
    python -m scripts.nightly_discord
    python -m scripts.nightly_discord --etl-only
    python -m scripts.nightly_discord --import-only

Windows Task Scheduler Setup:
    Action: Start a program
    Program: python
    Arguments: -m scripts.nightly_discord
    Start in: C:\\Users\\mattm\\ThinkorSwim\\jarvis-trader\\engine
    Schedule: Daily at 6:00 AM (before market open)
"""

import argparse
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

# Add engine to path if running standalone
ENGINE_DIR = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ENGINE_DIR))

# Ensure logs/ directory exists (engine/logs/ is the standard location)
LOGS_DIR = ENGINE_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(str(LOGS_DIR / "nightly_discord.log"), mode="a"),
    ],
)
logger = logging.getLogger(__name__)


def run_sentiment_etl() -> dict:
    """Run sentiment ETL and return stats dict."""
    logger.info("Starting sentiment ETL...")
    try:
        from discord.sentiment_provider import SentimentProvider

        sp = SentimentProvider()
        sp.run_etl()  # returns None — side effects are written to DB
        result = {"status": "ok"}
        logger.info(f"Sentiment ETL complete: {result}")
        return result
    except Exception as e:
        logger.error(f"Sentiment ETL failed: {e}", exc_info=True)
        return {"status": "error", "error": str(e)}


def run_discord_import() -> dict:
    """Run Discord message import (idempotent) via subprocess."""
    logger.info("Starting Discord import...")
    try:
        import subprocess

        result = subprocess.run(
            [sys.executable, "-m", "discord.cli"],
            capture_output=True,
            text=True,
            timeout=300,
            cwd=str(ENGINE_DIR),
        )
        stdout_tail = result.stdout[-500:] if result.stdout else "none"
        logger.info(f"Discord import stdout: {stdout_tail}")
        if result.returncode != 0:
            stderr_tail = result.stderr[-500:] if result.stderr else "none"
            logger.warning(f"Discord import stderr: {stderr_tail}")
        return {"returncode": result.returncode}
    except Exception as e:
        logger.error(f"Discord import failed: {e}", exc_info=True)
        return {"error": str(e)}


def main():
    parser = argparse.ArgumentParser(description="Nightly Discord data refresh")
    parser.add_argument("--etl-only", action="store_true", help="Only run sentiment ETL")
    parser.add_argument("--import-only", action="store_true", help="Only run Discord import")
    args = parser.parse_args()

    start = time.time()
    logger.info(f"=== Nightly Discord refresh started at {datetime.now().isoformat()} ===")

    results = {}

    if not args.etl_only:
        results["import"] = run_discord_import()

    if not args.import_only:
        results["etl"] = run_sentiment_etl()

    elapsed = time.time() - start
    logger.info(f"=== Nightly refresh complete in {elapsed:.1f}s. Results: {results} ===")
    return results


if __name__ == "__main__":
    main()
