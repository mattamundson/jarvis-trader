"""
Regression tests for the cross-provider thundering-herd guard in JarvisLLMClient.

Bug (found 2026-08-12, memory project_jarvis_llm_cascade_thundering_herd_2026_08_12.md):
Every pipeline agent holds its OWN JarvisLLMClient instance and independently runs the
Gemini->OpenAI credit-exhaustion cascade in call(). When Anthropic credits are exhausted,
N agents fire the same cascade within the same ~15s window, thundering-herding Gemini and
OpenAI with simultaneous requests and tripping a 429 on both from the shared per-key rate
limit -- a self-inflicted secondary outage on top of the real Anthropic one.

Fix: a CLASS-level (shared across every JarvisLLMClient instance in the process) cooldown
keyed by provider name. The first agent to see a 429 from a leg marks it degraded for a
window; every other agent's cascade (this cycle or a concurrent one) skips straight past
that leg instead of re-attempting and re-tripping the identical rate limit.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from llm import JarvisLLMClient


class _FakeHTTPStatusError(Exception):
    """Minimal stand-in for httpx.HTTPStatusError -- only needs .response.status_code,
    which is all _note_provider_rate_limited() inspects."""

    def __init__(self, status_code: int):
        super().__init__(f"HTTP {status_code}")
        self.response = SimpleNamespace(status_code=status_code)


@pytest.fixture(autouse=True)
def _clean_provider_cooldown_state():
    """The cooldown dict is a CLASS attribute by design (shared across instances) --
    reset it around every test in this file so no test leaks cooldown state into
    another test, in this file or any other collected in the same pytest run."""
    JarvisLLMClient._provider_degraded_until.clear()
    yield
    JarvisLLMClient._provider_degraded_until.clear()


def _make_client(tmp_path, monkeypatch, **env):
    monkeypatch.setenv("JARVIS_LLM_PROVIDER", env.pop("JARVIS_LLM_PROVIDER", "anthropic"))
    for key in (
        "OPENAI_API_KEY",
        "OPENAI_ENDPOINT",
        "JARVIS_LLM_OPENAI_FALLBACK",
        "GOOGLE_API_KEY",
        "JARVIS_LLM_GOOGLE_FALLBACK",
        "JARVIS_LLM_VERTEX_FAILOVER",
        "JARVIS_CLAUDE_USE_VERTEX",
    ):
        monkeypatch.delenv(key, raising=False)
    for key, val in env.items():
        monkeypatch.setenv(key, val)
    db_path = str(tmp_path / f"herd_test_costs_{len(env)}.db")
    return JarvisLLMClient(api_key="test-anthropic-key", db_path=db_path)


def _credit_exhaustion_error():
    return Exception("Your credit balance is too low to complete this request.")


class TestThunderingHerdGuard:
    @pytest.mark.asyncio
    async def test_second_agents_client_skips_gemini_after_first_agents_429(
        self, tmp_path, monkeypatch
    ):
        """RED without the fix: a second, independent JarvisLLMClient instance (as every
        pipeline agent has) would re-attempt Gemini and re-trip the same 429 instead of
        skipping straight to OpenAI."""
        client_a = _make_client(
            tmp_path, monkeypatch, GOOGLE_API_KEY="gemini-key", OPENAI_API_KEY="sk-openai-key"
        )
        client_a.google_fallback_enabled = True
        client_a.openai_fallback_enabled = True

        openai_ns = SimpleNamespace(
            usage=SimpleNamespace(input_tokens=80, output_tokens=40),
            content=[SimpleNamespace(text="HOLD")],
        )

        with (
            patch.object(client_a, "_call_with_retry", side_effect=_credit_exhaustion_error()),
            patch.object(client_a, "_call_google", side_effect=_FakeHTTPStatusError(429)),
            patch.object(client_a, "_call_openai", AsyncMock(return_value=openai_ns)),
        ):
            result_a = await client_a.call(
                model="claude-sonnet-4-6",
                system="sys",
                messages=[{"role": "user", "content": "signal?"}],
                agent_name="technical_analyst",
            )
        assert result_a.success is True  # 429 on gemini still falls through to openai

        # A second agent's OWN client instance, created fresh -- exactly the real
        # topology (bear_researcher/bull_researcher/etc. each own their client).
        client_b = _make_client(
            tmp_path, monkeypatch, GOOGLE_API_KEY="gemini-key", OPENAI_API_KEY="sk-openai-key"
        )
        client_b.google_fallback_enabled = True
        client_b.openai_fallback_enabled = True

        gemini_mock_b = AsyncMock(side_effect=_FakeHTTPStatusError(429))
        openai_mock_b = AsyncMock(return_value=openai_ns)

        with (
            patch.object(client_b, "_call_with_retry", side_effect=_credit_exhaustion_error()),
            patch.object(client_b, "_call_google", gemini_mock_b),
            patch.object(client_b, "_call_openai", openai_mock_b),
        ):
            result_b = await client_b.call(
                model="claude-sonnet-4-6",
                system="sys",
                messages=[{"role": "user", "content": "signal?"}],
                agent_name="fundamental_analyst",
            )

        assert result_b.success is True
        gemini_mock_b.assert_not_called()  # skipped -- cooling down from client_a's 429
        openai_mock_b.assert_called_once()

    @pytest.mark.asyncio
    async def test_cooldown_auto_clears_after_window_expires(self, tmp_path, monkeypatch):
        """The breaker is a soft, time-boxed backoff, not a permanent circuit trip --
        once the window elapses, the next agent's cascade retries the leg normally."""
        client = _make_client(
            tmp_path, monkeypatch, GOOGLE_API_KEY="gemini-key", OPENAI_API_KEY="sk-openai-key"
        )
        client.google_fallback_enabled = True
        client.openai_fallback_enabled = True

        assert client._is_provider_cooling_down("gemini") is False
        client._note_provider_rate_limited("gemini", _FakeHTTPStatusError(429))
        assert client._is_provider_cooling_down("gemini") is True

        # Force the recorded cooldown deadline into the past instead of sleeping --
        # equivalent to the window having elapsed.
        JarvisLLMClient._provider_degraded_until["gemini"] = 0.0
        assert client._is_provider_cooling_down("gemini") is False

        gemini_ns = SimpleNamespace(
            usage=SimpleNamespace(input_tokens=60, output_tokens=30),
            content=[SimpleNamespace(text="LONG")],
        )
        gemini_mock = AsyncMock(return_value=gemini_ns)
        with (
            patch.object(client, "_call_with_retry", side_effect=_credit_exhaustion_error()),
            patch.object(client, "_call_google", gemini_mock),
        ):
            result = await client.call(
                model="claude-sonnet-4-6",
                system="sys",
                messages=[{"role": "user", "content": "signal?"}],
                agent_name="trader",
            )

        assert result.success is True
        gemini_mock.assert_called_once()  # retried normally, not skipped

    @pytest.mark.asyncio
    async def test_non_429_failure_does_not_trip_the_breaker(self, tmp_path, monkeypatch):
        """A genuine outage (500, timeout, RuntimeError) is not a rate limit -- it must
        not suppress the next agent's attempt. Only a 429 should arm the cooldown."""
        client = _make_client(
            tmp_path, monkeypatch, GOOGLE_API_KEY="gemini-key", OPENAI_API_KEY="sk-openai-key"
        )
        client.google_fallback_enabled = True
        client.openai_fallback_enabled = True

        with (
            patch.object(client, "_call_with_retry", side_effect=_credit_exhaustion_error()),
            patch.object(client, "_call_google", side_effect=RuntimeError("Gemini 503")),
            patch.object(client, "_call_openai", AsyncMock(return_value=SimpleNamespace(
                usage=SimpleNamespace(input_tokens=10, output_tokens=5),
                content=[SimpleNamespace(text="ok")],
            ))),
        ):
            await client.call(
                model="claude-sonnet-4-6",
                system="sys",
                messages=[{"role": "user", "content": "signal?"}],
                agent_name="trader",
            )

        assert client._is_provider_cooling_down("gemini") is False

    @pytest.mark.asyncio
    async def test_single_agent_failure_path_unaffected_by_the_guard(self, tmp_path, monkeypatch):
        """No prior degradation recorded anywhere -- the ordinary single-agent cascade
        (Gemini fails non-429 -> OpenAI succeeds) behaves exactly as before the fix."""
        client = _make_client(
            tmp_path, monkeypatch, GOOGLE_API_KEY="gemini-key", OPENAI_API_KEY="sk-openai-key"
        )
        client.google_fallback_enabled = True
        client.openai_fallback_enabled = True

        openai_ns = SimpleNamespace(
            usage=SimpleNamespace(input_tokens=80, output_tokens=40),
            content=[SimpleNamespace(text="LONG MES @ 5800")],
        )

        with (
            patch.object(client, "_call_with_retry", side_effect=_credit_exhaustion_error()),
            patch.object(client, "_call_google", side_effect=RuntimeError("Gemini 503")),
            patch.object(client, "_call_openai", AsyncMock(return_value=openai_ns)),
        ):
            result = await client.call(
                model="claude-sonnet-4-6",
                system="sys",
                messages=[{"role": "user", "content": "signal?"}],
                agent_name="trader",
            )

        assert result.success is True
        assert result.content == "LONG MES @ 5800"
        assert client.openai_fallback_count == 1

    @pytest.mark.asyncio
    async def test_openai_cooldown_independent_of_gemini_cooldown(self, tmp_path, monkeypatch):
        """The two provider legs cool down independently -- a Gemini 429 must not
        suppress a subsequent agent's OpenAI attempt, and vice versa."""
        client = _make_client(
            tmp_path, monkeypatch, GOOGLE_API_KEY="gemini-key", OPENAI_API_KEY="sk-openai-key"
        )
        client._note_provider_rate_limited("gemini", _FakeHTTPStatusError(429))

        assert client._is_provider_cooling_down("gemini") is True
        assert client._is_provider_cooling_down("openai") is False
