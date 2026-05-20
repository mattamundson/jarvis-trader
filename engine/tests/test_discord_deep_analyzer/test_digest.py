"""Tests for deep_analyzer.digest."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from discord.deep_analyzer import digest, storage


@pytest.fixture
def populated_db(tmp_db: Path) -> Path:
    storage.migrate(tmp_db)
    conn = sqlite3.connect(tmp_db)
    # Seed bookmarks so the JOIN in digest finds them.
    conn.executemany(
        """
        INSERT INTO discord_bookmarks
          (id, message_id, posted_at, content, attachment_urls, url, url_kind, channel)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                1,
                "md1",
                "2026-05-20T10:00:00Z",
                None,
                None,
                "https://x.com/a/1",
                "x_post",
                "general",
            ),
            (
                2,
                "md2",
                "2026-05-20T10:01:00Z",
                None,
                "https://cdn.discordapp.com/a.png",
                None,
                None,
                "general",
            ),
            (3, "md3", "2026-05-20T10:02:00Z", "lunch?", None, None, None, "general"),
            (
                4,
                "md4",
                "2026-05-18T10:02:00Z",
                None,
                None,
                "https://x.com/a/2",
                "x_post",
                "general",
            ),
        ],
    )
    now = datetime.utcnow()
    rows = [
        (
            1,
            "url",
            "Bull on MES",
            '{"priority":5,"tickers":["MES"],"has_action_item":true}',
            0.001,
            now,
        ),
        (
            2,
            "image",
            "Random meme",
            '{"priority":1,"tickers":[],"has_action_item":false}',
            0.0008,
            now,
        ),
        (
            3,
            "text",
            "Lunch options",
            '{"priority":2,"tickers":["SPY"],"has_action_item":false}',
            0.0001,
            now,
        ),
        (
            4,
            "url",
            "Yesterday item",
            '{"priority":4,"tickers":["NQ"],"has_action_item":true}',
            0.001,
            now - timedelta(days=2),
        ),
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
    assert "Bull on MES" in text  # priority 5 — present
    assert "Yesterday item" not in text  # excluded by 24h cutoff


def test_render_digest_ranks_by_priority(populated_db, tmp_path):
    path = digest.render(db_path=populated_db, vault_root=tmp_path)
    text = path.read_text(encoding="utf-8")
    assert text.find("Bull on MES") < text.find("Random meme")


def test_render_digest_returns_stats(populated_db, tmp_path):
    path = digest.render(db_path=populated_db, vault_root=tmp_path)
    text = path.read_text(encoding="utf-8")
    assert "Total: 3" in text
    assert "Cost: $" in text
