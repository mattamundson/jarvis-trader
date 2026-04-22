import json
import logging
import os
import re
import sqlite3
from pathlib import Path
from typing import Optional

from .channel_parsers import (
    bookmark,
    bot_alerts,
    general,
    indicator_alerts,
    market_updates,
    trade_alerts,
)
from .models import Bookmark, BotSignal, CoreyAlert, CoreyCommentary, IBReport
from .storage import (
    init_tables,
    insert_bookmark,
    insert_bot_signal,
    insert_corey_alert,
    insert_corey_commentary,
    insert_ib_report,
    update_bookmark_context,
)

logger = logging.getLogger(__name__)

# Map channel IDs (from filename brackets) to parser modules and data types
CHANNEL_MAP = {
    # indicator-alerts
    "1133508659993915492": {"parser": "indicator_alerts", "type": "ib_report"},
    # proton-bot-alerts (master feed)
    "1133171126751735879": {
        "parser": "bot_alerts",
        "type": "bot_signal",
        "channel_name": "proton-bot-alerts",
    },
    # Instrument channels
    "1134346527096184914": {"parser": "bot_alerts", "type": "bot_signal", "channel_name": "es"},
    "1134346568317808710": {"parser": "bot_alerts", "type": "bot_signal", "channel_name": "nq"},
    "1134346604225241158": {"parser": "bot_alerts", "type": "bot_signal", "channel_name": "gc"},
    "1134346687519936596": {"parser": "bot_alerts", "type": "bot_signal", "channel_name": "cl"},
    "1139200691949273138": {"parser": "bot_alerts", "type": "bot_signal", "channel_name": "ym"},
    "1139199780321509416": {"parser": "bot_alerts", "type": "bot_signal", "channel_name": "rty"},
    "1134346637993594890": {"parser": "bot_alerts", "type": "bot_signal", "channel_name": "eurusd"},
    "1280340964061216843": {"parser": "bot_alerts", "type": "bot_signal", "channel_name": "btc"},
    "1134346719690240052": {"parser": "bot_alerts", "type": "bot_signal", "channel_name": "spy"},
    # trade-alerts
    "1130292150962245642": {"parser": "trade_alerts", "type": "corey_alert"},
    # market-updates
    "806343100435660801": {"parser": "market_updates", "type": "corey_commentary"},
    # general (tathedog filter ONLY)
    "741484321142997086": {"parser": "general", "type": "corey_commentary"},
    # jarvis-trader general (Matt's personal bookmark dump — X.com / GitHub / news)
    "1490851279180660819": {"parser": "bookmark", "type": "bookmark"},
}


def extract_channel_id(filename: str) -> Optional[str]:
    """Extract channel ID from filename like 'Server - Channel - name [ID].json'.

    Also handles DCE's --after suffix form: 'name [ID] (after YYYY-MM-DD).json'.
    """
    match = re.search(r"\[(\d+)\](?:\s*\([^)]*\))?\.json$", filename)
    return match.group(1) if match else None


def load_json_file(path: str) -> Optional[dict]:
    """Load and parse a Discord export JSON file."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        logger.error(f"JSON parse error in {path}: {e}")
        return None
    except Exception as e:
        logger.error(f"Error reading {path}: {e}")
        return None


def process_file(
    filepath: str,
    channel_id: str,
    channel_info: dict,
    conn: sqlite3.Connection,
    dry_run: bool = False,
) -> dict:
    """Process a single Discord export file. Returns stats dict."""
    stats = {
        "file": os.path.basename(filepath),
        "channel_id": channel_id,
        "messages_total": 0,
        "parsed": 0,
        "inserted": 0,
        "skipped": 0,
    }

    data = load_json_file(filepath)
    if not data:
        stats["error"] = "Failed to load JSON"
        return stats

    messages = data.get("messages", [])
    stats["messages_total"] = len(messages)

    parser_name = channel_info["parser"]
    data_type = channel_info["type"]
    channel_name = channel_info.get("channel_name", channel_info.get("parser", "unknown"))

    # Parse messages with appropriate parser
    if parser_name == "bot_alerts":
        parsed_list = bot_alerts.parse_channel(messages, channel_name)
    elif parser_name == "indicator_alerts":
        parsed_list = indicator_alerts.parse_channel(messages, "indicator-alerts")
    elif parser_name == "trade_alerts":
        parsed_list = trade_alerts.parse_channel(messages, "trade-alerts")
    elif parser_name == "market_updates":
        parsed_list = market_updates.parse_channel(messages, "market-updates")
    elif parser_name == "general":
        parsed_list = general.parse_channel(messages, "general")
    elif parser_name == "bookmark":
        parsed_list = bookmark.parse_channel(messages, "jarvis-trader-general")
    else:
        logger.warning(f"Unknown parser: {parser_name}")
        return stats

    stats["parsed"] = len(parsed_list)

    if dry_run:
        return stats

    # Insert into SQLite
    for item in parsed_list:
        inserted = False
        try:
            if data_type == "bot_signal":
                signal = BotSignal(**item)
                inserted = insert_bot_signal(conn, signal)
            elif data_type == "ib_report":
                report = IBReport(**item)
                inserted = insert_ib_report(conn, report)
            elif data_type == "corey_alert":
                alert = CoreyAlert(**item)
                inserted = insert_corey_alert(conn, alert)
            elif data_type == "corey_commentary":
                commentary = CoreyCommentary(**item)
                inserted = insert_corey_commentary(conn, commentary)
            elif data_type == "bookmark":
                bm = Bookmark(**item)
                inserted = insert_bookmark(conn, bm)
                # Whether new or duplicate, refresh content/author from the
                # current parse. Pre-Workstream-A rows have NULL for these;
                # edited Discord messages may have updated text. UPDATE is
                # cheap and idempotent on already-correct rows.
                if not inserted:
                    update_bookmark_context(
                        conn, bm.message_id, bm.content, bm.author_id, bm.author_name
                    )

            if inserted:
                stats["inserted"] += 1
            else:
                stats["skipped"] += 1
        except Exception as e:
            logger.error(f"Error inserting {data_type} {item.get('message_id', '?')}: {e}")
            stats["skipped"] += 1

    return stats


def run_import(
    source_dir: str, db_path: str, channel_filter: Optional[str] = None, dry_run: bool = False
) -> dict:
    """
    Main import function. Scans source_dir for .json files and imports them.

    Args:
        source_dir: Path to discord-export directory
        db_path: Path to SQLite database
        channel_filter: Optional channel ID or name to process only one channel
        dry_run: If True, parse but don't write to DB

    Returns:
        Dict with summary statistics
    """
    source_path = Path(source_dir)
    if not source_path.exists():
        raise ValueError(f"Source directory does not exist: {source_dir}")

    # Initialize tables
    if not dry_run:
        init_tables(db_path)

    json_files = list(source_path.glob("*.json"))
    logger.info(f"Found {len(json_files)} JSON files in {source_dir}")

    summary = {
        "total_files": len(json_files),
        "processed": 0,
        "skipped_unknown": 0,
        "total_messages": 0,
        "total_parsed": 0,
        "total_inserted": 0,
        "total_skipped": 0,
        "channels": [],
        "dry_run": dry_run,
    }

    conn = None
    if not dry_run:
        conn = sqlite3.connect(db_path)

    try:
        for json_file in sorted(json_files):
            channel_id = extract_channel_id(json_file.name)

            if not channel_id:
                logger.debug(f"No channel ID found in filename: {json_file.name}")
                summary["skipped_unknown"] += 1
                continue

            if channel_id not in CHANNEL_MAP:
                logger.debug(
                    f"Channel {channel_id} not in processing map, skipping: {json_file.name}"
                )
                summary["skipped_unknown"] += 1
                continue

            channel_info = CHANNEL_MAP[channel_id]

            # Apply channel filter if specified
            if channel_filter:
                if (
                    channel_id != channel_filter
                    and channel_info.get("channel_name", "") != channel_filter
                ):
                    continue

            logger.info(f"Processing: {json_file.name}")

            stats = process_file(str(json_file), channel_id, channel_info, conn, dry_run=dry_run)

            summary["processed"] += 1
            summary["total_messages"] += stats.get("messages_total", 0)
            summary["total_parsed"] += stats.get("parsed", 0)
            summary["total_inserted"] += stats.get("inserted", 0)
            summary["total_skipped"] += stats.get("skipped", 0)
            summary["channels"].append(stats)

            logger.info(
                f"  -> {stats.get('messages_total', 0)} messages, "
                f"{stats.get('parsed', 0)} parsed, "
                f"{stats.get('inserted', 0)} inserted"
            )

        if conn and not dry_run:
            conn.commit()

    finally:
        if conn:
            conn.close()

    logger.info(
        f"\nImport {'(DRY RUN) ' if dry_run else ''}complete: "
        f"{summary['processed']} files, "
        f"{summary['total_messages']} messages, "
        f"{summary['total_parsed']} parsed, "
        f"{summary['total_inserted']} inserted"
    )

    return summary
