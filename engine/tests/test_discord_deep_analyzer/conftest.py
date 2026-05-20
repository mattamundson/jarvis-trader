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
            (
                "m2",
                "2026-05-20T10:01:00Z",
                None,
                None,
                "https://x.com/a/status/1",
                "x_post",
                "general",
            ),
            (
                "m3",
                "2026-05-20T10:02:00Z",
                None,
                "https://cdn.discordapp.com/a.png",
                None,
                None,
                "general",
            ),
        ],
    )
    conn.commit()
    conn.close()
    return tmp_db
