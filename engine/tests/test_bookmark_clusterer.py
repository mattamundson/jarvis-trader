"""Regression tests for `agents.bookmark_clusterer`.

Covered:
  - `parse_cluster_response` strict JSON extraction (clean output)
  - Prose-around-JSON tolerance (model sometimes adds preamble)
  - Malformed JSON → empty list, no raise
  - Themes with <2 urls are dropped (enforcement of "≥2 supporting bookmarks")
  - Confidence clamping to [0.0, 1.0]
  - `fetch_recent_bookmarks` honors window + limit (SQL shape)
  - Cache hit returns cached=True without re-calling the LLM
  - Graceful degradation: no-LLM returns ClusterResult with error, not raise
  - Insufficient bookmarks (<4) short-circuits before LLM call
  - `ClusterResult.actionable` True iff any theme conf >= 0.5
  - `to_dict` includes all expected keys for downstream serialization
"""

from __future__ import annotations

import asyncio
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from agents.bookmark_clusterer import (
    BookmarkClusterer,
    ClusterResult,
    Theme,
    fetch_recent_bookmarks,
    parse_cluster_response,
)
from discord.models import Bookmark
from discord.storage import init_tables, insert_bookmark

# ──────────────────────────────────────────────────────────────────────────────
# parse_cluster_response
# ──────────────────────────────────────────────────────────────────────────────


def test_parse_clean_json_extracts_themes():
    content = """{
      "themes": [
        {"name": "AI agents", "description": "Agent frameworks",
         "urls": ["https://x.com/a", "https://x.com/b"], "confidence": 0.8}
      ]
    }"""
    themes = parse_cluster_response(content)
    assert len(themes) == 1
    assert themes[0].name == "AI agents"
    assert themes[0].count == 2
    assert themes[0].confidence == 0.8


def test_parse_tolerates_preamble():
    content = """Sure, here are the clusters:

    {"themes":[{"name":"T1","description":"d","urls":["u1","u2"],"confidence":0.6}]}

    Hope this helps!"""
    themes = parse_cluster_response(content)
    assert len(themes) == 1
    assert themes[0].name == "T1"


def test_parse_empty_or_malformed_returns_empty():
    assert parse_cluster_response("") == []
    assert parse_cluster_response("no json here") == []
    assert parse_cluster_response("{not valid json") == []
    assert parse_cluster_response('{"themes": "not a list"}') == []


def test_parse_drops_single_url_themes():
    content = """{"themes": [
      {"name": "valid", "description": "d", "urls": ["u1", "u2"], "confidence": 0.7},
      {"name": "too_few", "description": "d", "urls": ["u1"], "confidence": 0.9}
    ]}"""
    themes = parse_cluster_response(content)
    assert len(themes) == 1
    assert themes[0].name == "valid"


def test_parse_clamps_confidence_out_of_range():
    content = """{"themes": [
      {"name": "hi", "description": "d", "urls": ["u1","u2"], "confidence": 1.5},
      {"name": "lo", "description": "d", "urls": ["u1","u2"], "confidence": -0.3}
    ]}"""
    themes = parse_cluster_response(content)
    confs = sorted(t.confidence for t in themes)
    assert confs == [0.0, 1.0]


def test_parse_resolves_indices_against_bookmark_list():
    """New primary code path — Claude emits indices instead of full URLs."""
    bookmarks = [
        {"url": "https://x.com/a"},
        {"url": "https://x.com/b"},
        {"url": "https://x.com/c"},
        {"url": "https://x.com/d"},
    ]
    content = """{"themes": [
      {"name": "T1", "description": "d", "indices": [1, 3], "confidence": 0.8},
      {"name": "T2", "description": "d", "indices": [2, 4, 99], "confidence": 0.6}
    ]}"""
    themes = parse_cluster_response(content, bookmarks=bookmarks)
    assert len(themes) == 2
    assert themes[0].urls == ["https://x.com/a", "https://x.com/c"]
    # out-of-range index 99 is silently dropped, not raised
    assert themes[1].urls == ["https://x.com/b", "https://x.com/d"]


def test_parse_drops_unnamed_themes():
    content = """{"themes": [
      {"name": "", "description": "d", "urls": ["u1","u2"], "confidence": 0.7},
      {"name": "named", "description": "d", "urls": ["u1","u2"], "confidence": 0.7}
    ]}"""
    themes = parse_cluster_response(content)
    assert len(themes) == 1
    assert themes[0].name == "named"


# ──────────────────────────────────────────────────────────────────────────────
# fetch_recent_bookmarks
# ──────────────────────────────────────────────────────────────────────────────


def _seed_bookmarks(db_path: str, rows: list[dict]) -> None:
    init_tables(db_path)
    conn = sqlite3.connect(db_path)
    try:
        for r in rows:
            insert_bookmark(conn, Bookmark(**r))
        conn.commit()
    finally:
        conn.close()


def test_fetch_respects_lookback_window_and_limit():
    from datetime import datetime, timedelta, timezone

    now = datetime.now(tz=timezone.utc)
    with tempfile.TemporaryDirectory() as td:
        db = str(Path(td) / "t.db")
        rows = [
            # 3 days old — in 7d window
            {
                "message_id": "1",
                "channel_id": "C",
                "posted_at": (now - timedelta(days=3)).isoformat(),
                "url": "https://x.com/recent1",
                "domain": "x.com",
                "source_type": "x_post",
            },
            {
                "message_id": "2",
                "channel_id": "C",
                "posted_at": (now - timedelta(days=5)).isoformat(),
                "url": "https://x.com/recent2",
                "domain": "x.com",
                "source_type": "x_post",
            },
            # 30 days old — outside 7d window
            {
                "message_id": "3",
                "channel_id": "C",
                "posted_at": (now - timedelta(days=30)).isoformat(),
                "url": "https://x.com/old",
                "domain": "x.com",
                "source_type": "x_post",
            },
        ]
        _seed_bookmarks(db, rows)
        got = fetch_recent_bookmarks(lookback_days=7, db_path=db)
        urls = {r["url"] for r in got}
        assert urls == {"https://x.com/recent1", "https://x.com/recent2"}

        # limit enforcement
        got_lim = fetch_recent_bookmarks(lookback_days=7, db_path=db, max_rows=1)
        assert len(got_lim) == 1


# ──────────────────────────────────────────────────────────────────────────────
# BookmarkClusterer — async, mocked LLM
# ──────────────────────────────────────────────────────────────────────────────


def _make_llm_result(content: str, success: bool = True, model: str = "haiku", cost: float = 0.001, latency: int = 120):
    m = MagicMock()
    m.success = success
    m.content = content
    m.model = model
    m.cost_usd = cost
    m.latency_ms = latency
    m.error = None if success else "mocked error"
    return m


@pytest.mark.asyncio
async def test_cluster_recent_happy_path_parses_themes():
    fake_llm = MagicMock()
    fake_llm.call = AsyncMock(
        return_value=_make_llm_result(
            '{"themes":[{"name":"AI","description":"d","urls":["u1","u2"],"confidence":0.8}]}'
        )
    )
    clusterer = BookmarkClusterer(llm_client=fake_llm)

    from datetime import datetime, timedelta, timezone

    now = datetime.now(tz=timezone.utc)
    with tempfile.TemporaryDirectory() as td:
        db = str(Path(td) / "t.db")
        _seed_bookmarks(
            db,
            [
                {
                    "message_id": str(i),
                    "channel_id": "C",
                    "posted_at": (now - timedelta(days=1)).isoformat(),
                    "url": f"https://x.com/{i}",
                    "domain": "x.com",
                    "source_type": "x_post",
                }
                for i in range(5)
            ],
        )
        result = await clusterer.cluster_recent(db_path=db)

    assert result.error is None
    assert len(result.themes) == 1
    assert result.themes[0].name == "AI"
    assert result.bookmark_count == 5
    assert result.cost_usd == 0.001
    assert result.cached is False


@pytest.mark.asyncio
async def test_cluster_recent_caches_result():
    fake_llm = MagicMock()
    fake_llm.call = AsyncMock(
        return_value=_make_llm_result(
            '{"themes":[{"name":"AI","description":"d","urls":["u1","u2"],"confidence":0.8}]}'
        )
    )
    clusterer = BookmarkClusterer(llm_client=fake_llm)

    from datetime import datetime, timedelta, timezone

    now = datetime.now(tz=timezone.utc)
    with tempfile.TemporaryDirectory() as td:
        db = str(Path(td) / "t.db")
        _seed_bookmarks(
            db,
            [
                {
                    "message_id": str(i),
                    "channel_id": "C",
                    "posted_at": (now - timedelta(hours=1)).isoformat(),
                    "url": f"https://x.com/{i}",
                    "domain": "x.com",
                    "source_type": "x_post",
                }
                for i in range(5)
            ],
        )
        r1 = await clusterer.cluster_recent(db_path=db)
        r2 = await clusterer.cluster_recent(db_path=db)
        count_after_cache_hit = fake_llm.call.call_count
        # force_refresh bypasses cache — keep INSIDE the `with` block so the
        # tempdir (and the sqlite file inside it) still exists.
        r3 = await clusterer.cluster_recent(db_path=db, force_refresh=True)
        count_after_force_refresh = fake_llm.call.call_count

    assert r1.cached is False
    assert r2.cached is True
    assert count_after_cache_hit == 1  # second call served from cache
    assert r3.cached is False
    assert count_after_force_refresh == 2


@pytest.mark.asyncio
async def test_cluster_recent_no_llm_returns_error_not_raise():
    clusterer = BookmarkClusterer(llm_client=None)
    result = await clusterer.cluster_recent()
    assert result.error == "llm client unavailable"
    assert result.themes == []


@pytest.mark.asyncio
async def test_cluster_recent_too_few_bookmarks_short_circuits():
    fake_llm = MagicMock()
    fake_llm.call = AsyncMock()  # should not be called
    clusterer = BookmarkClusterer(llm_client=fake_llm)

    from datetime import datetime, timezone

    with tempfile.TemporaryDirectory() as td:
        db = str(Path(td) / "t.db")
        _seed_bookmarks(
            db,
            [
                {
                    "message_id": "1",
                    "channel_id": "C",
                    "posted_at": datetime.now(tz=timezone.utc).isoformat(),
                    "url": "https://x.com/only",
                    "domain": "x.com",
                    "source_type": "x_post",
                }
            ],
        )
        result = await clusterer.cluster_recent(db_path=db)

    assert "insufficient bookmarks" in (result.error or "")
    assert fake_llm.call.call_count == 0


@pytest.mark.asyncio
async def test_cluster_recent_llm_failure_returns_error_not_raise():
    fake_llm = MagicMock()
    fake_llm.call = AsyncMock(return_value=_make_llm_result("", success=False))
    clusterer = BookmarkClusterer(llm_client=fake_llm)

    from datetime import datetime, timedelta, timezone

    now = datetime.now(tz=timezone.utc)
    with tempfile.TemporaryDirectory() as td:
        db = str(Path(td) / "t.db")
        _seed_bookmarks(
            db,
            [
                {
                    "message_id": str(i),
                    "channel_id": "C",
                    "posted_at": (now - timedelta(hours=1)).isoformat(),
                    "url": f"https://x.com/{i}",
                    "domain": "x.com",
                    "source_type": "x_post",
                }
                for i in range(5)
            ],
        )
        result = await clusterer.cluster_recent(db_path=db)

    assert "llm call failed" in (result.error or "")


# ──────────────────────────────────────────────────────────────────────────────
# ClusterResult conveniences
# ──────────────────────────────────────────────────────────────────────────────


def test_actionable_flag_requires_confident_theme():
    low = ClusterResult(themes=[Theme(name="x", description="d", count=2, urls=["u1", "u2"], confidence=0.3)])
    high = ClusterResult(themes=[Theme(name="x", description="d", count=2, urls=["u1", "u2"], confidence=0.8)])
    empty = ClusterResult(themes=[])
    assert low.actionable is False
    assert high.actionable is True
    assert empty.actionable is False


def test_to_dict_round_trip_shape():
    r = ClusterResult(
        themes=[Theme(name="AI", description="d", count=2, urls=["u1", "u2"], confidence=0.8)],
        bookmark_count=10,
        lookback_days=7,
        model="haiku",
        latency_ms=120,
        cost_usd=0.0012345,
    )
    d = r.to_dict()
    assert set(d.keys()) == {
        "themes",
        "bookmark_count",
        "lookback_days",
        "model",
        "latency_ms",
        "cost_usd",
        "cached",
        "actionable",
        "error",
    }
    assert d["cost_usd"] == 0.0012  # rounded to 4 decimals
    assert d["actionable"] is True
    assert d["themes"][0]["urls"] == ["u1", "u2"]
