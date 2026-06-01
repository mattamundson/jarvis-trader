"""Tests for handlers.text."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from discord.deep_analyzer.handlers.text import (
    TextHandler,
    _is_broken_extract,
    _parse_json_reply,
)
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
        out = await h.analyze(
            {"message_id": "m1", "content": "thinking about shorting MES if it breaks 5800"}
        )
    assert out.bookmark_id == "m1"
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
        out = await h.analyze({"message_id": "m1", "content": "noise"})
    # Falls back to using the raw reply as summary
    assert out.summary == "plain prose not JSON"
    assert out.structured == {}


# ---------------------------------------------------------------------------
# P0 / FAILED tier — broken-extract detector
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "summary",
    [
        "The page could not be retrieved because a privacy extension blocked it.",
        "PRIVACY EXTENSION prevented the request.",
        "could not be retrieved due to a paywall",
        "Unable to analyze content — the page is dynamically rendered.",
        "Unable to analyze the content of this URL.",
        "Failed to load the article body.",
        "Failed to fetch the upstream resource.",
        "Failed to retrieve the page after 3 attempts.",
        "Content not available at this URL.",
        "Content not accessible without login.",
        "No readable content was found on the page.",
        "Blocked by browser security policy.",
        "Blocked by the browser due to mixed content.",
        "Anti-bot challenge prevented extraction.",
        "Cloudflare challenge intercepted the fetch.",
    ],
)
def test_is_broken_extract_matches_known_failure_patterns(summary):
    assert _is_broken_extract(summary) is True


@pytest.mark.parametrize(
    "summary",
    [
        "Bull thesis on MES into FOMC week — auction theory levels stacked.",
        "Trader argues NQ broke key resistance after CPI.",
        "Article reviewing Polymarket toolkit for calibration metrics.",
        "",
        None,
    ],
)
def test_is_broken_extract_does_not_match_normal_content(summary):
    assert _is_broken_extract(summary) is False


def test_parse_json_reply_overrides_priority_to_zero_on_broken_extract():
    payload = json.dumps(
        {
            "summary": "The page could not be retrieved due to a privacy extension.",
            "priority": 4,
            "tickers": [],
        }
    )
    summary, structured = _parse_json_reply(payload)
    assert "could not be retrieved" in summary
    assert structured["priority"] == 0


def test_parse_json_reply_preserves_priority_on_normal_content():
    payload = json.dumps(
        {
            "summary": "Bull thesis on MES into FOMC.",
            "priority": 4,
            "tickers": ["MES"],
        }
    )
    summary, structured = _parse_json_reply(payload)
    assert structured["priority"] == 4
    assert "MES" in summary


def test_parse_json_reply_forces_priority_zero_when_non_json_reply_is_broken():
    # Non-JSON reply path: the function returns reply as summary + {} dict.
    # If the prose itself is a broken-extract marker, priority must still be 0.
    reply = "Unable to analyze the content of this URL."
    summary, structured = _parse_json_reply(reply)
    assert summary == reply
    assert structured["priority"] == 0


def test_parse_json_reply_empty_dict_on_non_json_normal_content():
    reply = "Bull thesis on MES into FOMC."
    summary, structured = _parse_json_reply(reply)
    assert summary == reply
    assert structured == {}
