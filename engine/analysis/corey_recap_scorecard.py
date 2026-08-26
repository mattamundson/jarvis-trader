"""
Post-close Corey recap scorecard -- assembles the verdict grader over a session.

``corey_verdict_grader`` grades ONE (self-claim, mechanical-outcome) pair. This
module is the retrospective glue: pull a day's Corey recap posts, classify his
self-claimed verdict, and grade it against a mechanical outcome SUPPLIED for that
session. It runs POST-CLOSE / next-morning -- the pre-session morning briefing
(``daily_morning_briefing``) has no realized outcome yet, so it is the wrong host.

Dormant-safe: ``fetch_recap_texts`` returns [] while the Corey feed is dry, exactly
like ``analysis/corey_compare`` (Phase F stays inert until the Discord token is
refreshed). It reads the same ``discord_corey_commentary`` rows the live extractor
(``CoreyCommentaryProcessor``) consumes.

CLAIM-GRANULARITY (the divergence trap): the mechanical outcome MUST answer the
same question Corey claimed. ``corey_compare``'s ``corey_correct`` is a session
open->close DIRECTION grade -- it answers "was his bias right", NOT "did 7460
hold". Feeding a direction grade to a LEVEL-specific self-claim ("held perfectly")
manufactures a false OVERSTATE. Supply a level-specific outcome for level claims;
until an intraday level feed exists, grade only DIRECTIONAL self-claims off the
direction score. ``mechanical_from_correct`` carries the same warning.

Display / journal only -- imported by nothing in ``risk/`` or execution. Pure
except ``fetch_recap_texts`` (one read-only query). No LLM.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from typing import Any, Optional

from analysis.corey_verdict_grader import (
    classify_self_verdict,
    grade_divergence,
    render_verdict_divergence,
    summarize,
)

logger = logging.getLogger(__name__)

# Corey's own posts: #market-updates, plus #general from his author id. Mirrors
# CoreyCommentaryProcessor._fetch_commentary so the scorecard reads exactly the
# rows the live extractor treats as Corey.
_TATHEDOG_AUTHOR_ID = "564449478174703646"


def fetch_recap_texts(for_date: Any, db_path: Optional[str] = None) -> list[str]:
    """Return Corey's commentary message bodies for the date, or [] when dry.

    Dormant-safe: a missing ``db_path``, absent table, unreachable DB, or bad date
    all yield [] so the retrospective no-ops while the feed is frozen. Read-only --
    never creates or writes a table.
    """
    if not db_path:
        return []
    date_str = for_date.isoformat() if hasattr(for_date, "isoformat") else str(for_date)
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT content FROM discord_corey_commentary
                WHERE DATE(timestamp) = ?
                  AND (channel = 'market-updates'
                       OR (channel = 'general' AND author_id = ?))
                ORDER BY timestamp ASC
                """,
                (date_str, _TATHEDOG_AUTHOR_ID),
            ).fetchall()
        return [str(r["content"]) for r in rows if r["content"]]
    except Exception as exc:  # pragma: no cover - dormant-safe
        logger.debug("corey recap fetch dormant -- %s", exc)
        return []


def _snippet(text: str, limit: int = 140) -> str:
    t = re.sub(r"\s+", " ", (text or "")).strip()
    return t if len(t) <= limit else t[: limit - 1].rstrip() + "…"


def grade_day(
    recap_text: str, mechanical_verdict: str, for_date: Any = None
) -> dict[str, Any]:
    """Grade one session: classify Corey's recap self-verdict and compare it to the
    SUPPLIED mechanical verdict.

    Returns the ``grade_divergence`` record plus a ``quote`` snippet (and ``date``
    when given). Pure. Heed the module CLAIM-GRANULARITY note: the caller must pass
    a mechanical verdict whose granularity matches the self-claim.
    """
    self_verdict = classify_self_verdict(recap_text or "")
    record = grade_divergence(self_verdict, mechanical_verdict)
    record["quote"] = _snippet(recap_text or "")
    if for_date is not None:
        record["date"] = (
            for_date.isoformat() if hasattr(for_date, "isoformat") else str(for_date)
        )
    return record


def build_scorecard(day_records: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate per-day ``grade_day`` records into a ``summarize()`` scorecard.

    The result always carries n and a PROVISIONAL note (see ``summarize``).
    """
    return summarize(list(day_records))


def render_scorecard(day_records: list[dict[str, Any]]) -> list[str]:
    """Render the '## Corey Self-Report Divergence' section from per-day records.

    Empty list when nothing is gradeable (mirrors the dormant render contract).
    """
    return render_verdict_divergence(build_scorecard(day_records))
