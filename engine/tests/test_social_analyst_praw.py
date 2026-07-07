"""
PRAW (raw Reddit) integration tests for SocialAnalystAgent.

Covers only the _fetch_reddit_praw() code path added in the 2026-04-10 gap
closure session. Does NOT test the full analyze() flow (which would require
mocking the LLM client and 5 other upstream sources).

Key invariants verified:
  1. Missing REDDIT_CLIENT_ID / SECRET → silently returns None (no crash)
  2. PRAW unavailable (ImportError) → silently returns None
  3. Successful praw.Reddit mock → returns structured dict with top_posts
  4. PRAW exception (network/auth) → silently returns None
  5. Symbol mention counting works across multiple subreddits
"""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from agents.social_analyst import SocialAnalystAgent


@pytest.fixture()
def llm_stub() -> SimpleNamespace:
    """Minimal LLM client stub — we never invoke it in these tests."""
    return SimpleNamespace(api_key="test-key")


@pytest.fixture()
def agent_no_creds(llm_stub, monkeypatch) -> SocialAnalystAgent:
    """Agent with zero Reddit credentials set."""
    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)
    return SocialAnalystAgent(llm_client=llm_stub)


@pytest.fixture()
def agent_with_creds(llm_stub, monkeypatch) -> SocialAnalystAgent:
    """Agent with fake Reddit credentials configured."""
    monkeypatch.setenv("REDDIT_CLIENT_ID", "fake_id")
    monkeypatch.setenv("REDDIT_CLIENT_SECRET", "fake_secret")
    monkeypatch.setenv("REDDIT_USER_AGENT", "jarvis-trader-test/1.0")
    return SocialAnalystAgent(llm_client=llm_stub)


@pytest.mark.asyncio
async def test_praw_skipped_without_credentials(agent_no_creds) -> None:
    """No REDDIT_CLIENT_ID configured → PRAW fetch returns None without attempting import."""
    result = await agent_no_creds._fetch_reddit_praw("MCL", ["energy", "oilandgas"])
    assert result is None


@pytest.mark.asyncio
async def test_praw_skipped_when_praw_not_installed(
    agent_with_creds, monkeypatch
) -> None:
    """If praw import fails, fetch returns None — never raises."""
    # Force ImportError by making 'praw' unimportable
    monkeypatch.setitem(sys.modules, "praw", None)
    result = await agent_with_creds._fetch_reddit_praw("MCL", ["energy"])
    assert result is None


@pytest.mark.asyncio
async def test_praw_successful_fetch_returns_structured_dict(
    agent_with_creds, monkeypatch
) -> None:
    """Happy path for an EQUITY ticker (SPY). PRAW is futures-gated by policy,
    so the behavioral surface is tested only on equities."""
    mock_post_1 = MagicMock(
        title="SPY breakout setup",
        selftext="Looking at the 5800 level",
        score=150,
        num_comments=42,
    )
    mock_post_2 = MagicMock(
        title="Equity sector rotation",
        selftext="Thinking about SPY exposure",
        score=80,
        num_comments=15,
    )
    mock_post_3 = MagicMock(
        title="Random unrelated post",
        selftext="Nothing about the index",
        score=200,
        num_comments=100,
    )

    mock_subreddit = MagicMock()
    mock_subreddit.hot = MagicMock(return_value=iter([mock_post_1, mock_post_2, mock_post_3]))

    mock_reddit = MagicMock()
    mock_reddit.subreddit = MagicMock(return_value=mock_subreddit)

    mock_praw_module = MagicMock()
    mock_praw_module.Reddit = MagicMock(return_value=mock_reddit)

    monkeypatch.setitem(sys.modules, "praw", mock_praw_module)

    result = await agent_with_creds._fetch_reddit_praw("SPY", ["investing"])

    assert result is not None
    assert result["subreddits_queried"] == ["investing"]
    assert result["posts_scanned"] == 3
    # SPY appears in title of post 1 and selftext of post 2 — 2 mentions
    assert result["symbol_mentions"] == 2
    top = result["top_posts"]
    assert len(top) == 3
    assert top[0]["score"] == 200
    assert top[1]["score"] == 150
    assert top[2]["score"] == 80
    assert all("subreddit" in p and p["subreddit"] == "investing" for p in top)


@pytest.mark.asyncio
async def test_praw_exception_returns_none(agent_with_creds, monkeypatch) -> None:
    """If praw.Reddit() itself raises (bad credentials, network error), return None.
    Uses equity symbol because futures symbols are policy-gated above this path."""
    mock_praw_module = MagicMock()
    mock_praw_module.Reddit = MagicMock(
        side_effect=Exception("invalid_grant: auth failed")
    )
    monkeypatch.setitem(sys.modules, "praw", mock_praw_module)

    result = await agent_with_creds._fetch_reddit_praw("SPY", ["investing"])
    assert result is None


@pytest.mark.asyncio
async def test_praw_per_subreddit_failure_is_isolated(
    agent_with_creds, monkeypatch
) -> None:
    """If one subreddit errors out, the other subreddits still get scanned.
    Uses equity symbol (SPY) because futures are policy-gated above this path."""
    mock_post_good = MagicMock(
        title="Good post about SPY",
        selftext="",
        score=50,
        num_comments=5,
    )

    def _subreddit_factory(name):
        sub = MagicMock()
        if name == "broken_sub":
            sub.hot = MagicMock(side_effect=RuntimeError("subreddit banned"))
        else:
            sub.hot = MagicMock(return_value=iter([mock_post_good]))
        return sub

    mock_reddit = MagicMock()
    mock_reddit.subreddit = MagicMock(side_effect=_subreddit_factory)

    mock_praw_module = MagicMock()
    mock_praw_module.Reddit = MagicMock(return_value=mock_reddit)
    monkeypatch.setitem(sys.modules, "praw", mock_praw_module)

    result = await agent_with_creds._fetch_reddit_praw(
        "SPY", ["broken_sub", "working_sub"]
    )

    # Should succeed for the working subreddit even though broken_sub errored
    assert result is not None
    assert result["posts_scanned"] == 1
    assert result["symbol_mentions"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("symbol", ["MES", "MNQ", "MCL", "MGC"])
async def test_praw_futures_policy_gate_never_queries_reddit(
    llm_stub, monkeypatch, symbol
) -> None:
    """Policy enforcement (2026-04-19 owner directive): futures sentiment comes
    from Corey Discord #market-updates only. PRAW must never be called for a
    futures ticker, even when credentials are present and PRAW is installed."""
    monkeypatch.setenv("REDDIT_CLIENT_ID", "fake-id")
    monkeypatch.setenv("REDDIT_CLIENT_SECRET", "fake-secret")
    agent = SocialAnalystAgent(llm_client=llm_stub)

    # Any attempt to import or construct praw would be caught here — if the
    # gate fails, this test surfaces it deterministically.
    fake_praw = MagicMock()
    fake_praw.Reddit = MagicMock(side_effect=AssertionError(
        "PRAW must never be constructed for futures tickers"
    ))
    monkeypatch.setitem(sys.modules, "praw", fake_praw)

    result = await agent._fetch_reddit_praw(
        symbol, subreddits=["FuturesTrading", "emini"]
    )

    assert result is None, f"Futures gate leaked for {symbol}: {result}"
    fake_praw.Reddit.assert_not_called()
