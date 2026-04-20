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


def _msg(id_: str, content: str, timestamp: str = "2026-04-16T08:49:26.064-05:00", embeds=None) -> dict:
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
    parsed = bookmark_parser.parse_channel(
        [_msg("3", "see (https://github.com/foo/bar),")]
    )
    assert parsed[0]["url"] == "https://github.com/foo/bar"


def test_www_prefix_dropped_from_domain():
    parsed = bookmark_parser.parse_channel(
        [_msg("4", "https://www.example.com/article")]
    )
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

        parsed = bookmark_parser.parse_channel(
            [_msg("10", "https://github.com/foo/bar")]
        )
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
