"""Deep analyzer orchestrator — picks rows, dispatches, persists, finalizes."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

# Load engine/.env so ANTHROPIC_API_KEY, GOOGLE_API_KEY, etc. are populated
# when the runner is invoked from a scheduled-task PS1 wrapper or any other
# entry point that didn't already source the env file. Idempotent — never
# overrides an already-set var.
try:
    from dotenv import load_dotenv

    _engine_env = Path(__file__).resolve().parents[2] / ".env"
    if _engine_env.exists():
        load_dotenv(_engine_env, override=False)
except ImportError:  # pragma: no cover — dotenv is a runtime dep
    pass

from . import gbrain_sink, storage, vault
from .handlers.audio import AudioHandler
from .handlers.document import DocumentHandler
from .handlers.image import ImageHandler
from .handlers.text import TextHandler
from .handlers.url import UrlHandler
from .handlers.x_post import X_URL_RE, XPostHandler
from .models import ArtifactType

logger = logging.getLogger(__name__)

DISCORD_GUILD = "1490851278601982165"
DISCORD_CHANNEL = "1490851279180660819"

_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".gif")
_AUDIO_EXTS = (".wav", ".mp3", ".m4a", ".ogg", ".oga", ".webm", ".flac")
_DOC_EXTS = (".pdf",)


def _infer_artifact_type(row: dict[str, Any]) -> ArtifactType:
    """Route by precedence: URL (canonical) > attachment (supplementary) > text.

    Rationale: when a message has BOTH a URL and an attachment, the URL is
    almost always the primary signal (a shared link with a screenshot preview),
    and the attachment is supplementary. Analyzing the URL gives richer
    context. Attachment-only messages route on file extension.
    """
    if row.get("url"):
        if X_URL_RE.match(row["url"]):
            return ArtifactType.X_POST
        return ArtifactType.URL
    raw = row.get("attachment_urls") or ""
    if raw:
        first = raw.split()[0].split(",")[0].lower().split("?", 1)[0]
        if any(first.endswith(e) for e in _IMAGE_EXTS):
            return ArtifactType.IMAGE
        if any(first.endswith(e) for e in _AUDIO_EXTS):
            return ArtifactType.AUDIO
        if any(first.endswith(e) for e in _DOC_EXTS):
            return ArtifactType.DOCUMENT
        # Unknown attachment type — default to image (vision LLM handles unknowns best)
        return ArtifactType.IMAGE
    return ArtifactType.TEXT


def _daily_budget_usd() -> float:
    return float(os.getenv("DEEP_ANALYZER_DAILY_USD", "2.00"))


def _discord_url(row: dict[str, Any]) -> str:
    return f"https://discord.com/channels/{DISCORD_GUILD}/{DISCORD_CHANNEL}/{row['message_id']}"


def _slug_source(row: dict[str, Any]) -> str:
    return row.get("content") or row.get("url") or row.get("message_id") or "untitled"


async def run_once(
    *,
    db_path: Path | str,
    vault_root: Path,
    limit: int = 5,
) -> int:
    """One poll. Returns count of successful analyses written."""
    storage.migrate(db_path)

    spent = storage.daily_cost_usd(db_path)
    if spent >= _daily_budget_usd():
        logger.warning(
            "deep_analyzer: budget breached ($%.4f / $%.2f) — halting",
            spent,
            _daily_budget_usd(),
        )
        return 0

    rows = storage.pick_unanalyzed(db_path, limit=limit)
    if not rows:
        return 0
    storage.claim_rows(db_path, [str(r["message_id"]) for r in rows])

    handlers = {
        ArtifactType.TEXT: TextHandler(),
        ArtifactType.URL: UrlHandler(),
        ArtifactType.X_POST: XPostHandler(),
        ArtifactType.IMAGE: ImageHandler(),
        ArtifactType.AUDIO: AudioHandler(),
        ArtifactType.DOCUMENT: DocumentHandler(),
    }
    written = 0

    for row in rows:
        a_type = _infer_artifact_type(row)
        handler = handlers.get(a_type)
        message_id = str(row["message_id"])
        if handler is None:
            logger.info(
                "deep_analyzer: skipping %s — no handler for %s",
                message_id,
                a_type,
            )
            continue
        try:
            result = await handler.analyze(row)
        except Exception as exc:  # noqa: BLE001 — record failure, don't crash run
            logger.exception("deep_analyzer: handler error on row %s", message_id)
            storage.insert_analysis(
                db_path=db_path,
                bookmark_id=message_id,
                artifact_type=a_type.value,
                summary=f"FAILED: {exc}",
                structured_json={"error": str(exc)},
                error_text=str(exc),
                retries=0,
            )
            continue

        vault_path = vault.write_page(
            result=result,
            posted_at=row["posted_at"],
            slug_source=_slug_source(row),
            discord_url=_discord_url(row),
            vault_root=vault_root,
        )
        chunk_ids = gbrain_sink.ingest(result, posted_at=row["posted_at"])

        analysis_id = storage.insert_analysis(
            db_path=db_path,
            bookmark_id=message_id,
            artifact_type=result.artifact_type.value,
            summary=result.summary,
            structured_json=result.structured,
            vault_path=str(vault_path),
            gbrain_chunk_ids=chunk_ids,
            model_used=result.model_used,
            cost_usd=result.cost_usd,
        )
        storage.mark_analyzed(db_path, message_id, analysis_id)
        written += 1

    return written
