"""Audio artifact handler — local faster-whisper transcription + LLM analysis."""

from __future__ import annotations

import logging
import os
import re
import tempfile
from typing import Any

import certifi
import httpx

if not os.path.exists(os.environ.get("SSL_CERT_FILE", "")):
    os.environ["SSL_CERT_FILE"] = certifi.where()

from ..llm import call_text
from ..models import AnalysisResult, ArtifactType
from ..prompts import AUDIO_SYSTEM
from .text import _parse_json_reply

logger = logging.getLogger(__name__)

AUDIO_EXTS = (".wav", ".mp3", ".m4a", ".ogg", ".oga", ".webm", ".flac")
TIMEOUT = httpx.Timeout(60.0, read=120.0)
_model_singleton = None


def _split_urls(field: str) -> list[str]:
    return [u for u in re.split(r"[\s,]+", field.strip()) if u]


def _looks_like_audio(url: str) -> bool:
    low = url.lower().split("?", 1)[0]
    return any(low.endswith(ext) for ext in AUDIO_EXTS)


def _get_model():
    """Lazy singleton — load on first call, cache.

    Tests patch this function directly so heavy imports don't fire.
    """
    global _model_singleton
    if _model_singleton is None:
        from faster_whisper import WhisperModel  # heavy import — defer

        model_name = os.getenv("DEEP_ANALYZER_WHISPER_MODEL", "medium")
        device = os.getenv("DEEP_ANALYZER_WHISPER_DEVICE", "cuda")
        compute = os.getenv("DEEP_ANALYZER_WHISPER_COMPUTE", "float16")
        logger.info("audio_handler: loading whisper model=%s device=%s", model_name, device)
        _model_singleton = WhisperModel(model_name, device=device, compute_type=compute)
    return _model_singleton


async def _download_to_temp(url: str) -> str:
    async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True) as cli:
        r = await cli.get(url)
        r.raise_for_status()
        ext = os.path.splitext(url.split("?")[0])[1] or ".wav"
        fd, path = tempfile.mkstemp(suffix=ext, prefix="deep_analyzer_audio_")
        os.write(fd, r.content)
        os.close(fd)
        return path


def _transcribe(path: str) -> str:
    model = _get_model()
    segments, _info = model.transcribe(path, beam_size=1)
    return " ".join(s.text.strip() for s in segments).strip()


class AudioHandler:
    async def analyze(self, row: dict[str, Any]) -> AnalysisResult:
        urls = _split_urls(row.get("attachment_urls") or "")
        audio_urls = [u for u in urls if _looks_like_audio(u)]
        if not audio_urls:
            raise ValueError(f"no audio attachment in row {row.get('message_id')}")

        local = await _download_to_temp(audio_urls[0])
        try:
            transcript = _transcribe(local)
        finally:
            try:
                os.unlink(local)
            except OSError:
                pass

        if not transcript:
            transcript = "(transcription yielded no text)"

        resp = await call_text(prompt=f"Transcript:\n{transcript}", system=AUDIO_SYSTEM)
        summary, structured = _parse_json_reply(resp.reply)
        structured.setdefault("transcript_chars", len(transcript))

        return AnalysisResult(
            bookmark_id=str(row["message_id"]),
            artifact_type=ArtifactType.AUDIO,
            summary=summary,
            structured=structured,
            model_used=resp.model,
            usage=resp.usage,
            cost_usd=resp.cost_usd,
        )
