"""Tests for the search_knowledge MCP tool (curated gbrain knowledge brain).

search_knowledge proxies the single-writer gbrain daemon's POST /search (server-side
Voyage embed + hybrid retrieval), then reorders with the same cross-encoder rerank as
semantic_search. These tests mock aiohttp.ClientSession and inject a fake reranker into
sys.modules, so neither the brain daemon, a Voyage key, nor the (heavy) cross-encoder
model is needed.

The tool does `from engine.discord.reranker import overfetch_k, rerank` at call time, so
we import the tool via the same `engine.` namespace and patch in that namespace — the
function then resolves the exact module objects we control.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# search_knowledge imports `engine.discord.reranker`, which needs the repo root on
# sys.path so `engine` resolves as a (namespace) package. conftest only adds engine/.
_ROOT = Path(__file__).resolve().parents[2]  # .../jarvis-trader
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_post_session(status: int, json_payload: object) -> MagicMock:
    """Mock aiohttp.ClientSession whose post() returns status + json (async ctx mgrs)."""
    mock_resp = AsyncMock()
    mock_resp.status = status
    mock_resp.json = AsyncMock(return_value=json_payload)

    mock_post_ctx = AsyncMock()
    mock_post_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_post_ctx.__aexit__ = AsyncMock(return_value=None)

    mock_session = AsyncMock()
    mock_session.post = MagicMock(return_value=mock_post_ctx)

    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

    return mock_session_ctx


def _fake_reranker(rerank_impl):
    """A patch.dict context installing a fake engine.discord.reranker in sys.modules.

    Avoids importing the real reranker (and its cross-encoder model) during the unit
    test. overfetch_k records the limit it was asked for so the clamp can be asserted.
    """
    calls = {"overfetch_limit": None}

    def _overfetch_k(limit: int) -> int:
        calls["overfetch_limit"] = limit
        return limit * 3

    fake = types.ModuleType("engine.discord.reranker")
    fake.overfetch_k = _overfetch_k
    fake.rerank = rerank_impl
    return patch.dict(sys.modules, {"engine.discord.reranker": fake}), calls


_HITS = {
    "query": "how do we size risk on a breakout",
    "count": 2,
    "results": [
        {
            "slug": "wiki/trading/risk-sizing",
            "score": 0.8123,
            "type": "concept",
            "title": "Risk Sizing",
            "chunk_text": "A" * 500,  # > 400 to exercise truncation
        },
        {
            "slug": "clippings/playbook",
            "score": 0.6011,
            "title": "Playbook",
            "content": "On breakouts, risk a fixed fraction.",
        },
    ],
}


def _import_tool():
    from engine.discord.mcp_server import search_knowledge

    return search_knowledge


# ---------------------------------------------------------------------------
# search_knowledge
# ---------------------------------------------------------------------------


async def test_search_knowledge_ok() -> None:
    """Happy path: daemon returns hits, reranker reorders, content is truncated."""
    search_knowledge = _import_tool()

    async def _rerank(query, candidates, top_n=8, text_key="_full_content", min_score=0.0):
        # echo candidates (already mapped) back, truncated to top_n, report tier
        return candidates[:top_n], "voyage"

    fake_ctx, _ = _fake_reranker(_rerank)
    with (
        fake_ctx,
        patch(
            "engine.discord.knowledge.aiohttp.ClientSession",
            return_value=_mock_post_session(200, _HITS),
        ),
    ):
        result = await search_knowledge("how do we size risk on a breakout", limit=5)

    assert result["query"] == "how do we size risk on a breakout"
    assert result["rerank"] == "voyage"
    assert "voyage" in result["source"]
    assert "error" not in result
    assert len(result["results"]) == 2
    first = result["results"][0]
    assert first["slug"] == "wiki/trading/risk-sizing"
    assert first["type"] == "concept"
    assert first["similarity"] == 0.8123
    # _full_content is internal and must be stripped; content capped at 400 chars
    assert "_full_content" not in first
    assert first["content"] == "A" * 400
    # second hit had no `type` -> defaults to "" ; content from `content` key
    assert result["results"][1]["type"] == ""
    assert result["results"][1]["content"] == "On breakouts, risk a fixed fraction."


async def test_search_knowledge_empty_hits() -> None:
    """Daemon reachable but returns no hits -> rerank 'off', no error, empty results."""
    search_knowledge = _import_tool()

    async def _rerank(*a, **k):  # should never be called
        raise AssertionError("rerank must not run when there are no hits")

    fake_ctx, _ = _fake_reranker(_rerank)
    with (
        fake_ctx,
        patch(
            "engine.discord.knowledge.aiohttp.ClientSession",
            return_value=_mock_post_session(200, {"results": []}),
        ),
    ):
        result = await search_knowledge("anything", limit=5)

    assert result["results"] == []
    assert result["rerank"] == "off"
    assert "error" not in result


async def test_search_knowledge_http_error() -> None:
    """Non-200 from the daemon -> error key, empty results, no exception."""
    search_knowledge = _import_tool()

    async def _rerank(*a, **k):
        raise AssertionError("rerank must not run on HTTP error")

    fake_ctx, _ = _fake_reranker(_rerank)
    with (
        fake_ctx,
        patch(
            "engine.discord.knowledge.aiohttp.ClientSession",
            return_value=_mock_post_session(503, {}),
        ),
    ):
        result = await search_knowledge("q", limit=5)

    assert result["results"] == []
    assert "error" in result
    assert "503" in result["error"]


async def test_search_knowledge_unreachable() -> None:
    """Connection failure -> graceful error dict (the daemon may be down)."""
    search_knowledge = _import_tool()

    async def _rerank(*a, **k):
        raise AssertionError("rerank must not run when daemon is unreachable")

    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__ = AsyncMock(side_effect=Exception("Connection refused"))
    mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

    fake_ctx, _ = _fake_reranker(_rerank)
    with (
        fake_ctx,
        patch("engine.discord.knowledge.aiohttp.ClientSession", return_value=mock_session_ctx),
    ):
        result = await search_knowledge("q", limit=5)

    assert result["results"] == []
    assert "error" in result
    assert "unreachable" in result["error"]


async def test_search_knowledge_limit_clamped_and_overfetched() -> None:
    """limit is clamped to [1,20] and the daemon is asked for an over-fetched pool."""
    search_knowledge = _import_tool()

    seen = {"top_n": None}

    async def _rerank(query, candidates, top_n=8, text_key="_full_content", min_score=0.0):
        seen["top_n"] = top_n
        return candidates[:top_n], "voyage"

    fake_ctx, calls = _fake_reranker(_rerank)
    with (
        fake_ctx,
        patch(
            "engine.discord.knowledge.aiohttp.ClientSession",
            return_value=_mock_post_session(200, _HITS),
        ),
    ):
        result = await search_knowledge("q", limit=999)

    # clamped to 20, reranker asked to return 20, daemon over-fetched (20*3 via fake)
    assert seen["top_n"] == 20
    assert calls["overfetch_limit"] == 20
    assert result["rerank"] == "voyage"
