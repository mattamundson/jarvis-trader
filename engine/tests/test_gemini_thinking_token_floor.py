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


async def _captured_payload(llm_client, model, requested):
    captured = {}

    def _handler(request):
        import json

        captured["payload"] = json.loads(request.content)
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
    return captured["payload"]


async def _captured_max_tokens(llm_client, model, requested):
    return (await _captured_payload(llm_client, model, requested))["max_tokens"]


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


# --- reasoning_effort: disable thinking on 2.5 so the budget feeds the answer ---
# Bug (2026-06-06, live log): even with the 2048 floor, a heavy analyst prompt
# made gemini-2.5-flash spend ~1900 tokens thinking and truncate the JSON at
# out:80. Disabling thinking via reasoning_effort frees the whole budget.


@pytest.mark.asyncio
async def test_25_flash_disables_thinking_by_default(llm_client):
    payload = await _captured_payload(llm_client, "gemini-2.5-flash", 500)
    assert payload["reasoning_effort"] == "none"


@pytest.mark.asyncio
async def test_20_flash_no_reasoning_effort(llm_client):
    # Non-thinking model must not get the knob at all.
    payload = await _captured_payload(llm_client, "gemini-2.0-flash", 500)
    assert "reasoning_effort" not in payload


@pytest.mark.asyncio
async def test_reasoning_effort_is_env_tunable(llm_client, monkeypatch):
    monkeypatch.setenv("GEMINI_REASONING_EFFORT", "low")
    payload = await _captured_payload(llm_client, "gemini-2.5-flash", 500)
    assert payload["reasoning_effort"] == "low"


@pytest.mark.asyncio
async def test_reasoning_effort_blank_omits_knob(llm_client, monkeypatch):
    # Escape hatch: empty value omits the field (fall back to model default).
    monkeypatch.setenv("GEMINI_REASONING_EFFORT", "")
    payload = await _captured_payload(llm_client, "gemini-2.5-flash", 500)
    assert "reasoning_effort" not in payload


# --- gemini-2.5-pro cannot disable thinking ---
# Bug (2026-07-06, live probe): gemini-2.5-pro rejects reasoning_effort="none"
# with HTTP 400 "Budget 0 is invalid. This model only works in thinking mode."
# pro is the decision-tier credit-exhaustion failover (GOOGLE_FAILOVER_MAP:
# opus/sonnet -> gemini-2.5-pro), so sending "none" 400s every decision failover.
# pro must keep thinking on (knob omitted) unless an explicit non-"none" effort
# is set. flash is unaffected — it supports disabling thinking.


@pytest.mark.asyncio
async def test_25_pro_omits_reasoning_effort_by_default(llm_client):
    # Regression: pro must NOT get reasoning_effort="none" (Google 400s it).
    payload = await _captured_payload(llm_client, "gemini-2.5-pro", 500)
    assert "reasoning_effort" not in payload


@pytest.mark.asyncio
async def test_25_pro_ignores_explicit_none(llm_client, monkeypatch):
    # Even an explicit "none" is dropped for pro — it only works in thinking mode.
    monkeypatch.setenv("GEMINI_REASONING_EFFORT", "none")
    payload = await _captured_payload(llm_client, "gemini-2.5-pro", 500)
    assert "reasoning_effort" not in payload


@pytest.mark.asyncio
async def test_25_pro_respects_explicit_nonzero_effort(llm_client, monkeypatch):
    # A valid non-"none" effort is a supported (non-zero) thinking budget on pro.
    monkeypatch.setenv("GEMINI_REASONING_EFFORT", "low")
    payload = await _captured_payload(llm_client, "gemini-2.5-pro", 500)
    assert payload["reasoning_effort"] == "low"


@pytest.mark.asyncio
async def test_25_pro_still_floored(llm_client):
    # The output-budget floor still applies to pro (thinking shares the budget).
    assert await _captured_max_tokens(llm_client, "gemini-2.5-pro", 500) == 2048
