"""
Tests for `discord.bookmark_synthesizer`.

These tests use a temporary on-disk SQLite database (NOT the real
`engine/data/jarvis_trader.db`) seeded with mocked rows. Per spec:
"DO NOT mock against the real db."
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import List, Tuple

import pytest

from discord.bookmark_synthesizer import (  # noqa: E402
    BookmarkRow,
    _extract_github_repo,
    _extract_xcom_author,
    _query_bookmarks_in_window,
    _split_by_domain,
    _summarize_github_items,
    _summarize_xcom_authors,
    synthesize_delta,
)

# ── Fixture helpers ──────────────────────────────────────────────────────────


SCHEMA = """
CREATE TABLE discord_bookmarks (
    message_id TEXT PRIMARY KEY,
    channel_id TEXT NOT NULL,
    posted_at TEXT NOT NULL,
    url TEXT NOT NULL,
    domain TEXT,
    source_type TEXT,
    embed_title TEXT,
    embed_description TEXT,
    imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    content TEXT,
    author_id TEXT,
    author_name TEXT
);
"""


# (message_id, posted_at, url, source_type, embed_title, embed_description)
SeedRow = Tuple[str, str, str, str, str, str]


def _seed(db_path: Path, rows: List[SeedRow]) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(SCHEMA)
        conn.executemany(
            """
            INSERT INTO discord_bookmarks
              (message_id, channel_id, posted_at, url, domain, source_type,
               embed_title, embed_description)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    mid,
                    "1490851279180660819",
                    posted_at,
                    url,
                    None,
                    source_type,
                    title or None,
                    desc or None,
                )
                for (mid, posted_at, url, source_type, title, desc) in rows
            ],
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture()
def seeded_db(tmp_path: Path) -> Path:
    """A throwaway SQLite db seeded with a known 14-day delta."""
    db = tmp_path / "jarvis_trader_test.db"
    _seed(
        db,
        [
            # ── BEFORE window (should be excluded) ──
            ("m0", "2026-05-04T23:59:59", "https://x.com/oldauthor/status/1", "xcom", "", ""),
            (
                "m1",
                "2026-05-01T12:00:00",
                "https://github.com/old/repo",
                "github",
                "Old repo",
                "Old blurb",
            ),
            # ── INSIDE window 2026-05-05 .. 2026-05-19 ──
            (
                "m2",
                "2026-05-05T00:00:01",
                "https://github.com/radimsem/remindb",
                "github",
                "remindb",
                "Knowledge-base MCP server.",
            ),
            (
                "m3",
                "2026-05-07T10:00:00",
                "https://github.com/strukto-ai/mirage",
                "github",
                "mirage",
                "Unified VFS for AI agents.",
            ),
            (
                "m4",
                "2026-05-09T11:00:00",
                "https://github.com/garrytan/gbrain",
                "github",
                "gbrain",
                "Agent brain.",
            ),
            # X.com cluster: @tom_doerr 3 posts, @alice 2, @bob 1, @carol 1, @dan 1
            ("m5", "2026-05-06T09:00:00", "https://x.com/tom_doerr/status/100", "xcom", "", ""),
            ("m6", "2026-05-07T09:00:00", "https://x.com/tom_doerr/status/101", "xcom", "", ""),
            (
                "m7",
                "2026-05-08T09:00:00",
                "https://twitter.com/tom_doerr/status/102",
                "xcom",
                "",
                "",
            ),
            ("m8", "2026-05-09T09:00:00", "https://x.com/alice/status/200", "xcom", "", ""),
            ("m9", "2026-05-10T09:00:00", "https://x.com/Alice/status/201", "xcom", "", ""),  # case
            ("m10", "2026-05-11T09:00:00", "https://x.com/bob/status/300", "xcom", "", ""),
            ("m11", "2026-05-12T09:00:00", "https://x.com/carol/status/400", "xcom", "", ""),
            ("m12", "2026-05-13T09:00:00", "https://x.com/dan/status/500", "xcom", "", ""),
            # other-domain bookmark
            ("m13", "2026-05-14T09:00:00", "https://example.com/article", "web", "Article", "Misc"),
            # ── AFTER window (should be excluded) ──
            ("m14", "2026-05-19T00:00:01", "https://x.com/future/status/1", "xcom", "", ""),
            ("m15", "2026-06-01T00:00:00", "https://github.com/future/repo", "github", "", ""),
        ],
    )
    return db


# ── Tests (required ≥4) ──────────────────────────────────────────────────────


def test_query_window_excludes_pre_cutoff(seeded_db: Path) -> None:
    """Bookmarks posted before `since` must not appear in the result."""
    rows = _query_bookmarks_in_window("2026-05-05", "2026-05-19", db_path=str(seeded_db))
    msg_ids = {r.message_id for r in rows}
    # before-window rows excluded
    assert "m0" not in msg_ids
    assert "m1" not in msg_ids
    # boundary rows: 'until' is exclusive
    assert "m14" not in msg_ids
    assert "m15" not in msg_ids
    # 'since' is inclusive — m2 at 2026-05-05T00:00:01 should be included
    assert "m2" in msg_ids
    # spot-check in-window rows
    for mid in ("m3", "m4", "m5", "m12", "m13"):
        assert mid in msg_ids, f"expected {mid} in window result"
    # count: 12 rows in window (m2..m13)
    assert len(rows) == 12


def test_github_section_lists_all_repos_with_embeds(seeded_db: Path) -> None:
    """Every github bookmark in window must appear in the github section."""
    rows = _query_bookmarks_in_window("2026-05-05", "2026-05-19", db_path=str(seeded_db))
    buckets = _split_by_domain(rows)
    assert (
        len(buckets["github"]) == 3
    ), f"expected 3 github items in window, got {len(buckets['github'])}"
    section = _summarize_github_items(buckets["github"])
    # Every repo URL slug is listed
    for slug in ("radimsem/remindb", "strukto-ai/mirage", "garrytan/gbrain"):
        assert slug in section, f"expected {slug!r} in github section, got:\n{section}"
    # Embed titles and blurbs surface
    assert "remindb" in section
    assert "Knowledge-base MCP server." in section
    assert "Unified VFS for AI agents." in section
    # No LLM triage call ("actionable"/"probe"/"noise") in scaffold output
    # — only a deferred-triage notice; verify the explicit "deferred" string is present.
    assert "deferred" in section.lower()


def test_xcom_author_aggregation_correct(seeded_db: Path) -> None:
    """Author aggregation must match a hand-counted distribution.

    Expected (window): @tom_doerr=3, @alice=2 (case-insensitive merge),
    @bob=1, @carol=1, @dan=1. 5 distinct authors, 8 total posts.
    Top-10 coverage = 100%.
    """
    rows = _query_bookmarks_in_window("2026-05-05", "2026-05-19", db_path=str(seeded_db))
    buckets = _split_by_domain(rows)
    assert len(buckets["xcom"]) == 8

    section = _summarize_xcom_authors(buckets["xcom"])

    # Aggregation: tom_doerr is the top by count
    assert "| 3 | @tom_doerr |" in section, f"expected tom_doerr=3 row, got:\n{section}"
    assert "| 2 | @alice |" in section, f"expected alice=2 row, got:\n{section}"
    assert "| 1 | @bob |" in section
    assert "| 1 | @carol |" in section
    assert "| 1 | @dan |" in section

    # Distinct authors and totals reported correctly
    assert "8 X.com posts" in section
    assert "5 distinct authors" in section
    # 8 posts / top-10 covers all of them
    assert "100% of posts" in section


def test_synthesize_delta_returns_nonempty_markdown(seeded_db: Path) -> None:
    """End-to-end smoke: full markdown rendering."""
    md = synthesize_delta("2026-05-05", "2026-05-19", db_path=str(seeded_db))
    assert isinstance(md, str)
    assert len(md) > 500, "expected a substantive markdown document"
    # Headline numbers
    assert "12 new bookmarks" in md, f"expected total=12 in headline, got:\n{md[:400]}"
    assert "3 GitHub" in md
    assert "8 X.com" in md
    assert "1 other" in md
    # Section headers
    assert "## Headline" in md
    assert "## Volume profile" in md
    assert "## GitHub bucket" in md
    assert "## X.com bucket" in md
    assert "## Provenance" in md
    # Window appears in heading
    assert "2026-05-05 → 2026-05-19" in md


# ── Bonus coverage for unit helpers ──────────────────────────────────────────


def test_extract_xcom_author_variants() -> None:
    assert _extract_xcom_author("https://x.com/tom_doerr/status/1") == "tom_doerr"
    assert _extract_xcom_author("https://twitter.com/tom_doerr") == "tom_doerr"
    assert _extract_xcom_author("https://www.x.com/tom_doerr?ref=1") == "tom_doerr"
    # reserved paths are not authors
    assert _extract_xcom_author("https://x.com/home") is None
    assert _extract_xcom_author("https://x.com/i/lists/123") is None
    # non-twitter URLs
    assert _extract_xcom_author("https://github.com/foo/bar") is None
    assert _extract_xcom_author("") is None


def test_extract_github_repo_variants() -> None:
    assert _extract_github_repo("https://github.com/foo/bar") == "foo/bar"
    assert _extract_github_repo("https://github.com/foo/bar/tree/main") == "foo/bar"
    assert _extract_github_repo("https://github.com/foo/bar.git") == "foo/bar"
    assert _extract_github_repo("https://www.github.com/foo/bar?tab=readme") == "foo/bar"
    # Non-repo URL
    assert _extract_github_repo("https://x.com/foo") is None
    assert _extract_github_repo("") is None


def test_split_by_domain_falls_back_to_url_pattern() -> None:
    """When source_type is missing, URL pattern must still bucket correctly."""
    rows = [
        BookmarkRow("a", "c", "2026-05-10", "https://github.com/foo/bar", None, None, None, None),
        BookmarkRow("b", "c", "2026-05-10", "https://x.com/alice/status/1", None, None, None, None),
        BookmarkRow(
            "c", "c", "2026-05-10", "https://twitter.com/bob/status/1", None, None, None, None
        ),
        BookmarkRow("d", "c", "2026-05-10", "https://example.com/page", None, None, None, None),
    ]
    buckets = _split_by_domain(rows)
    assert [r.message_id for r in buckets["github"]] == ["a"]
    assert [r.message_id for r in buckets["xcom"]] == ["b", "c"]
    assert [r.message_id for r in buckets["other"]] == ["d"]
