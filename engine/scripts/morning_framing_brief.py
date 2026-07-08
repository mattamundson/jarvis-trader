"""
Automated morning framing brief for JARVIS TRADER.

Unattended, scheduled equivalent of the `.claude/skills/market-framing-brief`
Claude Code skill: generates a Corey-style Auction Market Theory brief for
ES/NQ every weekday morning, with no Claude Code session involved at runtime.

Pipeline (mirrors SKILL.md's Steps 0.5 -> 1a -> 2c -> 3 -> 4):
  1. framing_context.assemble_context() — Corey bias (today + yesterday) +
     engine/DB levels + system overlay, in one JSON context object.
  2. framing_synthesis.generate_framing_brief() — the one new LLM call that
     turns that context into the 7-section markdown brief.
  3. render_and_dispatch() — write the full brief to disk (feeds the dashboard
     router) and post it, chunked, to Discord.

Usage
-----
    python -m engine.scripts.morning_framing_brief               # today, live post
    python -m engine.scripts.morning_framing_brief --date 2026-07-08
    python -m engine.scripts.morning_framing_brief --dry-run      # generate + save, never post
    python -m engine.scripts.morning_framing_brief --no-discord   # save only, skip Discord
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
# Keep httpx/httpcore quiet: their INFO "HTTP Request: POST <url>" line logs the
# full Discord webhook URL (a secret) into stdout and the scheduled-task log.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger("morning_framing_brief")

# ---------------------------------------------------------------------------
# Path bootstrap — same pattern as daily_morning_briefing.py
# ---------------------------------------------------------------------------

_SCRIPTS_DIR = Path(__file__).resolve().parent
_ENGINE_DIR = _SCRIPTS_DIR.parent
if str(_ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(_ENGINE_DIR))

# SKILL.md's stated clock is CT (America/Chicago), not ET — Step 0 in the skill
# is explicit that the trader's clock is CT, so the automated path uses the
# same zone rather than daily_morning_briefing.py's ET.
_CT = ZoneInfo("America/Chicago")

_BRIEF_DIR = _ENGINE_DIR / "data" / "framing_briefs"

_DISCORD_CHUNK_LIMIT = 2000


# ---------------------------------------------------------------------------
# Discord chunking + posting
# ---------------------------------------------------------------------------


def chunk_for_discord(markdown: str, limit: int = _DISCORD_CHUNK_LIMIT) -> list[str]:
    """Split markdown into <=limit-char chunks on paragraph (blank-line)
    boundaries, never splitting a block mid-sentence. Matches Corey's own
    posting cadence in the source channel — his real briefs already arrive as
    several Discord messages because even he hits the 2000-char limit.

    Falls back to a hard character split only for a single block that itself
    exceeds the limit (rare — a long Structural Levels table, say).
    """
    blocks = markdown.split("\n\n")
    chunks: list[str] = []
    current = ""
    for block in blocks:
        candidate = f"{current}\n\n{block}" if current else block
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            chunks.append(current)
            current = ""
        if len(block) <= limit:
            current = block
        else:
            # Single oversized block — hard-split as a last resort.
            for i in range(0, len(block), limit):
                chunks.append(block[i : i + limit])
    if current:
        chunks.append(current)
    return chunks


async def post_chunks_to_discord(chunks: list[str]) -> bool:
    """POST each chunk in order to DISCORD_WEBHOOK_URL. Returns True only if
    every chunk posted successfully. Read fresh at call time (not at import)
    so a lazily-loaded .env is honored, matching daily_morning_briefing.py."""
    try:
        import httpx  # type: ignore[import-untyped]
    except ImportError:
        logger.warning("httpx not available — Discord post skipped")
        return False

    webhook_url = (os.getenv("DISCORD_WEBHOOK_URL") or "").strip()
    if not webhook_url:
        logger.info("DISCORD_WEBHOOK_URL not set — Discord post skipped")
        return False

    ok = True
    async with httpx.AsyncClient(timeout=10.0) as client:
        for i, chunk in enumerate(chunks, start=1):
            try:
                resp = await client.post(
                    webhook_url,
                    json={"content": chunk, "username": "JARVIS"},
                )
                if resp.status_code not in (200, 204):
                    logger.warning(
                        "Discord webhook chunk %d/%d returned %s: %s",
                        i,
                        len(chunks),
                        resp.status_code,
                        resp.text,
                    )
                    ok = False
            except Exception as exc:
                logger.warning("Discord webhook chunk %d/%d failed: %s", i, len(chunks), exc)
                ok = False
    return ok


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
    """Write the full brief to engine/data/framing_briefs/{date}.md (the same
    directory engine/routers/framing_brief_router.py serves) and, unless
    dry_run/no_discord, post it chunked to Discord. One generation, two
    surfaces — not a choice between them."""
    _BRIEF_DIR.mkdir(parents=True, exist_ok=True)
    report_path = _BRIEF_DIR / f"{briefing_date.isoformat()}.md"
    report_path.write_text(markdown, encoding="utf-8")
    logger.info("Framing brief saved -> %s", report_path)

    if dry_run:
        logger.info("--dry-run: skipping Discord post")
        return report_path
    if no_discord:
        logger.info("--no-discord: skipping Discord post")
        return report_path

    chunks = chunk_for_discord(markdown)
    ok = asyncio.run(post_chunks_to_discord(chunks))
    if ok:
        logger.info("Framing brief posted to Discord (%d message(s))", len(chunks))
    else:
        logger.warning("Framing brief Discord post incomplete or failed — see warnings above")
    return report_path


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def _run(target_date: date) -> dict[str, Any]:
    from analysis.framing_context import assemble_context
    from analysis.framing_synthesis import generate_framing_brief
    from discord.commentary_processor import build_default_llm_client

    llm_client = build_default_llm_client()
    context = await assemble_context(target_date, llm_client=llm_client)
    brief = await generate_framing_brief(context.to_dict(), llm_client=llm_client)
    return {"context": context, "brief": brief}


def main() -> None:
    parser = argparse.ArgumentParser(description="JARVIS automated morning framing brief")
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
            "Cannot generate a framing brief for a future date (%s > %s).",
            briefing_date,
            today_ct,
        )
        sys.exit(1)

    # Ensure ANTHROPIC_API_KEY is loaded from engine/.env when not already in
    # the environment (the scheduled task may or may not pre-load secrets).
    if not os.getenv("ANTHROPIC_API_KEY"):
        try:
            from dotenv import load_dotenv

            load_dotenv(_ENGINE_DIR / ".env", override=False)
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug(".env load skipped: %s", exc)

    logger.info("Generating morning framing brief for %s (CT)", briefing_date)

    result = asyncio.run(_run(briefing_date))
    context = result["context"]
    brief = result["brief"]

    report_path = render_and_dispatch(
        brief["markdown"],
        briefing_date,
        dry_run=args.dry_run,
        no_discord=args.no_discord,
    )

    # Print headline to stdout for the scheduled-task log.
    print(
        f"[FRAMING BRIEF] {briefing_date} | confidence={context.confidence_tier} | "
        f"data_quality={brief['data_quality']} | model={brief['model_used']} | "
        f"report={report_path.name}"
    )

    if brief["data_quality"] != "ok":
        # Non-zero exit so Task Scheduler / the loop wrapper shows red — a
        # degraded/failed brief must not look like a silent success.
        sys.exit(2)


if __name__ == "__main__":
    main()
