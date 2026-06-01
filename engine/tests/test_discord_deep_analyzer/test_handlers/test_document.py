"""Tests for handlers.document."""

from __future__ import annotations

import json
from io import BytesIO
from unittest.mock import AsyncMock, patch

import pytest
import respx
from httpx import Response
from pypdf import PdfWriter

from discord.deep_analyzer.handlers.document import DocumentHandler
from discord.deep_analyzer.llm import LLMResponse
from discord.deep_analyzer.models import LLMUsage


def _trivial_pdf_bytes() -> bytes:
    w = PdfWriter()
    w.add_blank_page(width=100, height=100)
    buf = BytesIO()
    w.write(buf)
    return buf.getvalue()


@pytest.fixture
def fake_doc_llm():
    return LLMResponse(
        reply=json.dumps(
            {
                "summary": "Empty PDF",
                "tickers": [],
                "topics": ["pdf"],
                "has_action_item": False,
                "key_points": [],
                "priority": 1,
            }
        ),
        model="claude-haiku-4-5-20251001",
        usage=LLMUsage(input_tokens=20, output_tokens=20),
        cost_usd=0.000056,
    )


@pytest.mark.asyncio
async def test_document_handler_extracts_and_analyzes(fake_doc_llm):
    with respx.mock() as mock:
        mock.get("https://cdn.discord.com/x.pdf").mock(
            return_value=Response(
                200,
                content=_trivial_pdf_bytes(),
                headers={"content-type": "application/pdf"},
            )
        )
        with patch(
            "discord.deep_analyzer.handlers.document.call_text",
            AsyncMock(return_value=fake_doc_llm),
        ):
            out = await DocumentHandler().analyze(
                {
                    "message_id": "m11",
                    "attachment_urls": "https://cdn.discord.com/x.pdf",
                }
            )
    assert out.artifact_type == "document"
    assert out.structured["topics"] == ["pdf"]
