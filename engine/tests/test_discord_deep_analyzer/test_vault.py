"""Tests for deep_analyzer.vault."""

from __future__ import annotations

from pathlib import Path

import pytest

from discord.deep_analyzer.models import AnalysisResult, ArtifactType, LLMUsage
from discord.deep_analyzer.vault import write_page


@pytest.fixture
def sample_result() -> AnalysisResult:
    return AnalysisResult(
        bookmark_id="42",
        artifact_type=ArtifactType.TEXT,
        summary="Trader thinking about MES short.",
        structured={"tickers": ["MES"], "priority": 4, "sentiment": "bearish"},
        model_used="gemini-2.5-flash",
        usage=LLMUsage(input_tokens=50, output_tokens=80),
        cost_usd=0.000215,
    )


def test_write_page_creates_dated_folder_and_file(sample_result, tmp_path):
    out = write_page(
        result=sample_result,
        vault_root=tmp_path,
        posted_at="2026-05-20T10:00:00Z",
        slug_source="thinking about shorting MES",
        discord_url="https://discord.com/channels/g/c/m",
    )
    assert out.exists()
    assert out.parent.name == "2026-05-20"
    assert out.parent.parent.name == "Discord-Feed"


def test_write_page_includes_frontmatter_and_body(sample_result, tmp_path):
    out = write_page(
        result=sample_result,
        vault_root=tmp_path,
        posted_at="2026-05-20T10:00:00Z",
        slug_source="MES short idea",
        discord_url="https://discord.com/channels/g/c/m",
    )
    text = out.read_text(encoding="utf-8")
    assert text.startswith("---")
    assert "artifact_type: text" in text
    assert "cost_usd: 0.000215" in text
    assert "model: gemini-2.5-flash" in text
    assert "MES short" in text  # body present


def test_write_page_filename_is_id_plus_slug(sample_result, tmp_path):
    out = write_page(
        result=sample_result,
        vault_root=tmp_path,
        posted_at="2026-05-20T10:00:00Z",
        slug_source="A " * 100,  # very long
        discord_url="https://discord.com/channels/g/c/m",
    )
    assert out.name.startswith("42--")
    assert len(out.name) <= 100  # truncated
    assert out.name.endswith(".md")


def test_write_page_overwrites_existing(sample_result, tmp_path):
    out1 = write_page(
        result=sample_result,
        vault_root=tmp_path,
        posted_at="2026-05-20T10:00:00Z",
        slug_source="same slug",
        discord_url="https://discord.com/channels/g/c/m",
    )
    out2 = write_page(
        result=sample_result,
        vault_root=tmp_path,
        posted_at="2026-05-20T10:00:00Z",
        slug_source="same slug",
        discord_url="https://discord.com/channels/g/c/m",
    )
    assert out1 == out2
