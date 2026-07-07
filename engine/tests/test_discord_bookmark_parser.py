"""Regression tests for the Jarvis-Trader bookmark pipeline.

Covered:
  - URL extraction picks the first http(s) URL in content
  - Trailing punctuation (closing paren / comma) stripped
  - Domain normalization drops `www.` prefix
  - Source-type classification: x.com / twitter.com → x_post; github.com → github;
    youtube.com → video; everything else → other
  - Messages with no URL are skipped (not an error)
  - embed_title / embed_description pulled when present, None when absent
  - Round-trip: parsed dict instantiates `Bookmark` model and inserts via
    `insert_bookmark` on a fresh in-memory schema. Duplicate message_id is no-op
    (INSERT OR IGNORE).
  - Dispatch wiring: CHANNEL_MAP has the jarvis-trader channel entry and
    process_file routes it to the bookmark parser.
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from discord.channel_parsers import bookmark as bookmark_parser
from discord.models import Bookmark
from discord.parser import CHANNEL_MAP
from discord.storage import init_tables, insert_bookmark

JARVIS_CHANNEL = "1490851279180660819"


def _msg(
    id_: str, content: str, timestamp: str = "2026-04-16T08:49:26.064-05:00", embeds=None
) -> dict:
    return {
        "id": id_,
        "content": content,
        "timestamp": timestamp,
        "embeds": embeds or [],
        "author": {"id": "564449478174703647", "name": "amoszn"},
    }


def test_extracts_first_url_from_content():
    parsed = bookmark_parser.parse_channel(
        [_msg("1", "https://x.com/noisyb0y1/status/2044692412061425748?s=12")]
    )
    assert len(parsed) == 1
    assert parsed[0]["url"] == "https://x.com/noisyb0y1/status/2044692412061425748?s=12"
    assert parsed[0]["domain"] == "x.com"
    assert parsed[0]["source_type"] == "x_post"
    assert parsed[0]["message_id"] == "1"
    assert parsed[0]["channel_id"] == JARVIS_CHANNEL


def test_first_url_wins_when_multiple():
    parsed = bookmark_parser.parse_channel(
        [_msg("2", "check these: https://github.com/foo/bar and https://x.com/baz")]
    )
    assert len(parsed) == 1
    assert parsed[0]["url"] == "https://github.com/foo/bar"
    assert parsed[0]["source_type"] == "github"


def test_trailing_punctuation_stripped():
    parsed = bookmark_parser.parse_channel([_msg("3", "see (https://github.com/foo/bar),")])
    assert parsed[0]["url"] == "https://github.com/foo/bar"


def test_www_prefix_dropped_from_domain():
    parsed = bookmark_parser.parse_channel([_msg("4", "https://www.example.com/article")])
    assert parsed[0]["domain"] == "example.com"
    assert parsed[0]["source_type"] == "other"


def test_source_type_classifications():
    msgs = [
        _msg("a", "https://x.com/foo"),
        _msg("b", "https://twitter.com/foo"),
        _msg("c", "https://github.com/foo/bar"),
        _msg("d", "https://youtube.com/watch?v=abc"),
        _msg("e", "https://youtu.be/xyz"),
        _msg("f", "https://some-news-site.com/article"),
    ]
    parsed = bookmark_parser.parse_channel(msgs)
    types = [p["source_type"] for p in parsed]
    assert types == ["x_post", "x_post", "github", "video", "video", "other"]


def test_messages_without_url_skipped_not_errored():
    parsed = bookmark_parser.parse_channel(
        [
            _msg("1", "hey did anyone see the thing"),
            _msg("2", "https://x.com/foo"),
            _msg("3", ""),
        ]
    )
    # Only the one with a URL survives; the other two are silently skipped
    assert len(parsed) == 1
    assert parsed[0]["message_id"] == "2"


def test_embed_title_and_description_populate_when_present():
    msg = _msg(
        "7",
        "https://x.com/noisyb0y1/status/2044692412061425748",
        embeds=[
            {
                "title": "",
                "description": "Anthropic hackathon winner automated his workflow",
                "url": "https://twitter.com/noisyb0y1/status/2044692412061425748",
            }
        ],
    )
    parsed = bookmark_parser.parse_channel([msg])
    assert parsed[0]["embed_title"] is None  # empty string → None
    assert parsed[0]["embed_description"] == "Anthropic hackathon winner automated his workflow"


def test_embed_fields_none_when_no_embeds():
    parsed = bookmark_parser.parse_channel([_msg("8", "https://github.com/foo/bar")])
    assert parsed[0]["embed_title"] is None
    assert parsed[0]["embed_description"] is None


def test_bookmark_model_accepts_parsed_dict():
    parsed = bookmark_parser.parse_channel([_msg("9", "https://x.com/foo")])
    bm = Bookmark(**parsed[0])
    assert bm.message_id == "9"
    assert bm.source_type == "x_post"


def test_insert_bookmark_and_idempotent_reimport():
    with tempfile.TemporaryDirectory() as td:
        db_path = str(Path(td) / "test.db")
        init_tables(db_path)

        parsed = bookmark_parser.parse_channel([_msg("10", "https://github.com/foo/bar")])
        bm = Bookmark(**parsed[0])

        conn = sqlite3.connect(db_path)
        try:
            first_insert = insert_bookmark(conn, bm)
            second_insert = insert_bookmark(conn, bm)  # duplicate PK
            count = conn.execute("SELECT COUNT(*) FROM discord_bookmarks").fetchone()[0]
        finally:
            conn.close()  # Windows won't release file lock until close()

        assert first_insert is True
        assert second_insert is False
        assert count == 1  # idempotent


def test_channel_map_has_jarvis_entry():
    assert JARVIS_CHANNEL in CHANNEL_MAP
    entry = CHANNEL_MAP[JARVIS_CHANNEL]
    assert entry["parser"] == "bookmark"
    assert entry["type"] == "bookmark"


# ── Workstream A: message context enrichment ──────────────────────────────────
# Captures the commentary and author around each URL so downstream agents
# (clusterer, vault renderer, master-jarvis reader) can reason about WHY a
# link was dropped, not just the link itself.


def test_content_captured_from_message():
    parsed = bookmark_parser.parse_channel(
        [_msg("c1", "this looks useful for regime detection https://github.com/foo/bar")]
    )
    assert (
        parsed[0]["content"] == "this looks useful for regime detection https://github.com/foo/bar"
    )


def test_author_metadata_captured():
    parsed = bookmark_parser.parse_channel([_msg("c2", "https://x.com/foo")])
    # _msg() fixture hard-codes author_id=564449478174703647, name=amoszn
    assert parsed[0]["author_id"] == "564449478174703647"
    assert parsed[0]["author_name"] == "amoszn"


def test_content_missing_author_safe():
    msg = {
        "id": "c3",
        "content": "https://x.com/foo",
        "timestamp": "2026-04-16T08:49:26.064-05:00",
        "embeds": [],
    }
    # No "author" key at all — parser must not raise
    parsed = bookmark_parser.parse_channel([msg])
    assert parsed[0]["author_id"] is None
    assert parsed[0]["author_name"] is None


def test_attachment_urls_extracted_when_present():
    """Path B (2026-05-20): DiscordChatExporter `attachments` list is captured.

    Voice memos / PDFs / images attached to a message are joined as a
    space-separated URL string in `attachment_urls`, matching the format
    deep_analyzer.handlers._split_urls accepts.
    """
    msg = {
        "id": "att1",
        "content": "voice memo + chart https://github.com/foo/bar",
        "timestamp": "2026-05-20T10:00:00Z",
        "embeds": [],
        "author": {"id": "1", "name": "amoszn"},
        "attachments": [
            {"url": "https://cdn.discordapp.com/attachments/1/2/memo.wav", "fileName": "memo.wav"},
            {
                "url": "https://cdn.discordapp.com/attachments/1/3/chart.png",
                "fileName": "chart.png",
            },
        ],
    }
    parsed = bookmark_parser.parse_channel([msg])
    assert len(parsed) == 1
    assert parsed[0]["attachment_urls"] == (
        "https://cdn.discordapp.com/attachments/1/2/memo.wav "
        "https://cdn.discordapp.com/attachments/1/3/chart.png"
    )


def test_attachment_urls_none_when_no_attachments():
    parsed = bookmark_parser.parse_channel([_msg("noatt", "https://github.com/foo/bar")])
    assert parsed[0]["attachment_urls"] is None


def test_attachment_with_missing_url_ignored():
    """Tolerate malformed attachment entries — drop those without `url`."""
    msg = {
        "id": "att2",
        "content": "https://github.com/foo/bar",
        "timestamp": "2026-05-20T10:00:00Z",
        "embeds": [],
        "author": {"id": "1", "name": "amoszn"},
        "attachments": [
            {"fileName": "no-url.txt"},  # malformed
            {"url": "https://cdn.discordapp.com/attachments/1/4/ok.png"},
        ],
    }
    parsed = bookmark_parser.parse_channel([msg])
    assert parsed[0]["attachment_urls"] == "https://cdn.discordapp.com/attachments/1/4/ok.png"


def test_real_dce_author_shape_uses_username():
    """DiscordChatExporter real output uses `username` + `global_name`, NOT `name`.

    Regression discovered 2026-04-20: the test fixture used `name` and the parser
    matched it, but live exports for the jarvis-trader channel have
    {id, username, global_name, discriminator, avatar, ...} with no `name` key.
    Author name resolution priority: global_name > username > name (fixture compat).
    """
    real_dce_msg = {
        "id": "dce-1",
        "content": "https://github.com/foo/bar",
        "timestamp": "2026-04-16T08:49:26.064-05:00",
        "embeds": [],
        "author": {
            "id": "592060613732204544",
            "username": "amoszn",
            "global_name": "AmoSZN",
            "discriminator": "0",
            "avatar": "xyz",
        },
    }
    parsed = bookmark_parser.parse_channel([real_dce_msg])
    assert parsed[0]["author_id"] == "592060613732204544"
    assert parsed[0]["author_name"] == "AmoSZN"  # prefer display name


def test_real_dce_author_falls_back_to_username_when_global_name_absent():
    msg = {
        "id": "dce-2",
        "content": "https://github.com/foo/bar",
        "timestamp": "2026-04-16T08:49:26.064-05:00",
        "embeds": [],
        "author": {"id": "592060613732204544", "username": "amoszn"},
    }
    parsed = bookmark_parser.parse_channel([msg])
    assert parsed[0]["author_name"] == "amoszn"


def test_real_dce_author_null_when_all_name_fields_empty():
    msg = {
        "id": "dce-3",
        "content": "https://github.com/foo/bar",
        "timestamp": "2026-04-16T08:49:26.064-05:00",
        "embeds": [],
        "author": {"id": "abc", "username": "", "global_name": None},
    }
    parsed = bookmark_parser.parse_channel([msg])
    assert parsed[0]["author_name"] is None


def test_content_truncated_at_5000_chars():
    long_text = "x" * 6000 + " https://github.com/foo/bar"
    parsed = bookmark_parser.parse_channel([_msg("c4", long_text)])
    assert len(parsed[0]["content"]) == 5000


def test_bookmark_model_accepts_content_and_author_fields():
    bm = Bookmark(
        message_id="c5",
        channel_id=JARVIS_CHANNEL,
        posted_at="2026-04-16T08:49:26.064-05:00",
        url="https://x.com/foo",
        content="hey look at this",
        author_id="564449478174703647",
        author_name="amoszn",
    )
    assert bm.content == "hey look at this"
    assert bm.author_id == "564449478174703647"
    assert bm.author_name == "amoszn"


def test_init_tables_adds_content_columns_on_pre_workstream_a_db():
    """Simulates migration against a DB created with the OLD 8-column schema."""
    with tempfile.TemporaryDirectory() as td:
        db_path = str(Path(td) / "old.db")
        # Pre-Workstream-A DDL: 8 columns, no content/author
        conn = sqlite3.connect(db_path)
        try:
            conn.executescript(
                """
                CREATE TABLE discord_bookmarks (
                    message_id TEXT PRIMARY KEY,
                    channel_id TEXT NOT NULL,
                    posted_at TEXT NOT NULL,
                    url TEXT NOT NULL,
                    domain TEXT,
                    source_type TEXT,
                    embed_title TEXT,
                    embed_description TEXT,
                    imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
            """
            )
            conn.execute(
                "INSERT INTO discord_bookmarks (message_id, channel_id, posted_at, url) "
                "VALUES (?, ?, ?, ?)",
                ("legacy-1", JARVIS_CHANNEL, "2026-04-07T00:00:00+00:00", "https://x.com/legacy"),
            )
            conn.commit()
        finally:
            conn.close()

        # Run the migration
        init_tables(db_path)

        # New columns exist; legacy row has NULL values (not errors)
        conn = sqlite3.connect(db_path)
        try:
            cols = {
                row[1] for row in conn.execute("PRAGMA table_info(discord_bookmarks)").fetchall()
            }
            assert "content" in cols
            assert "author_id" in cols
            assert "author_name" in cols
            row = conn.execute(
                "SELECT content, author_id, author_name FROM discord_bookmarks WHERE message_id='legacy-1'"
            ).fetchone()
            assert row == (None, None, None)
        finally:
            conn.close()


def test_init_tables_is_idempotent_on_migrated_db():
    """Running init_tables a second time must not raise on existing columns."""
    with tempfile.TemporaryDirectory() as td:
        db_path = str(Path(td) / "new.db")
        init_tables(db_path)
        init_tables(db_path)  # second call: columns already exist
        init_tables(db_path)  # third call for good measure


def test_insert_bookmark_persists_content_and_author():
    with tempfile.TemporaryDirectory() as td:
        db_path = str(Path(td) / "test.db")
        init_tables(db_path)

        bm = Bookmark(
            message_id="c6",
            channel_id=JARVIS_CHANNEL,
            posted_at="2026-04-16T08:49:26.064-05:00",
            url="https://github.com/foo/bar",
            content="worth evaluating for the regime stack",
            author_id="564449478174703647",
            author_name="amoszn",
        )

        conn = sqlite3.connect(db_path)
        try:
            insert_bookmark(conn, bm)
            row = conn.execute(
                "SELECT content, author_id, author_name FROM discord_bookmarks WHERE message_id=?",
                (bm.message_id,),
            ).fetchone()
        finally:
            conn.close()

        assert row == ("worth evaluating for the regime stack", "564449478174703647", "amoszn")


def test_update_bookmark_context_backfills_existing_row():
    """Used by CLI re-import to populate content/author on rows already inserted pre-Workstream-A."""
    from discord.storage import update_bookmark_context

    with tempfile.TemporaryDirectory() as td:
        db_path = str(Path(td) / "test.db")
        init_tables(db_path)

        bare = Bookmark(
            message_id="c7",
            channel_id=JARVIS_CHANNEL,
            posted_at="2026-04-16T08:49:26.064-05:00",
            url="https://github.com/foo/bar",
        )
        conn = sqlite3.connect(db_path)
        try:
            insert_bookmark(conn, bare)
            updated = update_bookmark_context(
                conn, "c7", "added context later", "564449478174703647", "amoszn"
            )
            row = conn.execute(
                "SELECT content, author_id, author_name FROM discord_bookmarks WHERE message_id=?",
                ("c7",),
            ).fetchone()
        finally:
            conn.close()

        assert updated is True
        assert row == ("added context later", "564449478174703647", "amoszn")


def test_update_bookmark_context_returns_false_for_missing_row():
    from discord.storage import update_bookmark_context

    with tempfile.TemporaryDirectory() as td:
        db_path = str(Path(td) / "test.db")
        init_tables(db_path)
        conn = sqlite3.connect(db_path)
        try:
            result = update_bookmark_context(conn, "nonexistent", "x", "y", "z")
        finally:
            conn.close()
        assert result is False


def test_process_file_backfills_context_on_second_import():
    """
    Simulates the backfill flow: 371 rows from the 2026-04-20 01:30 CT import
    have NULL content/author. A re-import with the same source JSON must
    populate those fields via UPDATE, even though INSERT OR IGNORE skips the row.
    """
    import json

    from discord.parser import process_file

    sample_messages = [
        {
            "id": "backfill-1",
            "content": "this repo might help the regime stack https://github.com/foo/bar",
            "timestamp": "2026-04-16T08:49:26.064-05:00",
            "embeds": [],
            "author": {"id": "564449478174703647", "name": "amoszn"},
        }
    ]

    with tempfile.TemporaryDirectory() as td:
        db_path = str(Path(td) / "test.db")
        init_tables(db_path)

        # Simulate a pre-Workstream-A import: insert the row with content=NULL.
        conn = sqlite3.connect(db_path)
        try:
            bare = Bookmark(
                message_id="backfill-1",
                channel_id=JARVIS_CHANNEL,
                posted_at="2026-04-16T08:49:26.064-05:00",
                url="https://github.com/foo/bar",
            )
            insert_bookmark(conn, bare)  # content/author NULL
            conn.commit()  # persist before next connection opens
            pre = conn.execute(
                "SELECT content, author_id FROM discord_bookmarks WHERE message_id=?",
                ("backfill-1",),
            ).fetchone()
            assert pre == (None, None)  # baseline: NULL before re-import
        finally:
            conn.close()

        # Write fixture JSON that process_file expects (DiscordChatExporter shape).
        fixture = Path(td) / "Jarvis-Trader - general [1490851279180660819].json"
        fixture.write_text(
            json.dumps({"messages": sample_messages, "channel": {"id": JARVIS_CHANNEL}}),
            encoding="utf-8",
        )

        # Re-import — INSERT OR IGNORE will skip the existing row, but the
        # backfill step must UPDATE content/author from the fresh parse.
        conn = sqlite3.connect(db_path)
        try:
            channel_info = {"parser": "bookmark", "type": "bookmark"}
            stats = process_file(
                filepath=str(fixture),
                channel_id=JARVIS_CHANNEL,
                channel_info=channel_info,
                conn=conn,
                dry_run=False,
            )
            conn.commit()
            row = conn.execute(
                "SELECT content, author_id, author_name FROM discord_bookmarks WHERE message_id=?",
                ("backfill-1",),
            ).fetchone()
        finally:
            conn.close()

        assert row == (
            "this repo might help the regime stack https://github.com/foo/bar",
            "564449478174703647",
            "amoszn",
        ), f"process_file did not backfill context on second import; got {row}"
        # Also: the row counted as "skipped" (already present) but context was updated.
        assert stats["skipped"] == 1
        assert stats["inserted"] == 0


def test_row_roundtrip_preserves_all_columns():
    """Insert a bookmark with every field populated; verify SELECT returns same values."""
    with tempfile.TemporaryDirectory() as td:
        db_path = str(Path(td) / "test.db")
        init_tables(db_path)

        bm = Bookmark(
            message_id="11",
            channel_id=JARVIS_CHANNEL,
            posted_at="2026-04-16T08:49:26.064-05:00",
            url="https://x.com/foo/status/123",
            domain="x.com",
            source_type="x_post",
            embed_title="Some tweet",
            embed_description="The tweet body lorem ipsum.",
        )

        conn = sqlite3.connect(db_path)
        try:
            insert_bookmark(conn, bm)
            row = conn.execute(
                """
                SELECT message_id, channel_id, posted_at, url, domain,
                       source_type, embed_title, embed_description
                  FROM discord_bookmarks WHERE message_id = ?
                """,
                (bm.message_id,),
            ).fetchone()
        finally:
            conn.close()

        assert row == (
            "11",
            JARVIS_CHANNEL,
            "2026-04-16T08:49:26.064-05:00",
            "https://x.com/foo/status/123",
            "x.com",
            "x_post",
            "Some tweet",
            "The tweet body lorem ipsum.",
        )
