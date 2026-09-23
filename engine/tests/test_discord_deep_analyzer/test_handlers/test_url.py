"""Tests for handlers.url."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
import respx
from httpx import Response

from discord.deep_analyzer.handlers.url import UrlHandler
from discord.deep_analyzer.llm import LLMResponse
from discord.deep_analyzer.models import LLMUsage


@pytest.fixture
def fake_llm():
    return LLMResponse(
        reply=json.dumps(
            {
                "summary": "GitHub repo about vol scanning",
                "tickers": [],
                "topics": ["github", "tools"],
                "sentiment": "neutral",
                "has_action_item": False,
                "source_kind": "github",
                "author": "someone",
                "priority": 3,
            }
        ),
        model="gemini-2.5-flash",
        usage=LLMUsage(input_tokens=400, output_tokens=80),
        cost_usd=0.000320,
    )


@pytest.mark.asyncio
async def test_url_handler_fetches_and_summarizes_article(fake_llm):
    html = "<html><body><article><h1>Hi</h1><p>Body text here with enough words to look like content for readability extraction to consider it the main article.</p></article></body></html>"
    with respx.mock() as mock:
        mock.get("https://example.com/article").mock(return_value=Response(200, text=html))
        with patch(
            "discord.deep_analyzer.handlers.url.call_text", AsyncMock(return_value=fake_llm)
        ):
            out = await UrlHandler().analyze(
                {"message_id": "m9", "url": "https://example.com/article", "content": None}
            )
    assert out.artifact_type == "url"
    assert out.structured["source_kind"] == "github"


@pytest.mark.asyncio
async def test_url_handler_handles_x_js_required_fallback(fake_llm):
    js_required = "<html><body><noscript>Please enable JavaScript</noscript></body></html>"
    with respx.mock() as mock:
        mock.get("https://x.com/foo/status/1").mock(return_value=Response(200, text=js_required))
        with patch(
            "discord.deep_analyzer.handlers.url.call_text", AsyncMock(return_value=fake_llm)
        ):
            out = await UrlHandler().analyze(
                {"message_id": "m9", "url": "https://x.com/foo/status/1", "content": None}
            )
    assert out.summary  # got an analysis even with JS-required body


@pytest.mark.asyncio
async def test_url_handler_handles_404(fake_llm):
    with respx.mock() as mock:
        mock.get("https://example.com/gone").mock(return_value=Response(404))
        with patch(
            "discord.deep_analyzer.handlers.url.call_text", AsyncMock(return_value=fake_llm)
        ):
            out = await UrlHandler().analyze(
                {"message_id": "m9", "url": "https://example.com/gone", "content": None}
            )
    assert out.summary  # 404 doesn't kill the row — LLM gets URL as context
<<<<<<< HEAD
=======


@pytest.mark.asyncio
async def test_url_handler_handles_malformed_url_port(fake_llm):
    # A bookmark whose URL has a malformed port (e.g. pasted inside Discord
    # markdown backticks: `http://localhost:8010`) makes httpx raise
    # httpx.InvalidURL at request-build time. InvalidURL is not a RequestError,
    # so it must be caught explicitly — otherwise the whole row is recorded as
    # FAILED instead of degrading to a URL-only prompt. Regression for the
    # deep_analyzer_loop "Invalid port: '8010`'" crash.
    bad_url = "http://localhost:8010`"
    with patch(
        "discord.deep_analyzer.handlers.url.call_text", AsyncMock(return_value=fake_llm)
    ) as mock_llm:
        out = await UrlHandler().analyze(
            {"message_id": "m9", "url": bad_url, "content": None}
        )
    assert out.summary  # malformed URL doesn't kill the row
    assert out.artifact_type == "url"
    # Handler still reached the LLM with the URL as context (graceful fallback).
    prompt = mock_llm.call_args.kwargs["prompt"]
    assert bad_url in prompt
>>>>>>> e9ab478a30fb5d2b005069b9003501d801cea0b2
