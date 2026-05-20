"""Tests for deep_analyzer.llm — adapter over JarvisLLMClient."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from discord.deep_analyzer import llm
from llm.client import LLMCallResult


@pytest.fixture
def fake_engine_client():
    """Patch the underlying JarvisLLMClient instance for the test."""
    fake = MagicMock()
    fake.call = AsyncMock()
    with patch("discord.deep_analyzer.llm._get_engine_client", return_value=fake):
        yield fake


@pytest.mark.asyncio
async def test_call_text_returns_llmresponse(fake_engine_client):
    fake_engine_client.call.return_value = LLMCallResult(
        success=True,
        model="claude-haiku-4-5-20251001",
        input_tokens=10,
        output_tokens=5,
        cost_usd=0.000028,
        latency_ms=120,
        retries=0,
        content="hello back",
    )
    resp = await llm.call_text(prompt="hi", system="be terse")
    assert resp.reply == "hello back"
    assert resp.model == "claude-haiku-4-5-20251001"
    assert resp.usage.total_tokens == 15
    assert resp.cost_usd == pytest.approx(0.000028)


@pytest.mark.asyncio
async def test_call_text_raises_on_failed_result(fake_engine_client):
    fake_engine_client.call.return_value = LLMCallResult(
        success=False,
        model="claude-haiku-4-5-20251001",
        input_tokens=0,
        output_tokens=0,
        cost_usd=0,
        latency_ms=10,
        retries=3,
        content="",
        error="all retries exhausted",
    )
    with pytest.raises(llm.LLMError):
        await llm.call_text(prompt="hi")


@pytest.mark.asyncio
async def test_call_text_uses_haiku_by_default(fake_engine_client):
    fake_engine_client.call.return_value = LLMCallResult(
        success=True,
        model="claude-haiku-4-5-20251001",
        input_tokens=1,
        output_tokens=1,
        cost_usd=0.0,
        latency_ms=1,
        retries=0,
        content="x",
    )
    await llm.call_text(prompt="hi")
    _args, kwargs = fake_engine_client.call.call_args
    assert kwargs["model"] == "claude-haiku-4-5-20251001"
    assert kwargs["agent_name"] == "deep_analyzer"


@pytest.mark.asyncio
async def test_call_vision_passes_multimodal_content(fake_engine_client):
    fake_engine_client.call.return_value = LLMCallResult(
        success=True,
        model="claude-haiku-4-5-20251001",
        input_tokens=100,
        output_tokens=20,
        cost_usd=0.000160,
        latency_ms=200,
        retries=0,
        content="red square",
    )
    out = await llm.call_vision(prompt="describe", image_bytes=b"\x89PNG\r\n", mime="image/png")
    assert out.reply == "red square"
    # Confirm the user message has a content list (multimodal)
    _args, kwargs = fake_engine_client.call.call_args
    msgs = kwargs["messages"]
    assert isinstance(msgs[0]["content"], list)
    assert any(part.get("type") == "image" for part in msgs[0]["content"])
