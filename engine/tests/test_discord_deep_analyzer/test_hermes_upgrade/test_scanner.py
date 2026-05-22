"""Unit tests for engine/discord/hermes_upgrade/scanner.py."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from discord.hermes_upgrade.scanner import (
    HERMES_TOPICS,
    TARGET_CHANNEL,
    _parse_structured,
    scan_for_candidates,
    score_candidate,
)

# ---------------------------------------------------------------------------
# score_candidate
# ---------------------------------------------------------------------------


def test_score_empty_inputs_returns_zero():
    assert score_candidate([], "", False, "url") == 0.0


def test_score_trading_only_topics_stays_low():
    # Trading vocabulary (ticker / futures) shares no overlap with HERMES_TOPICS
    score = score_candidate(["ticker", "futures", "macro"], "", False, "url")
    assert score == 0.0


def test_score_hermes_masterclass_input_high():
    # Multiple topic hits + action item + github + keywords in summary
    topics = ["agent", "mcp-server", "claude-code", "skill", "cron"]
    summary = (
        "A new Hermes-compatible MCP server for agent orchestration. "
        "Uses GEPA prompts and a Claude Code skill to manage cron jobs. "
        "Supports browser-use + playwright for autonomous workflows."
    )
    score = score_candidate(topics, summary, True, "github")
    assert score >= 0.7, f"expected >=0.7, got {score}"


def test_score_topic_hit_cap_at_six():
    # 8 topic hits should cap topic contribution at 0.6
    topics = list(HERMES_TOPICS)[:8]
    score = score_candidate(topics, "", False, "url")
    assert score == pytest.approx(0.6, abs=1e-6)


def test_score_keyword_cap_at_thirty():
    # Many keyword hits in summary should cap at 0.30
    summary = "hermes hermes hermes agent agent agent skill skill skill cron cron cron"
    score = score_candidate([], summary, False, "url")
    # 12 hits * 0.05 = 0.60, capped at 0.30
    assert score == pytest.approx(0.30, abs=1e-6)


def test_score_total_caps_at_one():
    topics = list(HERMES_TOPICS)
    summary = " ".join(["hermes", "agent", "skill", "mcp server", "cron"] * 20)
    score = score_candidate(topics, summary, True, "github")
    assert score == 1.0


def test_score_action_item_adds_fifteen():
    base = score_candidate(["agent"], "", False, "url")
    with_action = score_candidate(["agent"], "", True, "url")
    assert with_action - base == pytest.approx(0.15, abs=1e-6)


def test_score_x_post_or_github_adds_ten():
    base = score_candidate(["agent"], "", False, "url")
    xp = score_candidate(["agent"], "", False, "x_post")
    gh = score_candidate(["agent"], "", False, "github")
    assert xp - base == pytest.approx(0.10, abs=1e-6)
    assert gh - base == pytest.approx(0.10, abs=1e-6)


def test_score_non_string_topics_filtered_safely():
    # Defensive: a malformed topics list with non-strings shouldn't blow up
    score = score_candidate(["agent", 42, None, "skill"], "", False, "url")
    # Only "agent" + "skill" should count -> 2 * 0.15 = 0.30
    assert score == pytest.approx(0.30, abs=1e-6)


# ---------------------------------------------------------------------------
# _parse_structured
# ---------------------------------------------------------------------------


def test_parse_structured_none_returns_defaults():
    assert _parse_structured(None) == ([], False, "url")


def test_parse_structured_empty_string_returns_defaults():
    assert _parse_structured("") == ([], False, "url")


def test_parse_structured_invalid_json_returns_defaults():
    assert _parse_structured("not json {[") == ([], False, "url")


def test_parse_structured_full_payload():
    raw = json.dumps(
        {
            "topics": ["agent", "skill"],
            "has_action_item": True,
            "source_kind": "x_post",
        }
    )
    topics, has_ai, sk = _parse_structured(raw)
    assert topics == ["agent", "skill"]
    assert has_ai is True
    assert sk == "x_post"


def test_parse_structured_missing_keys_defaults():
    raw = json.dumps({"unrelated": "field"})
    topics, has_ai, sk = _parse_structured(raw)
    assert topics == []
    assert has_ai is False
    assert sk == "url"


def test_parse_structured_non_dict_root():
    raw = json.dumps(["just", "a", "list"])
    assert _parse_structured(raw) == ([], False, "url")


def test_parse_structured_non_string_source_kind():
    raw = json.dumps({"source_kind": 123})
    _, _, sk = _parse_structured(raw)
    assert sk == "url"


# ---------------------------------------------------------------------------
# scan_for_candidates — in-memory SQLite
# ---------------------------------------------------------------------------


@pytest.fixture
def scanner_db(tmp_path: Path) -> Path:
    """A tmp db with the production bookmark + analysis shape, seeded with rows."""
    db = tmp_path / "scanner.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE discord_bookmarks (
            message_id        TEXT PRIMARY KEY NOT NULL,
            channel_id        TEXT,
            posted_at         TEXT NOT NULL,
            url               TEXT,
            analyzed_at       TIMESTAMP,
            analysis_id       INTEGER
        );
        CREATE TABLE discord_analyses (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            bookmark_id     TEXT NOT NULL,
            artifact_type   TEXT NOT NULL,
            summary         TEXT NOT NULL,
            structured_json TEXT NOT NULL
        );
        """
    )
    rows = [
        # m1: high-leverage, applicable
        (
            "m1",
            TARGET_CHANNEL,
            "2026-05-20T10:00:00Z",
            "https://github.com/x/hermes-skill",
            "url",
            "A Hermes MCP server skill for Claude Code agents",
            {
                "topics": ["agent", "mcp-server", "skill", "claude-code"],
                "has_action_item": True,
                "source_kind": "github",
            },
        ),
        # m2: medium — barely passes
        (
            "m2",
            TARGET_CHANNEL,
            "2026-05-20T10:01:00Z",
            "https://x.com/a/status/2",
            "url",
            "Notes on prompt design",
            {
                "topics": ["prompts"],
                "has_action_item": False,
                "source_kind": "x_post",
            },
        ),
        # m3: low — should be filtered at min_score=0.25
        (
            "m3",
            TARGET_CHANNEL,
            "2026-05-20T10:02:00Z",
            "https://example.com/article",
            "url",
            "Some trading commentary",
            {
                "topics": ["futures", "macro"],
                "has_action_item": False,
                "source_kind": "url",
            },
        ),
        # m4: wrong channel — must be excluded regardless of score
        (
            "m4",
            "other-channel-id",
            "2026-05-20T10:03:00Z",
            "https://github.com/y/other",
            "url",
            "Another hermes mcp skill",
            {
                "topics": ["hermes", "mcp", "skill", "agent"],
                "has_action_item": True,
                "source_kind": "github",
            },
        ),
        # m5: empty summary — filtered by the SQL WHERE clause
        (
            "m5",
            TARGET_CHANNEL,
            "2026-05-20T10:04:00Z",
            "https://example.com/empty",
            "url",
            "",
            {
                "topics": ["hermes", "skill"],
                "has_action_item": True,
                "source_kind": "url",
            },
        ),
    ]
    cur = conn.cursor()
    for mid, chan, posted, url, atype, summary, struct in rows:
        cur.execute(
            "INSERT INTO discord_analyses(bookmark_id, artifact_type, summary, structured_json) "
            "VALUES (?, ?, ?, ?)",
            (mid, atype, summary, json.dumps(struct)),
        )
        analysis_id = cur.lastrowid
        cur.execute(
            "INSERT INTO discord_bookmarks(message_id, channel_id, posted_at, url, "
            "analyzed_at, analysis_id) VALUES (?, ?, ?, ?, datetime('now'), ?)",
            (mid, chan, posted, url, analysis_id),
        )
    conn.commit()
    conn.close()
    return db


def test_scan_picks_high_score_drops_low(scanner_db: Path):
    cands = scan_for_candidates(scanner_db, min_score=0.25)
    ids = [c.bookmark_id for c in cands]
    assert "m1" in ids
    # m3 = trading-only, score 0.0; m5 = empty summary; both must be excluded
    assert "m3" not in ids
    assert "m5" not in ids


def test_scan_excludes_other_channels(scanner_db: Path):
    cands = scan_for_candidates(scanner_db, min_score=0.25)
    ids = [c.bookmark_id for c in cands]
    assert "m4" not in ids


def test_scan_sorted_by_score_desc(scanner_db: Path):
    cands = scan_for_candidates(scanner_db, min_score=0.0)
    scores = [c.score for c in cands]
    assert scores == sorted(scores, reverse=True)


def test_scan_respects_limit(scanner_db: Path):
    cands = scan_for_candidates(scanner_db, min_score=0.0, limit=1)
    assert len(cands) == 1


def test_scan_candidate_shape(scanner_db: Path):
    cands = scan_for_candidates(scanner_db, min_score=0.25)
    m1 = next(c for c in cands if c.bookmark_id == "m1")
    assert m1.analysis_id > 0
    assert m1.url == "https://github.com/x/hermes-skill"
    assert m1.summary.startswith("A Hermes MCP server skill")
    assert m1.topics == ["agent", "mcp-server", "skill", "claude-code"]
    assert m1.has_action_item is True
    assert m1.source_kind == "github"
    assert m1.artifact_type == "url"
    assert m1.posted_at == "2026-05-20T10:00:00Z"
    assert m1.score > 0.5


def test_scan_alternate_channel_id_param(scanner_db: Path):
    cands = scan_for_candidates(scanner_db, channel_id="other-channel-id", min_score=0.25)
    ids = [c.bookmark_id for c in cands]
    assert ids == ["m4"]
