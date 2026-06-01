"""Tests for handlers.x_post — fxtwitter-backed X.com handler."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
import respx
from httpx import Response

from discord.deep_analyzer.handlers.x_post import (
    X_URL_RE,
    XPostHandler,
    _build_prompt,
    _extract_article_block,
    _extract_body_text,
    _extract_media_urls,
)
from discord.deep_analyzer.llm import LLMResponse
from discord.deep_analyzer.models import ArtifactType, LLMUsage


@pytest.fixture
def fake_llm():
    return LLMResponse(
        reply=json.dumps(
            {
                "summary": "Auction-theory take on the MES open drive.",
                "tickers": ["MES"],
                "topics": ["futures", "auction"],
                "sentiment": "bullish",
                "has_action_item": False,
                "source_kind": "x_post",
                "author": "@coreysures",
                "priority": 4,
            }
        ),
        model="claude-haiku-4-5",
        usage=LLMUsage(input_tokens=500, output_tokens=100),
        cost_usd=0.0005,
    )


@pytest.fixture
def short_tweet_fixture():
    """fxtwitter response for a short tweet (no article)."""
    return {
        "code": 200,
        "message": "OK",
        "tweet": {
            "url": "https://x.com/coreysures/status/12345",
            "id": "12345",
            "text": "MES held value-area high; expect rotation up to last week's POC.",
            "raw_text": {"text": "MES held VAH; expect rotation up to LW POC."},
            "lang": "en",
            "created_at": "Tue May 20 10:00:00 +0000 2026",
            "likes": 250,
            "retweets": 30,
            "replies": 12,
            "quotes": 5,
            "bookmarks": 80,
            "views": 12500,
            "possibly_sensitive": False,
            "is_note_tweet": False,
            "author": {
                "screen_name": "coreysures",
                "name": "Corey Sures",
                "description": "Auction theory + futures",
                "followers": 25000,
                "verification": {"verified": True},
            },
        },
    }


@pytest.fixture
def article_tweet_fixture():
    """fxtwitter response for a long-form article post."""
    return {
        "code": 200,
        "message": "OK",
        "tweet": {
            "url": "https://x.com/educator/status/99999",
            "id": "99999",
            "text": "New piece on order flow.",
            "raw_text": "New piece on order flow.",
            "created_at": "Tue May 20 11:00:00 +0000 2026",
            "likes": 1200,
            "retweets": 150,
            "replies": 80,
            "quotes": 20,
            "bookmarks": 600,
            "views": 80000,
            "author": {
                "screen_name": "educator",
                "name": "Trader Educator",
                "verification": "Blue",
            },
            "media": {
                "photos": [
                    {"url": "https://pbs.twimg.com/media/abc.jpg"},
                    {"url": "https://pbs.twimg.com/media/def.jpg"},
                ],
                "videos": [],
            },
            "article": {
                "title": "How to read absorption in MES",
                "preview_text": "Absorption shows where institutional bids defend.",
                "content": {
                    "blocks": [
                        {"text": "Block one: definition", "type": "header-one"},
                        {"text": "Block two: example trade", "type": "unstyled"},
                        {"text": "", "type": "atomic"},
                        {"text": "Block three: risk", "type": "unstyled"},
                    ],
                    "entityMap": [],
                },
                "media_entities": [
                    {"media_info": {"original_img_url": "https://pbs.twimg.com/article/xyz.jpg"}}
                ],
            },
        },
    }


# ---------------------------------------------------------------------------
# URL regex
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url,expect_match,expect_user,expect_id",
    [
        ("https://x.com/a/status/1", True, "a", "1"),
        ("https://twitter.com/a/status/1234567890", True, "a", "1234567890"),
        ("https://www.x.com/foo/status/42?s=20", True, "foo", "42"),
        ("https://fxtwitter.com/b/status/55", True, "b", "55"),
        ("https://vxtwitter.com/c/status/77", True, "c", "77"),
        ("https://nitter.com/d/status/88", True, "d", "88"),
        ("http://x.com/a/status/9", True, "a", "9"),
        ("https://example.com/article", False, None, None),
        ("https://x.com/a", False, None, None),  # no /status/<id>
        ("https://github.com/owner/repo", False, None, None),
    ],
)
def test_url_regex_matches_known_x_patterns(url, expect_match, expect_user, expect_id):
    m = X_URL_RE.match(url)
    if expect_match:
        assert m is not None
        assert m.group(1) == expect_user
        assert m.group(2) == expect_id
    else:
        assert m is None


# ---------------------------------------------------------------------------
# Field extractors
# ---------------------------------------------------------------------------


def test_extract_body_text_prefers_text_over_raw_text():
    tweet = {"text": "formatted", "raw_text": {"text": "raw"}}
    assert _extract_body_text(tweet) == "formatted"


def test_extract_body_text_falls_back_to_raw_text_dict():
    tweet = {"text": "", "raw_text": {"text": "raw value"}}
    assert _extract_body_text(tweet) == "raw value"


def test_extract_body_text_handles_raw_text_as_string():
    tweet = {"text": "", "raw_text": "plain string"}
    assert _extract_body_text(tweet) == "plain string"


def test_extract_body_text_empty_when_nothing_set():
    assert _extract_body_text({}) == ""


def test_extract_article_block_returns_empty_when_no_article():
    assert _extract_article_block({"text": "tweet only"}) == ""


def test_extract_article_block_pulls_title_preview_and_blocks(article_tweet_fixture):
    tweet = article_tweet_fixture["tweet"]
    block = _extract_article_block(tweet)
    assert "How to read absorption in MES" in block
    assert "Absorption shows where" in block
    assert "Block one: definition" in block
    assert "Block two: example trade" in block
    assert "Block three: risk" in block


def test_extract_article_block_skips_empty_blocks():
    tweet = {
        "article": {
            "title": "T",
            "content": {
                "blocks": [
                    {"text": "keep"},
                    {"text": "   "},  # whitespace only
                    {"text": ""},  # empty
                    {"text": None},  # null
                    "not-a-dict",  # malformed
                ]
            },
        }
    }
    block = _extract_article_block(tweet)
    assert "keep" in block
    # only one body block survived
    assert block.count("\n\n") <= 2  # title + content section


def test_extract_article_block_caps_content_length():
    huge = "x" * 20_000
    tweet = {
        "article": {
            "content": {"blocks": [{"text": huge}]},
        }
    }
    block = _extract_article_block(tweet)
    # 8000 char cap from MAX_ARTICLE_CHARS
    assert len(block) < 9000


def test_extract_media_urls_collects_photos_videos_and_article_media(article_tweet_fixture):
    tweet = article_tweet_fixture["tweet"]
    urls = _extract_media_urls(tweet)
    assert "https://pbs.twimg.com/media/abc.jpg" in urls
    assert "https://pbs.twimg.com/media/def.jpg" in urls
    assert "https://pbs.twimg.com/article/xyz.jpg" in urls
    assert len(urls) == 3


def test_extract_media_urls_empty_when_no_media():
    assert _extract_media_urls({}) == []


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------


def test_build_prompt_includes_author_engagement_and_body(short_tweet_fixture):
    tweet = short_tweet_fixture["tweet"]
    prompt = _build_prompt("https://x.com/coreysures/status/12345", tweet)
    assert "@coreysures" in prompt
    assert "Corey Sures" in prompt
    assert "(verified)" in prompt
    assert "12,500 views" in prompt
    assert "250 likes" in prompt
    assert "MES held value-area high" in prompt


def test_build_prompt_includes_article_when_present(article_tweet_fixture):
    tweet = article_tweet_fixture["tweet"]
    prompt = _build_prompt("https://x.com/educator/status/99999", tweet)
    assert "Article title: How to read absorption in MES" in prompt
    assert "Block one: definition" in prompt
    assert "Media: 3 attached" in prompt


def test_build_prompt_handles_string_verification(article_tweet_fixture):
    tweet = article_tweet_fixture["tweet"]
    prompt = _build_prompt("https://x.com/educator/status/99999", tweet)
    assert "verified: Blue" in prompt


def test_build_prompt_omits_empty_engagement_gracefully():
    tweet = {"author": {"screen_name": "x"}, "text": "hi"}
    prompt = _build_prompt("https://x.com/x/status/1", tweet)
    assert "0 views" in prompt
    assert "hi" in prompt


# ---------------------------------------------------------------------------
# Handler end-to-end (mocked HTTP + LLM)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handler_full_path_with_article(article_tweet_fixture, fake_llm):
    url = "https://x.com/educator/status/99999"
    with respx.mock() as mock:
        mock.get("https://api.fxtwitter.com/educator/status/99999").mock(
            return_value=Response(200, json=article_tweet_fixture)
        )
        with patch(
            "discord.deep_analyzer.handlers.x_post.call_text",
            AsyncMock(return_value=fake_llm),
        ) as llm_mock:
            out = await XPostHandler().analyze({"message_id": "m1", "url": url})

    assert out.artifact_type == ArtifactType.X_POST
    assert out.summary == "Auction-theory take on the MES open drive."
    assert out.structured["source_kind"] == "x_post"
    assert out.structured["tickers"] == ["MES"]
    # LLM was called with the synthesized prompt
    call_kwargs = llm_mock.call_args.kwargs
    assert "Block one: definition" in call_kwargs["prompt"]
    assert "X post by @educator" in call_kwargs["prompt"]


@pytest.mark.asyncio
async def test_handler_short_tweet_no_article(short_tweet_fixture, fake_llm):
    url = "https://x.com/coreysures/status/12345"
    with respx.mock() as mock:
        mock.get("https://api.fxtwitter.com/coreysures/status/12345").mock(
            return_value=Response(200, json=short_tweet_fixture)
        )
        with patch(
            "discord.deep_analyzer.handlers.x_post.call_text",
            AsyncMock(return_value=fake_llm),
        ) as llm_mock:
            out = await XPostHandler().analyze({"message_id": "m2", "url": url})

    assert out.artifact_type == ArtifactType.X_POST
    # Author backfill: structured["author"] should come from fxtwitter
    # if LLM omitted it — but in this fixture LLM already returned one.
    assert out.structured["author"] == "@coreysures"
    # Prompt did not contain an article block
    assert "Article title" not in llm_mock.call_args.kwargs["prompt"]


@pytest.mark.asyncio
async def test_handler_backfills_author_when_llm_omits_it(short_tweet_fixture):
    """LLM returns no author field -> we inject @screen_name from fxtwitter."""
    llm_no_author = LLMResponse(
        reply=json.dumps(
            {
                "summary": "s",
                "tickers": [],
                "topics": [],
                "sentiment": "neutral",
                "has_action_item": False,
                "priority": 3,
            }
        ),
        model="claude-haiku-4-5",
        usage=LLMUsage(input_tokens=1, output_tokens=1),
        cost_usd=0.0,
    )
    with respx.mock() as mock:
        mock.get("https://api.fxtwitter.com/coreysures/status/12345").mock(
            return_value=Response(200, json=short_tweet_fixture)
        )
        with patch(
            "discord.deep_analyzer.handlers.x_post.call_text",
            AsyncMock(return_value=llm_no_author),
        ):
            out = await XPostHandler().analyze(
                {"message_id": "m3", "url": "https://x.com/coreysures/status/12345"}
            )
    assert out.structured["author"] == "@coreysures"
    assert out.structured["source_kind"] == "x_post"


@pytest.mark.asyncio
async def test_handler_falls_back_to_embed_on_fxtwitter_404(fake_llm):
    url = "https://x.com/gone/status/404"
    with respx.mock() as mock:
        mock.get("https://api.fxtwitter.com/gone/status/404").mock(return_value=Response(404))
        with patch(
            "discord.deep_analyzer.handlers.x_post.call_text",
            AsyncMock(return_value=fake_llm),
        ) as llm_mock:
            out = await XPostHandler().analyze(
                {
                    "message_id": "m4",
                    "url": url,
                    "embed_title": "Cached title",
                    "embed_description": "Cached preview text",
                }
            )

    assert out.artifact_type == ArtifactType.X_POST
    prompt = llm_mock.call_args.kwargs["prompt"]
    assert "fxtwitter unavailable" in prompt
    assert "Cached title" in prompt
    assert "Cached preview text" in prompt


@pytest.mark.asyncio
async def test_handler_falls_back_when_url_does_not_match(fake_llm):
    """If routing somehow lands a non-X URL here, fallback (don't crash)."""
    with patch(
        "discord.deep_analyzer.handlers.x_post.call_text",
        AsyncMock(return_value=fake_llm),
    ) as llm_mock:
        out = await XPostHandler().analyze(
            {"message_id": "m5", "url": "https://example.com/not-an-x-url"}
        )
    assert out.artifact_type == ArtifactType.X_POST
    assert "not_an_x_url" in llm_mock.call_args.kwargs["prompt"]


@pytest.mark.asyncio
async def test_handler_fxtwitter_returns_non_dict_payload(fake_llm):
    """If fxtwitter returns valid JSON but the wrong shape, fall back."""
    url = "https://x.com/weird/status/1"
    with respx.mock() as mock:
        mock.get("https://api.fxtwitter.com/weird/status/1").mock(
            return_value=Response(200, json=["unexpected", "list"])
        )
        with patch(
            "discord.deep_analyzer.handlers.x_post.call_text",
            AsyncMock(return_value=fake_llm),
        ) as llm_mock:
            out = await XPostHandler().analyze({"message_id": "m6", "url": url})
    assert out.artifact_type == ArtifactType.X_POST
    assert "fxtwitter unavailable" in llm_mock.call_args.kwargs["prompt"]


# ---------------------------------------------------------------------------
# Dispatch routing
# ---------------------------------------------------------------------------


def test_infer_artifact_type_routes_x_urls_to_x_post():
    from discord.deep_analyzer.runner import _infer_artifact_type

    assert _infer_artifact_type({"url": "https://x.com/a/status/1"}) == ArtifactType.X_POST
    assert _infer_artifact_type({"url": "https://twitter.com/a/status/1"}) == ArtifactType.X_POST


def test_infer_artifact_type_non_x_urls_stay_url():
    from discord.deep_analyzer.runner import _infer_artifact_type

    assert _infer_artifact_type({"url": "https://example.com/article"}) == ArtifactType.URL
    assert _infer_artifact_type({"url": "https://github.com/owner/repo"}) == ArtifactType.URL
