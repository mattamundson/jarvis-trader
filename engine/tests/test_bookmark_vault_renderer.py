"""Tests for the Discord bookmark → second-brain vault renderer.

Shape reference: `second-brain/wiki/discord-bookmarks/github/aaif-goose__goose.md`
                 `second-brain/wiki/discord-bookmarks/x/0xjeff-2043656911044870203.md`
                 `second-brain/wiki/discord-bookmarks/index.md`

v1 policy (catch-up mode):
  - If target MD file exists, SKIP it. Preserves manual triage and README excerpts
    from the 2026-04-17 one-shot render.
  - If target file is missing, CREATE it with a minimal but complete frontmatter
    block + placeholder body. GitHub enrichment is out of scope for v1.
  - Index is always regenerated from current SQLite state (cheap, derivable).
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

from discord.models import Bookmark
from discord.storage import init_tables, insert_bookmark
from scripts.render_bookmarks_to_vault import (
    github_slug,
    other_slug,
    render_page_for_bookmark,
    render_vault,
    x_post_slug,
)

JARVIS_CHANNEL = "1490851279180660819"


# ── Slug rules ────────────────────────────────────────────────────────────────

def test_github_slug_basic():
    assert github_slug("https://github.com/foo/bar") == "foo__bar"


def test_github_slug_preserves_case_in_repo_but_lowercases_owner():
    # Matches existing render: owner lowercased, repo preserved as-seen
    assert github_slug("https://github.com/AI4Finance-Foundation/FinGPT") == "ai4finance-foundation__fingpt"


def test_github_slug_strips_trailing_path():
    assert github_slug("https://github.com/foo/bar/tree/main") == "foo__bar"
    assert github_slug("https://github.com/foo/bar/blob/main/README.md") == "foo__bar"
    assert github_slug("https://github.com/foo/bar/pull/51") == "foo__bar"
    assert github_slug("https://github.com/foo/bar#readme") == "foo__bar"
    assert github_slug("https://github.com/foo/bar?linkId=1") == "foo__bar"


def test_github_slug_dots_in_repo_preserved():
    # Real-world: github.com/astral-sh/uv.docs — dot is valid in repo name
    assert github_slug("https://github.com/foo/bar.docs") == "foo__bar.docs"


def test_x_post_slug_basic():
    assert (
        x_post_slug("https://x.com/noisyb0y1/status/2044692412061425748?s=12")
        == "noisyb0y1-2044692412061425748"
    )


def test_x_post_slug_preserves_handle_case_lowercased():
    # Existing render lowercases handles: rohonchain not RohOnChain
    assert (
        x_post_slug("https://x.com/RohOnChain/status/2041180375838498950")
        == "rohonchain-2041180375838498950"
    )


def test_x_post_slug_twitter_com_alias():
    assert (
        x_post_slug("https://twitter.com/foo/status/123")
        == "foo-123"
    )


def test_other_slug_uses_domain_and_message_id():
    assert other_slug("https://youtube.com/watch?v=abc", "msg-123") == "youtube_com-msg-123"


# ── Page rendering ────────────────────────────────────────────────────────────

def _bm(**kwargs) -> Bookmark:
    defaults = {
        "message_id": "m1",
        "channel_id": JARVIS_CHANNEL,
        "posted_at": "2026-04-18T12:00:00+00:00",
        "url": "https://github.com/foo/bar",
        "domain": "github.com",
        "source_type": "github",
        "content": "check this out https://github.com/foo/bar",
        "author_id": "592060613732204544",
        "author_name": "AmoSZN",
    }
    defaults.update(kwargs)
    return Bookmark(**defaults)


def test_render_github_page_has_valid_frontmatter():
    bm = _bm(source_type="github", url="https://github.com/foo/bar")
    page = render_page_for_bookmark(bm)
    assert page.startswith("---\n")
    assert 'source: "discord-bookmark"' in page
    assert 'kind: "github"' in page
    assert 'url: "https://github.com/foo/bar"' in page
    assert 'owner: "foo"' in page
    assert 'repo: "bar"' in page
    assert 'jarvis_module: "unclassified"' in page
    assert 'status: "pending-review"' in page
    assert "# foo/bar" in page  # body heading


def test_render_x_post_page_has_valid_frontmatter():
    bm = _bm(
        source_type="x_post",
        url="https://x.com/noisyb0y1/status/2044692412061425748?s=12",
        domain="x.com",
        embed_title="Some tweet title",
        embed_description="Anthropic hackathon winner automated his workflow",
        content="https://x.com/noisyb0y1/status/2044692412061425748?s=12",
    )
    page = render_page_for_bookmark(bm)
    assert 'kind: "x-post"' in page
    assert 'author: "noisyb0y1"' in page
    assert 'status_id: "2044692412061425748"' in page
    assert "**@noisyb0y1**" in page
    # Body should include the embed_description in the quote block
    assert "Anthropic hackathon winner" in page


def test_render_x_post_uses_content_when_embed_absent():
    bm = _bm(
        source_type="x_post",
        url="https://x.com/foo/status/123",
        domain="x.com",
        embed_title=None,
        embed_description=None,
        content="hey look at this https://x.com/foo/status/123",
    )
    page = render_page_for_bookmark(bm)
    # With no embed, the user's Discord message text should surface as the quote
    assert "hey look at this" in page


def test_render_page_author_reflects_captured_name():
    bm = _bm(source_type="x_post", url="https://x.com/foo/status/123", domain="x.com")
    page = render_page_for_bookmark(bm)
    # Workstream A author_name bubbles through to the page body
    assert "AmoSZN" in page


# ── Full vault render (integration) ───────────────────────────────────────────

def _seed_db_with(bookmarks: list[Bookmark]) -> str:
    """Write a tempfile SQLite with the given bookmarks. Returns db_path."""
    td = tempfile.mkdtemp()
    db_path = str(Path(td) / "test.db")
    init_tables(db_path)
    conn = sqlite3.connect(db_path)
    try:
        for bm in bookmarks:
            insert_bookmark(conn, bm)
        conn.commit()
    finally:
        conn.close()
    return db_path


def test_render_vault_creates_new_github_page(tmp_path):
    db_path = _seed_db_with([
        _bm(message_id="new-1", url="https://github.com/foo/bar", source_type="github"),
    ])
    stats = render_vault(db_path, str(tmp_path))

    gh_file = tmp_path / "github" / "foo__bar.md"
    assert gh_file.exists()
    assert 'owner: "foo"' in gh_file.read_text(encoding="utf-8")
    assert stats["created"] == 1
    assert stats["skipped_existing"] == 0


def test_render_vault_skips_existing_page(tmp_path):
    """Core catch-up rule: existing files must never be overwritten."""
    gh_dir = tmp_path / "github"
    gh_dir.mkdir()
    preserved = gh_dir / "foo__bar.md"
    preserved.write_text(
        "---\nstatus: reviewed\njarvis_module: strategy\nnotes: user triage kept\n---\n# foo/bar\n<user body>\n",
        encoding="utf-8",
    )

    db_path = _seed_db_with([
        _bm(message_id="existing-1", url="https://github.com/foo/bar", source_type="github"),
    ])
    stats = render_vault(db_path, str(tmp_path))

    content = preserved.read_text(encoding="utf-8")
    # Must not overwrite ANY existing content
    assert "status: reviewed" in content
    assert "jarvis_module: strategy" in content
    assert "notes: user triage kept" in content
    assert "<user body>" in content
    assert stats["created"] == 0
    assert stats["skipped_existing"] == 1


def test_render_vault_creates_x_post_page(tmp_path):
    db_path = _seed_db_with([
        _bm(
            message_id="new-x",
            url="https://x.com/noisyb0y1/status/2044692412061425748?s=12",
            source_type="x_post",
            domain="x.com",
            embed_description="Anthropic hackathon winner",
        ),
    ])
    stats = render_vault(db_path, str(tmp_path))

    x_file = tmp_path / "x" / "noisyb0y1-2044692412061425748.md"
    assert x_file.exists()
    assert "Anthropic hackathon winner" in x_file.read_text(encoding="utf-8")
    assert stats["created"] == 1


def test_render_vault_is_idempotent(tmp_path):
    """Second run produces zero new files and makes zero changes."""
    db_path = _seed_db_with([
        _bm(message_id="m1", url="https://github.com/foo/bar", source_type="github"),
        _bm(message_id="m2", url="https://x.com/foo/status/123", source_type="x_post", domain="x.com"),
    ])

    stats1 = render_vault(db_path, str(tmp_path))
    stats2 = render_vault(db_path, str(tmp_path))

    assert stats1["created"] == 2
    assert stats2["created"] == 0
    assert stats2["skipped_existing"] == 2


def test_render_vault_writes_index_with_counts(tmp_path):
    db_path = _seed_db_with([
        _bm(message_id="m1", url="https://github.com/foo/bar", source_type="github"),
        _bm(message_id="m2", url="https://x.com/foo/status/123", source_type="x_post", domain="x.com"),
        _bm(message_id="m3", url="https://x.com/baz/status/456", source_type="x_post", domain="x.com"),
    ])
    render_vault(db_path, str(tmp_path))

    index_file = tmp_path / "index.md"
    assert index_file.exists()
    content = index_file.read_text(encoding="utf-8")
    assert 'total_links: "3"' in content
    # At least one wikilink per bookmark
    assert "foo__bar" in content
    assert "foo-123" in content
    assert "baz-456" in content


def test_render_vault_video_goes_to_other_bucket(tmp_path):
    db_path = _seed_db_with([
        _bm(
            message_id="v1",
            url="https://youtube.com/watch?v=abc",
            source_type="video",
            domain="youtube.com",
        ),
    ])
    render_vault(db_path, str(tmp_path))

    other_dir = tmp_path / "other"
    assert other_dir.exists()
    files = list(other_dir.glob("*.md"))
    assert len(files) == 1
    assert "youtube_com" in files[0].name
