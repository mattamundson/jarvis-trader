#!/usr/bin/env python3
"""
generate_trading_journal.py — daily trading journal generator.

Combines paper trades, PnL snapshots, Corey commentary, bot signals,
and JARVIS interactions into a single vault-ingestible Markdown entry.

Usage:
    engine/.venv/Scripts/python scripts/generate_trading_journal.py
    engine/.venv/Scripts/python scripts/generate_trading_journal.py --date 2026-05-20
    engine/.venv/Scripts/python scripts/generate_trading_journal.py --date 2026-05-20 --dry-run
    engine/.venv/Scripts/python scripts/generate_trading_journal.py --date 2026-05-20 \\
        --output-dir C:/Users/mattm/master-jarvis/second-brain/raw

Default output: ~/master-jarvis/second-brain/raw/_session-journal/<YYYY-MM-DD>.md
Default date: yesterday (post-close write-up pattern — running next morning
              writes the prior day's entry; running again is idempotent).
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# Force UTF-8 stdout on Windows — Discord content contains emojis and other
# multi-byte characters that cp1252 (Windows default) cannot encode.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Ensure project root is on sys.path when run as a script
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from engine.journal.builder import build_journal_entry, render_markdown, write_to_vault

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_DB_PATH = _PROJECT_ROOT / "engine" / "data" / "jarvis_trader.db"
DEFAULT_LOG_PATH = _PROJECT_ROOT / "engine" / "logs" / "jarvis_ask.log"
DEFAULT_VAULT_ROOT = Path(os.path.expanduser("~/master-jarvis/second-brain/raw"))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a daily trading journal entry and write it to the vault. "
            "Default date is yesterday (post-close write-up pattern). "
            "Running twice for the same date overwrites the file (idempotent)."
        )
    )
    parser.add_argument(
        "--date",
        metavar="YYYY-MM-DD",
        default=None,
        help="Date to generate the journal for (default: yesterday UTC).",
    )
    parser.add_argument(
        "--output-dir",
        metavar="DIR",
        default=None,
        help=(
            f"Vault root directory (default: {DEFAULT_VAULT_ROOT}). "
            "Entry is written to <DIR>/_session-journal/<date>.md."
        ),
    )
    parser.add_argument(
        "--db",
        metavar="PATH",
        default=None,
        help=f"Path to jarvis_trader.db (default: {DEFAULT_DB_PATH}).",
    )
    parser.add_argument(
        "--log-file",
        metavar="PATH",
        default=None,
        help=f"Path to jarvis_ask.log (default: {DEFAULT_LOG_PATH}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the generated journal to stdout without writing to disk.",
    )
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    # Resolve target date — default to yesterday (post-close write-up pattern)
    if args.date:
        try:
            target_date = date.fromisoformat(args.date)
        except ValueError:
            logger.error("Invalid --date %r — expected YYYY-MM-DD.", args.date)
            return 1
    else:
        target_date = (datetime.now(timezone.utc) - timedelta(days=1)).date()

    # Resolve paths
    db_path = Path(args.db) if args.db else DEFAULT_DB_PATH
    log_path = Path(args.log_file) if args.log_file else DEFAULT_LOG_PATH
    vault_root = Path(args.output_dir) if args.output_dir else DEFAULT_VAULT_ROOT

    if not db_path.exists():
        logger.error("Database not found: %s", db_path)
        return 1

    logger.info("Generating journal for %s", target_date.isoformat())
    logger.info("  DB:       %s", db_path)
    logger.info(
        "  Log:      %s",
        log_path if log_path.exists() else f"{log_path} (not found, skipped)",
    )
    logger.info("  Vault:    %s", vault_root)

    entry = build_journal_entry(
        target_date=target_date,
        db_path=str(db_path),
        log_path=str(log_path) if log_path.exists() else None,
    )

    if args.dry_run:
        print("=== DRY RUN — no file written ===\n")
        print(render_markdown(entry))
        return 0

    out_path = write_to_vault(entry, str(vault_root))
    logger.info("Journal written: %s", out_path)
    logger.info(
        "  trades=%d  daily_pnl=%s  win_rate=%s  jarvis_queries=%d",
        entry["frontmatter"]["trade_count"],
        entry["frontmatter"]["daily_pnl_usd"],
        entry["frontmatter"]["win_rate"],
        entry["jarvis_asks"].get("total_queries", 0),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
