"""Tests for deep_analyzer.force_drain.

The conftest `tmp_db` fixture does not include `attachment_urls` (added
2026-05-20). Each test adds the column explicitly to mirror the production
schema migration in `engine.discord.storage._BOOKMARK_MIGRATION_COLUMNS`.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from discord.deep_analyzer import force_drain, storage

CHANNEL_ID = "1490851279180660819"


def _add_attachment_urls_column(db_path: Path) -> None:
    """Mirror prod migration — add attachment_urls TEXT to discord_bookmarks."""
    conn = sqlite3.connect(db_path)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(discord_bookmarks)")}
    if "attachment_urls" not in cols:
        conn.execute("ALTER TABLE discord_bookmarks ADD COLUMN attachment_urls TEXT")
    conn.commit()
    conn.close()


def _seed_rows(
    db_path: Path,
    rows: list[tuple[str, str | None]],
) -> None:
    """Insert rows shaped (message_id, attachment_urls) on the target channel."""
    conn = sqlite3.connect(db_path)
    for msg_id, att in rows:
        conn.execute(
            "INSERT INTO discord_bookmarks "
            "(message_id, channel_id, posted_at, url, source_type, attachment_urls) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (msg_id, CHANNEL_ID, "2026-05-20T10:00:00Z", "https://example.com/a", "other", att),
        )
    conn.commit()
    conn.close()


def _write_dce_export(
    tmp_path: Path,
    messages: list[dict],
) -> Path:
    """Write a minimal DCE-shaped JSON file. Returns the path."""
    payload = {
        "guild": {"id": "g", "name": "g"},
        "channel": {"id": CHANNEL_ID, "name": "general"},
        "messages": messages,
    }
    export = tmp_path / "export.json"
    export.write_text(json.dumps(payload), encoding="utf-8")
    return export


# -------------------------------------------------------------------- backfill


def test_backfill_attachment_urls_from_dce(tmp_db: Path, tmp_path: Path):
    _add_attachment_urls_column(tmp_db)
    _seed_rows(tmp_db, [("m1", None), ("m2", None)])
    export = _write_dce_export(
        tmp_path,
        [
            {
                "id": "m1",
                "attachments": [{"url": "https://cdn.discordapp.com/a/x.png"}],
            },
            {
                "id": "m2",
                "attachments": [],
            },
        ],
    )

    result = force_drain.backfill_attachment_urls(tmp_db, export, CHANNEL_ID)

    assert result["updated"] == ["m1"]
    assert result["skipped_already_set"] == []
    assert result["missing_in_db"] == []

    conn = sqlite3.connect(tmp_db)
    row = conn.execute(
        "SELECT attachment_urls FROM discord_bookmarks WHERE message_id = 'm1'"
    ).fetchone()
    conn.close()
    assert row[0] == "https://cdn.discordapp.com/a/x.png"


def test_backfill_skips_rows_with_attachment_already_set(tmp_db: Path, tmp_path: Path):
    _add_attachment_urls_column(tmp_db)
    _seed_rows(tmp_db, [("m1", "https://existing.example/img.png")])
    export = _write_dce_export(
        tmp_path,
        [{"id": "m1", "attachments": [{"url": "https://newer.example/x.png"}]}],
    )

    result = force_drain.backfill_attachment_urls(tmp_db, export, CHANNEL_ID)
    assert result["updated"] == []
    assert result["skipped_already_set"] == ["m1"]

    conn = sqlite3.connect(tmp_db)
    row = conn.execute(
        "SELECT attachment_urls FROM discord_bookmarks WHERE message_id = 'm1'"
    ).fetchone()
    conn.close()
    # Original value preserved — backfill must not clobber.
    assert row[0] == "https://existing.example/img.png"


def test_backfill_records_missing_in_db(tmp_db: Path, tmp_path: Path):
    _add_attachment_urls_column(tmp_db)
    _seed_rows(tmp_db, [("m1", None)])
    export = _write_dce_export(
        tmp_path,
        [
            {"id": "m1", "attachments": [{"url": "https://a/x.png"}]},
            {"id": "m_never_imported", "attachments": [{"url": "https://b/y.png"}]},
        ],
    )

    result = force_drain.backfill_attachment_urls(tmp_db, export, CHANNEL_ID)
    assert result["updated"] == ["m1"]
    assert result["missing_in_db"] == ["m_never_imported"]


# -------------------------------------------------------------------- requeue


def test_mark_for_reanalysis_clears_analyzed_at_when_prior_was_text(tmp_db: Path, tmp_path: Path):
    _add_attachment_urls_column(tmp_db)
    storage.migrate(tmp_db)
    _seed_rows(tmp_db, [("m1", "https://cdn/x.png")])

    # Simulate prior text-only analysis having completed.
    conn = sqlite3.connect(tmp_db)
    cur = conn.execute(
        "INSERT INTO discord_analyses "
        "(bookmark_id, artifact_type, summary, structured_json, cost_usd) "
        "VALUES ('m1', 'text', 'old summary', '{}', 0.001)"
    )
    analysis_id = cur.lastrowid
    conn.execute(
        "UPDATE discord_bookmarks SET analyzed_at = datetime('now'), analysis_id = ? "
        "WHERE message_id = 'm1'",
        (analysis_id,),
    )
    conn.commit()
    conn.close()

    requeued = force_drain.mark_for_reanalysis(tmp_db, ["m1"])
    assert requeued == ["m1"]

    conn = sqlite3.connect(tmp_db)
    row = conn.execute(
        "SELECT analyzed_at, analysis_id FROM discord_bookmarks WHERE message_id = 'm1'"
    ).fetchone()
    conn.close()
    assert row[0] is None
    assert row[1] is None


def test_mark_for_reanalysis_skips_when_prior_was_image(tmp_db: Path):
    """Rows already analyzed as image/audio/document already saw the attachment."""
    _add_attachment_urls_column(tmp_db)
    storage.migrate(tmp_db)
    _seed_rows(tmp_db, [("m1", "https://cdn/x.png")])

    conn = sqlite3.connect(tmp_db)
    cur = conn.execute(
        "INSERT INTO discord_analyses "
        "(bookmark_id, artifact_type, summary, structured_json, cost_usd) "
        "VALUES ('m1', 'image', 'image analyzed', '{}', 0.001)"
    )
    analysis_id = cur.lastrowid
    conn.execute(
        "UPDATE discord_bookmarks SET analyzed_at = datetime('now'), analysis_id = ? "
        "WHERE message_id = 'm1'",
        (analysis_id,),
    )
    conn.commit()
    conn.close()

    requeued = force_drain.mark_for_reanalysis(tmp_db, ["m1"])
    assert requeued == []

    conn = sqlite3.connect(tmp_db)
    analyzed_at = conn.execute(
        "SELECT analyzed_at FROM discord_bookmarks WHERE message_id = 'm1'"
    ).fetchone()[0]
    conn.close()
    assert analyzed_at is not None  # unchanged


def test_mark_for_reanalysis_includes_never_analyzed_rows(tmp_db: Path):
    """A row with attachments and no prior analysis should be considered retryable."""
    _add_attachment_urls_column(tmp_db)
    storage.migrate(tmp_db)
    _seed_rows(tmp_db, [("m1", "https://cdn/x.png")])

    requeued = force_drain.mark_for_reanalysis(tmp_db, ["m1"])
    assert requeued == ["m1"]


# -------------------------------------------------------------------- dry-run


def test_dry_run_makes_no_db_writes(tmp_db: Path, tmp_path: Path):
    _add_attachment_urls_column(tmp_db)
    storage.migrate(tmp_db)
    _seed_rows(tmp_db, [("m1", None)])
    export = _write_dce_export(
        tmp_path,
        [{"id": "m1", "attachments": [{"url": "https://cdn/x.png"}]}],
    )

    backfill = force_drain.backfill_attachment_urls(tmp_db, export, CHANNEL_ID, dry_run=True)
    assert backfill["updated"] == ["m1"]

    # Verify NOTHING was written — attachment_urls still NULL.
    conn = sqlite3.connect(tmp_db)
    att = conn.execute(
        "SELECT attachment_urls FROM discord_bookmarks WHERE message_id = 'm1'"
    ).fetchone()[0]
    conn.close()
    assert att is None

    # Now manually populate attachment_urls so mark_for_reanalysis has a real row
    # to evaluate; verify dry_run=True does not clear analyzed_at.
    conn = sqlite3.connect(tmp_db)
    cur = conn.execute(
        "INSERT INTO discord_analyses "
        "(bookmark_id, artifact_type, summary, structured_json, cost_usd) "
        "VALUES ('m1', 'text', 's', '{}', 0.001)"
    )
    analysis_id = cur.lastrowid
    conn.execute(
        "UPDATE discord_bookmarks SET attachment_urls = 'https://cdn/x.png', "
        "analyzed_at = datetime('now'), analysis_id = ? WHERE message_id = 'm1'",
        (analysis_id,),
    )
    conn.commit()
    conn.close()

    requeued = force_drain.mark_for_reanalysis(tmp_db, ["m1"], dry_run=True)
    assert requeued == ["m1"]  # reported as a candidate ...

    # ... but analyzed_at NOT cleared in dry-run.
    conn = sqlite3.connect(tmp_db)
    analyzed_at = conn.execute(
        "SELECT analyzed_at FROM discord_bookmarks WHERE message_id = 'm1'"
    ).fetchone()[0]
    conn.close()
    assert analyzed_at is not None


# -------------------------------------------------------------------- budget cap


@pytest.mark.asyncio
async def test_drain_respects_daily_cost_cap(tmp_db: Path, tmp_path: Path, monkeypatch):
    _add_attachment_urls_column(tmp_db)
    storage.migrate(tmp_db)
    _seed_rows(tmp_db, [("m1", None), ("m2", None)])

    monkeypatch.setenv("DEEP_ANALYZER_DAILY_USD", "0.50")
    conn = sqlite3.connect(tmp_db)
    conn.execute(
        "INSERT INTO discord_analyses "
        "(bookmark_id, artifact_type, summary, structured_json, cost_usd) "
        "VALUES ('m1', 'text', 's', '{}', 1.00)"  # exceeds 0.50 cap
    )
    conn.commit()
    conn.close()

    stats = await force_drain.drain(
        db_path=tmp_db,
        vault_root=tmp_path / "vault",
        channel_id=CHANNEL_ID,
        batch_size=10,
        max_passes=3,
    )
    assert stats["halted_reason"] == "budget_exceeded"
    assert stats["processed"] == 0


# -------------------------------------------------------------------- end-to-end loop


@pytest.mark.asyncio
async def test_drain_stops_when_queue_empty(tmp_db: Path, tmp_path: Path, monkeypatch):
    """No queued rows → drain exits on first pass with halted_reason='queue_empty'."""
    _add_attachment_urls_column(tmp_db)
    storage.migrate(tmp_db)
    # Seed one row but mark it analyzed so the queue is empty.
    _seed_rows(tmp_db, [("m1", "https://cdn/x.png")])
    conn = sqlite3.connect(tmp_db)
    cur = conn.execute(
        "INSERT INTO discord_analyses "
        "(bookmark_id, artifact_type, summary, structured_json, cost_usd) "
        "VALUES ('m1', 'image', 's', '{}', 0.001)"
    )
    conn.execute(
        "UPDATE discord_bookmarks SET analyzed_at = datetime('now'), analysis_id = ? "
        "WHERE message_id = 'm1'",
        (cur.lastrowid,),
    )
    conn.commit()
    conn.close()

    monkeypatch.setenv("DEEP_ANALYZER_DAILY_USD", "10.00")
    stats = await force_drain.drain(
        db_path=tmp_db,
        vault_root=tmp_path / "vault",
        channel_id=CHANNEL_ID,
        batch_size=10,
        max_passes=3,
    )
    assert stats["halted_reason"] == "queue_empty"
    assert stats["processed"] == 0


def test_extract_attachment_urls_joins_multiple(tmp_path: Path):
    msg = {
        "attachments": [
            {"url": "https://cdn/x.png"},
            {"url": "https://cdn/y.wav"},
        ]
    }
    assert force_drain._extract_attachment_urls(msg) == ("https://cdn/x.png https://cdn/y.wav")


def test_extract_attachment_urls_returns_none_for_empty():
    assert force_drain._extract_attachment_urls({}) is None
    assert force_drain._extract_attachment_urls({"attachments": []}) is None
