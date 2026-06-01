"""Shared fixtures for deep_analyzer tests."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    """Empty sqlite db with the production discord_bookmarks schema pre-created."""
    db = tmp_path / "discord.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE discord_bookmarks (
            message_id        TEXT PRIMARY KEY NOT NULL,
            channel_id        TEXT,
            posted_at         TEXT NOT NULL,
            url               TEXT,
            domain            TEXT,
            source_type       TEXT,
            embed_title       TEXT,
            embed_description TEXT,
            imported_at       TEXT DEFAULT CURRENT_TIMESTAMP,
            content           TEXT,
            author_id         TEXT,
            author_name       TEXT
        );
        """
    )
    conn.commit()
    conn.close()
    return db


@pytest.fixture
def seeded_db(tmp_db: Path) -> Path:
    """tmp_db with 3 unanalyzed rows matching production-shaped data."""
    conn = sqlite3.connect(tmp_db)
    conn.executemany(
        """
        INSERT INTO discord_bookmarks
          (message_id, channel_id, posted_at, url, domain, source_type, content)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            # m1: text-only (no url) — represents a future text-only message
            ("m1", "c1", "2026-05-20T10:00:00Z", None, None, None, "text-only note"),
            # m2: x-post (the dominant real shape)
            (
                "m2",
                "c1",
                "2026-05-20T10:01:00Z",
                "https://x.com/a/status/1",
                "x.com",
                "x_post",
                "https://x.com/a/status/1",
            ),
            # m3: github (the other common shape)
            (
                "m3",
                "c1",
                "2026-05-20T10:02:00Z",
                "https://github.com/owner/repo",
                "github.com",
                "github",
                "https://github.com/owner/repo",
            ),
        ],
    )
    conn.commit()
    conn.close()
    return tmp_db
