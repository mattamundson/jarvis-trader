"""Tests for deep_analyzer.gbrain_sink."""

from __future__ import annotations

from pathlib import Path

import pytest

from discord.deep_analyzer.gbrain_sink import ingest
from discord.deep_analyzer.models import AnalysisResult, ArtifactType, LLMUsage


@pytest.fixture
def sample() -> AnalysisResult:
    return AnalysisResult(
        bookmark_id="m7",
        artifact_type=ArtifactType.TEXT,
        summary="hello",
        structured={"tickers": ["MES"]},
        model_used="gemini-2.5-flash",
        usage=LLMUsage(input_tokens=1, output_tokens=1),
        cost_usd=0.0,
    )


def test_ingest_writes_file_when_dir_exists(sample, tmp_path, monkeypatch):
    raw = tmp_path / "raw" / "discord-feed"
    raw.mkdir(parents=True)
    monkeypatch.setenv("GBRAIN_RAW_DIR", str(raw))
    chunk_ids = ingest(sample, posted_at="2026-05-20T10:00:00Z")
    files = list(raw.glob("*.md"))
    assert len(files) == 1
    assert chunk_ids == [files[0].stem]


def test_ingest_skips_silently_when_dir_missing(sample, tmp_path, monkeypatch):
    monkeypatch.setenv("GBRAIN_RAW_DIR", str(tmp_path / "does-not-exist"))
    chunk_ids = ingest(sample, posted_at="2026-05-20T10:00:00Z")
    assert chunk_ids == []
