"""Plain-text artifact handler."""

from __future__ import annotations

import json
import logging
from typing import Any

from ..llm import call_text
from ..models import AnalysisResult, ArtifactType, LLMUsage
from ..prompts import TEXT_SYSTEM

logger = logging.getLogger(__name__)


def _parse_json_reply(reply: str) -> tuple[str, dict[str, Any]]:
    """Try to parse the LLM reply as JSON. Returns (summary, structured)."""
    stripped = reply.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        logger.warning("deep_analyzer.text: non-JSON reply; using raw text as summary")
        return reply, {}
    # `data.pop("summary", reply)` returns None when the JSON has
    # `"summary": null`, which would crash Pydantic validation. Fall back
    # explicitly to the raw reply (or a placeholder if the reply is empty).
    summary = data.pop("summary", None) or reply or "(empty)"
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
