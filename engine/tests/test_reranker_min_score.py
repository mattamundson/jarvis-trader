"""Tests for the rerank() relevance floor (min_score).

min_score drops candidates whose cross-encoder score is below the floor BEFORE
the top_n truncation, so low-relevance noise (archive pages matching vocabulary
but not intent) can't pad results. These tests patch the Voyage scorer with a
controlled score vector (no key, no network, no model) and force the tier via
RERANKER_MODE so the filter logic is exercised in isolation.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

# rerank lives in discord.reranker; conftest adds engine/, but importing
# via the top-level namespace keeps patch targets unambiguous (mirrors the
# search_knowledge test).
_ROOT = Path(__file__).resolve().parents[2]  # .../jarvis-trader
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from discord import reranker  # noqa: E402


def _cands() -> list[dict]:
    # Document text drives nothing here (scorer is mocked) but rerank reads text_key.
    return [
        {"slug": "a", "content": "alpha"},
        {"slug": "b", "content": "bravo"},
        {"slug": "c", "content": "charlie"},
        {"slug": "d", "content": "delta"},
    ]


async def test_min_score_drops_below_floor() -> None:
    """Candidates scoring below min_score are dropped; survivors keep order."""
    # Scores align to candidate index: a=0.9, b=0.5, c=0.15, d=0.05
    scores = [0.9, 0.5, 0.15, 0.05]
    with (
        patch.dict("os.environ", {"RERANKER_MODE": "voyage"}),
        patch.object(reranker, "_voyage_scores", AsyncMock(return_value=scores)),
    ):
        out, tier = await reranker.rerank("q", _cands(), top_n=10, min_score=0.2)

    assert tier == "voyage"
    # Only a (0.9) and b (0.5) clear the 0.2 floor; c/d dropped.
    assert [c["slug"] for c in out] == ["a", "b"]
    assert out[0]["rerank_score"] == 0.9
    assert out[1]["rerank_score"] == 0.5


async def test_min_score_zero_keeps_all() -> None:
    """min_score=0.0 preserves pre-threshold behavior (all, sorted, truncated)."""
    scores = [0.9, 0.5, 0.15, 0.05]
    with (
        patch.dict("os.environ", {"RERANKER_MODE": "voyage"}),
        patch.object(reranker, "_voyage_scores", AsyncMock(return_value=scores)),
    ):
        out, tier = await reranker.rerank("q", _cands(), top_n=10, min_score=0.0)

    assert tier == "voyage"
    assert [c["slug"] for c in out] == ["a", "b", "c", "d"]


async def test_min_score_respects_top_n_after_filter() -> None:
    """Floor filters first, then top_n truncates the survivors."""
    scores = [0.9, 0.8, 0.7, 0.05]
    with (
        patch.dict("os.environ", {"RERANKER_MODE": "voyage"}),
        patch.object(reranker, "_voyage_scores", AsyncMock(return_value=scores)),
    ):
        out, tier = await reranker.rerank("q", _cands(), top_n=2, min_score=0.2)

    # a,b,c clear the floor but top_n=2 caps to the two best.
    assert [c["slug"] for c in out] == ["a", "b"]


async def test_all_below_floor_returns_reranked_unfiltered() -> None:
    """Never-empty guard: if the floor drops every candidate, return reranked top_n."""
    # Every score is below the 0.2 floor (simulates a Voyage->local fallback whose
    # sigmoid probabilities all sit low) — must NOT return an empty list.
    scores = [0.15, 0.10, 0.05, 0.02]
    with (
        patch.dict("os.environ", {"RERANKER_MODE": "voyage"}),
        patch.object(reranker, "_voyage_scores", AsyncMock(return_value=scores)),
    ):
        out, tier = await reranker.rerank("q", _cands(), top_n=3, min_score=0.2)

    assert tier == "voyage"
    # Reranked (sorted desc), truncated to top_n=3, NOT emptied by the floor.
    assert [c["slug"] for c in out] == ["a", "b", "c"]
    assert out[0]["rerank_score"] == 0.15  # still annotated despite being sub-floor
    assert len(out) == 3


async def test_off_tier_ignores_min_score() -> None:
    """The identity ('off') tier has no scores -> min_score is a no-op."""
    with patch.dict("os.environ", {"RERANKER_MODE": "off"}):
        out, tier = await reranker.rerank("q", _cands(), top_n=3, min_score=0.9)

    assert tier == "off"
    # No scoring happened; vector order preserved, just truncated to top_n.
    assert [c["slug"] for c in out] == ["a", "b", "c"]
    assert all("rerank_score" not in c for c in out)
