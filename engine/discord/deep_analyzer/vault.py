"""Write per-artifact analysis pages into the Obsidian vault."""

from __future__ import annotations

import json
import re
from pathlib import Path

from vault.paths import vault_root as _vault_root

from .models import AnalysisResult

MAX_FILENAME_CHARS = 100


def _slugify(text: str, max_len: int = 60) -> str:
    text = re.sub(r"[^a-zA-Z0-9\s-]", "", text).strip().lower()
    text = re.sub(r"\s+", "-", text)
    return text[:max_len] or "untitled"


def _build_filename(bookmark_id: str, slug_source: str) -> str:
    slug = _slugify(slug_source)
    name = f"{bookmark_id}--{slug}.md"
    return name[:MAX_FILENAME_CHARS]


def _render(result: AnalysisResult, posted_at: str, discord_url: str) -> str:
    tags = sorted(
        {
            "discord-feed",
            result.artifact_type.value,
            *result.structured.get("topics", []),
        }
    )
    tickers = result.structured.get("tickers", [])
    lines = [
        "---",
        f"date: {posted_at}",
        f"discord_url: {discord_url}",
        f"artifact_type: {result.artifact_type.value}",
        f"model: {result.model_used}",
        f"cost_usd: {result.cost_usd:.6f}",
        f"input_tokens: {result.usage.input_tokens}",
        f"output_tokens: {result.usage.output_tokens}",
        f"tickers: {tickers}",
        f"tags: {tags}",
        "---",
        "",
        "# Summary",
        "",
        result.summary,
        "",
        "# Structured",
        "",
        "```json",
        json.dumps(result.structured, indent=2),
        "```",
        "",
        f"[Original Discord message]({discord_url})",
    ]
    return "\n".join(lines)


def write_page(
    *,
    result: AnalysisResult,
    posted_at: str,
    slug_source: str,
    discord_url: str,
    vault_root: Path | None = None,
) -> Path:
    """Write the analysis to Obsidian. Returns absolute file path."""
    # Fall back to the canonical resolver (honours JARVIS_VAULT_ROOT) rather than a
    # duplicated ~/my-vault default, so every writer shares one vault root.
    root = Path(vault_root) if vault_root else _vault_root()
    date_str = posted_at[:10]  # YYYY-MM-DD
    folder = root / "Discord-Feed" / date_str
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / _build_filename(result.bookmark_id, slug_source)
    path.write_text(_render(result, posted_at, discord_url), encoding="utf-8")
    return path
