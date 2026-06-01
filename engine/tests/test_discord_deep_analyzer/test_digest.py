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
          (message_id, channel_id, posted_at, url, domain, source_type, content)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                "md1",
                "c1",
                "2026-05-20T10:00:00Z",
                "https://x.com/a/1",
                "x.com",
                "x_post",
                "https://x.com/a/1",
            ),
            ("md2", "c1", "2026-05-20T10:01:00Z", None, None, None, "image dropped here"),
            ("md3", "c1", "2026-05-20T10:02:00Z", None, None, None, "lunch?"),
            ("md4", "c1", "2026-05-18T10:02:00Z", "https://x.com/a/2", "x.com", "x_post", None),
        ],
    )
    now = datetime.utcnow()
    rows = [
        (
            "md1",
            "url",
            "Bull on MES",
            '{"priority":5,"tickers":["MES"],"has_action_item":true}',
            0.001,
            now,
        ),
        (
            "md2",
            "image",
            "Random meme",
            '{"priority":1,"tickers":[],"has_action_item":false}',
            0.0008,
            now,
        ),
        (
            "md3",
            "text",
            "Lunch options",
            '{"priority":2,"tickers":["SPY"],"has_action_item":false}',
            0.0001,
            now,
        ),
        (
            "md4",
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


@pytest.fixture
def db_with_p0(tmp_db: Path) -> Path:
    """Seed a db with one P0 (broken extract) and one P4 row."""
    storage.migrate(tmp_db)
    conn = sqlite3.connect(tmp_db)
    conn.executemany(
        """
        INSERT INTO discord_bookmarks
          (message_id, channel_id, posted_at, url, domain, source_type, content)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            ("p0_id", "c1", "2026-05-20T10:00:00Z", "https://x.com/a/1", "x.com", "x_post", None),
            ("p4_id", "c1", "2026-05-20T10:01:00Z", "https://x.com/a/2", "x.com", "x_post", None),
        ],
    )
    now = datetime.utcnow()
    conn.executemany(
        "INSERT INTO discord_analyses "
        "(bookmark_id, artifact_type, summary, structured_json, cost_usd, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [
            (
                "p0_id",
                "url",
                "Page could not be retrieved (privacy extension).",
                '{"priority":0,"tickers":[]}',
                0.0002,
                now.strftime("%Y-%m-%d %H:%M:%S"),
            ),
            (
                "p4_id",
                "url",
                "Bull thesis on MES into FOMC.",
                '{"priority":4,"tickers":["MES"]}',
                0.0010,
                now.strftime("%Y-%m-%d %H:%M:%S"),
            ),
        ],
    )
    conn.commit()
    conn.close()
    return tmp_db


def test_render_digest_filters_p0_from_top_items(db_with_p0, tmp_path):
    path = digest.render(db_path=db_with_p0, vault_root=tmp_path)
    text = path.read_text(encoding="utf-8")
    # P0 broken-extract summary must NOT appear in top items
    assert "could not be retrieved" not in text
    # P4 signal row must still appear
    assert "Bull thesis on MES" in text


def test_render_digest_reports_p0_count_separately(db_with_p0, tmp_path):
    path = digest.render(db_path=db_with_p0, vault_root=tmp_path)
    text = path.read_text(encoding="utf-8")
    # Total reflects signal rows only (1), P0 reported separately (1)
    assert "Total: 1" in text
    assert "Filtered (P0 / broken extracts): 1" in text


def test_render_digest_cost_includes_p0(db_with_p0, tmp_path):
    path = digest.render(db_path=db_with_p0, vault_root=tmp_path)
    text = path.read_text(encoding="utf-8")
    # Cost line should reflect BOTH rows (0.0002 + 0.0010 = 0.0012)
    assert "Cost: $0.0012" in text
