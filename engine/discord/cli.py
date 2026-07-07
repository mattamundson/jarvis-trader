"""
Discord data import CLI for JARVIS Trader.

Usage:
    python -m engine.discord.cli --source "C:\\Users\\mattm\\discord-export" --db "data/jarvis_trader.db"
    python -m engine.discord.cli --source "C:\\Users\\mattm\\discord-export" --dry-run
    python -m engine.discord.cli --source "C:\\Users\\mattm\\discord-export" --channel 1134346527096184914
"""

import argparse
import logging
import sys
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

logger = logging.getLogger("engine.discord.cli")


def main():
    parser = argparse.ArgumentParser(
        description="Import Discord export JSON files into JARVIS SQLite database",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--source",
        default=r"C:\Users\mattm\discord-export",
        help="Path to discord-export directory (default: C:\\Users\\mattm\\discord-export)",
    )
    parser.add_argument(
        "--db",
        default="data/jarvis_trader.db",
        help="Path to SQLite database (default: data/jarvis_trader.db)",
    )
    parser.add_argument(
        "--channel", default=None, help="Process only this channel ID or name (for testing)"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Parse and print stats without writing to DB"
    )
    parser.add_argument(
        "--stats-only",
        action="store_true",
        help="Show stats from existing DB and exit (requires --db)",
    )
    parser.add_argument(
        "--trigger-commentary",
        action="store_true",
        help="After import, fire CoreyCommentaryProcessor to refresh today's session bias (skipped if 0 new rows inserted)",
    )

    args = parser.parse_args()

    if args.stats_only:
        from .storage import get_stats

        stats = get_stats(args.db)
        print("\n=== Discord Import Stats ===")
        for table, data in stats.items():
            if isinstance(data, dict) and "count" in data:
                print(f"\n{table}:")
                print(f"  Count: {data['count']}")
                print(f"  Range: {data['earliest']} -> {data['latest']}")
        if "bot_signals_by_symbol" in stats:
            print("\nBot Signals by Symbol:")
            for sym, count in stats["bot_signals_by_symbol"].items():
                print(f"  {sym}: {count}")
        return 0

    # Validate source directory
    source_path = Path(args.source)
    if not source_path.exists():
        logger.error(f"Source directory not found: {args.source}")
        return 1

    # Import
    from .parser import run_import

    logger.info("Starting Discord import")
    logger.info(f"  Source: {args.source}")
    logger.info(f"  DB: {args.db}")
    if args.dry_run:
        logger.info("  Mode: DRY RUN (no writes)")
    if args.channel:
        logger.info(f"  Channel filter: {args.channel}")

    try:
        summary = run_import(
            source_dir=args.source,
            db_path=args.db,
            channel_filter=args.channel,
            dry_run=args.dry_run,
        )

        print("\n=== Import Summary ===")
        print(f"Files found:   {summary['total_files']}")
        print(f"Files processed: {summary['processed']}")
        print(f"Files skipped (not in map): {summary['skipped_unknown']}")
        print(f"Total messages: {summary['total_messages']:,}")
        print(f"Total parsed:  {summary['total_parsed']:,}")
        if not args.dry_run:
            print(f"Total inserted: {summary['total_inserted']:,}")
            print(f"Total skipped (duplicates): {summary['total_skipped']:,}")

        print("\n=== Per-Channel Breakdown ===")
        for ch in summary["channels"]:
            name = ch.get("file", "?")
            print(
                f"  {name.encode(sys.stdout.encoding or 'utf-8', errors='replace').decode(sys.stdout.encoding or 'utf-8')}"
            )
            print(
                f"    Messages: {ch.get('messages_total', 0):,} | Parsed: {ch.get('parsed', 0):,}",
                end="",
            )
            if not args.dry_run:
                print(f" | Inserted: {ch.get('inserted', 0):,}", end="")
            print()

        # Commentary trigger — skipped in dry-run, skipped if 0 new rows
        if args.trigger_commentary and not args.dry_run:
            inserted = summary.get("total_inserted", 0)
            if inserted > 0:
                import asyncio
                from datetime import date

                from .commentary_processor import (
                    CoreyCommentaryProcessor,
                    build_default_llm_client,
                )

                # Load engine/.env so the Vertex/Gemini/OpenAI failover config is
                # present when building the LLM client. The CLI doesn't otherwise
                # load it; without it the standalone refresh falls back to the
                # raw direct-Anthropic POST (dead credit since 2026-06-29) and
                # every daily bias write degrades to data_quality='none'.
                try:
                    from dotenv import load_dotenv

                    load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)
                except Exception:
                    pass

                logger.info("Triggering commentary processor (%d new rows)...", inserted)
                processor = CoreyCommentaryProcessor(
                    db_path=args.db,
                    llm_client=build_default_llm_client(args.db),
                )
                processor.invalidate_cache(date.today())
                bias = asyncio.run(processor.get_session_bias())
                logger.info(
                    "Commentary processor complete — bias=%s conviction=%.2f quality=%s",
                    bias.directional_bias,
                    bias.conviction,
                    bias.data_quality,
                )
                if bias.data_quality == "none":
                    logger.warning(
                        "Commentary processor returned no-data result; check ANTHROPIC_API_KEY and DB."
                    )
            else:
                logger.info("Skipping commentary processor — 0 new rows inserted.")

        return 0

    except Exception as e:
        logger.error(f"Import failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
