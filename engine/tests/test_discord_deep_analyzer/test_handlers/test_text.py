"""Tests for handlers.text."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from discord.deep_analyzer.handlers.text import TextHandler
from discord.deep_analyzer.llm import LLMResponse
from discord.deep_analyzer.models import LLMUsage


@pytest.mark.asyncio
async def test_text_handler_returns_structured_result():
    fake = LLMResponse(
        reply=json.dumps(
            {
                "summary": "Trader thought about MES short",
                "tickers": ["MES"],
                "topics": ["futures", "intraday"],
                "sentiment": "bearish",
                "has_action_item": True,
                "priority": 4,
            }
        ),
        model="gemini-2.5-flash",
        usage=LLMUsage(input_tokens=50, output_tokens=80),
        cost_usd=0.000215,
    )
    with patch("discord.deep_analyzer.handlers.text.call_text", AsyncMock(return_value=fake)):
        h = TextHandler()
        out = await h.analyze({"id": 1, "content": "thinking about shorting MES if it breaks 5800"})
    assert out.bookmark_id == 1
    assert out.artifact_type == "text"
    assert out.structured["tickers"] == ["MES"]
    assert "MES" in out.summary
    assert out.model_used == "gemini-2.5-flash"


@pytest.mark.asyncio
async def test_text_handler_handles_non_json_reply_gracefully():
    fake = LLMResponse(
        reply="plain prose not JSON",
        model="gemini-2.5-flash",
        usage=LLMUsage(input_tokens=5, output_tokens=5),
        cost_usd=0.0,
    )
    with patch("discord.deep_analyzer.handlers.text.call_text", AsyncMock(return_value=fake)):
        h = TextHandler()
        out = await h.analyze({"id": 1, "content": "noise"})
    # Falls back to using the raw reply as summary
    assert out.summary == "plain prose not JSON"
    assert out.structured == {}
