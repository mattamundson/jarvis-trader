"""Tests for the cross-encoder reranker (engine/discord/reranker.py).

The reranker has three tiers (voyage -> local -> off) selected by RERANKER_MODE.
These tests exercise tier selection, the auto fallback chain, score-based
reordering, and graceful degradation — all without downloading the local model
or hitting the Voyage network API (both are mocked).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from discord import reranker

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _candidates() -> list[dict]:
    """Four candidates in deliberately-wrong (vector) order vs. true relevance."""
    return [
        {"rowid": 1, "similarity": 0.91, "content": "off-topic chatter about lunch"},
        {"rowid": 2, "similarity": 0.90, "content": "ES gamma flip and dealer hedging"},
        {"rowid": 3, "similarity": 0.89, "content": "random gif reaction"},
        {"rowid": 4, "similarity": 0.88, "content": "0DTE put wall into the close"},
    ]


@pytest.fixture(autouse=True)
def _reset_local_latch():
    """Reset the local-model module state between tests."""
    reranker._local_model = None
    reranker._local_tokenizer = None
    reranker._local_failed = False
    yield


# ---------------------------------------------------------------------------
# overfetch_k
# ---------------------------------------------------------------------------


def test_overfetch_k_scales_then_caps() -> None:
    with patch.object(reranker, "OVERFETCH_FACTOR", 4), patch.object(reranker, "OVERFETCH_MAX", 40):
        assert reranker.overfetch_k(8) == 32  # 8 * 4
        assert reranker.overfetch_k(20) == 40  # 20 * 4 = 80, capped at 40
        assert reranker.overfetch_k(1) == 4


# ---------------------------------------------------------------------------
# Tier 3 (off) — identity passthrough
# ---------------------------------------------------------------------------


async def test_mode_off_preserves_order_and_truncates() -> None:
    with patch.dict("os.environ", {"RERANKER_MODE": "off"}):
        out, tier = await reranker.rerank("ES gamma", _candidates(), top_n=2)

    assert tier == "off"
    assert [c["rowid"] for c in out] == [1, 2]  # original order, just cut to 2
    assert "rerank_score" not in out[0]  # no reranker ran


async def test_empty_candidates_short_circuits() -> None:
    out, tier = await reranker.rerank("anything", [], top_n=5)
    assert out == []
    assert tier == "off"


# ---------------------------------------------------------------------------
# Tier 1 (voyage)
# ---------------------------------------------------------------------------


async def test_voyage_reorders_by_relevance_score() -> None:
    # Voyage says candidate index 3 (0DTE put wall) is most relevant, then idx 1.
    voyage_payload = {
        "data": [
            {"index": 0, "relevance_score": 0.05},
            {"index": 1, "relevance_score": 0.70},
            {"index": 2, "relevance_score": 0.02},
            {"index": 3, "relevance_score": 0.95},
        ]
    }

    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value=voyage_payload)
    post_ctx = AsyncMock()
    post_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
    post_ctx.__aexit__ = AsyncMock(return_value=None)
    session = AsyncMock()
    session.post = lambda *a, **k: post_ctx
    session_ctx = AsyncMock()
    session_ctx.__aenter__ = AsyncMock(return_value=session)
    session_ctx.__aexit__ = AsyncMock(return_value=None)

    with (
        patch.dict("os.environ", {"RERANKER_MODE": "voyage", "VOYAGE_API_KEY": "vk-test"}),
        patch("discord.reranker.aiohttp.ClientSession", return_value=session_ctx),
    ):
        out, tier = await reranker.rerank("0DTE put wall", _candidates(), top_n=2)

    assert tier == "voyage"
    assert [c["rowid"] for c in out] == [4, 2]  # idx3->rowid4 (0.95), idx1->rowid2 (0.70)
    assert out[0]["rerank_score"] == 0.95


async def test_voyage_missing_key_falls_through_in_auto() -> None:
    """auto mode with no key + no local model -> Tier 3 (off)."""
    with (
        patch.dict("os.environ", {"RERANKER_MODE": "auto"}, clear=False),
        patch.object(reranker, "_load_local", return_value=False),
    ):
        # Ensure no key
        with patch.dict("os.environ", {"VOYAGE_API_KEY": ""}):
            out, tier = await reranker.rerank("ES", _candidates(), top_n=3)

    assert tier == "off"
    assert [c["rowid"] for c in out] == [1, 2, 3]


async def test_voyage_http_error_falls_through_to_local() -> None:
    """auto: Voyage returns 500 -> falls to local, which scores."""
    mock_resp = AsyncMock()
    mock_resp.status = 500
    post_ctx = AsyncMock()
    post_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
    post_ctx.__aexit__ = AsyncMock(return_value=None)
    session = AsyncMock()
    session.post = lambda *a, **k: post_ctx
    session_ctx = AsyncMock()
    session_ctx.__aenter__ = AsyncMock(return_value=session)
    session_ctx.__aexit__ = AsyncMock(return_value=None)

    # Local scorer: rank candidate idx 1 (ES gamma) top.
    async def fake_local(query, docs):
        return [0.1, 0.9, 0.2, 0.3]

    with (
        patch.dict("os.environ", {"RERANKER_MODE": "auto", "VOYAGE_API_KEY": "vk"}),
        patch("discord.reranker.aiohttp.ClientSession", return_value=session_ctx),
        patch("discord.reranker._local_scores", side_effect=fake_local),
    ):
        out, tier = await reranker.rerank("ES gamma", _candidates(), top_n=1)

    assert tier == "local"
    assert out[0]["rowid"] == 2


# ---------------------------------------------------------------------------
# Tier 2 (local) — mocked inference, no model download
# ---------------------------------------------------------------------------


async def test_local_reorders_by_logit() -> None:
    async def fake_local(query, docs):
        # Highest logit on idx 3 (0DTE), then idx 1 (ES gamma).
        return [0.0, 0.8, -0.5, 1.2]

    with (
        patch.dict("os.environ", {"RERANKER_MODE": "local"}),
        patch("discord.reranker._local_scores", side_effect=fake_local),
    ):
        out, tier = await reranker.rerank("0DTE", _candidates(), top_n=2)

    assert tier == "local"
    assert [c["rowid"] for c in out] == [4, 2]
    assert out[0]["rerank_score"] == 1.2


async def test_local_load_failure_falls_to_off() -> None:
    with (
        patch.dict("os.environ", {"RERANKER_MODE": "local"}),
        patch.object(reranker, "_load_local", return_value=False),
    ):
        out, tier = await reranker.rerank("ES", _candidates(), top_n=2)

    assert tier == "off"
    assert [c["rowid"] for c in out] == [1, 2]


async def test_custom_text_key_used_for_scoring() -> None:
    captured = {}

    async def fake_local(query, docs):
        captured["docs"] = list(docs)
        return [0.5, 0.4]

    cands = [
        {"rowid": 1, "_full": "full document one"},
        {"rowid": 2, "_full": "full document two"},
    ]
    with (
        patch.dict("os.environ", {"RERANKER_MODE": "local"}),
        patch("discord.reranker._local_scores", side_effect=fake_local),
    ):
        out, tier = await reranker.rerank("q", cands, top_n=2, text_key="_full")

    assert captured["docs"] == ["full document one", "full document two"]
    assert tier == "local"
