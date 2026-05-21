"""CLI entry point for the Hermes self-improvement pipeline.

Runs Phase 1 (scanner + classifier) + Phase 2 (backlog generator) end-to-end:

    python -m engine.discord.hermes_upgrade --limit 50

Reads `discord_bookmarks` + `discord_analyses` from the configured sqlite db,
filters via heuristic scanner, sends survivors through the LLM classifier,
tiers each result, then writes a fresh `~/.hermes/upgrade/backlog.md` (+ a
JSONL sidecar). Re-runs preserve apply_status from the prior JSONL unless
``--no-merge`` is passed.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from collections import Counter
from pathlib import Path

# Windows cp1252 stdout crashes on Unicode chars like → (U+2192) found in
# soul_template entries. Force UTF-8 before any print() runs.
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

# Load engine/.env so ANTHROPIC_API_KEY is available when this CLI is run
# standalone (no engine process to inherit env from). Mirrors the pattern in
# engine/discord/mcp_server.py.
try:
    from dotenv import load_dotenv  # type: ignore

    _ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
    if _ENV_PATH.exists():
        load_dotenv(_ENV_PATH)
except ImportError:
    pass

from .backlog import (
    assign_tier,
    default_backlog_dir,
    hydrate_entry,
    merge_with_existing,
    write_backlog,
)
from .classifier import classify_batch
from .scanner import scan_for_candidates

logger = logging.getLogger(__name__)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="python -m engine.discord.hermes_upgrade",
        description="Scan + classify Discord bookmarks into a tiered Hermes upgrade backlog.",
    )
    p.add_argument("--db", default="engine/data/jarvis_trader.db")
    p.add_argument(
        "--channel-id",
        default="1490851279180660819",
        help="Discord channel id to scan (defaults to the futures bookmarks channel).",
    )
    p.add_argument(
        "--min-score",
        type=float,
        default=0.25,
        help="Scanner heuristic threshold (0.0-1.0).",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Cap candidate count before classification (useful for testing).",
    )
    p.add_argument(
        "--out-dir",
        type=str,
        default=None,
        help="Output directory. Defaults to ~/.hermes/upgrade.",
    )
    p.add_argument(
        "--concurrency",
        type=int,
        default=5,
        help="Max concurrent LLM calls in the classifier.",
    )
    p.add_argument(
        "--no-merge",
        action="store_true",
        help="Do NOT preserve apply_status from the existing JSONL (full reset).",
    )
    p.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="DEBUG-level logging.",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    print(f"Scanning {args.db} ...")
    candidates = scan_for_candidates(
        args.db,
        channel_id=args.channel_id,
        min_score=args.min_score,
        limit=args.limit,
    )
    print(f"  {len(candidates)} candidates above score {args.min_score}")

    if not candidates:
        print("No candidates. Exiting.")
        return 0

    print(
        f"Classifying {len(candidates)} candidates via LLM " f"(concurrency={args.concurrency}) ..."
    )
    classified = asyncio.run(classify_batch(candidates, concurrency=args.concurrency))
    applicable_count = sum(1 for c in classified if c.applicable)
    print(f"  {applicable_count} applicable / {len(classified)} classified")

    # Hydrate each classification into a BacklogEntry and assign tier.
    entries = []
    for cls in classified:
        be = hydrate_entry(cls, args.db, channel_id=args.channel_id)
        be.tier = assign_tier(cls)
        entries.append(be)

    out_dir = Path(args.out_dir) if args.out_dir else default_backlog_dir()
    jsonl_path = out_dir / "backlog.jsonl"
    if not args.no_merge and jsonl_path.exists():
        entries = merge_with_existing(entries, jsonl_path)

    md_path, jsonl_path = write_backlog(entries, out_dir=out_dir)
    print(f"Wrote {md_path}")
    print(f"Wrote {jsonl_path}")

    tally = Counter(e.tier for e in entries)
    print(
        f"Tier 1: {tally['tier_1']}  "
        f"Tier 2: {tally['tier_2']}  "
        f"Tier 3: {tally['tier_3']}  "
        f"Deferred: {tally['defer']}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
