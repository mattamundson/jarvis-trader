"""Tests for handlers.image."""

from __future__ import annotations

import json
from io import BytesIO
from unittest.mock import AsyncMock, patch

import pytest
import respx
from httpx import Response
from PIL import Image

from discord.deep_analyzer.handlers.image import ImageHandler
from discord.deep_analyzer.llm import LLMResponse
from discord.deep_analyzer.models import LLMUsage


def _png_bytes(color=(255, 0, 0)) -> bytes:
    img = Image.new("RGB", (10, 10), color)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def fake_vision_llm():
    return LLMResponse(
        reply=json.dumps(
            {
                "summary": "Red square",
                "ocr_text": "",
                "is_chart": False,
                "ticker": None,
                "timeframe": None,
                "topics": ["image"],
                "priority": 1,
            }
        ),
        model="claude-haiku-4-5-20251001",
        usage=LLMUsage(input_tokens=300, output_tokens=40),
        cost_usd=0.000190,
    )


@pytest.mark.asyncio
async def test_image_handler_downloads_and_analyzes(fake_vision_llm):
    with respx.mock() as mock:
        mock.get("https://cdn.discord.com/red.png").mock(
            return_value=Response(200, content=_png_bytes(), headers={"content-type": "image/png"})
        )
        with patch(
            "discord.deep_analyzer.handlers.image.call_vision",
            AsyncMock(return_value=fake_vision_llm),
        ):
            out = await ImageHandler().analyze(
                {
                    "message_id": "m5",
                    "attachment_urls": "https://cdn.discord.com/red.png",
                }
            )
    assert out.artifact_type == "image"
    assert out.structured["is_chart"] is False


@pytest.mark.asyncio
async def test_image_handler_picks_first_attachment_when_multiple():
    with respx.mock() as mock:
        mock.get("https://cdn.discord.com/a.png").mock(
            return_value=Response(200, content=_png_bytes(), headers={"content-type": "image/png"})
        )
        fake = LLMResponse(
            reply='{"summary":"x","ocr_text":"","is_chart":false,"topics":[],"priority":1}',
            model="claude-haiku-4-5-20251001",
            usage=LLMUsage(),
            cost_usd=0,
        )
        with patch(
            "discord.deep_analyzer.handlers.image.call_vision",
            AsyncMock(return_value=fake),
        ):
            out = await ImageHandler().analyze(
                {
                    "message_id": "m5",
                    "attachment_urls": "https://cdn.discord.com/a.png https://cdn.discord.com/b.png",
                }
            )
    assert out.summary == "x"
