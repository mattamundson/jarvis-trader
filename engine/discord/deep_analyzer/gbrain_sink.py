"""Side-effect sink: drop analyses into gbrain's raw/ watched directory."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from .models import AnalysisResult

logger = logging.getLogger(__name__)


def _raw_dir() -> Path:
    return Path(
        os.getenv("GBRAIN_RAW_DIR", os.path.expanduser("~/.gbrain-trading/raw/discord-feed"))
    )


def ingest(result: AnalysisResult, *, posted_at: str) -> list[str]:
    """Write a single markdown chunk for gbrain to ingest. Returns chunk-id list.

    Idempotent on (bookmark_id, artifact_type). Silent skip if dir missing.
    """
    raw = _raw_dir()
    if not raw.exists():
        logger.info("deep_analyzer.gbrain_sink: %s missing - skipping", raw)
        return []

    chunk_id = f"discord-{result.bookmark_id}-{result.artifact_type.value}"
    path = raw / f"{chunk_id}.md"

    body_lines = [
        f"# Discord {result.artifact_type.value} #{result.bookmark_id}",
        "",
        f"Posted: {posted_at}",
        f"Tickers: {', '.join(result.structured.get('tickers', []))}",
        "",
        result.summary,
    ]
    path.write_text("\n".join(body_lines), encoding="utf-8")
    return [chunk_id]
