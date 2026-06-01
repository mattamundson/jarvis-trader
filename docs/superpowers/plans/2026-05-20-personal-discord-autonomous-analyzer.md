# Personal Discord Autonomous Analyzer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an autonomous deep-analysis pipeline that processes every artifact in personal Discord channel `1490851279180660819` (URLs, images, audio, PDFs, text) and lands results in Obsidian + gbrain + a daily digest.

**Architecture:** New `engine/discord/deep_analyzer/` submodule with a runner that polls `discord_bookmarks` for unanalyzed rows every 2 min, dispatches by artifact type to handlers, and writes results to a new `discord_analyses` table + vault page + gbrain. Hermes is LLM gateway only (Gemini primary, Anthropic Haiku fallback) — never orchestrator. Additive schema, side-effect-isolated, daily budget cap.

**Tech Stack:** Python 3.12 (engine venv), Pydantic v2, FastAPI conventions, SQLite, httpx, readability-lxml, pypdf, faster-whisper, Pillow, Hermes HTTP API, gbrain ingest dir, Obsidian markdown, Windows Task Scheduler.

**Spec:** `docs/superpowers/specs/2026-05-20-personal-discord-autonomous-analyzer-design.md`

---

## File Structure

```
engine/discord/deep_analyzer/
├── __init__.py
├── runner.py             # Orchestrator
├── storage.py            # Schema + CRUD + budget query
├── llm.py                # Hermes LLM client
├── models.py             # Pydantic v2 result models
├── prompts.py            # Per-artifact prompt templates
├── vault.py              # Obsidian markdown writer
├── gbrain_sink.py        # gbrain ingest
├── digest.py             # Daily digest generator
└── handlers/
    ├── __init__.py
    ├── base.py           # Handler protocol
    ├── text.py
    ├── url.py
    ├── image.py
    ├── audio.py
    └── document.py

engine/tests/test_discord_deep_analyzer/
├── __init__.py
├── conftest.py
├── test_storage.py
├── test_models.py
├── test_llm.py
├── test_runner.py
├── test_vault.py
├── test_gbrain_sink.py
├── test_digest.py
└── test_handlers/
    ├── test_text.py
    ├── test_url.py
    ├── test_image.py
    ├── test_audio.py
    └── test_document.py

scripts/
├── deep_analyzer_loop.ps1            # 2-min wrapper
├── deep_analyzer_digest.ps1          # 06:00 wrapper
├── deep_analyzer_backfill.ps1        # one-shot Phase 5
└── install-deep-analyzer-tasks.ps1   # task installer
```

---

# Phase 0 — Schema Migration

## Task 1: Schema additions for `discord_bookmarks` + new `discord_analyses` table

**Files:**
- Create: `engine/discord/deep_analyzer/__init__.py`
- Create: `engine/discord/deep_analyzer/storage.py`
- Create: `engine/tests/test_discord_deep_analyzer/__init__.py`
- Create: `engine/tests/test_discord_deep_analyzer/conftest.py`
- Create: `engine/tests/test_discord_deep_analyzer/test_storage.py`

- [ ] **Step 1: Create empty package init files**

`engine/discord/deep_analyzer/__init__.py`:
```python
"""Deep analyzer for personal Discord channel artifacts."""
```

`engine/tests/test_discord_deep_analyzer/__init__.py`:
```python
```

- [ ] **Step 2: Write the test fixtures**

`engine/tests/test_discord_deep_analyzer/conftest.py`:
```python
"""Shared fixtures for deep_analyzer tests."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    """Empty sqlite db with the existing discord_bookmarks table pre-created."""
    db = tmp_path / "discord.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE discord_bookmarks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id TEXT UNIQUE NOT NULL,
            posted_at TEXT NOT NULL,
            content TEXT,
            attachment_urls TEXT,
            url TEXT,
            url_kind TEXT,
            channel TEXT NOT NULL,
            source TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    conn.commit()
    conn.close()
    return db


@pytest.fixture
def seeded_db(tmp_db: Path) -> Path:
    """tmp_db with 3 unanalyzed rows."""
    conn = sqlite3.connect(tmp_db)
    conn.executemany(
        """
        INSERT INTO discord_bookmarks
          (message_id, posted_at, content, attachment_urls, url, url_kind, channel)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            ("m1", "2026-05-20T10:00:00Z", "text-only note", None, None, None, "general"),
            ("m2", "2026-05-20T10:01:00Z", None, None, "https://x.com/a/status/1", "x_post", "general"),
            ("m3", "2026-05-20T10:02:00Z", None, "https://cdn.discordapp.com/a.png", None, None, "general"),
        ],
    )
    conn.commit()
    conn.close()
    return tmp_db
```

`engine/tests/test_discord_deep_analyzer/test_storage.py`:
```python
"""Tests for deep_analyzer.storage."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from engine.discord.deep_analyzer import storage


def test_migrate_adds_columns_to_discord_bookmarks(tmp_db: Path):
    storage.migrate(tmp_db)
    conn = sqlite3.connect(tmp_db)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(discord_bookmarks)")}
    conn.close()
    assert "analyzed_at" in cols
    assert "claimed_at" in cols
    assert "analysis_id" in cols


def test_migrate_creates_discord_analyses_table(tmp_db: Path):
    storage.migrate(tmp_db)
    conn = sqlite3.connect(tmp_db)
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert "discord_analyses" in tables


def test_migrate_is_idempotent(tmp_db: Path):
    storage.migrate(tmp_db)
    storage.migrate(tmp_db)  # second run must not raise
    conn = sqlite3.connect(tmp_db)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(discord_bookmarks)")}
    conn.close()
    assert "analyzed_at" in cols


def test_pick_unanalyzed_returns_ids(seeded_db: Path):
    storage.migrate(seeded_db)
    rows = storage.pick_unanalyzed(seeded_db, limit=10)
    assert len(rows) == 3
    assert {r["message_id"] for r in rows} == {"m1", "m2", "m3"}


def test_pick_unanalyzed_respects_limit(seeded_db: Path):
    storage.migrate(seeded_db)
    rows = storage.pick_unanalyzed(seeded_db, limit=2)
    assert len(rows) == 2


def test_pick_unanalyzed_skips_recently_claimed(seeded_db: Path):
    storage.migrate(seeded_db)
    conn = sqlite3.connect(seeded_db)
    conn.execute("UPDATE discord_bookmarks SET claimed_at = datetime('now') WHERE message_id = 'm1'")
    conn.commit()
    conn.close()
    rows = storage.pick_unanalyzed(seeded_db, limit=10)
    ids = {r["message_id"] for r in rows}
    assert "m1" not in ids
    assert ids == {"m2", "m3"}


def test_pick_unanalyzed_reclaims_stale(seeded_db: Path):
    storage.migrate(seeded_db)
    conn = sqlite3.connect(seeded_db)
    # 11 minutes ago — stale (threshold is 10 min)
    conn.execute(
        "UPDATE discord_bookmarks SET claimed_at = datetime('now', '-11 minutes') WHERE message_id = 'm1'"
    )
    conn.commit()
    conn.close()
    rows = storage.pick_unanalyzed(seeded_db, limit=10)
    assert "m1" in {r["message_id"] for r in rows}


def test_daily_cost_returns_sum(seeded_db: Path):
    storage.migrate(seeded_db)
    conn = sqlite3.connect(seeded_db)
    conn.executemany(
        "INSERT INTO discord_analyses (bookmark_id, artifact_type, summary, structured_json, cost_usd) "
        "VALUES (1, 'text', 's', '{}', ?)",
        [(0.50,), (0.30,)],
    )
    conn.commit()
    conn.close()
    assert storage.daily_cost_usd(seeded_db) == pytest.approx(0.80)
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
cd engine && .venv/Scripts/python -m pytest tests/test_discord_deep_analyzer/test_storage.py -v
```
Expected: ImportError or AttributeError — `storage` module doesn't exist.

- [ ] **Step 4: Implement `storage.py`**

`engine/discord/deep_analyzer/storage.py`:
```python
"""Schema migration + row claim/lock for deep_analyzer."""
from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

MIGRATION_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS discord_analyses (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    bookmark_id     INTEGER NOT NULL REFERENCES discord_bookmarks(id),
    artifact_type   TEXT    NOT NULL,
    summary         TEXT    NOT NULL,
    structured_json TEXT    NOT NULL,
    vault_path      TEXT,
    gbrain_chunk_ids TEXT,
    model_used      TEXT,
    cost_usd        REAL    DEFAULT 0,
    error_text      TEXT,
    retries         INTEGER DEFAULT 0,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_discord_analyses_bookmark
    ON discord_analyses(bookmark_id);

CREATE INDEX IF NOT EXISTS idx_discord_analyses_created
    ON discord_analyses(created_at);
"""

CLAIM_STALE_SECONDS = 600  # 10 minutes


def _has_column(conn: sqlite3.Connection, table: str, col: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r[1] == col for r in rows)


def migrate(db_path: Path | str) -> None:
    """Apply additive schema migration. Idempotent."""
    conn = sqlite3.connect(db_path)
    try:
        for col, ddl in [
            ("analyzed_at", "ALTER TABLE discord_bookmarks ADD COLUMN analyzed_at TIMESTAMP"),
            ("claimed_at",  "ALTER TABLE discord_bookmarks ADD COLUMN claimed_at TIMESTAMP"),
            ("analysis_id", "ALTER TABLE discord_bookmarks ADD COLUMN analysis_id INTEGER"),
        ]:
            if not _has_column(conn, "discord_bookmarks", col):
                conn.execute(ddl)
        conn.executescript(MIGRATION_SQL)
        conn.commit()
        logger.info("deep_analyzer.storage: migration applied to %s", db_path)
    finally:
        conn.close()


def pick_unanalyzed(db_path: Path | str, limit: int = 5) -> list[dict[str, Any]]:
    """Return up to `limit` unanalyzed and unclaimed (or stale-claimed) rows."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            f"""
            SELECT * FROM discord_bookmarks
            WHERE analyzed_at IS NULL
              AND (claimed_at IS NULL
                   OR claimed_at < datetime('now', '-{CLAIM_STALE_SECONDS} seconds'))
            ORDER BY posted_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def claim_rows(db_path: Path | str, ids: list[int]) -> int:
    """Mark rows as claimed_at = now(). Returns rowcount."""
    if not ids:
        return 0
    placeholders = ",".join("?" * len(ids))
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            f"UPDATE discord_bookmarks SET claimed_at = datetime('now') WHERE id IN ({placeholders})",
            ids,
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def insert_analysis(
    db_path: Path | str,
    *,
    bookmark_id: int,
    artifact_type: str,
    summary: str,
    structured_json: dict,
    vault_path: str | None = None,
    gbrain_chunk_ids: list[str] | None = None,
    model_used: str | None = None,
    cost_usd: float = 0.0,
    error_text: str | None = None,
    retries: int = 0,
) -> int:
    """Insert an analysis row. Returns the new id."""
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            """
            INSERT INTO discord_analyses
              (bookmark_id, artifact_type, summary, structured_json, vault_path,
               gbrain_chunk_ids, model_used, cost_usd, error_text, retries)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                bookmark_id,
                artifact_type,
                summary,
                json.dumps(structured_json),
                vault_path,
                json.dumps(gbrain_chunk_ids or []),
                model_used,
                cost_usd,
                error_text,
                retries,
            ),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def mark_analyzed(db_path: Path | str, bookmark_id: int, analysis_id: int) -> None:
    """Finalize a row — sets analyzed_at = now() and links analysis_id."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "UPDATE discord_bookmarks SET analyzed_at = datetime('now'), analysis_id = ? WHERE id = ?",
            (analysis_id, bookmark_id),
        )
        conn.commit()
    finally:
        conn.close()


def daily_cost_usd(db_path: Path | str) -> float:
    """SUM of today's cost_usd."""
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) FROM discord_analyses "
            "WHERE date(created_at) = date('now')"
        ).fetchone()
        return float(row[0])
    finally:
        conn.close()
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd engine && .venv/Scripts/python -m pytest tests/test_discord_deep_analyzer/test_storage.py -v
```
Expected: 8 passed.

- [ ] **Step 6: Commit**

```bash
git add engine/discord/deep_analyzer/__init__.py \
        engine/discord/deep_analyzer/storage.py \
        engine/tests/test_discord_deep_analyzer/__init__.py \
        engine/tests/test_discord_deep_analyzer/conftest.py \
        engine/tests/test_discord_deep_analyzer/test_storage.py
git commit -m "feat(discord): deep_analyzer storage + schema migration"
```

---

# Phase 1 — Text handler validates end-to-end pipeline

## Task 2: `models.py` — Pydantic v2 result types

**Files:**
- Create: `engine/discord/deep_analyzer/models.py`
- Create: `engine/tests/test_discord_deep_analyzer/test_models.py`

- [ ] **Step 1: Write the test**

`engine/tests/test_discord_deep_analyzer/test_models.py`:
```python
"""Tests for deep_analyzer.models."""
import pytest
from pydantic import ValidationError

from engine.discord.deep_analyzer.models import AnalysisResult, ArtifactType, LLMUsage


def test_analysis_result_minimal_construction():
    r = AnalysisResult(
        bookmark_id=1,
        artifact_type=ArtifactType.TEXT,
        summary="hi",
        structured={},
        model_used="gemini-2.5-flash",
        usage=LLMUsage(input_tokens=10, output_tokens=5),
        cost_usd=0.0001,
    )
    assert r.bookmark_id == 1
    assert r.artifact_type == "text"


def test_artifact_type_rejects_unknown():
    with pytest.raises(ValidationError):
        AnalysisResult(
            bookmark_id=1,
            artifact_type="unknown",  # type: ignore[arg-type]
            summary="x",
            structured={},
            model_used="m",
            usage=LLMUsage(input_tokens=0, output_tokens=0),
            cost_usd=0,
        )


def test_llm_usage_total_tokens():
    u = LLMUsage(input_tokens=10, output_tokens=20)
    assert u.total_tokens == 30
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd engine && .venv/Scripts/python -m pytest tests/test_discord_deep_analyzer/test_models.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement `models.py`**

`engine/discord/deep_analyzer/models.py`:
```python
"""Pydantic v2 result types for deep_analyzer."""
from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ArtifactType(StrEnum):
    TEXT = "text"
    URL = "url"
    IMAGE = "image"
    AUDIO = "audio"
    DOCUMENT = "document"


class LLMUsage(BaseModel):
    model_config = ConfigDict(frozen=True)
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class AnalysisResult(BaseModel):
    """A single artifact's analysis output. Persisted to discord_analyses."""
    model_config = ConfigDict(frozen=True)

    bookmark_id: int
    artifact_type: ArtifactType
    summary: str
    structured: dict[str, Any] = Field(default_factory=dict)
    model_used: str
    usage: LLMUsage
    cost_usd: float
    vault_path: str | None = None
    gbrain_chunk_ids: list[str] = Field(default_factory=list)
    error_text: str | None = None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd engine && .venv/Scripts/python -m pytest tests/test_discord_deep_analyzer/test_models.py -v
```
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add engine/discord/deep_analyzer/models.py \
        engine/tests/test_discord_deep_analyzer/test_models.py
git commit -m "feat(discord): deep_analyzer result models (Pydantic v2)"
```

---

## Task 3: `llm.py` — adapter over engine's `JarvisLLMClient`

**Files:**
- Create: `engine/discord/deep_analyzer/llm.py`
- Create: `engine/tests/test_discord_deep_analyzer/test_llm.py`

**Critical correction (vs original draft):** Hermes is a Telegram/Discord adapter with no REST LLM endpoint. Use the **existing** `engine.llm.client.JarvisLLMClient` (Anthropic primary, Gemini failover, cost tracking, `llm_path_healthy` health signal — all already wired). The deep_analyzer's `llm.py` is a thin async adapter exposing `call_text(prompt, system)` and `call_vision(prompt, image_bytes, mime)` that the handlers can call without each one knowing about messages-format details.

Anthropic key comes from `engine/.env` (already loaded by `engine.config.settings`). Google failover key (`GOOGLE_API_KEY` / `GEMINI_API_KEY`) is read by `JarvisLLMClient` itself — no extra wiring needed.

- [ ] **Step 1: Write the test**

`engine/tests/test_discord_deep_analyzer/test_llm.py`:
```python
"""Tests for deep_analyzer.llm — adapter over JarvisLLMClient."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from engine.discord.deep_analyzer import llm
from engine.discord.deep_analyzer.models import LLMUsage
from engine.llm.client import LLMCallResult


@pytest.fixture
def fake_engine_client():
    """Patch the underlying JarvisLLMClient instance for the test."""
    fake = MagicMock()
    fake.call = AsyncMock()
    with patch("engine.discord.deep_analyzer.llm._get_engine_client", return_value=fake):
        yield fake


@pytest.mark.asyncio
async def test_call_text_returns_llmresponse(fake_engine_client):
    fake_engine_client.call.return_value = LLMCallResult(
        success=True,
        model="claude-haiku-4-5-20251001",
        input_tokens=10,
        output_tokens=5,
        cost_usd=0.000028,
        latency_ms=120,
        retries=0,
        content="hello back",
    )
    resp = await llm.call_text(prompt="hi", system="be terse")
    assert resp.reply == "hello back"
    assert resp.model == "claude-haiku-4-5-20251001"
    assert resp.usage.total_tokens == 15
    assert resp.cost_usd == pytest.approx(0.000028)


@pytest.mark.asyncio
async def test_call_text_raises_on_failed_result(fake_engine_client):
    fake_engine_client.call.return_value = LLMCallResult(
        success=False,
        model="claude-haiku-4-5-20251001",
        input_tokens=0,
        output_tokens=0,
        cost_usd=0,
        latency_ms=10,
        retries=3,
        content="",
        error="all retries exhausted",
    )
    with pytest.raises(llm.LLMError):
        await llm.call_text(prompt="hi")


@pytest.mark.asyncio
async def test_call_text_uses_haiku_by_default(fake_engine_client):
    fake_engine_client.call.return_value = LLMCallResult(
        success=True, model="claude-haiku-4-5-20251001",
        input_tokens=1, output_tokens=1, cost_usd=0.0,
        latency_ms=1, retries=0, content="x",
    )
    await llm.call_text(prompt="hi")
    args, kwargs = fake_engine_client.call.call_args
    assert kwargs["model"] == "claude-haiku-4-5-20251001"
    assert kwargs["agent_name"] == "deep_analyzer"


@pytest.mark.asyncio
async def test_call_vision_passes_multimodal_content(fake_engine_client):
    fake_engine_client.call.return_value = LLMCallResult(
        success=True, model="claude-haiku-4-5-20251001",
        input_tokens=100, output_tokens=20, cost_usd=0.000160,
        latency_ms=200, retries=0, content="red square",
    )
    out = await llm.call_vision(prompt="describe", image_bytes=b"\x89PNG\r\n", mime="image/png")
    assert out.reply == "red square"
    # Confirm the user message has a content list (multimodal)
    args, kwargs = fake_engine_client.call.call_args
    msgs = kwargs["messages"]
    assert isinstance(msgs[0]["content"], list)
    assert any(part.get("type") == "image" for part in msgs[0]["content"])
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd engine && .venv/Scripts/python -m pytest tests/test_discord_deep_analyzer/test_llm.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement `llm.py`**

`engine/discord/deep_analyzer/llm.py`:
```python
"""LLM adapter for deep_analyzer.

Thin layer over `engine.llm.client.JarvisLLMClient` — reuses Anthropic retry +
Gemini failover + cost tracking + `llm_path_healthy` health signal. Exposes
`call_text` and `call_vision` so handlers don't need to know about the
messages-format or model selection.
"""
from __future__ import annotations

import base64
import logging
import os
from dataclasses import dataclass
from typing import Any

from ..models import LLMUsage  # noqa: TID252 — package-local import
from engine.llm.client import JarvisLLMClient

logger = logging.getLogger(__name__)


class LLMError(RuntimeError):
    """LLM call failed (after retries + fallback)."""


@dataclass(frozen=True)
class LLMResponse:
    reply: str
    model: str
    usage: LLMUsage
    cost_usd: float


# Singleton — JarvisLLMClient is expensive to construct (DB connection, anthropic client).
_client_singleton: JarvisLLMClient | None = None

# Default model for deep_analyzer: Haiku 4.5 (cheapest Claude tier).
# Failover chain inside JarvisLLMClient: Haiku → no further Claude tier →
# (if GOOGLE_API_KEY set) gemini-2.0-flash.
DEFAULT_MODEL = "claude-haiku-4-5-20251001"
AGENT_NAME = "deep_analyzer"


def _get_engine_client() -> JarvisLLMClient:
    global _client_singleton
    if _client_singleton is None:
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        db_path = os.getenv("JARVIS_LLM_COST_DB", "data/llm_costs.db")
        _client_singleton = JarvisLLMClient(api_key=api_key, db_path=db_path)
    return _client_singleton


def _to_response(r) -> "LLMResponse":
    if not r.success:
        raise LLMError(r.error or "LLM call failed without error message")
    return LLMResponse(
        reply=r.content,
        model=r.model,
        usage=LLMUsage(input_tokens=r.input_tokens, output_tokens=r.output_tokens),
        cost_usd=float(r.cost_usd or 0.0),
    )


async def call_text(*, prompt: str, system: str | None = None) -> LLMResponse:
    """Single text turn. Returns the model's text reply + usage + cost."""
    client = _get_engine_client()
    messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
    r = await client.call(
        model=DEFAULT_MODEL,
        system=system or "",
        messages=messages,
        max_tokens=1024,
        agent_name=AGENT_NAME,
        temperature=0.2,
        tier="fast",
        compact=False,  # deep_analyzer prompts are short; skip compaction overhead
    )
    return _to_response(r)


async def call_vision(*, prompt: str, image_bytes: bytes, mime: str) -> LLMResponse:
    """Vision turn — single image + text prompt. Uses Anthropic multimodal."""
    client = _get_engine_client()
    b64 = base64.b64encode(image_bytes).decode("ascii")
    messages: list[dict[str, Any]] = [{
        "role": "user",
        "content": [
            {"type": "image", "source": {"type": "base64", "media_type": mime, "data": b64}},
            {"type": "text", "text": prompt},
        ],
    }]
    r = await client.call(
        model=DEFAULT_MODEL,
        system="",
        messages=messages,
        max_tokens=1024,
        agent_name=AGENT_NAME,
        temperature=0.2,
        tier="fast",
        compact=False,
    )
    return _to_response(r)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd engine && .venv/Scripts/python -m pytest tests/test_discord_deep_analyzer/test_llm.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add engine/discord/deep_analyzer/llm.py \
        engine/tests/test_discord_deep_analyzer/test_llm.py
git commit -m "feat(discord): deep_analyzer LLM adapter over JarvisLLMClient"
```

---

## Task 4: `prompts.py` — per-artifact prompt templates

**Files:**
- Create: `engine/discord/deep_analyzer/prompts.py`

- [ ] **Step 1: Implement `prompts.py` (no separate tests — pure constants tested via handler integration)**

`engine/discord/deep_analyzer/prompts.py`:
```python
"""Prompt templates for each artifact type.

All prompts ask the model to respond with strict JSON so handlers can parse
structured fields reliably. The summary field is always required.
"""
from __future__ import annotations

TEXT_SYSTEM = """\
You analyze short text snippets that a futures/options trader saved as a Discord bookmark.
Respond with strict JSON only. No prose outside the JSON object.

Fields:
- summary (string): one-paragraph summary of what the text is about and why it might matter to a trader.
- tickers (list[str]): any explicit ticker symbols mentioned (uppercase, no $).
- topics (list[str]): 1-4 short tag-like topics.
- sentiment ("bullish" | "bearish" | "neutral" | "mixed"): direction implied by the text.
- has_action_item (bool): true if it implies the user should DO something.
- priority (1-5): trader-relevance, where 5 = "look at this before market open".
"""

URL_SYSTEM = """\
You analyze the contents of a web page or social media post that a futures/options trader saved.
The user already extracted the readable body — you do not need to fetch anything else.
Respond with strict JSON only.

Fields:
- summary (string): one-paragraph summary of the page or post.
- tickers (list[str]): explicit ticker symbols mentioned (uppercase, no $).
- topics (list[str]): 1-4 short tags.
- sentiment ("bullish" | "bearish" | "neutral" | "mixed"): direction implied.
- has_action_item (bool): true if it implies the user should DO something.
- source_kind ("x_post" | "github" | "article" | "video" | "other"): best fit.
- author (string|null): who wrote/posted it, if recoverable.
- priority (1-5): trader-relevance.
"""

IMAGE_SYSTEM = """\
You analyze an image that a futures/options trader saved as a Discord attachment.
Respond with strict JSON only.

Fields:
- summary (string): one-paragraph description.
- ocr_text (string): any text visible in the image.
- is_chart (bool): true if this is a price chart.
- ticker (string|null): if a chart, what symbol.
- timeframe (string|null): if a chart, what timeframe (e.g. "5m", "1h", "1d").
- topics (list[str]): 1-4 short tags.
- priority (1-5): trader-relevance.
"""

AUDIO_SYSTEM = """\
You analyze a transcribed voice memo that the user dictated and saved as a Discord attachment.
Respond with strict JSON only.

Fields:
- summary (string): one-paragraph summary of the memo.
- tickers (list[str]): symbols mentioned (uppercase, no $).
- topics (list[str]): 1-4 short tags.
- has_action_item (bool): true if the user said they intend to DO something.
- priority (1-5): trader-relevance.
"""

DOCUMENT_SYSTEM = """\
You analyze the extracted text of a PDF or document a futures/options trader saved.
Respond with strict JSON only.

Fields:
- summary (string): one-paragraph summary.
- tickers (list[str]): symbols mentioned (uppercase, no $).
- topics (list[str]): 1-4 short tags.
- has_action_item (bool): true if it implies the user should DO something.
- key_points (list[str]): up to 5 salient points.
- priority (1-5): trader-relevance.
"""
```

- [ ] **Step 2: Commit**

```bash
git add engine/discord/deep_analyzer/prompts.py
git commit -m "feat(discord): deep_analyzer prompt templates"
```

---

## Task 5: `handlers/base.py` — Handler protocol

**Files:**
- Create: `engine/discord/deep_analyzer/handlers/__init__.py`
- Create: `engine/discord/deep_analyzer/handlers/base.py`

- [ ] **Step 1: Create handlers package and protocol**

`engine/discord/deep_analyzer/handlers/__init__.py`:
```python
```

`engine/discord/deep_analyzer/handlers/base.py`:
```python
"""Handler protocol for artifact-specific analyzers."""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from ..models import AnalysisResult


@runtime_checkable
class Handler(Protocol):
    """All handlers expose the same async entry point.

    The runner passes the row dict (from discord_bookmarks) and gets back
    a fully-formed AnalysisResult (or raises on permanent failure).
    """

    async def analyze(self, row: dict[str, Any]) -> AnalysisResult: ...
```

- [ ] **Step 2: Commit**

```bash
git add engine/discord/deep_analyzer/handlers/__init__.py \
        engine/discord/deep_analyzer/handlers/base.py
git commit -m "feat(discord): deep_analyzer handler protocol"
```

---

## Task 6: `handlers/text.py` — text artifact handler

**Files:**
- Create: `engine/discord/deep_analyzer/handlers/text.py`
- Create: `engine/tests/test_discord_deep_analyzer/test_handlers/__init__.py`
- Create: `engine/tests/test_discord_deep_analyzer/test_handlers/test_text.py`

- [ ] **Step 1: Create test package init and write the test**

`engine/tests/test_discord_deep_analyzer/test_handlers/__init__.py`:
```python
```

`engine/tests/test_discord_deep_analyzer/test_handlers/test_text.py`:
```python
"""Tests for handlers.text."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from engine.discord.deep_analyzer.handlers.text import TextHandler
from engine.discord.deep_analyzer.llm import LLMResponse
from engine.discord.deep_analyzer.models import LLMUsage


@pytest.mark.asyncio
async def test_text_handler_returns_structured_result():
    fake = LLMResponse(
        reply=json.dumps({
            "summary": "Trader thought about MES short",
            "tickers": ["MES"],
            "topics": ["futures", "intraday"],
            "sentiment": "bearish",
            "has_action_item": True,
            "priority": 4,
        }),
        model="gemini-2.5-flash",
        provider="google",
        usage=LLMUsage(input_tokens=50, output_tokens=80),
        cost_usd=0.000215,
    )
    with patch("engine.discord.deep_analyzer.handlers.text.call_text", AsyncMock(return_value=fake)):
        h = TextHandler()
        out = await h.analyze({"id": 1, "content": "thinking about shorting MES if it breaks 5800"})
    assert out.bookmark_id == 1
    assert out.artifact_type == "text"
    assert out.structured["tickers"] == ["MES"]
    assert "MES" in out.summary
    assert out.model_used == "gemini-2.5-flash"


@pytest.mark.asyncio
async def test_text_handler_handles_non_json_reply_gracefully():
    fake = LLMResponse(
        reply="plain prose not JSON",
        model="gemini-2.5-flash",
        provider="google",
        usage=LLMUsage(input_tokens=5, output_tokens=5),
        cost_usd=0.0,
    )
    with patch("engine.discord.deep_analyzer.handlers.text.call_text", AsyncMock(return_value=fake)):
        h = TextHandler()
        out = await h.analyze({"id": 1, "content": "noise"})
    # Falls back to using the raw reply as summary
    assert out.summary == "plain prose not JSON"
    assert out.structured == {}
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd engine && .venv/Scripts/python -m pytest tests/test_discord_deep_analyzer/test_handlers/test_text.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement `handlers/text.py`**

`engine/discord/deep_analyzer/handlers/text.py`:
```python
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
    summary = data.pop("summary", reply)
    return summary, data


class TextHandler:
    async def analyze(self, row: dict[str, Any]) -> AnalysisResult:
        content = row.get("content") or ""
        if not content.strip():
            return AnalysisResult(
                bookmark_id=int(row["id"]),
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
            bookmark_id=int(row["id"]),
            artifact_type=ArtifactType.TEXT,
            summary=summary,
            structured=structured,
            model_used=resp.model,
            usage=resp.usage,
            cost_usd=resp.cost_usd,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd engine && .venv/Scripts/python -m pytest tests/test_discord_deep_analyzer/test_handlers/test_text.py -v
```
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add engine/discord/deep_analyzer/handlers/text.py \
        engine/tests/test_discord_deep_analyzer/test_handlers/__init__.py \
        engine/tests/test_discord_deep_analyzer/test_handlers/test_text.py
git commit -m "feat(discord): deep_analyzer text handler"
```

---

## Task 7: `vault.py` — Obsidian markdown writer

**Files:**
- Create: `engine/discord/deep_analyzer/vault.py`
- Create: `engine/tests/test_discord_deep_analyzer/test_vault.py`

- [ ] **Step 1: Write the test**

`engine/tests/test_discord_deep_analyzer/test_vault.py`:
```python
"""Tests for deep_analyzer.vault."""
from __future__ import annotations

from pathlib import Path

import pytest

from engine.discord.deep_analyzer.models import AnalysisResult, ArtifactType, LLMUsage
from engine.discord.deep_analyzer.vault import write_page


@pytest.fixture
def sample_result() -> AnalysisResult:
    return AnalysisResult(
        bookmark_id=42,
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
    # second write — same id + slug → same path; idempotent overwrite
    out2 = write_page(
        result=sample_result,
        vault_root=tmp_path,
        posted_at="2026-05-20T10:00:00Z",
        slug_source="same slug",
        discord_url="https://discord.com/channels/g/c/m",
    )
    assert out1 == out2
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd engine && .venv/Scripts/python -m pytest tests/test_discord_deep_analyzer/test_vault.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement `vault.py`**

`engine/discord/deep_analyzer/vault.py`:
```python
"""Write per-artifact analysis pages into the Obsidian vault."""
from __future__ import annotations

import os
import re
from pathlib import Path

from .models import AnalysisResult

DEFAULT_VAULT_ROOT = Path(os.path.expanduser("~/my-vault"))
MAX_FILENAME_CHARS = 100  # bookmark_id + slug + .md


def _slugify(text: str, max_len: int = 60) -> str:
    text = re.sub(r"[^a-zA-Z0-9\s-]", "", text).strip().lower()
    text = re.sub(r"\s+", "-", text)
    return text[:max_len] or "untitled"


def _build_filename(bookmark_id: int, slug_source: str) -> str:
    slug = _slugify(slug_source)
    name = f"{bookmark_id}--{slug}.md"
    return name[:MAX_FILENAME_CHARS]


def _render(result: AnalysisResult, posted_at: str, discord_url: str) -> str:
    tags = sorted(set(["discord-feed", result.artifact_type.value, *result.structured.get("topics", [])]))
    tickers = result.structured.get("tickers", [])
    fm_lines = [
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
        __import__("json").dumps(result.structured, indent=2),
        "```",
        "",
        f"[Original Discord message]({discord_url})",
    ]
    return "\n".join(fm_lines)


def write_page(
    *,
    result: AnalysisResult,
    posted_at: str,
    slug_source: str,
    discord_url: str,
    vault_root: Path | None = None,
) -> Path:
    """Write the analysis to Obsidian. Returns absolute file path."""
    root = Path(vault_root) if vault_root else DEFAULT_VAULT_ROOT
    date_str = posted_at[:10]  # YYYY-MM-DD
    folder = root / "Discord-Feed" / date_str
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / _build_filename(result.bookmark_id, slug_source)
    path.write_text(_render(result, posted_at, discord_url), encoding="utf-8")
    return path
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd engine && .venv/Scripts/python -m pytest tests/test_discord_deep_analyzer/test_vault.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add engine/discord/deep_analyzer/vault.py \
        engine/tests/test_discord_deep_analyzer/test_vault.py
git commit -m "feat(discord): deep_analyzer Obsidian vault writer"
```

---

## Task 8: `gbrain_sink.py` — write analysis to gbrain raw/ ingest directory

**Files:**
- Create: `engine/discord/deep_analyzer/gbrain_sink.py`
- Create: `engine/tests/test_discord_deep_analyzer/test_gbrain_sink.py`

**Notes:** Per memory `project_gbrain_trading_reinit_procedure.md`, the trading brain auto-ingests files dropped into its `raw/` watched directory. Default location: `~/.gbrain-trading/raw/discord-feed/`. Override via `GBRAIN_RAW_DIR` env. If the directory doesn't exist (gbrain not installed in this environment), skip silently — gbrain ingest must not block the vault write per spec.

- [ ] **Step 1: Write the test**

`engine/tests/test_discord_deep_analyzer/test_gbrain_sink.py`:
```python
"""Tests for deep_analyzer.gbrain_sink."""
from __future__ import annotations

from pathlib import Path

import pytest

from engine.discord.deep_analyzer.gbrain_sink import ingest
from engine.discord.deep_analyzer.models import AnalysisResult, ArtifactType, LLMUsage


@pytest.fixture
def sample() -> AnalysisResult:
    return AnalysisResult(
        bookmark_id=7,
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd engine && .venv/Scripts/python -m pytest tests/test_discord_deep_analyzer/test_gbrain_sink.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement `gbrain_sink.py`**

`engine/discord/deep_analyzer/gbrain_sink.py`:
```python
"""Side-effect sink: drop analyses into gbrain's raw/ watched directory."""
from __future__ import annotations

import logging
import os
from pathlib import Path

from .models import AnalysisResult

logger = logging.getLogger(__name__)


def _raw_dir() -> Path:
    return Path(os.getenv("GBRAIN_RAW_DIR", os.path.expanduser("~/.gbrain-trading/raw/discord-feed")))


def ingest(result: AnalysisResult, *, posted_at: str) -> list[str]:
    """Write a single markdown chunk for gbrain to ingest. Returns chunk-id list.

    Idempotent on (bookmark_id, artifact_type). Silent skip if dir missing.
    """
    raw = _raw_dir()
    if not raw.exists():
        logger.info("deep_analyzer.gbrain_sink: %s missing — skipping", raw)
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd engine && .venv/Scripts/python -m pytest tests/test_discord_deep_analyzer/test_gbrain_sink.py -v
```
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add engine/discord/deep_analyzer/gbrain_sink.py \
        engine/tests/test_discord_deep_analyzer/test_gbrain_sink.py
git commit -m "feat(discord): deep_analyzer gbrain ingest sink"
```

---

## Task 9: `runner.py` — orchestrator with text-only dispatch (Phase 1 end-to-end)

**Files:**
- Create: `engine/discord/deep_analyzer/runner.py`
- Create: `engine/tests/test_discord_deep_analyzer/test_runner.py`

**Notes:** This is the integration point. Runner picks rows, picks the right handler by artifact-type inference, calls it, persists analysis + vault + gbrain, finalizes the bookmark. For Phase 1, only TextHandler is wired — other types are skipped with a log line.

- [ ] **Step 1: Write the test**

`engine/tests/test_discord_deep_analyzer/test_runner.py`:
```python
"""Tests for deep_analyzer.runner."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from engine.discord.deep_analyzer import runner, storage
from engine.discord.deep_analyzer.models import AnalysisResult, ArtifactType, LLMUsage


@pytest.fixture
def text_only_db(seeded_db: Path) -> Path:
    """Reduce to one text-only row (`m1`)."""
    storage.migrate(seeded_db)
    conn = sqlite3.connect(seeded_db)
    conn.execute("DELETE FROM discord_bookmarks WHERE message_id != 'm1'")
    conn.commit()
    conn.close()
    return seeded_db


@pytest.fixture
def stub_text_result():
    return AnalysisResult(
        bookmark_id=0,  # will be overridden
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
        "engine.discord.deep_analyzer.handlers.text.TextHandler.analyze",
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
async def test_runner_halts_on_daily_budget_breach(
    text_only_db, tmp_path, monkeypatch
):
    monkeypatch.setenv("DEEP_ANALYZER_DAILY_USD", "0.00")  # any cost breaches
    conn = sqlite3.connect(text_only_db)
    conn.execute(
        "INSERT INTO discord_analyses (bookmark_id, artifact_type, summary, structured_json, cost_usd) "
        "VALUES (1, 'text', 's', '{}', 5.00)"
    )
    conn.commit()
    conn.close()

    n = await runner.run_once(db_path=text_only_db, vault_root=tmp_path, limit=5)
    assert n == 0  # budget breached, nothing processed


@pytest.mark.asyncio
async def test_runner_writes_failure_row_on_handler_exception(
    text_only_db, tmp_path, monkeypatch
):
    async def boom(self, row):
        raise RuntimeError("transient upstream")

    monkeypatch.setattr(
        "engine.discord.deep_analyzer.handlers.text.TextHandler.analyze",
        boom,
    )
    n = await runner.run_once(db_path=text_only_db, vault_root=tmp_path, limit=5)
    assert n == 0

    conn = sqlite3.connect(text_only_db)
    conn.row_factory = sqlite3.Row
    a = conn.execute("SELECT * FROM discord_analyses").fetchone()
    row = conn.execute("SELECT analyzed_at FROM discord_bookmarks WHERE id=1").fetchone()
    conn.close()
    assert a is not None  # failure row recorded
    assert "transient" in (a["error_text"] or "")
    assert row["analyzed_at"] is None  # not marked analyzed; will retry next run
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd engine && .venv/Scripts/python -m pytest tests/test_discord_deep_analyzer/test_runner.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement `runner.py`**

`engine/discord/deep_analyzer/runner.py`:
```python
"""Deep analyzer orchestrator — picks rows, dispatches, persists, finalizes."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from . import storage, vault, gbrain_sink
from .handlers.text import TextHandler
from .models import ArtifactType

logger = logging.getLogger(__name__)

DISCORD_GUILD = "1490851278601982165"
DISCORD_CHANNEL = "1490851279180660819"


def _infer_artifact_type(row: dict[str, Any]) -> ArtifactType:
    """Decide which handler should process this row.

    Phase 1 only routes text; everything else is skipped (logged, not failed)
    so the runner can advance on text rows without TextHandler-only churn.
    """
    if row.get("attachment_urls"):
        # Will be split into image/audio/document in Phase 3.
        return ArtifactType.IMAGE
    if row.get("url"):
        return ArtifactType.URL
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
        logger.warning("deep_analyzer: budget breached ($%.4f / $%.2f) — halting", spent, _daily_budget_usd())
        return 0

    rows = storage.pick_unanalyzed(db_path, limit=limit)
    if not rows:
        return 0
    storage.claim_rows(db_path, [r["id"] for r in rows])

    handlers = {ArtifactType.TEXT: TextHandler()}
    written = 0

    for row in rows:
        a_type = _infer_artifact_type(row)
        handler = handlers.get(a_type)
        if handler is None:
            logger.info("deep_analyzer: skipping %s — handler for %s not wired in Phase 1", row["id"], a_type)
            continue
        try:
            result = await handler.analyze(row)
        except Exception as exc:  # noqa: BLE001 — record failure, don't crash run
            logger.exception("deep_analyzer: handler error on row %s", row["id"])
            storage.insert_analysis(
                db_path=db_path,
                bookmark_id=int(row["id"]),
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
            bookmark_id=int(row["id"]),
            artifact_type=result.artifact_type.value,
            summary=result.summary,
            structured_json=result.structured,
            vault_path=str(vault_path),
            gbrain_chunk_ids=chunk_ids,
            model_used=result.model_used,
            cost_usd=result.cost_usd,
        )
        storage.mark_analyzed(db_path, int(row["id"]), analysis_id)
        written += 1

    return written
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd engine && .venv/Scripts/python -m pytest tests/test_discord_deep_analyzer/test_runner.py -v
```
Expected: 3 passed.

- [ ] **Step 5: Run full new-module test suite to confirm nothing regressed**

```bash
cd engine && .venv/Scripts/python -m pytest tests/test_discord_deep_analyzer/ -v
```
Expected: all tests pass (storage: 8, models: 3, llm: 4, text handler: 2, vault: 4, gbrain: 2, runner: 3 = 26).

- [ ] **Step 6: Commit**

```bash
git add engine/discord/deep_analyzer/runner.py \
        engine/tests/test_discord_deep_analyzer/test_runner.py
git commit -m "feat(discord): deep_analyzer runner (Phase 1 text-only end-to-end)"
```

---

## Task 10: Phase 1 manual validation — analyze 10 historical text-only rows

**Files:**
- Create: `scripts/deep_analyzer_phase1_smoke.ps1`

- [ ] **Step 1: Write the smoke script**

`scripts/deep_analyzer_phase1_smoke.ps1` (save as **UTF-8 with BOM**):
```powershell
#requires -Version 5.1
$ErrorActionPreference = 'Stop'
Start-Transcript -Path "$env:TEMP\deep_analyzer_phase1_smoke.log" -Append

$repo = "C:\Users\mattm\ThinkorSwim\jarvis-trader"
$db   = "$repo\data\discord.db"
$python = "$repo\engine\.venv\Scripts\python.exe"

Write-Host "Phase 1 smoke: analyzing up to 10 text-only historical rows..."

& $python -c @"
import asyncio
from pathlib import Path
from engine.discord.deep_analyzer.runner import run_once

async def main():
    total = 0
    for _ in range(2):  # 2 batches of 5
        n = await run_once(
            db_path=Path(r'$db'),
            vault_root=Path.home() / 'my-vault',
            limit=5,
        )
        total += n
        if n == 0:
            break
    print(f'Phase 1 smoke wrote {total} analyses')

asyncio.run(main())
"@

Stop-Transcript
```

- [ ] **Step 2: Run the smoke script**

```powershell
pwsh -File scripts\deep_analyzer_phase1_smoke.ps1
```
Expected: "Phase 1 smoke wrote N analyses" where N > 0.

- [ ] **Step 3: Inspect output**

```powershell
ls ~/my-vault/Discord-Feed/
sqlite3 data/discord.db "SELECT artifact_type, COUNT(*), SUM(cost_usd) FROM discord_analyses GROUP BY artifact_type"
```
Expected: at least one date folder under `Discord-Feed/`; SQL row showing `text|N|<small cost>`.

- [ ] **Step 4: Manually open 2-3 vault pages and verify content quality**

Open in Obsidian or any markdown viewer. Each page should have:
- YAML frontmatter (date, artifact_type, model, cost_usd, tickers, tags)
- "# Summary" section with a coherent paragraph
- "# Structured" code-fenced JSON block
- Working "Original Discord message" link

- [ ] **Step 5: Commit the smoke script**

```bash
git add scripts/deep_analyzer_phase1_smoke.ps1
git commit -m "feat(discord): Phase 1 smoke script for deep_analyzer text handler"
```

---

# Phase 2 — URL handler

## Task 11: `handlers/url.py` — URL fetch + readability + X-post + LLM

**Files:**
- Create: `engine/discord/deep_analyzer/handlers/url.py`
- Create: `engine/tests/test_discord_deep_analyzer/test_handlers/test_url.py`

**Notes:** Use `httpx` for fetch and `readability-lxml` for body extraction. X.com posts get a lightweight special case: try fetching as HTML; if the body is the X "JavaScript required" notice, fall back to using the URL itself as the prompt content (the LLM has enough context from the URL slug and trailing path).

- [ ] **Step 1: Install dependencies**

```bash
cd engine && .venv/Scripts/python -m pip install readability-lxml lxml httpx
```

- [ ] **Step 2: Write the test**

`engine/tests/test_discord_deep_analyzer/test_handlers/test_url.py`:
```python
"""Tests for handlers.url."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
import respx
from httpx import Response

from engine.discord.deep_analyzer.handlers.url import UrlHandler
from engine.discord.deep_analyzer.llm import LLMResponse
from engine.discord.deep_analyzer.models import LLMUsage


@pytest.fixture
def fake_llm():
    return LLMResponse(
        reply=json.dumps({
            "summary": "GitHub repo about vol scanning",
            "tickers": [],
            "topics": ["github", "tools"],
            "sentiment": "neutral",
            "has_action_item": False,
            "source_kind": "github",
            "author": "someone",
            "priority": 3,
        }),
        model="gemini-2.5-flash",
        provider="google",
        usage=LLMUsage(input_tokens=400, output_tokens=80),
        cost_usd=0.000320,
    )


@pytest.mark.asyncio
async def test_url_handler_fetches_and_summarizes_article(fake_llm):
    html = "<html><body><article><h1>Hi</h1><p>Body text here.</p></article></body></html>"
    with respx.mock() as mock:
        mock.get("https://example.com/article").mock(return_value=Response(200, text=html))
        with patch("engine.discord.deep_analyzer.handlers.url.call_text", AsyncMock(return_value=fake_llm)):
            out = await UrlHandler().analyze(
                {"id": 9, "url": "https://example.com/article", "content": None}
            )
    assert out.artifact_type == "url"
    assert "GitHub" in out.summary or "vol" in out.summary
    assert out.structured["source_kind"] == "github"


@pytest.mark.asyncio
async def test_url_handler_handles_x_js_required_fallback(fake_llm):
    js_required = "<html><body><noscript>Please enable JavaScript</noscript></body></html>"
    with respx.mock() as mock:
        mock.get("https://x.com/foo/status/1").mock(return_value=Response(200, text=js_required))
        with patch("engine.discord.deep_analyzer.handlers.url.call_text", AsyncMock(return_value=fake_llm)):
            out = await UrlHandler().analyze(
                {"id": 9, "url": "https://x.com/foo/status/1", "content": None}
            )
    # Even with the JS-required body, we still get an analysis (LLM is fed the URL)
    assert out.summary


@pytest.mark.asyncio
async def test_url_handler_handles_404(fake_llm):
    with respx.mock() as mock:
        mock.get("https://example.com/gone").mock(return_value=Response(404))
        with patch("engine.discord.deep_analyzer.handlers.url.call_text", AsyncMock(return_value=fake_llm)):
            out = await UrlHandler().analyze(
                {"id": 9, "url": "https://example.com/gone", "content": None}
            )
    # 404 doesn't kill the row — LLM gets just the URL as context
    assert out.summary
```

- [ ] **Step 3: Run test to verify it fails**

```bash
cd engine && .venv/Scripts/python -m pytest tests/test_discord_deep_analyzer/test_handlers/test_url.py -v
```
Expected: ImportError.

- [ ] **Step 4: Implement `handlers/url.py`**

`engine/discord/deep_analyzer/handlers/url.py`:
```python
"""URL artifact handler — fetch + readability + LLM."""
from __future__ import annotations

import json
import logging
from typing import Any

import httpx
from readability import Document  # readability-lxml

from ..llm import call_text
from ..models import AnalysisResult, ArtifactType, LLMUsage
from ..prompts import URL_SYSTEM
from .text import _parse_json_reply  # re-use the JSON parsing helper

logger = logging.getLogger(__name__)

USER_AGENT = "JarvisTrader/1.0 (+https://github.com/mattamundson)"
MAX_BODY_CHARS = 12_000  # cap to keep token cost bounded
TIMEOUT = httpx.Timeout(20.0, read=30.0)


async def _fetch_html(url: str) -> str | None:
    try:
        async with httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT},
            timeout=TIMEOUT,
            follow_redirects=True,
        ) as cli:
            r = await cli.get(url)
            if r.status_code != 200:
                logger.info("url_handler: %s returned %s", url, r.status_code)
                return None
            return r.text
    except httpx.RequestError as e:
        logger.info("url_handler: fetch error %s on %s", e, url)
        return None


def _extract_body(html: str) -> str:
    """Use readability-lxml to pull the main article body. Cap at MAX_BODY_CHARS."""
    try:
        doc = Document(html)
        body = doc.summary(html_partial=True)
        # Crude HTML strip — good enough for LLM input
        import re
        text = re.sub(r"<[^>]+>", " ", body)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:MAX_BODY_CHARS]
    except Exception as e:  # noqa: BLE001
        logger.info("url_handler: readability failed %s", e)
        return ""


def _is_js_required(body: str) -> bool:
    lowered = body.lower()
    return "enable javascript" in lowered or len(body.strip()) < 50


class UrlHandler:
    async def analyze(self, row: dict[str, Any]) -> AnalysisResult:
        url = row.get("url") or ""
        html = await _fetch_html(url) if url else None
        body = _extract_body(html) if html else ""

        if not body or _is_js_required(body):
            # Feed just the URL — LLM has enough context from the path for X posts, etc.
            prompt = f"URL only (fetch failed or JS-required): {url}"
        else:
            prompt = f"URL: {url}\n\nExtracted body:\n{body}"

        resp = await call_text(prompt=prompt, system=URL_SYSTEM)
        summary, structured = _parse_json_reply(resp.reply)

        return AnalysisResult(
            bookmark_id=int(row["id"]),
            artifact_type=ArtifactType.URL,
            summary=summary,
            structured=structured,
            model_used=resp.model,
            usage=resp.usage,
            cost_usd=resp.cost_usd,
        )
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd engine && .venv/Scripts/python -m pytest tests/test_discord_deep_analyzer/test_handlers/test_url.py -v
```
Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add engine/discord/deep_analyzer/handlers/url.py \
        engine/tests/test_discord_deep_analyzer/test_handlers/test_url.py
git commit -m "feat(discord): deep_analyzer URL handler (readability + X-post fallback)"
```

---

## Task 12: Wire URL handler into runner dispatch

**Files:**
- Modify: `engine/discord/deep_analyzer/runner.py` — update `handlers` dict
- Modify: `engine/tests/test_discord_deep_analyzer/test_runner.py` — add URL routing test

- [ ] **Step 1: Update the runner test to cover URL routing**

Append to `engine/tests/test_discord_deep_analyzer/test_runner.py`:
```python
@pytest.mark.asyncio
async def test_runner_routes_url_row_to_url_handler(seeded_db, tmp_path, monkeypatch):
    from engine.discord.deep_analyzer import storage as st
    st.migrate(seeded_db)

    # Keep only the X-post row
    import sqlite3 as _s
    c = _s.connect(seeded_db)
    c.execute("DELETE FROM discord_bookmarks WHERE message_id != 'm2'")
    c.commit(); c.close()

    monkeypatch.setenv("GBRAIN_RAW_DIR", str(tmp_path / "raw"))
    (tmp_path / "raw").mkdir()

    async def fake_url_analyze(self, row):
        return AnalysisResult(
            bookmark_id=int(row["id"]),
            artifact_type=ArtifactType.URL,
            summary="X post summary",
            structured={"source_kind": "x_post"},
            model_used="gemini-2.5-flash",
            usage=LLMUsage(input_tokens=20, output_tokens=10),
            cost_usd=0.0001,
        )

    monkeypatch.setattr(
        "engine.discord.deep_analyzer.handlers.url.UrlHandler.analyze",
        fake_url_analyze,
    )

    n = await runner.run_once(db_path=seeded_db, vault_root=tmp_path, limit=5)
    assert n == 1

    c = _s.connect(seeded_db)
    a = c.execute("SELECT artifact_type FROM discord_analyses").fetchone()
    c.close()
    assert a[0] == "url"
```

- [ ] **Step 2: Update `runner.py` to wire UrlHandler**

In `engine/discord/deep_analyzer/runner.py`, replace:
```python
from .handlers.text import TextHandler
```
with:
```python
from .handlers.text import TextHandler
from .handlers.url import UrlHandler
```

And replace:
```python
    handlers = {ArtifactType.TEXT: TextHandler()}
```
with:
```python
    handlers = {
        ArtifactType.TEXT: TextHandler(),
        ArtifactType.URL: UrlHandler(),
    }
```

- [ ] **Step 3: Run tests to verify they pass**

```bash
cd engine && .venv/Scripts/python -m pytest tests/test_discord_deep_analyzer/ -v
```
Expected: 30 passed (previous 26 + URL routing test + 3 URL handler tests).

- [ ] **Step 4: Commit**

```bash
git add engine/discord/deep_analyzer/runner.py \
        engine/tests/test_discord_deep_analyzer/test_runner.py
git commit -m "feat(discord): wire UrlHandler into deep_analyzer runner"
```

---

## Task 13: Phase 2 manual validation — analyze 50 URL backfill rows

**Files:** No new files. Re-uses Phase 1 smoke script.

- [ ] **Step 1: Reset claim state for fast iteration**

```powershell
sqlite3 data/discord.db "UPDATE discord_bookmarks SET claimed_at = NULL WHERE analyzed_at IS NULL"
```

- [ ] **Step 2: Run the runner in a loop for 50 items (10 invocations × 5/batch)**

```powershell
$python = "C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\.venv\Scripts\python.exe"
1..10 | ForEach-Object {
    & $python -c @"
import asyncio
from pathlib import Path
from engine.discord.deep_analyzer.runner import run_once
async def main():
    n = await run_once(
        db_path=Path(r'C:\Users\mattm\ThinkorSwim\jarvis-trader\data\discord.db'),
        vault_root=Path.home() / 'my-vault',
        limit=5,
    )
    print(f'batch wrote {n}')
asyncio.run(main())
"@
}
```

- [ ] **Step 3: Inspect**

```powershell
sqlite3 data/discord.db "SELECT artifact_type, COUNT(*), ROUND(SUM(cost_usd),4) FROM discord_analyses GROUP BY artifact_type"
sqlite3 data/discord.db "SELECT bookmark_id, error_text FROM discord_analyses WHERE error_text IS NOT NULL LIMIT 10"
```
Expected: `url|~50|~$0.05-0.20` and `text|~5-10|<$0.01`. Error rate <5%.

- [ ] **Step 4: Spot-check 5 vault pages** — confirm URL summaries are coherent and tickers/topics are extracted.

---

# Phase 3 — Attachment handlers (image, audio, document)

## Task 14: `handlers/image.py` — Gemini vision via Hermes

**Files:**
- Create: `engine/discord/deep_analyzer/handlers/image.py`
- Create: `engine/tests/test_discord_deep_analyzer/test_handlers/test_image.py`

- [ ] **Step 1: Install Pillow if missing**

```bash
cd engine && .venv/Scripts/python -c "import PIL" 2>nul || .venv/Scripts/python -m pip install Pillow
```

- [ ] **Step 2: Write the test**

`engine/tests/test_discord_deep_analyzer/test_handlers/test_image.py`:
```python
"""Tests for handlers.image."""
from __future__ import annotations

import json
from io import BytesIO
from unittest.mock import AsyncMock, patch

import pytest
import respx
from httpx import Response
from PIL import Image

from engine.discord.deep_analyzer.handlers.image import ImageHandler
from engine.discord.deep_analyzer.llm import LLMResponse
from engine.discord.deep_analyzer.models import LLMUsage


def _png_bytes(color=(255, 0, 0)) -> bytes:
    img = Image.new("RGB", (10, 10), color)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def fake_vision_llm():
    return LLMResponse(
        reply=json.dumps({
            "summary": "Red square",
            "ocr_text": "",
            "is_chart": False,
            "ticker": None,
            "timeframe": None,
            "topics": ["image"],
            "priority": 1,
        }),
        model="gemini-2.5-flash",
        provider="google",
        usage=LLMUsage(input_tokens=300, output_tokens=40),
        cost_usd=0.000190,
    )


@pytest.mark.asyncio
async def test_image_handler_downloads_and_analyzes(fake_vision_llm):
    with respx.mock() as mock:
        mock.get("https://cdn.discord.com/red.png").mock(
            return_value=Response(200, content=_png_bytes(), headers={"content-type": "image/png"})
        )
        with patch(
            "engine.discord.deep_analyzer.handlers.image.call_vision",
            AsyncMock(return_value=fake_vision_llm),
        ):
            out = await ImageHandler().analyze({
                "id": 5,
                "attachment_urls": "https://cdn.discord.com/red.png",
            })
    assert out.artifact_type == "image"
    assert out.structured["is_chart"] is False


@pytest.mark.asyncio
async def test_image_handler_picks_first_attachment_when_multiple():
    """attachment_urls is space- or comma-separated; pick first."""
    with respx.mock() as mock:
        mock.get("https://cdn.discord.com/a.png").mock(
            return_value=Response(200, content=_png_bytes(), headers={"content-type": "image/png"})
        )
        fake = LLMResponse(
            reply='{"summary":"x","ocr_text":"","is_chart":false,"topics":[],"priority":1}',
            model="gemini-2.5-flash", provider="google",
            usage=LLMUsage(), cost_usd=0,
        )
        with patch(
            "engine.discord.deep_analyzer.handlers.image.call_vision",
            AsyncMock(return_value=fake),
        ):
            out = await ImageHandler().analyze({
                "id": 5,
                "attachment_urls": "https://cdn.discord.com/a.png https://cdn.discord.com/b.png",
            })
    assert out.summary == "x"
```

- [ ] **Step 3: Run test to verify it fails**

```bash
cd engine && .venv/Scripts/python -m pytest tests/test_discord_deep_analyzer/test_handlers/test_image.py -v
```
Expected: ImportError.

- [ ] **Step 4: Implement `handlers/image.py`**

`engine/discord/deep_analyzer/handlers/image.py`:
```python
"""Image artifact handler — Gemini vision via Hermes."""
from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from ..llm import call_vision
from ..models import AnalysisResult, ArtifactType
from ..prompts import IMAGE_SYSTEM
from .text import _parse_json_reply

logger = logging.getLogger(__name__)

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".gif")
MAX_BYTES = 8 * 1024 * 1024  # 8 MB cap — typical Discord limit
TIMEOUT = httpx.Timeout(30.0, read=60.0)


def _split_urls(field: str) -> list[str]:
    """attachment_urls can be space- or comma-separated."""
    return [u for u in re.split(r"[\s,]+", field.strip()) if u]


def _looks_like_image(url: str) -> bool:
    low = url.lower().split("?", 1)[0]
    return any(low.endswith(ext) for ext in IMAGE_EXTS)


async def _download(url: str) -> tuple[bytes, str]:
    async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True) as cli:
        r = await cli.get(url)
        r.raise_for_status()
        mime = r.headers.get("content-type", "application/octet-stream").split(";", 1)[0].strip()
        data = r.content[:MAX_BYTES]
        return data, mime


class ImageHandler:
    async def analyze(self, row: dict[str, Any]) -> AnalysisResult:
        urls = _split_urls(row.get("attachment_urls") or "")
        image_urls = [u for u in urls if _looks_like_image(u)]
        if not image_urls:
            raise ValueError(f"no image attachment in row {row.get('id')}")

        data, mime = await _download(image_urls[0])
        resp = await call_vision(prompt=IMAGE_SYSTEM, image_bytes=data, mime=mime)
        summary, structured = _parse_json_reply(resp.reply)

        return AnalysisResult(
            bookmark_id=int(row["id"]),
            artifact_type=ArtifactType.IMAGE,
            summary=summary,
            structured=structured,
            model_used=resp.model,
            usage=resp.usage,
            cost_usd=resp.cost_usd,
        )
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd engine && .venv/Scripts/python -m pytest tests/test_discord_deep_analyzer/test_handlers/test_image.py -v
```
Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add engine/discord/deep_analyzer/handlers/image.py \
        engine/tests/test_discord_deep_analyzer/test_handlers/test_image.py
git commit -m "feat(discord): deep_analyzer image handler (Gemini vision)"
```

---

## Task 15: `handlers/audio.py` — local faster-whisper transcription + LLM

**Files:**
- Create: `engine/discord/deep_analyzer/handlers/audio.py`
- Create: `engine/tests/test_discord_deep_analyzer/test_handlers/test_audio.py`

**Notes:** Per spec decision, default model is `medium`. Use env var `DEEP_ANALYZER_WHISPER_MODEL` to override. `faster-whisper` loads the model lazily on first call — singleton it to avoid reloading per row.

- [ ] **Step 1: Install faster-whisper**

```bash
cd engine && .venv/Scripts/python -m pip install faster-whisper
```

- [ ] **Step 2: Write the test (mock the whisper model)**

`engine/tests/test_discord_deep_analyzer/test_handlers/test_audio.py`:
```python
"""Tests for handlers.audio."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import respx
from httpx import Response

from engine.discord.deep_analyzer.handlers.audio import AudioHandler
from engine.discord.deep_analyzer.llm import LLMResponse
from engine.discord.deep_analyzer.models import LLMUsage


@pytest.fixture
def fake_audio_llm():
    return LLMResponse(
        reply=json.dumps({
            "summary": "User says they want to short MES tomorrow.",
            "tickers": ["MES"],
            "topics": ["voice-memo", "futures"],
            "has_action_item": True,
            "priority": 4,
        }),
        model="gemini-2.5-flash",
        provider="google",
        usage=LLMUsage(input_tokens=50, output_tokens=40),
        cost_usd=0.000115,
    )


@pytest.mark.asyncio
async def test_audio_handler_transcribes_and_analyzes(fake_audio_llm):
    # Fake whisper: returns (segments, info) where segments is iterable of objs with .text
    fake_seg = MagicMock(text="short MES tomorrow")
    fake_model = MagicMock()
    fake_model.transcribe.return_value = ([fake_seg], MagicMock(language="en"))

    with respx.mock() as mock:
        mock.get("https://cdn.discord.com/memo.wav").mock(
            return_value=Response(200, content=b"\x00" * 100, headers={"content-type": "audio/wav"})
        )
        with patch("engine.discord.deep_analyzer.handlers.audio._get_model", return_value=fake_model), \
             patch("engine.discord.deep_analyzer.handlers.audio.call_text",
                   AsyncMock(return_value=fake_audio_llm)):
            out = await AudioHandler().analyze({
                "id": 6,
                "attachment_urls": "https://cdn.discord.com/memo.wav",
            })

    assert out.artifact_type == "audio"
    assert "MES" in out.summary
    assert out.structured["tickers"] == ["MES"]
```

- [ ] **Step 3: Run test to verify it fails**

```bash
cd engine && .venv/Scripts/python -m pytest tests/test_discord_deep_analyzer/test_handlers/test_audio.py -v
```
Expected: ImportError.

- [ ] **Step 4: Implement `handlers/audio.py`**

`engine/discord/deep_analyzer/handlers/audio.py`:
```python
"""Audio artifact handler — local faster-whisper transcription + LLM analysis."""
from __future__ import annotations

import logging
import os
import re
import tempfile
from typing import Any

import httpx

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
    """Lazy singleton — load on first call, cache."""
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
            raise ValueError(f"no audio attachment in row {row.get('id')}")

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
            bookmark_id=int(row["id"]),
            artifact_type=ArtifactType.AUDIO,
            summary=summary,
            structured=structured,
            model_used=resp.model,
            usage=resp.usage,
            cost_usd=resp.cost_usd,
        )
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd engine && .venv/Scripts/python -m pytest tests/test_discord_deep_analyzer/test_handlers/test_audio.py -v
```
Expected: 1 passed.

- [ ] **Step 6: Commit**

```bash
git add engine/discord/deep_analyzer/handlers/audio.py \
        engine/tests/test_discord_deep_analyzer/test_handlers/test_audio.py
git commit -m "feat(discord): deep_analyzer audio handler (faster-whisper local)"
```

---

## Task 16: `handlers/document.py` — PDF + text extract + LLM

**Files:**
- Create: `engine/discord/deep_analyzer/handlers/document.py`
- Create: `engine/tests/test_discord_deep_analyzer/test_handlers/test_document.py`

- [ ] **Step 1: Install pypdf**

```bash
cd engine && .venv/Scripts/python -m pip install pypdf
```

- [ ] **Step 2: Write the test**

`engine/tests/test_discord_deep_analyzer/test_handlers/test_document.py`:
```python
"""Tests for handlers.document."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
import respx
from httpx import Response
from pypdf import PdfWriter

from engine.discord.deep_analyzer.handlers.document import DocumentHandler
from engine.discord.deep_analyzer.llm import LLMResponse
from engine.discord.deep_analyzer.models import LLMUsage


def _trivial_pdf_bytes() -> bytes:
    """Generate an empty PDF (pypdf can read it back)."""
    from io import BytesIO
    w = PdfWriter()
    w.add_blank_page(width=100, height=100)
    buf = BytesIO()
    w.write(buf)
    return buf.getvalue()


@pytest.fixture
def fake_doc_llm():
    return LLMResponse(
        reply=json.dumps({
            "summary": "Empty PDF",
            "tickers": [],
            "topics": ["pdf"],
            "has_action_item": False,
            "key_points": [],
            "priority": 1,
        }),
        model="gemini-2.5-flash",
        provider="google",
        usage=LLMUsage(input_tokens=20, output_tokens=20),
        cost_usd=0.000056,
    )


@pytest.mark.asyncio
async def test_document_handler_extracts_and_analyzes(fake_doc_llm):
    with respx.mock() as mock:
        mock.get("https://cdn.discord.com/x.pdf").mock(
            return_value=Response(200, content=_trivial_pdf_bytes(), headers={"content-type": "application/pdf"})
        )
        with patch("engine.discord.deep_analyzer.handlers.document.call_text",
                   AsyncMock(return_value=fake_doc_llm)):
            out = await DocumentHandler().analyze({
                "id": 11,
                "attachment_urls": "https://cdn.discord.com/x.pdf",
            })
    assert out.artifact_type == "document"
    assert out.structured["topics"] == ["pdf"]
```

- [ ] **Step 3: Run test to verify it fails**

```bash
cd engine && .venv/Scripts/python -m pytest tests/test_discord_deep_analyzer/test_handlers/test_document.py -v
```
Expected: ImportError.

- [ ] **Step 4: Implement `handlers/document.py`**

`engine/discord/deep_analyzer/handlers/document.py`:
```python
"""Document artifact handler — extract text from PDFs and analyze."""
from __future__ import annotations

import logging
import os
import re
import tempfile
from io import BytesIO
from typing import Any

import httpx
from pypdf import PdfReader

from ..llm import call_text
from ..models import AnalysisResult, ArtifactType
from ..prompts import DOCUMENT_SYSTEM
from .text import _parse_json_reply

logger = logging.getLogger(__name__)

DOC_EXTS = (".pdf",)
MAX_TEXT_CHARS = 16_000
TIMEOUT = httpx.Timeout(30.0, read=60.0)


def _split_urls(field: str) -> list[str]:
    return [u for u in re.split(r"[\s,]+", field.strip()) if u]


def _looks_like_doc(url: str) -> bool:
    low = url.lower().split("?", 1)[0]
    return any(low.endswith(ext) for ext in DOC_EXTS)


async def _download(url: str) -> bytes:
    async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True) as cli:
        r = await cli.get(url)
        r.raise_for_status()
        return r.content


def _extract_text(pdf_bytes: bytes) -> str:
    reader = PdfReader(BytesIO(pdf_bytes))
    parts = []
    for page in reader.pages:
        try:
            parts.append(page.extract_text() or "")
        except Exception as e:  # noqa: BLE001
            logger.info("document_handler: page extract error %s", e)
    return "\n".join(parts)[:MAX_TEXT_CHARS]


class DocumentHandler:
    async def analyze(self, row: dict[str, Any]) -> AnalysisResult:
        urls = _split_urls(row.get("attachment_urls") or "")
        doc_urls = [u for u in urls if _looks_like_doc(u)]
        if not doc_urls:
            raise ValueError(f"no document attachment in row {row.get('id')}")

        data = await _download(doc_urls[0])
        text = _extract_text(data)
        if not text.strip():
            text = "(no extractable text)"

        resp = await call_text(prompt=text, system=DOCUMENT_SYSTEM)
        summary, structured = _parse_json_reply(resp.reply)
        structured.setdefault("doc_chars", len(text))

        return AnalysisResult(
            bookmark_id=int(row["id"]),
            artifact_type=ArtifactType.DOCUMENT,
            summary=summary,
            structured=structured,
            model_used=resp.model,
            usage=resp.usage,
            cost_usd=resp.cost_usd,
        )
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd engine && .venv/Scripts/python -m pytest tests/test_discord_deep_analyzer/test_handlers/test_document.py -v
```
Expected: 1 passed.

- [ ] **Step 6: Commit**

```bash
git add engine/discord/deep_analyzer/handlers/document.py \
        engine/tests/test_discord_deep_analyzer/test_handlers/test_document.py
git commit -m "feat(discord): deep_analyzer document handler (PDF extract + LLM)"
```

---

## Task 17: Wire attachment handlers into runner dispatch with mime-based routing

**Files:**
- Modify: `engine/discord/deep_analyzer/runner.py` — improve `_infer_artifact_type`
- Modify: `engine/tests/test_discord_deep_analyzer/test_runner.py` — add image/audio/document routing tests

- [ ] **Step 1: Update test file with attachment routing tests**

Append to `engine/tests/test_discord_deep_analyzer/test_runner.py`:
```python
@pytest.mark.asyncio
async def test_infer_artifact_type_image_from_attachment_ext():
    from engine.discord.deep_analyzer.runner import _infer_artifact_type
    assert _infer_artifact_type({"attachment_urls": "https://x.com/a.png"}) == ArtifactType.IMAGE


@pytest.mark.asyncio
async def test_infer_artifact_type_audio_from_attachment_ext():
    from engine.discord.deep_analyzer.runner import _infer_artifact_type
    assert _infer_artifact_type({"attachment_urls": "https://x.com/a.wav"}) == ArtifactType.AUDIO


@pytest.mark.asyncio
async def test_infer_artifact_type_document_from_attachment_ext():
    from engine.discord.deep_analyzer.runner import _infer_artifact_type
    assert _infer_artifact_type({"attachment_urls": "https://x.com/a.pdf"}) == ArtifactType.DOCUMENT


@pytest.mark.asyncio
async def test_infer_artifact_type_url_when_url_only():
    from engine.discord.deep_analyzer.runner import _infer_artifact_type
    assert _infer_artifact_type({"url": "https://example.com"}) == ArtifactType.URL


@pytest.mark.asyncio
async def test_infer_artifact_type_text_when_neither():
    from engine.discord.deep_analyzer.runner import _infer_artifact_type
    assert _infer_artifact_type({"content": "hello"}) == ArtifactType.TEXT
```

- [ ] **Step 2: Update `_infer_artifact_type` in `runner.py`**

Replace the existing `_infer_artifact_type` with:
```python
_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".gif")
_AUDIO_EXTS = (".wav", ".mp3", ".m4a", ".ogg", ".oga", ".webm", ".flac")
_DOC_EXTS   = (".pdf",)


def _infer_artifact_type(row: dict[str, Any]) -> ArtifactType:
    """Route on attachment extension first, then URL, then text."""
    raw = row.get("attachment_urls") or ""
    if raw:
        first = raw.split()[0].split(",")[0].lower().split("?", 1)[0]
        if any(first.endswith(e) for e in _IMAGE_EXTS):
            return ArtifactType.IMAGE
        if any(first.endswith(e) for e in _AUDIO_EXTS):
            return ArtifactType.AUDIO
        if any(first.endswith(e) for e in _DOC_EXTS):
            return ArtifactType.DOCUMENT
        # Unknown attachment type — default to image (vision LLM handles unknown best)
        return ArtifactType.IMAGE
    if row.get("url"):
        return ArtifactType.URL
    return ArtifactType.TEXT
```

- [ ] **Step 3: Update the `handlers` dict in `run_once`**

Add imports near top of `runner.py`:
```python
from .handlers.image import ImageHandler
from .handlers.audio import AudioHandler
from .handlers.document import DocumentHandler
```

Replace the handlers dict:
```python
    handlers = {
        ArtifactType.TEXT: TextHandler(),
        ArtifactType.URL: UrlHandler(),
        ArtifactType.IMAGE: ImageHandler(),
        ArtifactType.AUDIO: AudioHandler(),
        ArtifactType.DOCUMENT: DocumentHandler(),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd engine && .venv/Scripts/python -m pytest tests/test_discord_deep_analyzer/ -v
```
Expected: 35 passed.

- [ ] **Step 5: Commit**

```bash
git add engine/discord/deep_analyzer/runner.py \
        engine/tests/test_discord_deep_analyzer/test_runner.py
git commit -m "feat(discord): wire image/audio/document handlers + mime-based routing"
```

---

## Task 18: VRAM check for whisper coexistence with Ollama

**Files:**
- Create: `scripts/deep_analyzer_vram_check.ps1`

- [ ] **Step 1: Write the VRAM check script**

`scripts/deep_analyzer_vram_check.ps1` (save **UTF-8 with BOM**):
```powershell
#requires -Version 5.1
$ErrorActionPreference = 'Continue'

Write-Host "Checking GPU + Whisper coexistence with Ollama..."

# Snapshot before whisper load
nvidia-smi --query-gpu=memory.free,memory.used,memory.total --format=csv,noheader,nounits

Write-Host "`nLoading faster-whisper 'medium' (and then 'large-v3') to measure VRAM delta..."

$python = "C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\.venv\Scripts\python.exe"

foreach ($model in @('medium', 'large-v3')) {
    Write-Host "`n--- Model: $model ---"
    & $python -c @"
from faster_whisper import WhisperModel
import subprocess, sys
print(f'loading $model...', flush=True)
m = WhisperModel('$model', device='cuda', compute_type='float16')
print('loaded.', flush=True)
out = subprocess.check_output(['nvidia-smi','--query-gpu=memory.free,memory.used','--format=csv,noheader,nounits'])
print(f'GPU state: {out.decode().strip()}', flush=True)
"@
}

Write-Host "`nDecision:"
Write-Host "  - If both fit alongside Ollama with >2GB free, set DEEP_ANALYZER_WHISPER_MODEL=large-v3"
Write-Host "  - Otherwise keep default 'medium'"
```

- [ ] **Step 2: Run the check**

```powershell
pwsh -File scripts\deep_analyzer_vram_check.ps1
```

- [ ] **Step 3: Decide and set env var**

If both models fit with headroom: `[System.Environment]::SetEnvironmentVariable("DEEP_ANALYZER_WHISPER_MODEL","large-v3","User")`.
Otherwise: leave default (`medium`).

- [ ] **Step 4: Commit the check script**

```bash
git add scripts/deep_analyzer_vram_check.ps1
git commit -m "feat(discord): whisper VRAM check script for deep_analyzer"
```

---

## Task 19: Phase 3 manual validation

- [ ] **Step 1: Reset claim state**

```powershell
sqlite3 data/discord.db "UPDATE discord_bookmarks SET claimed_at = NULL WHERE analyzed_at IS NULL"
```

- [ ] **Step 2: Run 10 batches** (same loop as Phase 2 Task 13 Step 2).

- [ ] **Step 3: Inspect**

```powershell
sqlite3 data/discord.db "SELECT artifact_type, COUNT(*), ROUND(SUM(cost_usd),4) FROM discord_analyses GROUP BY artifact_type"
```

Expected: rows for `text`, `url`, plus `image`/`audio`/`document` depending on what attachments existed. Errors <5%.

- [ ] **Step 4: Spot-check 3 vault pages per non-text type** — confirm OCR text appears for images, transcript-derived summary for audio, key_points for PDFs.

---

# Phase 4 — Scheduled task + daily digest

## Task 20: `digest.py` — daily digest writer + Hermes DM

**Files:**
- Create: `engine/discord/deep_analyzer/digest.py`
- Create: `engine/tests/test_discord_deep_analyzer/test_digest.py`

- [ ] **Step 1: Write the test**

`engine/tests/test_discord_deep_analyzer/test_digest.py`:
```python
"""Tests for deep_analyzer.digest."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from engine.discord.deep_analyzer import digest, storage


@pytest.fixture
def populated_db(tmp_db: Path) -> Path:
    storage.migrate(tmp_db)
    conn = sqlite3.connect(tmp_db)
    now = datetime.utcnow()
    rows = [
        # priority, has_action_item via structured_json
        (1, "url", "Bull on MES",      '{"priority":5,"tickers":["MES"],"has_action_item":true}',  0.001, now),
        (2, "image", "Random meme",    '{"priority":1,"tickers":[],"has_action_item":false}',     0.0008, now),
        (3, "text",  "Lunch options",  '{"priority":2,"tickers":["SPY"],"has_action_item":false}', 0.0001, now),
        (4, "url",   "Yesterday item", '{"priority":4,"tickers":["NQ"],"has_action_item":true}',   0.001, now - timedelta(days=2)),  # excluded — >24h
    ]
    for bookmark_id, atype, summary, struct, cost, ts in rows:
        conn.execute(
            "INSERT INTO discord_analyses (bookmark_id, artifact_type, summary, structured_json, cost_usd, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (bookmark_id, atype, summary, struct, cost, ts.strftime("%Y-%m-%d %H:%M:%S")),
        )
    conn.commit()
    conn.close()
    return tmp_db


def test_render_digest_writes_vault_page(populated_db, tmp_path):
    path = digest.render(db_path=populated_db, vault_root=tmp_path)
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "Overnight feed" in text
    assert "Bull on MES" in text          # priority 5 — present
    assert "Yesterday item" not in text   # excluded by 24h cutoff


def test_render_digest_ranks_by_priority(populated_db, tmp_path):
    path = digest.render(db_path=populated_db, vault_root=tmp_path)
    text = path.read_text(encoding="utf-8")
    # priority 5 must come before priority 2 (1 also exists but tested by 'before')
    assert text.find("Bull on MES") < text.find("Random meme")


def test_render_digest_returns_stats(populated_db, tmp_path):
    path = digest.render(db_path=populated_db, vault_root=tmp_path)
    text = path.read_text(encoding="utf-8")
    assert "Total: 3" in text  # 4th item excluded by 24h cutoff
    assert "Cost: $" in text
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd engine && .venv/Scripts/python -m pytest tests/test_discord_deep_analyzer/test_digest.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement `digest.py`**

`engine/discord/deep_analyzer/digest.py`:
```python
"""Daily digest — ranks last 24h of analyses, writes vault page, optionally DMs via Hermes."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
from datetime import datetime
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

DEFAULT_VAULT_ROOT = Path(os.path.expanduser("~/my-vault"))
HERMES_BASE = os.getenv("HERMES_BASE_URL", "http://127.0.0.1:8765")
DM_USER = os.getenv("DEEP_ANALYZER_DM_USER", "amo")


def _fetch_last_24h(db_path: Path | str) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT a.*, b.message_id, b.posted_at
            FROM discord_analyses a
            JOIN discord_bookmarks b ON a.bookmark_id = b.id
            WHERE datetime(a.created_at) >= datetime('now', '-24 hours')
            ORDER BY a.created_at DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _priority(row: dict) -> int:
    try:
        return int(json.loads(row.get("structured_json") or "{}").get("priority", 0))
    except (json.JSONDecodeError, ValueError, TypeError):
        return 0


def _render_page(rows: list[dict]) -> str:
    rows_sorted = sorted(rows, key=_priority, reverse=True)
    total_cost = sum(float(r.get("cost_usd") or 0) for r in rows_sorted)
    by_type: dict[str, int] = {}
    for r in rows_sorted:
        by_type[r["artifact_type"]] = by_type.get(r["artifact_type"], 0) + 1

    lines = [
        "",
        "## Overnight feed",
        "",
        f"Total: {len(rows_sorted)}  |  Cost: ${total_cost:.4f}",
        f"By type: {', '.join(f'{k}={v}' for k, v in by_type.items()) or '(none)'}",
        "",
        "### Top items",
        "",
    ]
    for r in rows_sorted[:10]:
        prio = _priority(r)
        struct = {}
        try:
            struct = json.loads(r.get("structured_json") or "{}")
        except json.JSONDecodeError:
            pass
        tickers = struct.get("tickers", [])
        ticker_str = f" `{','.join(tickers)}`" if tickers else ""
        lines.append(f"- **[{prio}]{ticker_str}** ({r['artifact_type']}) {r['summary']}")
    return "\n".join(lines) + "\n"


def render(*, db_path: Path | str, vault_root: Path | None = None) -> Path:
    """Generate the daily digest. Returns path to the daily page that was appended."""
    root = Path(vault_root) if vault_root else DEFAULT_VAULT_ROOT
    today = datetime.utcnow().strftime("%Y-%m-%d")
    folder = root / "Daily"
    folder.mkdir(parents=True, exist_ok=True)
    page = folder / f"{today}.md"

    rows = _fetch_last_24h(db_path)
    body = _render_page(rows)

    # Append (preserve any existing daily content)
    existing = page.read_text(encoding="utf-8") if page.exists() else f"# {today}\n"
    page.write_text(existing + body, encoding="utf-8")
    return page


async def send_dm_via_hermes(*, page_path: Path, n_items: int, cost: float) -> None:
    """Fire-and-forget DM to Amo via Hermes. Errors are logged but never raised."""
    msg = (
        f"Overnight feed: {n_items} items analyzed, ${cost:.4f} spent. "
        f"Top 3 in vault: {page_path}"
    )
    try:
        async with httpx.AsyncClient(base_url=HERMES_BASE, timeout=20.0) as cli:
            await cli.post("/v1/dm/send", json={"to": DM_USER, "text": msg})
    except (httpx.RequestError, httpx.HTTPStatusError) as e:
        logger.warning("digest: Hermes DM failed: %s", e)


def render_and_dm(*, db_path: Path | str, vault_root: Path | None = None) -> Path:
    """Convenience: render the digest page and DM Amo. Returns path."""
    rows = _fetch_last_24h(db_path)
    path = render(db_path=db_path, vault_root=vault_root)
    cost = sum(float(r.get("cost_usd") or 0) for r in rows)
    asyncio.run(send_dm_via_hermes(page_path=path, n_items=len(rows), cost=cost))
    return path
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd engine && .venv/Scripts/python -m pytest tests/test_discord_deep_analyzer/test_digest.py -v
```
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add engine/discord/deep_analyzer/digest.py \
        engine/tests/test_discord_deep_analyzer/test_digest.py
git commit -m "feat(discord): deep_analyzer daily digest writer + Hermes DM"
```

---

## Task 21: `deep_analyzer_loop.ps1` — 2-minute scheduled task wrapper

**Files:**
- Create: `scripts/deep_analyzer_loop.ps1`

- [ ] **Step 1: Write the wrapper (UTF-8 with BOM)**

`scripts/deep_analyzer_loop.ps1`:
```powershell
#requires -Version 5.1
$ErrorActionPreference = 'Stop'
Start-Transcript -Path "$env:TEMP\deep_analyzer_loop.log" -Append

$repo   = "C:\Users\mattm\ThinkorSwim\jarvis-trader"
$python = "$repo\engine\.venv\Scripts\python.exe"
$db     = "$repo\data\discord.db"

& $python -c @"
import asyncio
from pathlib import Path
from engine.discord.deep_analyzer.runner import run_once

async def main():
    n = await run_once(
        db_path=Path(r'$db'),
        vault_root=Path.home() / 'my-vault',
        limit=5,
    )
    print(f'wrote {n}')

asyncio.run(main())
"@

if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: runner exited $LASTEXITCODE"
    Stop-Transcript
    exit 1
}

Stop-Transcript
```

- [ ] **Step 2: Verify UTF-8 with BOM encoding**

```powershell
$bytes = [System.IO.File]::ReadAllBytes("scripts/deep_analyzer_loop.ps1")
"$($bytes[0]):$($bytes[1]):$($bytes[2])"  # Must be 239:187:191 (BOM)
```

- [ ] **Step 3: Run once manually to verify**

```powershell
pwsh -File scripts\deep_analyzer_loop.ps1
```
Expected: output ends with `wrote N`.

- [ ] **Step 4: Commit**

```bash
git add scripts/deep_analyzer_loop.ps1
git commit -m "feat(discord): deep_analyzer 2-min scheduled task wrapper"
```

---

## Task 22: `deep_analyzer_digest.ps1` — 06:00 daily wrapper

**Files:**
- Create: `scripts/deep_analyzer_digest.ps1`

- [ ] **Step 1: Write the wrapper (UTF-8 with BOM)**

`scripts/deep_analyzer_digest.ps1`:
```powershell
#requires -Version 5.1
$ErrorActionPreference = 'Stop'
Start-Transcript -Path "$env:TEMP\deep_analyzer_digest.log" -Append

$repo   = "C:\Users\mattm\ThinkorSwim\jarvis-trader"
$python = "$repo\engine\.venv\Scripts\python.exe"
$db     = "$repo\data\discord.db"

& $python -c @"
from pathlib import Path
from engine.discord.deep_analyzer.digest import render_and_dm

path = render_and_dm(
    db_path=Path(r'$db'),
    vault_root=Path.home() / 'my-vault',
)
print(f'digest written: {path}')
"@

if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: digest exited $LASTEXITCODE"
    Stop-Transcript
    exit 1
}

Stop-Transcript
```

- [ ] **Step 2: Run once manually**

```powershell
pwsh -File scripts\deep_analyzer_digest.ps1
```
Expected: prints `digest written: <path>` and the file exists at `~/my-vault/Daily/<today>.md`.

- [ ] **Step 3: Commit**

```bash
git add scripts/deep_analyzer_digest.ps1
git commit -m "feat(discord): deep_analyzer daily digest wrapper"
```

---

## Task 23: `install-deep-analyzer-tasks.ps1` — register both scheduled tasks

**Files:**
- Create: `scripts/install-deep-analyzer-tasks.ps1`

- [ ] **Step 1: Write the installer (UTF-8 with BOM)**

`scripts/install-deep-analyzer-tasks.ps1`:
```powershell
#requires -Version 5.1
$ErrorActionPreference = 'Stop'

$repo = "C:\Users\mattm\ThinkorSwim\jarvis-trader"
$pwsh = "$env:LOCALAPPDATA\Microsoft\WindowsApps\pwsh.exe"

# --- Task 1: 2-minute loop ---
$loopName = "JarvisTrader_DiscordDeepAnalyzer"
$loopAction = New-ScheduledTaskAction -Execute $pwsh `
    -Argument "-NoProfile -File `"$repo\scripts\deep_analyzer_loop.ps1`""
$loopTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 2)
$loopSettings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -RestartCount 1 -RestartInterval (New-TimeSpan -Minutes 5)

Register-ScheduledTask -TaskName $loopName -Action $loopAction `
    -Trigger $loopTrigger -Settings $loopSettings -Force -RunLevel Limited

Write-Host "Installed: $loopName (every 2 min)"

# --- Task 2: 06:00 daily digest ---
$digestName = "JarvisTrader_DiscordDigest"
$digestAction = New-ScheduledTaskAction -Execute $pwsh `
    -Argument "-NoProfile -File `"$repo\scripts\deep_analyzer_digest.ps1`""
$digestTrigger = New-ScheduledTaskTrigger -Daily -At "06:00"
$digestSettings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable

Register-ScheduledTask -TaskName $digestName -Action $digestAction `
    -Trigger $digestTrigger -Settings $digestSettings -Force -RunLevel Limited

Write-Host "Installed: $digestName (daily 06:00)"

# --- Verify ---
schtasks /Query /TN $loopName /V /FO LIST | Select-String "Status|Next Run"
schtasks /Query /TN $digestName /V /FO LIST | Select-String "Status|Next Run"
```

- [ ] **Step 2: Run the installer**

```powershell
pwsh -File scripts\install-deep-analyzer-tasks.ps1
```

Expected:
```
Installed: JarvisTrader_DiscordDeepAnalyzer (every 2 min)
Installed: JarvisTrader_DiscordDigest (daily 06:00)
Status: Ready
Next Run Time: <plausible date>
```

- [ ] **Step 3: Confirm tasks visible**

```powershell
schtasks /Query /FO LIST /V | Select-String "JarvisTrader_Discord"
```

- [ ] **Step 4: Commit**

```bash
git add scripts/install-deep-analyzer-tasks.ps1
git commit -m "feat(discord): scheduled-task installer for deep_analyzer + digest"
```

---

## Task 24: Phase 4 — 48-hour live monitoring

- [ ] **Step 1: After 2 hours**

```powershell
sqlite3 data/discord.db "SELECT artifact_type, COUNT(*), ROUND(SUM(cost_usd),4) FROM discord_analyses WHERE date(created_at)=date('now') GROUP BY artifact_type"
sqlite3 data/discord.db "SELECT COUNT(*) FROM discord_analyses WHERE error_text IS NOT NULL AND date(created_at)=date('now')"
schtasks /Query /TN JarvisTrader_DiscordDeepAnalyzer /V /FO LIST | Select-String "Last Result"
```

Expected:
- Some rows analyzed
- Error count <5% of total
- Last Result: `0` (success)

- [ ] **Step 2: After 24 hours — confirm digest fired at 06:00**

```powershell
ls ~/my-vault/Daily/  # most recent file should be today's date
gc ~/my-vault/Daily/(Get-Date -Format yyyy-MM-dd).md | Select-Object -Last 30
```
Expected: digest section present at the bottom of today's daily page.

- [ ] **Step 3: After 48 hours — final health check (per `rules/verification.md`)**

```powershell
# 1. Sensible count
sqlite3 data/discord.db "SELECT COUNT(*) FROM discord_analyses WHERE date(created_at) >= date('now', '-2 days')"

# 2. Vault populated
ls ~/my-vault/Discord-Feed/ | Select-Object -Last 3

# 3. Hermes still healthy
curl -s http://127.0.0.1:8765/health | python -m json.tool

# 4. Cost within budget
sqlite3 data/discord.db "SELECT date(created_at), ROUND(SUM(cost_usd),4) FROM discord_analyses WHERE date(created_at) >= date('now','-2 days') GROUP BY date(created_at)"
```

Each day's cost must be ≤ `DEEP_ANALYZER_DAILY_USD` (default $2.00).

- [ ] **Step 4: If anything looks off — pause and investigate**

```powershell
schtasks /Change /TN JarvisTrader_DiscordDeepAnalyzer /DISABLE
```

---

# Phase 5 — Full historical backfill

## Task 25: `deep_analyzer_backfill.ps1` — clear analyzed_at + run drainer

**Files:**
- Create: `scripts/deep_analyzer_backfill.ps1`

**Notes:** Phase 5 chews through the 393 historical rows. Run pattern: pause the 2-min loop, clear `analyzed_at` for the rows you want backfilled, run the drainer until done, then re-enable the live loop. Drainer uses a higher per-batch limit since we're explicitly draining.

- [ ] **Step 1: Write the backfill script (UTF-8 with BOM)**

`scripts/deep_analyzer_backfill.ps1`:
```powershell
#requires -Version 5.1
$ErrorActionPreference = 'Stop'
param(
    [int]$BatchSize = 10,
    [int]$MaxBatches = 200,
    [switch]$DryRun
)

Start-Transcript -Path "$env:TEMP\deep_analyzer_backfill.log" -Append

$repo   = "C:\Users\mattm\ThinkorSwim\jarvis-trader"
$python = "$repo\engine\.venv\Scripts\python.exe"
$db     = "$repo\data\discord.db"

# 1. Pause the live loop
Write-Host "Disabling JarvisTrader_DiscordDeepAnalyzer..."
schtasks /Change /TN JarvisTrader_DiscordDeepAnalyzer /DISABLE | Out-Null

# 2. Pre-count
$unanalyzed = & $python -c "import sqlite3; c=sqlite3.connect(r'$db'); print(c.execute('SELECT COUNT(*) FROM discord_bookmarks WHERE analyzed_at IS NULL').fetchone()[0])"
Write-Host "Unanalyzed rows: $unanalyzed"

if ($DryRun) {
    Write-Host "DryRun — re-enabling loop and exiting."
    schtasks /Change /TN JarvisTrader_DiscordDeepAnalyzer /ENABLE | Out-Null
    Stop-Transcript
    exit 0
}

# 3. Drain
for ($i = 0; $i -lt $MaxBatches; $i++) {
    $n = & $python -c @"
import asyncio
from pathlib import Path
from engine.discord.deep_analyzer.runner import run_once
async def main():
    n = await run_once(
        db_path=Path(r'$db'),
        vault_root=Path.home() / 'my-vault',
        limit=$BatchSize,
    )
    print(n)
asyncio.run(main())
"@
    Write-Host "batch $i wrote $n"
    if ([int]$n -eq 0) { break }
}

# 4. Re-enable the live loop
Write-Host "Re-enabling JarvisTrader_DiscordDeepAnalyzer..."
schtasks /Change /TN JarvisTrader_DiscordDeepAnalyzer /ENABLE | Out-Null

# 5. Final tally
& $python -c "import sqlite3; c=sqlite3.connect(r'$db'); print('remaining unanalyzed:', c.execute('SELECT COUNT(*) FROM discord_bookmarks WHERE analyzed_at IS NULL').fetchone()[0])"

Stop-Transcript
```

- [ ] **Step 2: Dry-run first**

```powershell
pwsh -File scripts\deep_analyzer_backfill.ps1 -DryRun
```
Expected: prints unanalyzed count, exits without processing.

- [ ] **Step 3: Run backfill in screen-friendly windows**

Run a small batch first to verify behavior:
```powershell
pwsh -File scripts\deep_analyzer_backfill.ps1 -BatchSize 5 -MaxBatches 2
```
Expected: drains 10 rows, re-enables the live loop.

Then full drain:
```powershell
pwsh -File scripts\deep_analyzer_backfill.ps1 -BatchSize 10 -MaxBatches 100
```
Expected: drains up to 1000 rows; total 393 historical rows finishes well under cap.

- [ ] **Step 4: Verify**

```powershell
sqlite3 data/discord.db "SELECT COUNT(*) FROM discord_bookmarks WHERE analyzed_at IS NULL"
sqlite3 data/discord.db "SELECT artifact_type, COUNT(*), ROUND(SUM(cost_usd),4) FROM discord_analyses GROUP BY artifact_type"
schtasks /Query /TN JarvisTrader_DiscordDeepAnalyzer /V /FO LIST | Select-String "Status"
```

Expected:
- Unanalyzed = 0 (or near-zero — some permanent-error rows may linger)
- Per-type counts roughly: url ~350, image ~30, audio ~2, document ~5, text ~6
- Live loop status: Ready

- [ ] **Step 5: Commit the backfill script**

```bash
git add scripts/deep_analyzer_backfill.ps1
git commit -m "feat(discord): deep_analyzer historical backfill script"
```

---

# Final verification — full test suite

- [ ] **Step 1: Run the entire deep_analyzer suite**

```bash
cd engine && .venv/Scripts/python -m pytest tests/test_discord_deep_analyzer/ -v
```
Expected: ~38 tests passing.

- [ ] **Step 2: Run the existing Discord suite to confirm no regressions**

```bash
cd engine && .venv/Scripts/python -m pytest tests/test_discord_*.py -v
```
Expected: 172 existing tests still passing.

- [ ] **Step 3: Confirm health gates**

```powershell
# Engine still healthy
curl -s http://127.0.0.1:8010/health | python -m json.tool

# Hermes still healthy
curl -s http://127.0.0.1:8765/health | python -m json.tool

# Both scheduled tasks ready + Last Result 0
schtasks /Query /TN JarvisTrader_DiscordDeepAnalyzer /V /FO LIST | Select-String "Status|Last Result"
schtasks /Query /TN JarvisTrader_DiscordDigest /V /FO LIST       | Select-String "Status|Last Result"
```

---

# Appendix — Operational notes for the engineer

**Disabling the loop in an emergency:**
```powershell
schtasks /Change /TN JarvisTrader_DiscordDeepAnalyzer /DISABLE
schtasks /Change /TN JarvisTrader_DiscordDigest /DISABLE
```

**Adjusting the daily budget:**
```powershell
[System.Environment]::SetEnvironmentVariable("DEEP_ANALYZER_DAILY_USD","5.00","User")
```
Takes effect on the next scheduled invocation. The runner reads the env var each run.

**Re-analyzing a specific row** (for debugging):
```powershell
sqlite3 data/discord.db "UPDATE discord_bookmarks SET analyzed_at=NULL, claimed_at=NULL, analysis_id=NULL WHERE id=<id>"
# Next 2-min poll will pick it up.
```

**Permanent-error rows** (`analyzed_at` set but `error_text` non-null) will not retry. To force a retry:
```powershell
sqlite3 data/discord.db "UPDATE discord_bookmarks SET analyzed_at=NULL WHERE analysis_id IN (SELECT id FROM discord_analyses WHERE error_text IS NOT NULL)"
```

**Whisper model upgrade** (after VRAM check):
```powershell
[System.Environment]::SetEnvironmentVariable("DEEP_ANALYZER_WHISPER_MODEL","large-v3","User")
```
Next audio-handler invocation reloads the model.

---

# Spec → task coverage check (self-review)

| Spec requirement | Implemented in |
|---|---|
| Schema additive only | Task 1 |
| `discord_analyses` table | Task 1 |
| `claimed_at` row lock + 10-min stale reclaim | Task 1 |
| Text handler | Task 6 |
| URL handler with X-post fallback | Task 11 |
| Image handler (Gemini vision) | Task 14 |
| Audio handler (faster-whisper, `medium` default) | Task 15 |
| Document handler (PDF) | Task 16 |
| LLM gateway (Hermes Gemini → Anthropic fallback) | Task 3 |
| Daily budget cap | Task 9 (runner) + Task 1 (daily_cost_usd) |
| Cost tracking per call | Task 3 (_price) + Task 9 |
| Idempotent (analyzed_at IS NULL predicate) | Task 1 |
| Limit 5 per run | Task 9 |
| Vault page per artifact, dated folder, slug filename | Task 7 |
| Discord-link YAML frontmatter | Task 7 |
| gbrain ingest dir (skip silent if missing) | Task 8 |
| Daily digest at 06:00 | Task 22 + Task 23 |
| Digest in vault page + Discord DM | Task 20 |
| 5-phase rollout | Tasks 1, 6-10, 11-13, 14-19, 20-24, 25 |
| Verification gates per phase | Tasks 10, 13, 19, 24 |
| Roll-back per phase | Reversible: task disable + DDL is `CREATE IF NOT EXISTS` |
| UTF-8 with BOM PS1 files | Tasks 10, 18, 21, 22, 23, 25 |
| `127.0.0.1` not `localhost` | Task 3 (DEFAULT_BASE), runner uses Hermes via llm.py |
| `[safety-review]` tag NOT required | This work doesn't touch `engine/risk/` or `engine/config.py` |
