"""Overnight Claude-over-vault synthesis jobs.

Two automations adapted from DamiDefi's "9 Things My Obsidian Vault Does While
I Sleep":

  * run_synthesis_brief    — the 6am daily brief (#1): synthesise, don't summarise.
  * run_contradiction_check — the 7am conflict scan (#5): 02-Theses vs 01-Sources.

The LLM client is injected (any object with an async ``call(...)`` returning an
object exposing ``.success`` and ``.content``) so the jobs are unit-testable
without network access. Neither job touches the order path — they read notes,
call Claude, and write a markdown note back into 00-Inbox.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from . import paths

logger = logging.getLogger(__name__)

# Default model tiers. Synthesis/contradiction benefit from Sonnet-class
# reasoning; callers can override. Kept as plain strings (not config imports)
# so this module stays free of the safety-tagged config surface.
DEFAULT_SYNTHESIS_MODEL = "claude-sonnet-4-6"

_SYNTHESIS_SYSTEM = (
    "You are reading an Obsidian vault belonging to a futures/options trader. "
    "Synthesise, do not summarise. The trader already knows what each note says; "
    "your value is finding what they would not find by re-reading notes in isolation."
)

_SYNTHESIS_PROMPT = (
    "Read these vault notes from the last {days} days. Produce exactly four sections "
    "in markdown:\n\n"
    "## Connections\n"
    "Two non-obvious links between separately captured notes. Name both notes. "
    "If a connection is obvious it does not qualify.\n\n"
    "## Pattern\n"
    "One theme appearing across three or more notes, in one sentence.\n\n"
    "## Contradiction\n"
    "Two notes whose positions conflict. Quote both.\n\n"
    "## Best capture\n"
    "The single note most worth developing further, and why.\n\n"
    "Do not summarise. Synthesise.\n\n"
    "{notes}"
)

_CONTRADICTION_SYSTEM = (
    "You are an adversarial reviewer of a trader's documented positions. "
    "Your only job is to find conflict between what they believe and the evidence "
    "they have captured. Do not validate. Do not look for agreement."
)

_CONTRADICTION_PROMPT = (
    "Here are my current thesis notes from 02-Theses:\n\n{theses}\n\n"
    "Here are source notes I captured in the last {days} days from 01-Sources:\n\n"
    "{sources}\n\n"
    "For each thesis, tell me whether any source note contradicts, complicates, or "
    "materially updates that position. Quote the conflicting source. If there is no "
    "conflict for a given thesis, say so in one word: Clear."
)


def _utc_date_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _frontmatter(job: str, model: str, source_count: int) -> str:
    return (
        "---\n"
        f"generated: {datetime.now(timezone.utc).isoformat()}\n"
        f"job: {job}\n"
        f"model: {model}\n"
        f"source_notes: {source_count}\n"
        "tags: [vault-automation, " + job + "]\n"
        "---\n\n"
    )


async def run_synthesis_brief(
    client,
    root: Path | None = None,
    days: int = 7,
    model: str = DEFAULT_SYNTHESIS_MODEL,
    max_tokens: int = 1200,
) -> Path | None:
    """Daily synthesis brief (#1). Returns the written note path, or None if no notes."""
    base = paths.ensure_folders(root)
    notes: list[Path] = []
    for folder in (paths.INBOX, paths.SOURCES, paths.THESES, paths.PROJECTS):
        notes.extend(paths.iter_recent_notes(folder, days=days, root=base))
    if not notes:
        logger.info("synthesis brief: no notes modified in last %d days — skipping", days)
        return None

    notes_text = paths.read_notes_text(notes, vault_base=base)
    prompt = _SYNTHESIS_PROMPT.format(days=days, notes=notes_text)
    result = await client.call(
        model=model,
        system=_SYNTHESIS_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
        agent_name="vault_synthesis_brief",
        temperature=0.4,
    )
    if not getattr(result, "success", False):
        logger.error("synthesis brief: LLM call failed: %s", getattr(result, "error", "unknown"))
        return None

    body = _frontmatter("synthesis-brief", model, len(notes)) + result.content
    out = paths.write_note(paths.INBOX, f"brief-{_utc_date_str()}.md", body, root=base)
    logger.info("synthesis brief written: %s (%d source notes)", out, len(notes))
    return out


async def run_contradiction_check(
    client,
    root: Path | None = None,
    days: int = 30,
    model: str = DEFAULT_SYNTHESIS_MODEL,
    max_tokens: int = 1200,
) -> Path | None:
    """Thesis contradiction check (#5). Returns the written note path, or None if nothing to compare."""
    base = paths.ensure_folders(root)
    thesis_notes = paths.iter_recent_notes(paths.THESES, days=3650, root=base)
    source_notes = paths.iter_recent_notes(paths.SOURCES, days=days, root=base)
    if not thesis_notes or not source_notes:
        logger.info(
            "contradiction check: theses=%d sources=%d — need both, skipping",
            len(thesis_notes),
            len(source_notes),
        )
        return None

    prompt = _CONTRADICTION_PROMPT.format(
        theses=paths.read_notes_text(thesis_notes, vault_base=base),
        sources=paths.read_notes_text(source_notes, vault_base=base),
        days=days,
    )
    result = await client.call(
        model=model,
        system=_CONTRADICTION_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
        agent_name="vault_contradiction_check",
        temperature=0.3,
    )
    if not getattr(result, "success", False):
        logger.error(
            "contradiction check: LLM call failed: %s", getattr(result, "error", "unknown")
        )
        return None

    source_count = len(thesis_notes) + len(source_notes)
    body = _frontmatter("contradiction-check", model, source_count) + result.content
    out = paths.write_note(paths.INBOX, f"contradictions-{_utc_date_str()}.md", body, root=base)
    logger.info("contradiction check written: %s", out)
    return out
