"""
Automated pre-close framing brief for JARVIS TRADER.

Same-day companion to morning_framing_brief.py (this is a sibling script, not
a --session flag on it, to keep that script's diff at zero — see
.claude/skills/market-close-brief/SKILL.md). Runs roughly 1 hour before the
CME RTH close and produces a Corey-style "Acceptance vs Rejection at the
Close" read for ES/NQ, reconciled against today's morning framing brief.

Pipeline (mirrors market-close-brief/SKILL.md's Steps 0 -> 1 -> 2 -> 3):
  1. framing_context.assemble_context(session="preclose") — today's realized
     intraday snapshot + Corey's pre-close commentary, plus the same-day
     morning-brief reference frame (corey_today / engine_levels).
  2. framing_synthesis.generate_framing_brief(session="preclose") — the LLM
     call that turns that context into the pre-close markdown brief.
  3. render_and_dispatch() — write to disk (feeds the dashboard router, under
     a `-preclose` filename suffix so it never collides with the AM brief)
     and post it, chunked, to Discord — reusing morning_framing_brief.py's
     chunk_for_discord()/post_chunks_to_discord() rather than duplicating them.

Usage
-----
    python -m engine.scripts.preclose_framing_brief               # today, live post
    python -m engine.scripts.preclose_framing_brief --date 2026-07-08
    python -m engine.scripts.preclose_framing_brief --dry-run      # generate + save, never post
    python -m engine.scripts.preclose_framing_brief --no-discord   # save only, skip Discord
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger("preclose_framing_brief")

# ---------------------------------------------------------------------------
# Path bootstrap — same pattern as morning_framing_brief.py
# ---------------------------------------------------------------------------

_SCRIPTS_DIR = Path(__file__).resolve().parent
_ENGINE_DIR = _SCRIPTS_DIR.parent
if str(_ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(_ENGINE_DIR))

# Same CT clock discipline as morning_framing_brief.py / market-close-brief/SKILL.md.
_CT = ZoneInfo("America/Chicago")

_BRIEF_DIR = _ENGINE_DIR / "data" / "framing_briefs"


# ---------------------------------------------------------------------------
# Output — write to disk (feeds the dashboard router) + dispatch to Discord
# ---------------------------------------------------------------------------


def render_and_dispatch(
    markdown: str,
    briefing_date: date,
    *,
    dry_run: bool,
    no_discord: bool,
) -> Path:
    """Write to engine/data/framing_briefs/{date}-preclose.md — the `-preclose`
    suffix means the router's AM-only glob (exactly `????-??-??.md`) can never
    match this file, so the existing /framing-brief/latest route needs zero
    changes to keep serving AM-only results. Unless dry_run/no_discord, post
    chunked to the same Discord webhook as the AM brief (reusing
    morning_framing_brief.py's helpers, not duplicating them)."""
    from scripts.morning_framing_brief import chunk_for_discord, post_chunks_to_discord

    _BRIEF_DIR.mkdir(parents=True, exist_ok=True)
    report_path = _BRIEF_DIR / f"{briefing_date.isoformat()}-preclose.md"
    report_path.write_text(markdown, encoding="utf-8")
    logger.info("Pre-close framing brief saved -> %s", report_path)

    if dry_run:
        logger.info("--dry-run: skipping Discord post")
        return report_path
    if no_discord:
        logger.info("--no-discord: skipping Discord post")
        return report_path

    chunks = chunk_for_discord(markdown)
    ok = asyncio.run(post_chunks_to_discord(chunks))
    if ok:
        logger.info("Pre-close framing brief posted to Discord (%d message(s))", len(chunks))
    else:
        logger.warning("Pre-close framing brief Discord post incomplete or failed — see warnings above")
    return report_path


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def _run(target_date: date) -> dict[str, Any]:
    from analysis.framing_context import assemble_context
    from analysis.framing_synthesis import generate_framing_brief
    from discord.commentary_processor import build_default_llm_client

    llm_client = build_default_llm_client()
    context = await assemble_context(target_date, session="preclose", llm_client=llm_client)
    brief = await generate_framing_brief(context.to_dict(), llm_client=llm_client, session="preclose")
    return {"context": context, "brief": brief}


def main() -> None:
    parser = argparse.ArgumentParser(description="JARVIS automated pre-close framing brief")
    parser.add_argument(
        "--date",
        default=None,
        help="Target session date YYYY-MM-DD (default: today CT)",
    )
    parser.add_argument(
        "--no-discord",
        action="store_true",
        help="Generate and save, but skip the Discord post",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate and save only — never posts to Discord. Use during the "
        "rollout gating period before trusting live auto-post.",
    )
    args = parser.parse_args()

    if args.date:
        try:
            briefing_date = date.fromisoformat(args.date)
        except ValueError:
            logger.error("Invalid --date '%s'. Use YYYY-MM-DD.", args.date)
            sys.exit(1)
    else:
        briefing_date = datetime.now(_CT).date()

    today_ct = datetime.now(_CT).date()
    if briefing_date > today_ct:
        logger.error(
            "Cannot generate a pre-close framing brief for a future date (%s > %s).",
            briefing_date,
            today_ct,
        )
        sys.exit(1)

    if not os.getenv("ANTHROPIC_API_KEY"):
        try:
            from dotenv import load_dotenv

            load_dotenv(_ENGINE_DIR / ".env", override=False)
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug(".env load skipped: %s", exc)

    logger.info("Generating pre-close framing brief for %s (CT)", briefing_date)

    result = asyncio.run(_run(briefing_date))
    context = result["context"]
    brief = result["brief"]

    report_path = render_and_dispatch(
        brief["markdown"],
        briefing_date,
        dry_run=args.dry_run,
        no_discord=args.no_discord,
    )

    print(
        f"[PRECLOSE FRAMING BRIEF] {briefing_date} | confidence={context.confidence_tier} | "
        f"data_quality={brief['data_quality']} | model={brief['model_used']} | "
        f"report={report_path.name}"
    )

    if brief["data_quality"] != "ok":
        sys.exit(2)


if __name__ == "__main__":
    main()
