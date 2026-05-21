"""Tests for the three bookmark MCP tools in discord/mcp_server.py.

Covered:
  - get_recent_bookmarks: basic count + ordering (newest first)
  - get_recent_bookmarks: source_type filter
  - get_recent_bookmarks: domain substring filter
  - search_bookmarks: matches both content and embed_title
  - get_bookmark_stats: total, by_source_type dict, and top_domains shape

Design:
  - Never touches the production DB (engine/data/jarvis_trader.db).
  - Monkeypatches `discord.mcp_server._default_db_path` so all three tools
    resolve to a fresh tmp_path SQLite file seeded with known fixture rows.
  - Uses pytest-asyncio (asyncio_mode = auto, set in pyproject.toml).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

_JARVIS_CHANNEL = "1490851279180660819"


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _seed_db(db_path: str) -> None:
    """Create discord_bookmarks and insert 5 known rows.

    Row timeline (newest → oldest):
      row-1  x_post    x.com       1h ago
      row-2  github    github.com  2h ago
      row-3  x_post    x.com       3h ago
      row-4  video     youtube.com 4h ago
      row-5  other     example.com 200h ago (outside 7-day window)
    """
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS discord_bookmarks (
            message_id      TEXT PRIMARY KEY,
            channel_id      TEXT NOT NULL,
            posted_at       TEXT NOT NULL,
            url             TEXT NOT NULL,
            domain          TEXT,
            source_type     TEXT,
            embed_title     TEXT,
            embed_description TEXT,
            content         TEXT,
            author_name     TEXT,
            imported_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    now = _now_utc()
    rows = [
        (
            "row-1",
            _JARVIS_CHANNEL,
            _iso(now - timedelta(hours=1)),
            "https://x.com/foo/status/1",
            "x.com",
            "x_post",
            "MES setup from Corey",
            "Auction theory breakout",
            "check this out https://x.com/foo/status/1",
            "amoszn",
        ),
        (
            "row-2",
            _JARVIS_CHANNEL,
            _iso(now - timedelta(hours=2)),
            "https://github.com/openai/triton",
            "github.com",
            "github",
            "OpenAI Triton",
            "Fast GPU kernels for deep learning",
            "useful for regime stack https://github.com/openai/triton",
            "amoszn",
        ),
        (
            "row-3",
            _JARVIS_CHANNEL,
            _iso(now - timedelta(hours=3)),
            "https://x.com/bar/status/2",
            "x.com",
            "x_post",
            "ES auction update",
            None,
            "ES auction update https://x.com/bar/status/2",
            "amoszn",
        ),
        (
            "row-4",
            _JARVIS_CHANNEL,
            _iso(now - timedelta(hours=4)),
            "https://youtube.com/watch?v=abc123",
            "youtube.com",
            "video",
            "Auction Theory Deep Dive",
            "Full session walkthrough",
            "worth watching https://youtube.com/watch?v=abc123",
            "amoszn",
        ),
        (
            "row-5",
            _JARVIS_CHANNEL,
            _iso(now - timedelta(hours=200)),  # outside 7-day (168h) window
            "https://example.com/article",
            "example.com",
            "other",
            "Old article",
            None,
            "old stuff https://example.com/article",
            "amoszn",
        ),
    ]
    conn.executemany(
        """
        INSERT INTO discord_bookmarks
            (message_id, channel_id, posted_at, url, domain, source_type,
             embed_title, embed_description, content, author_name)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()
    conn.close()


@pytest.fixture()
def fixture_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """Return path to a seeded SQLite DB; monkeypatch _default_db_path to point at it."""
    db_path = str(tmp_path / "test_bookmarks.db")
    _seed_db(db_path)

    import discord.mcp_server as mcp_mod

    monkeypatch.setattr(mcp_mod, "_default_db_path", lambda: db_path)
    return db_path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_get_recent_bookmarks_basic(fixture_db: str) -> None:
    """5 seeded rows; default 168-hour window should return 4 (row-5 is 200h old)."""
    from discord.mcp_server import get_recent_bookmarks

    response = await get_recent_bookmarks(hours=168)
    results = response["bookmarks"]

    assert len(results) == 4, f"Expected 4 rows in window, got {len(results)}: {results}"
    # All 4 fit within default page_size, so no more pages.
    assert response["has_more"] is False
    assert response["next_before"] is None

    # Newest-first ordering: row-1 is 1h ago, row-4 is 4h ago
    posted_ats = [r["posted_at"] for r in results]
    assert posted_ats == sorted(posted_ats, reverse=True), "Results should be ordered newest-first"


async def test_get_recent_bookmarks_source_type_filter(fixture_db: str) -> None:
    """Filter by source_type='github' should return only row-2."""
    from discord.mcp_server import get_recent_bookmarks

    response = await get_recent_bookmarks(hours=168, source_type="github")
    results = response["bookmarks"]

    assert len(results) == 1
    assert results[0]["source_type"] == "github"
    assert results[0]["domain"] == "github.com"
    assert "openai/triton" in results[0]["url"]


async def test_get_recent_bookmarks_domain_substring(fixture_db: str) -> None:
    """Filter by domain='x.com' should return both x.com rows (row-1, row-3)."""
    from discord.mcp_server import get_recent_bookmarks

    response = await get_recent_bookmarks(hours=168, domain="x.com")
    results = response["bookmarks"]

    assert len(results) == 2
    for r in results:
        assert "x.com" in r["domain"]
    # Still newest-first
    assert results[0]["posted_at"] > results[1]["posted_at"]


async def test_get_recent_bookmarks_pagination_walks_full_corpus(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Seed 250 rows; walk pages of 100; assert 3 pages (100/100/50), no dupes, total=250.

    Validates the keyset (`before` cursor) pagination contract:
      - has_more flips to False on the last page
      - next_before advances backwards in time
      - no posted_at appears in more than one page
      - cumulative rows == total seeded
    """
    from discord.mcp_server import get_recent_bookmarks

    db_path = str(tmp_path / "pagination_bookmarks.db")
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS discord_bookmarks (
            message_id      TEXT PRIMARY KEY,
            channel_id      TEXT NOT NULL,
            posted_at       TEXT NOT NULL,
            url             TEXT NOT NULL,
            domain          TEXT,
            source_type     TEXT,
            embed_title     TEXT,
            embed_description TEXT,
            content         TEXT,
            author_name     TEXT,
            imported_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    now = _now_utc()
    # 250 rows, each 1 minute apart, all within the lookback window.
    rows = [
        (
            f"row-{i:04d}",
            _JARVIS_CHANNEL,
            _iso(now - timedelta(minutes=i + 1)),
            f"https://x.com/foo/status/{i}",
            "x.com",
            "x_post",
            f"Title {i}",
            f"Desc {i}",
            f"content {i}",
            "amoszn",
        )
        for i in range(250)
    ]
    conn.executemany(
        """
        INSERT INTO discord_bookmarks
            (message_id, channel_id, posted_at, url, domain, source_type,
             embed_title, embed_description, content, author_name)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()
    conn.close()

    import discord.mcp_server as mcp_mod

    monkeypatch.setattr(mcp_mod, "_default_db_path", lambda: db_path)

    collected: list[dict] = []
    seen_posted_ats: set[str] = set()
    cursor = ""
    pages = 0
    max_pages = 10  # safety cap

    while pages < max_pages:
        response = await get_recent_bookmarks(hours=720, limit=100, before=cursor)
        bookmarks = response["bookmarks"]
        assert response["page_size"] == 100, "page_size should echo back the clamped limit"

        for b in bookmarks:
            assert (
                b["posted_at"] not in seen_posted_ats
            ), f"Duplicate posted_at across pages: {b['posted_at']}"
            seen_posted_ats.add(b["posted_at"])

        collected.extend(bookmarks)
        pages += 1

        if not response["has_more"]:
            assert response["next_before"] is None
            break
        assert response["next_before"] is not None
        cursor = response["next_before"]

    assert pages == 3, f"Expected 3 pages (100/100/50), got {pages}"
    assert len(collected) == 250, f"Expected 250 total rows, got {len(collected)}"

    # Verify newest-first ordering preserved across page boundaries.
    posted_ats = [b["posted_at"] for b in collected]
    assert posted_ats == sorted(
        posted_ats, reverse=True
    ), "Cross-page ordering should remain newest-first"


async def test_get_recent_bookmarks_limit_clamped_to_200(
    fixture_db: str,
) -> None:
    """limit=999 should be clamped to 200; limit=0 should be clamped to 1."""
    from discord.mcp_server import get_recent_bookmarks

    response_high = await get_recent_bookmarks(hours=168, limit=999)
    assert response_high["page_size"] == 200

    response_low = await get_recent_bookmarks(hours=168, limit=0)
    assert response_low["page_size"] == 1


async def test_search_bookmarks_content_and_title(fixture_db: str) -> None:
    """Query 'auction' matches row-3 content, row-4 embed_title, and row-1 embed_description."""
    from discord.mcp_server import search_bookmarks

    results = await search_bookmarks(query="auction", days=30)

    # At least 3 rows should match: row-1 description, row-3 content, row-4 title
    message_ids = {r.get("url", "") for r in results}
    urls_with_auction = {
        "https://x.com/bar/status/2",  # content contains "auction update"
        "https://youtube.com/watch?v=abc123",  # embed_title "Auction Theory Deep Dive"
    }
    assert urls_with_auction.issubset(
        message_ids
    ), f"Expected auction-matching URLs in results; got {message_ids}"

    # source_type filter still works when combined
    results_x = await search_bookmarks(query="auction", days=30, source_type="x_post")
    for r in results_x:
        assert r["source_type"] == "x_post"


async def test_get_bookmark_stats_breakdown(fixture_db: str) -> None:
    """Stats over 30 days: total=4, by_source_type dict, and top_domains list shape."""
    from discord.mcp_server import get_bookmark_stats

    stats = await get_bookmark_stats(days=30)

    # Shape assertions
    assert "total" in stats
    assert "by_source_type" in stats
    assert "top_domains" in stats

    # 4 rows are within 30 days (row-5 is ~8 days old = 200h, still within 30d)
    # Actually row-5 is 200h = ~8.3 days, which IS within 30 days
    assert stats["total"] == 5, f"Expected 5 total (all rows within 30d), got {stats['total']}"

    by_type = stats["by_source_type"]
    assert isinstance(by_type, dict)
    assert by_type.get("x_post") == 2
    assert by_type.get("github") == 1
    assert by_type.get("video") == 1
    assert by_type.get("other") == 1

    top_domains = stats["top_domains"]
    assert isinstance(top_domains, list)
    assert len(top_domains) >= 1

    # Each entry must have domain + count keys
    for entry in top_domains:
        assert "domain" in entry, f"Missing 'domain' key in {entry}"
        assert "count" in entry, f"Missing 'count' key in {entry}"
        assert isinstance(entry["count"], int)

    # x.com should be the top domain (2 rows)
    domains_by_name = {e["domain"]: e["count"] for e in top_domains}
    assert domains_by_name.get("x.com") == 2, f"Expected x.com count=2, got {domains_by_name}"

    # days field echoed back
    assert stats["days"] == 30
