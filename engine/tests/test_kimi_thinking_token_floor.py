"""Regression: floor the Kimi K3 output budget (same failure class as Gemini 2.5).

Bug (2026-07-20, shadow test against real Trader/BullResearcher prompts): K3
always runs max thinking effort with no way to disable it, and the completion
budget is shared between internal reasoning and the visible answer -- same
failure class as gemini-2.5-pro (see test_gemini_thinking_token_floor.py). At
the production budget (max_tokens=1200) BOTH real prompts truncated mid-JSON
(Trader cut mid-number, BullResearcher cut mid-word). A re-run at 6000
produced complete, valid JSON using only 603/1708 tokens -- pure budget
starvation, not a prompt or model-quality problem.

Fix: _call_kimi floors the output budget (KIMI_MIN_OUTPUT_TOKENS, default
4096; only ever raises).
"""

import json
import os
import sys
from pathlib import Path

import httpx
import pytest
import respx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from llm import JarvisLLMClient  # noqa: E402

_KIMI_URL = "https://api.moonshot.ai/v1/chat/completions"


@pytest.fixture
def llm_client(tmp_path: Path):
    client = JarvisLLMClient(api_key="test-key", db_path=str(tmp_path / "costs.db"))
    client.kimi_api_key = "fake-kimi-key"
    client.kimi_endpoint = _KIMI_URL
    yield client


def _ok():
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": '{"signal": 0.0}'}}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 5},
        },
    )


async def _captured_max_completion_tokens(llm_client, requested):
    captured = {}

    def _handler(request):
        captured["payload"] = json.loads(request.content)
        return _ok()

    with respx.mock:
        respx.post(_KIMI_URL).mock(side_effect=_handler)
        await llm_client._call_kimi(
            system="sys",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=requested,
            temperature=0.0,
            model="kimi-k3",
        )
    return captured["payload"]["max_completion_tokens"]


@pytest.mark.asyncio
async def test_small_production_budget_is_floored(llm_client):
    # trader/bull_researcher-style 1200 -> floored to the 4096 default.
    assert await _captured_max_completion_tokens(llm_client, 1200) == 4096


@pytest.mark.asyncio
async def test_large_budget_unchanged(llm_client):
    # Caller already above the floor -> kept as-is (floor only raises).
    assert await _captured_max_completion_tokens(llm_client, 6000) == 6000


@pytest.mark.asyncio
async def test_floor_is_env_tunable(llm_client, monkeypatch):
    monkeypatch.setenv("KIMI_MIN_OUTPUT_TOKENS", "8000")
    assert await _captured_max_completion_tokens(llm_client, 1200) == 8000


@pytest.mark.asyncio
async def test_floor_env_var_invalid_falls_back_to_default(llm_client, monkeypatch):
    monkeypatch.setenv("KIMI_MIN_OUTPUT_TOKENS", "not-a-number")
    assert await _captured_max_completion_tokens(llm_client, 1200) == 4096
