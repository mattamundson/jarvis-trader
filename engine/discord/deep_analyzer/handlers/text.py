"""Plain-text artifact handler."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from ..llm import call_text
from ..models import AnalysisResult, ArtifactType, LLMUsage
from ..prompts import TEXT_SYSTEM

logger = logging.getLogger(__name__)

# P0 / FAILED tier — broken-extract markers in the LLM-returned summary.
# When the upstream URL fetch returned a JS-required shell, a privacy
# interstitial, or a Cloudflare challenge, the LLM faithfully reports it
# (e.g. "the page could not be retrieved due to a privacy extension").
# These items pollute the P1 noise band; route them to P0 so the digest
# can skip them while the vault page is still written for searchability.
_BROKEN_EXTRACT_RE = re.compile(
    r"(privacy extension|could not be retrieved|unable to analyze( the)? content|"
    r"failed to (load|fetch|retrieve)|content not (available|accessible)|"
    r"no readable content|blocked by( the)? browser|anti-bot|cloudflare challenge)",
    re.IGNORECASE,
)


def _is_broken_extract(summary: str | None) -> bool:
    """True if the LLM summary indicates the upstream artifact was unreadable."""
    return bool(summary and _BROKEN_EXTRACT_RE.search(summary))


def _parse_json_reply(reply: str) -> tuple[str, dict[str, Any]]:
    """Try to parse the LLM reply as JSON. Returns (summary, structured).

    Post-process side effect: if the resulting summary matches a known
    broken-extract pattern, the structured dict's `priority` is forced to 0
    (P0 / FAILED tier) so downstream digest logic can filter it out.
    """
    stripped = reply.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        logger.warning("deep_analyzer.text: non-JSON reply; using raw text as summary")
        summary = reply
        structured: dict[str, Any] = {}
        if _is_broken_extract(summary):
            structured["priority"] = 0
        return summary, structured
    # `data.pop("summary", reply)` returns None when the JSON has
    # `"summary": null`, which would crash Pydantic validation. Fall back
    # explicitly to the raw reply (or a placeholder if the reply is empty).
    summary = data.pop("summary", None) or reply or "(empty)"
    if _is_broken_extract(summary):
        data["priority"] = 0
    return summary, data


class TextHandler:
    async def analyze(self, row: dict[str, Any]) -> AnalysisResult:
        content = row.get("content") or ""
        if not content.strip():
            return AnalysisResult(
                bookmark_id=str(row["message_id"]),
                artifact_type=ArtifactType.TEXT,
                summary="(empty text — nothing to analyze)",
                structured={},
                model_used="none",
                usage=LLMUsage(),
                cost_usd=0.0,
            )

        resp = await call_text(prompt=content, system=TEXT_SYSTEM)
        summary, structured = _parse_json_reply(resp.reply)

        return AnalysisResult(
            bookmark_id=str(row["message_id"]),
            artifact_type=ArtifactType.TEXT,
            summary=summary,
            structured=structured,
            model_used=resp.model,
            usage=resp.usage,
            cost_usd=resp.cost_usd,
        )
