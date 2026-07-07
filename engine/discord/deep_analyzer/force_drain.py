"""Force-drain: backfill attachment_urls from a fresh DCE export and re-process.

Aggressively re-ingests a Discord channel from a freshly-exported
DiscordChatExporter (DCE) JSON file:

1. **Backfill**: for each message present in the DCE export and the DB, populate
   `attachment_urls` where the DB column is NULL but DCE shows attachments.
2. **Mark for re-analysis**: any row whose attachments were newly populated AND
   whose prior `analysis.artifact_type` was 'text' or 'url' (i.e. the original
   analysis missed the attachment) is re-queued by clearing `analyzed_at` and
   `analysis_id`.
3. **Drain**: invoke `runner.run_once` in a loop with a high batch size
   (default 50) until queue empties or `--max-passes` cap reached. Bypasses the
   every-2-min cron cadence; respects `DEEP_ANALYZER_DAILY_USD`.

Reuses `runner.run_once` end-to-end — no duplicated analyze/persist logic.

Invocation:
    python -m engine.discord.deep_analyzer.force_drain \
        --export engine/data/discord-export/1490851279180660819.json \
        --channel-id 1490851279180660819 \
        --batch-size 50 --max-passes 50

    # Preview only (no DB mutation, no analyses dispatched)
    python -m engine.discord.deep_analyzer.force_drain \
        --export engine/data/discord-export/1490851279180660819.json \
        --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import runner, storage

logger = logging.getLogger(__name__)

DEFAULT_CHANNEL_ID = "1490851279180660819"
DEFAULT_BATCH_SIZE = 50
DEFAULT_MAX_PASSES = 50

# Artifact types whose original analysis would have missed a newly-discovered
# attachment. If the original analysis was image/audio/document the attachment
# was already considered, so re-analysis would not produce new signal.
_RETRYABLE_PRIOR_ARTIFACT_TYPES = ("text", "url")


def _engine_root() -> Path:
    """Resolve engine/ root from this file: engine/discord/deep_analyzer/force_drain.py."""
    return Path(__file__).resolve().parents[2]


def _default_db_path() -> Path:
    return _engine_root() / "data" / "jarvis_trader.db"


def _default_vault_root() -> Path:
    # Mirror runner's vault target — Discord-Feed/<date> pages must land in the
    # SAME Obsidian vault as URL/text analyses so the channel is searchable
    # as one corpus. runner.py / vault.py default to ~/my-vault; match that.
    # Override via DEEP_ANALYZER_VAULT_ROOT only if you want a separate sink.
    override = os.getenv("DEEP_ANALYZER_VAULT_ROOT")
    if override:
        return Path(override)
    return Path(os.path.expanduser("~/my-vault"))


def _default_log_path() -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log_dir = _engine_root() / "logs" / "deep_analyzer"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / f"force-drain-{ts}.log"


def _extract_attachment_urls(msg: dict[str, Any]) -> str | None:
    """Return space-joined attachment URLs (capped 4000 chars), mirroring bookmark parser."""
    attachments = msg.get("attachments") or []
    urls = [a.get("url") for a in attachments if isinstance(a, dict) and a.get("url")]
    if not urls:
        return None
    return " ".join(urls)[:4000]


def _load_dce_messages(export_path: Path) -> list[dict[str, Any]]:
    """Load the DCE JSON file and return the messages list.

    DCE JSON shape: {"guild": {...}, "channel": {...}, "messages": [...]}.
    Returns [] gracefully if the file is malformed or missing the key.
    """
    try:
        with export_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        logger.error("force_drain: failed to load %s: %s", export_path, exc)
        return []
    messages = data.get("messages")
    if not isinstance(messages, list):
        logger.error("force_drain: %s has no 'messages' list", export_path)
        return []
    return messages


def _existing_message_ids(conn: sqlite3.Connection, channel_id: str) -> dict[str, str | None]:
    """Map message_id -> current attachment_urls value (None if NULL) for the channel."""
    rows = conn.execute(
        "SELECT message_id, attachment_urls FROM discord_bookmarks WHERE channel_id = ?",
        (channel_id,),
    ).fetchall()
    return {r[0]: r[1] for r in rows}


def backfill_attachment_urls(
    db_path: Path | str,
    export_path: Path,
    channel_id: str,
    *,
    dry_run: bool = False,
) -> dict[str, list[str]]:
    """Backfill `attachment_urls` from the DCE export for rows where it is NULL.

    Returns {"updated": [msg_ids], "skipped_already_set": [...], "missing_in_db": [...]}.
    In dry-run mode performs no writes.
    """
    messages = _load_dce_messages(export_path)
    updated: list[str] = []
    skipped: list[str] = []
    missing: list[str] = []

    if not messages:
        return {"updated": [], "skipped_already_set": [], "missing_in_db": []}

    conn = sqlite3.connect(db_path)
    try:
        existing = _existing_message_ids(conn, channel_id)
        for msg in messages:
            msg_id = str(msg.get("id", ""))
            if not msg_id:
                continue
            new_urls = _extract_attachment_urls(msg)
            if not new_urls:
                continue
            if msg_id not in existing:
                missing.append(msg_id)
                continue
            current = existing[msg_id]
            if current:
                skipped.append(msg_id)
                continue
            if not dry_run:
                conn.execute(
                    "UPDATE discord_bookmarks SET attachment_urls = ? WHERE message_id = ?",
                    (new_urls, msg_id),
                )
            updated.append(msg_id)
        if not dry_run:
            conn.commit()
    finally:
        conn.close()

    return {
        "updated": updated,
        "skipped_already_set": skipped,
        "missing_in_db": missing,
    }


def mark_for_reanalysis(
    db_path: Path | str,
    message_ids: list[str],
    *,
    dry_run: bool = False,
) -> list[str]:
    """Clear analyzed_at + analysis_id for rows whose prior analysis was text/url.

    Returns the list of message_ids that were actually re-queued (a subset of
    `message_ids` — rows whose prior artifact_type was already image/audio/
    document are left alone).
    """
    if not message_ids:
        return []
    placeholders = ",".join("?" * len(message_ids))
    conn = sqlite3.connect(db_path)
    try:
        # Identify rows whose prior analysis was text/url (or no analysis yet).
        # We re-queue both: rows that were never analyzed AND newly have an
        # attachment, and rows analyzed-as-text/url whose attachment was missed.
        candidates = conn.execute(
            f"""
            SELECT b.message_id, a.artifact_type
              FROM discord_bookmarks b
              LEFT JOIN discord_analyses a ON a.id = b.analysis_id
             WHERE b.message_id IN ({placeholders})
               AND b.attachment_urls IS NOT NULL
            """,
            message_ids,
        ).fetchall()

        retryable = [
            mid
            for (mid, prior_type) in candidates
            if prior_type is None or prior_type in _RETRYABLE_PRIOR_ARTIFACT_TYPES
        ]
        if not retryable or dry_run:
            return retryable

        retryable_placeholders = ",".join("?" * len(retryable))
        conn.execute(
            f"UPDATE discord_bookmarks SET analyzed_at = NULL, analysis_id = NULL, "
            f"claimed_at = NULL WHERE message_id IN ({retryable_placeholders})",
            retryable,
        )
        conn.commit()
        return retryable
    finally:
        conn.close()


def _queued_count_for_channel(db_path: Path | str, channel_id: str) -> int:
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM discord_bookmarks "
            "WHERE channel_id = ? AND analyzed_at IS NULL",
            (channel_id,),
        ).fetchone()
        return int(row[0])
    finally:
        conn.close()


def _budget_remaining_usd(db_path: Path | str) -> float:
    cap = float(os.getenv("DEEP_ANALYZER_DAILY_USD", "2.00"))
    return cap - storage.daily_cost_usd(db_path)


async def drain(
    *,
    db_path: Path | str,
    vault_root: Path,
    channel_id: str,
    batch_size: int = DEFAULT_BATCH_SIZE,
    max_passes: int = DEFAULT_MAX_PASSES,
) -> dict[str, Any]:
    """Loop runner.run_once until the channel queue is empty or caps hit.

    Returns {"passes": N, "processed": N, "halted_reason": str}.
    """
    storage.migrate(db_path)
    processed_total = 0
    halted_reason = "queue_empty"

    for pass_idx in range(1, max_passes + 1):
        if _budget_remaining_usd(db_path) <= 0:
            halted_reason = "budget_exceeded"
            logger.warning("force_drain: daily budget exceeded — halting at pass %d", pass_idx)
            break

        queued = _queued_count_for_channel(db_path, channel_id)
        if queued == 0:
            logger.info("force_drain: channel queue empty at pass %d", pass_idx)
            break

        logger.info(
            "force_drain: pass %d/%d — %d queued for channel %s",
            pass_idx,
            max_passes,
            queued,
            channel_id,
        )
        written = await runner.run_once(db_path=db_path, vault_root=vault_root, limit=batch_size)
        processed_total += written
        if written == 0:
            # No progress — likely all remaining rows are claimed by another
            # process or budget tripped inside runner. Stop to avoid spin.
            halted_reason = "no_progress"
            logger.warning("force_drain: zero written on pass %d — halting", pass_idx)
            break
    else:
        halted_reason = "max_passes_hit"

    return {
        "passes": pass_idx,
        "processed": processed_total,
        "halted_reason": halted_reason,
    }


def _configure_file_logging(log_path: Path) -> None:
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setLevel(logging.INFO)
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    logging.getLogger().addHandler(fh)
    logging.getLogger().setLevel(logging.INFO)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Force-drain Discord channel — re-ingest attachments + drain queue.",
    )
    parser.add_argument(
        "--export",
        type=Path,
        required=True,
        help="Path to fresh DCE JSON export for the target channel.",
    )
    parser.add_argument(
        "--channel-id",
        default=DEFAULT_CHANNEL_ID,
        help=f"Target Discord channel ID (default: {DEFAULT_CHANNEL_ID})",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"Rows per runner.run_once pass (default: {DEFAULT_BATCH_SIZE})",
    )
    parser.add_argument(
        "--max-passes",
        type=int,
        default=DEFAULT_MAX_PASSES,
        help=f"Hard cap on drain loop iterations (default: {DEFAULT_MAX_PASSES})",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=None,
        help="Path to SQLite DB (default: engine/data/jarvis_trader.db)",
    )
    parser.add_argument(
        "--vault-root",
        type=Path,
        default=None,
        help="Vault root for analysis pages (default: engine/data/discord-vault)",
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        default=None,
        help="Log destination (default: engine/logs/deep_analyzer/force-drain-<ts>.log)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview which rows would be backfilled / re-queued; no DB writes, no analyses.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    log_path = args.log_file or _default_log_path()
    _configure_file_logging(log_path)

    db_path = args.db or _default_db_path()
    vault_root = args.vault_root or _default_vault_root()
    export_path = args.export

    if not export_path.exists():
        logger.error("force_drain: export file not found: %s", export_path)
        return 2
    if not db_path.exists():
        logger.error("force_drain: database not found: %s", db_path)
        return 2

    started = time.time()
    cost_before = storage.daily_cost_usd(db_path) if not args.dry_run else 0.0

    logger.info(
        "force_drain: start — export=%s db=%s channel=%s dry_run=%s log=%s",
        export_path,
        db_path,
        args.channel_id,
        args.dry_run,
        log_path,
    )

    # Step 1 — backfill attachment_urls from the fresh export.
    backfill = backfill_attachment_urls(
        db_path,
        export_path,
        args.channel_id,
        dry_run=args.dry_run,
    )
    logger.info(
        "force_drain: backfill — updated=%d skipped_already_set=%d missing_in_db=%d",
        len(backfill["updated"]),
        len(backfill["skipped_already_set"]),
        len(backfill["missing_in_db"]),
    )

    # Step 2 — mark newly-attachmented rows for re-analysis (only if prior was text/url).
    requeued = mark_for_reanalysis(
        db_path,
        backfill["updated"],
        dry_run=args.dry_run,
    )
    logger.info("force_drain: requeued %d rows for re-analysis", len(requeued))

    drain_stats: dict[str, Any] = {
        "passes": 0,
        "processed": 0,
        "halted_reason": "dry_run" if args.dry_run else "not_started",
    }

    if args.dry_run:
        logger.info("force_drain: dry-run — skipping drain phase")
    else:
        # Step 3 — drain.
        drain_stats = asyncio.run(
            drain(
                db_path=db_path,
                vault_root=vault_root,
                channel_id=args.channel_id,
                batch_size=args.batch_size,
                max_passes=args.max_passes,
            )
        )

    elapsed = time.time() - started
    cost_after = storage.daily_cost_usd(db_path) if not args.dry_run else 0.0

    summary = {
        "backfilled": len(backfill["updated"]),
        "requeued": len(requeued),
        "processed": drain_stats["processed"],
        "passes": drain_stats["passes"],
        "halted_reason": drain_stats["halted_reason"],
        "cost_usd_delta": round(cost_after - cost_before, 6),
        "elapsed_seconds": round(elapsed, 2),
        "log_file": str(log_path),
    }
    logger.info("force_drain: summary %s", summary)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover — entry point
    sys.exit(main())
