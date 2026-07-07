"""Regression: surface the Gemini endpoint response body on a 4xx/5xx.

Bug class (2026-06-05): the Gemini OpenAI-compat fallback was failing 54x with
`Client error '404 Not Found'`. The caller logs the httpx.HTTPStatusError via
"%s"/"{gex}", whose string form omits the response *body* — so the logs could
not distinguish a revoked/invalid GOOGLE_API_KEY ("API key not valid") from an
unknown model id ("models/... is not found"). Diagnosis was blind.

The fix in `_call_google` logs the status + truncated body at the source (a
WARNING) before re-raising, so the real cause is one `grep` away. Control flow
is unchanged: a 4xx/5xx still raises httpx.HTTPStatusError for the caller's
fallback logic.
"""

import logging
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
    # Ensure the Gemini path is reachable regardless of ambient env.
    client.google_api_key = "fake-google-key"
    client.google_endpoint = _GEMINI_URL
    yield client


@respx.mock
@pytest.mark.asyncio
async def test_404_body_is_logged_and_still_raises(llm_client, caplog):
    body = '{"error":{"code":404,"message":"models/gemini-2.5-flash is not found","status":"NOT_FOUND"}}'
    respx.post(_GEMINI_URL).mock(return_value=httpx.Response(404, text=body))

    caplog.set_level(logging.WARNING, logger="llm.client")

    with pytest.raises(httpx.HTTPStatusError):
        await llm_client._call_google(
            system="sys",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=10,
            temperature=0.0,
            model="gemini-2.5-flash",
        )

    combined = "\n".join(r.getMessage() for r in caplog.records)
    assert "is not found" in combined, f"Body text missing from logs:\n{combined}"
    assert "404" in combined, f"Status code missing from logs:\n{combined}"


@respx.mock
@pytest.mark.asyncio
async def test_invalid_key_body_distinguishes_from_model_error(llm_client, caplog):
    body = '{"error":{"code":400,"message":"API key not valid. Please pass a valid API key.","status":"INVALID_ARGUMENT"}}'
    respx.post(_GEMINI_URL).mock(return_value=httpx.Response(400, text=body))

    caplog.set_level(logging.WARNING, logger="llm.client")

    with pytest.raises(httpx.HTTPStatusError):
        await llm_client._call_google(
            system="sys",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=10,
            temperature=0.0,
            model="gemini-2.5-flash",
        )

    combined = "\n".join(r.getMessage() for r in caplog.records)
    # The key-vs-model distinction the old log could not make:
    assert "API key not valid" in combined, f"Body text missing from logs:\n{combined}"


@respx.mock
@pytest.mark.asyncio
async def test_2xx_path_logs_no_warning_and_returns_content(llm_client, caplog):
    ok = {
        "choices": [{"message": {"content": "hello"}}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 1},
    }
    respx.post(_GEMINI_URL).mock(return_value=httpx.Response(200, json=ok))

    caplog.set_level(logging.WARNING, logger="llm.client")

    result = await llm_client._call_google(
        system="sys",
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=10,
        temperature=0.0,
        model="gemini-2.5-flash",
    )

    assert result.content[0].text == "hello"
    combined = "\n".join(r.getMessage() for r in caplog.records)
    assert "returned HTTP" not in combined, f"Unexpected warning on 2xx:\n{combined}"
