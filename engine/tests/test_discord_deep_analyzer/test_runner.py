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
        bookmark_id=0,
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
        return stub_text_result.model_copy(update={"bookmark_id": row["id"]})

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
        "VALUES (1, 'text', 's', '{}', 5.00)"
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
    row = conn.execute("SELECT analyzed_at FROM discord_bookmarks WHERE id=1").fetchone()
    conn.close()
    assert a is not None
    assert "transient" in (a["error_text"] or "")
    assert row["analyzed_at"] is None
