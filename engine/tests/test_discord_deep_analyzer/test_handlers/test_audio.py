"""Tests for handlers.audio."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import respx
from httpx import Response

from discord.deep_analyzer.handlers.audio import AudioHandler
from discord.deep_analyzer.llm import LLMResponse
from discord.deep_analyzer.models import LLMUsage


@pytest.fixture
def fake_audio_llm():
    return LLMResponse(
        reply=json.dumps(
            {
                "summary": "User says they want to short MES tomorrow.",
                "tickers": ["MES"],
                "topics": ["voice-memo", "futures"],
                "has_action_item": True,
                "priority": 4,
            }
        ),
        model="claude-haiku-4-5-20251001",
        usage=LLMUsage(input_tokens=50, output_tokens=40),
        cost_usd=0.000115,
    )


@pytest.mark.asyncio
async def test_audio_handler_transcribes_and_analyzes(fake_audio_llm):
    fake_seg = MagicMock(text="short MES tomorrow")
    fake_model = MagicMock()
    fake_model.transcribe.return_value = ([fake_seg], MagicMock(language="en"))

    with respx.mock() as mock:
        mock.get("https://cdn.discord.com/memo.wav").mock(
            return_value=Response(200, content=b"\x00" * 100, headers={"content-type": "audio/wav"})
        )
        with (
            patch("discord.deep_analyzer.handlers.audio._get_model", return_value=fake_model),
            patch(
                "discord.deep_analyzer.handlers.audio.call_text",
                AsyncMock(return_value=fake_audio_llm),
            ),
        ):
            out = await AudioHandler().analyze(
                {
                    "message_id": "m6",
                    "attachment_urls": "https://cdn.discord.com/memo.wav",
                }
            )

    assert out.artifact_type == "audio"
    assert "MES" in out.summary
    assert out.structured["tickers"] == ["MES"]
