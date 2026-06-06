"""Regression: floor the Gemini output budget for 2.5 thinking models.

Bug (2026-06-05, live log): GEMINI_PRIMARY analysts pass small max_tokens
(social=500, news=800, fundamental=256). gemini-2.5-flash is a *thinking* model
whose max_tokens budget over the OpenAI-compat endpoint is shared between
internal reasoning and the visible answer — so reasoning consumed the budget and
the JSON response truncated mid-object (observed cut at '"confidence":'). This
permanently degraded the 4 Gemini-primary analysts, not just during the outage.

Fix: _call_google floors the output budget for gemini-2.5* models
(GEMINI_MIN_OUTPUT_TOKENS, default 2048; only ever raises). Non-thinking models
(gemini-2.0-flash) keep the caller's value.
"""

import os
import sys
from pathlib import Path

import httpx
import pytest
import respx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from llm import JarvisLLMClient  # noqa: E402

_GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"


@pytest.fixture
def llm_client(tmp_path: Path):
    client = JarvisLLMClient(api_key="test-key", db_path=str(tmp_path / "costs.db"))
    client.google_api_key = "fake-google-key"
    client.google_endpoint = _GEMINI_URL
    yield client


def _ok():
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": '{"signal": 0.0}'}}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 5},
        },
    )


async def _captured_max_tokens(llm_client, model, requested):
    captured = {}

    def _handler(request):
        import json

        captured["max_tokens"] = json.loads(request.content)["max_tokens"]
        return _ok()

    with respx.mock:
        respx.post(_GEMINI_URL).mock(side_effect=_handler)
        await llm_client._call_google(
            system="sys",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=requested,
            temperature=0.0,
            model=model,
        )
    return captured["max_tokens"]


@pytest.mark.asyncio
async def test_25_flash_small_budget_is_floored(llm_client):
    # social_analyst-style 500 → floored to the 2048 default.
    assert await _captured_max_tokens(llm_client, "gemini-2.5-flash", 500) == 2048


@pytest.mark.asyncio
async def test_25_flash_large_budget_unchanged(llm_client):
    # Caller already above the floor → kept as-is (floor only raises).
    assert await _captured_max_tokens(llm_client, "gemini-2.5-flash", 4096) == 4096


@pytest.mark.asyncio
async def test_20_flash_not_floored(llm_client):
    # Non-thinking model keeps the caller's small budget.
    assert await _captured_max_tokens(llm_client, "gemini-2.0-flash", 500) == 500


@pytest.mark.asyncio
async def test_floor_is_env_tunable(llm_client, monkeypatch):
    monkeypatch.setenv("GEMINI_MIN_OUTPUT_TOKENS", "1500")
    assert await _captured_max_tokens(llm_client, "gemini-2.5-flash", 500) == 1500
