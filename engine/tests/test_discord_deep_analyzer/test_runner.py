"""Tests for deep_analyzer.runner."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from discord.deep_analyzer import runner, storage
from discord.deep_analyzer.models import AnalysisResult, ArtifactType, LLMUsage


@pytest.fixture
def text_only_db(seeded_db: Path) -> Path:
    """Reduce seeded_db to one text-only row (m1, id=1)."""
    storage.migrate(seeded_db)
    conn = sqlite3.connect(seeded_db)
    conn.execute("DELETE FROM discord_bookmarks WHERE message_id != 'm1'")
    conn.commit()
    conn.close()
    return seeded_db


@pytest.fixture
def stub_text_result():
    return AnalysisResult(
        bookmark_id="placeholder",
        artifact_type=ArtifactType.TEXT,
        summary="stub",
        structured={"tickers": ["MES"], "priority": 3},
        model_used="gemini-2.5-flash",
        usage=LLMUsage(input_tokens=10, output_tokens=20),
        cost_usd=0.0001,
    )


@pytest.mark.asyncio
async def test_runner_processes_text_row_end_to_end(
    text_only_db, tmp_path, monkeypatch, stub_text_result
):
    vault = tmp_path / "vault"
    monkeypatch.setenv("GBRAIN_RAW_DIR", str(tmp_path / "raw"))
    (tmp_path / "raw").mkdir()

    async def fake_analyze(self, row):
        return stub_text_result.model_copy(update={"bookmark_id": str(row["message_id"])})

    monkeypatch.setattr(
        "discord.deep_analyzer.handlers.text.TextHandler.analyze",
        fake_analyze,
    )

    n = await runner.run_once(db_path=text_only_db, vault_root=vault, limit=5)
    assert n == 1

    conn = sqlite3.connect(text_only_db)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM discord_bookmarks WHERE message_id='m1'").fetchone()
    a = conn.execute("SELECT * FROM discord_analyses").fetchone()
    conn.close()

    assert row["analyzed_at"] is not None
    assert row["analysis_id"] == a["id"]
    assert a["artifact_type"] == "text"
    assert (vault / "Discord-Feed" / "2026-05-20").exists()


@pytest.mark.asyncio
async def test_runner_halts_on_daily_budget_breach(text_only_db, tmp_path, monkeypatch):
    monkeypatch.setenv("DEEP_ANALYZER_DAILY_USD", "0.00")
    conn = sqlite3.connect(text_only_db)
    conn.execute(
        "INSERT INTO discord_analyses (bookmark_id, artifact_type, summary, structured_json, cost_usd) "
        "VALUES ('m1', 'text', 's', '{}', 5.00)"
    )
    conn.commit()
    conn.close()

    n = await runner.run_once(db_path=text_only_db, vault_root=tmp_path, limit=5)
    assert n == 0


@pytest.mark.asyncio
async def test_runner_writes_failure_row_on_handler_exception(text_only_db, tmp_path, monkeypatch):
    async def boom(self, row):
        raise RuntimeError("transient upstream")

    monkeypatch.setattr(
        "discord.deep_analyzer.handlers.text.TextHandler.analyze",
        boom,
    )
    n = await runner.run_once(db_path=text_only_db, vault_root=tmp_path, limit=5)
    assert n == 0

    conn = sqlite3.connect(text_only_db)
    conn.row_factory = sqlite3.Row
    a = conn.execute("SELECT * FROM discord_analyses").fetchone()
    row = conn.execute("SELECT analyzed_at FROM discord_bookmarks WHERE message_id='m1'").fetchone()
    conn.close()
    assert a is not None
    assert "transient" in (a["error_text"] or "")
    assert row["analyzed_at"] is None


@pytest.mark.asyncio
async def test_runner_routes_url_row_to_url_handler(seeded_db, tmp_path, monkeypatch):
    storage.migrate(seeded_db)

    # Keep only the github row (m3) — generic URL routing.
    # (The x.com row m2 now routes to XPostHandler instead of UrlHandler.)
    conn = sqlite3.connect(seeded_db)
    conn.execute("DELETE FROM discord_bookmarks WHERE message_id != 'm3'")
    conn.commit()
    conn.close()

    monkeypatch.setenv("GBRAIN_RAW_DIR", str(tmp_path / "raw"))
    (tmp_path / "raw").mkdir()

    async def fake_url_analyze(self, row):
        return AnalysisResult(
            bookmark_id=str(row["message_id"]),
            artifact_type=ArtifactType.URL,
            summary="GH repo summary",
            structured={"source_kind": "github"},
            model_used="gemini-2.5-flash",
            usage=LLMUsage(input_tokens=20, output_tokens=10),
            cost_usd=0.0001,
        )

    monkeypatch.setattr(
        "discord.deep_analyzer.handlers.url.UrlHandler.analyze",
        fake_url_analyze,
    )

    n = await runner.run_once(db_path=seeded_db, vault_root=tmp_path, limit=5)
    assert n == 1

    conn = sqlite3.connect(seeded_db)
    a = conn.execute("SELECT artifact_type FROM discord_analyses").fetchone()
    conn.close()
    assert a[0] == "url"


@pytest.mark.asyncio
async def test_runner_routes_x_url_to_x_post_handler(seeded_db, tmp_path, monkeypatch):
    """The x.com row in seeded_db must dispatch to XPostHandler, not UrlHandler."""
    storage.migrate(seeded_db)

    conn = sqlite3.connect(seeded_db)
    conn.execute("DELETE FROM discord_bookmarks WHERE message_id != 'm2'")
    conn.commit()
    conn.close()

    monkeypatch.setenv("GBRAIN_RAW_DIR", str(tmp_path / "raw"))
    (tmp_path / "raw").mkdir()

    async def fake_x_analyze(self, row):
        return AnalysisResult(
            bookmark_id=str(row["message_id"]),
            artifact_type=ArtifactType.X_POST,
            summary="X post summary",
            structured={"source_kind": "x_post"},
            model_used="claude-haiku-4-5",
            usage=LLMUsage(input_tokens=20, output_tokens=10),
            cost_usd=0.0001,
        )

    monkeypatch.setattr(
        "discord.deep_analyzer.handlers.x_post.XPostHandler.analyze",
        fake_x_analyze,
    )

    n = await runner.run_once(db_path=seeded_db, vault_root=tmp_path, limit=5)
    assert n == 1

    conn = sqlite3.connect(seeded_db)
    a = conn.execute("SELECT artifact_type FROM discord_analyses").fetchone()
    conn.close()
    assert a[0] == "x_post"


def test_infer_artifact_type_image_from_attachment_ext():
    from discord.deep_analyzer.runner import _infer_artifact_type

    assert _infer_artifact_type({"attachment_urls": "https://x.com/a.png"}) == ArtifactType.IMAGE


def test_infer_artifact_type_audio_from_attachment_ext():
    from discord.deep_analyzer.runner import _infer_artifact_type

    assert _infer_artifact_type({"attachment_urls": "https://x.com/a.wav"}) == ArtifactType.AUDIO


def test_infer_artifact_type_document_from_attachment_ext():
    from discord.deep_analyzer.runner import _infer_artifact_type

    assert _infer_artifact_type({"attachment_urls": "https://x.com/a.pdf"}) == ArtifactType.DOCUMENT


def test_infer_artifact_type_url_when_url_only():
    from discord.deep_analyzer.runner import _infer_artifact_type

    assert _infer_artifact_type({"url": "https://example.com"}) == ArtifactType.URL


def test_infer_artifact_type_text_when_neither():
    from discord.deep_analyzer.runner import _infer_artifact_type

    assert _infer_artifact_type({"content": "hello"}) == ArtifactType.TEXT


def test_infer_artifact_type_prefers_url_when_both_present():
    """Path B: when a message has BOTH url and attachment, URL wins.

    Common case: user shares an article link; Discord auto-attaches a
    preview image. The URL is the primary signal — analyzing the linked
    page gives richer context than OCRing the screenshot.
    """
    from discord.deep_analyzer.runner import _infer_artifact_type

    row = {
        "url": "https://example.com/article",
        "attachment_urls": "https://cdn.discordapp.com/a/b/preview.png",
    }
    assert _infer_artifact_type(row) == ArtifactType.URL
