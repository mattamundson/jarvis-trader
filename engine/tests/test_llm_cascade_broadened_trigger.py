"""
Regression suite for PRB-10: the cross-provider cascade (Vertex -> Gemini ->
OpenAI -> Kimi) used to fire ONLY on the narrow _is_credit_exhaustion() string
match. Any other Anthropic-side failure -- a plain 5xx, an auth error, a
malformed response, a sustained rate-limit or hard-timeout with no same-family
fallback left -- skipped the cascade entirely and failed the call immediately,
even when Vertex/Gemini/OpenAI/Kimi were all healthy.

This locks in the fix: `_cross_provider_fallback()` is now reachable from all
three exception handlers in `call()` (RateLimitError, APIConnectionError/
APIStatusError, and the generic Exception catch-all), for ANY failure kind --
while the credit-exhaustion-specific ops alert (notify_credits_exhausted)
still fires ONLY for genuine credit exhaustion, so ops can tell "we're out of
credits" apart from "Anthropic had a blip" in logs/alerts.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from anthropic import APIStatusError, RateLimitError

from llm import JarvisLLMClient


def _make_client(tmp_path, monkeypatch, **env):
    monkeypatch.setenv("JARVIS_LLM_PROVIDER", env.pop("JARVIS_LLM_PROVIDER", "anthropic"))
    for key in (
        "GOOGLE_API_KEY",
        "GEMINI_API_KEY",
        "JARVIS_LLM_GOOGLE_FALLBACK",
        "OPENAI_API_KEY",
        "JARVIS_LLM_OPENAI_FALLBACK",
        "MOONSHOT_API_KEY",
        "JARVIS_LLM_KIMI_FALLBACK",
        "JARVIS_CLAUDE_USE_VERTEX",
        "JARVIS_LLM_VERTEX_FAILOVER",
        "JARVIS_DECISION_PRIMARY",
    ):
        monkeypatch.delenv(key, raising=False)
    for key, val in env.items():
        monkeypatch.setenv(key, val)
    db_path = str(tmp_path / "cascade_broadened_costs.db")
    return JarvisLLMClient(api_key="test-anthropic-key", db_path=db_path)


def _gemini_response(text="OK"):
    return SimpleNamespace(
        usage=SimpleNamespace(input_tokens=50, output_tokens=20),
        content=[SimpleNamespace(text=text)],
    )


def _fake_api_status_error(status_code: int, message: str) -> APIStatusError:
    """Build a real anthropic.APIStatusError the way the SDK raises one."""
    request = SimpleNamespace(method="POST", url="https://api.anthropic.com/v1/messages")
    response = SimpleNamespace(status_code=status_code, headers={}, request=request)
    return APIStatusError(message, response=response, body={"error": {"message": message}})


class _FakeAuthError(Exception):
    """Mimics an Anthropic auth error surfaced as a generic exception (the
    shape _call_with_retry re-raises malformed/unexpected failures as)."""


# ── Generic `except Exception` path: any non-credit failure now cascades ──────


class TestGenericExceptionBroadenedCascade:
    @pytest.mark.asyncio
    async def test_plain_500_falls_over_to_gemini(self, tmp_path, monkeypatch):
        """A plain 500 (not the credit-exhaustion string) must still reach
        Gemini -- this is the exact PRB-10 bug: it used to fail immediately."""
        client = _make_client(tmp_path, monkeypatch, GOOGLE_API_KEY="gemini-key")
        client.google_fallback_enabled = True

        with (
            patch.object(
                client, "_call_with_retry",
                side_effect=Exception("500 Internal Server Error: upstream_error"),
            ),
            patch.object(client, "_call_google", AsyncMock(return_value=_gemini_response("HOLD"))),
        ):
            result = await client.call(
                model="claude-sonnet-4-6",
                system="sys",
                messages=[{"role": "user", "content": "hi"}],
                agent_name="trader",
                allow_fallback=False,
            )

        assert result.success is True
        assert result.content == "HOLD"
        assert client.google_fallback_count == 1

    @pytest.mark.asyncio
    async def test_malformed_response_falls_over_to_openai(self, tmp_path, monkeypatch):
        """A malformed-response error (no credit-exhaustion phrasing, no Gemini
        configured) must still reach OpenAI."""
        client = _make_client(tmp_path, monkeypatch, OPENAI_API_KEY="sk-openai-key")
        client.openai_fallback_enabled = True

        openai_ns = SimpleNamespace(
            usage=SimpleNamespace(input_tokens=40, output_tokens=15),
            content=[SimpleNamespace(text="LONG MES")],
        )
        with (
            patch.object(
                client, "_call_with_retry",
                side_effect=_FakeAuthError("malformed response: missing 'content' field"),
            ),
            patch.object(client, "_call_openai", AsyncMock(return_value=openai_ns)),
        ):
            result = await client.call(
                model="claude-sonnet-4-6",
                system="sys",
                messages=[{"role": "user", "content": "hi"}],
                agent_name="trader",
                allow_fallback=False,
            )

        assert result.success is True
        assert result.content == "LONG MES"
        assert client.openai_fallback_count == 1

    @pytest.mark.asyncio
    async def test_non_credit_failure_all_legs_down_flips_unhealthy_without_credit_alert(
        self, tmp_path, monkeypatch
    ):
        """Every leg unconfigured + a non-credit error: healthy flips False
        (unlike the pre-fix behavior, which silently left it untouched), but
        the credit-exhaustion-specific ops alert must NOT fire -- that alert
        is reserved for genuine credit exhaustion."""
        from llm.client import get_llm_path_state

        client = _make_client(tmp_path, monkeypatch)

        with (
            patch.object(
                client, "_call_with_retry", side_effect=Exception("401 authentication_error")
            ),
            patch(
                "notifications.openclaw_notifier.notify_credits_exhausted",
                new=AsyncMock(return_value=True),
            ) as mock_notify,
        ):
            result = await client.call(
                model="claude-sonnet-4-6",
                system="sys",
                messages=[{"role": "user", "content": "hi"}],
                agent_name="trader",
                allow_fallback=False,
            )

        assert result.success is False
        state = get_llm_path_state()
        assert state["healthy"] is False
        assert "non-credit" in (state["last_failure_reason"] or "")
        mock_notify.assert_not_called()

    @pytest.mark.asyncio
    async def test_credit_exhaustion_still_sends_specific_alert(self, tmp_path, monkeypatch):
        """Distinct-alerting requirement: genuine credit exhaustion (with
        everything else also down) still fires notify_credits_exhausted, and
        the /health reason string is NOT tagged as the generic non-credit
        failure -- ops can tell the two apart."""
        from llm.client import get_llm_path_state

        client = _make_client(tmp_path, monkeypatch)

        with (
            patch.object(
                client,
                "_call_with_retry",
                side_effect=Exception("Your credit balance is too low to complete this request."),
            ),
            patch(
                "notifications.openclaw_notifier.notify_credits_exhausted",
                new=AsyncMock(return_value=True),
            ) as mock_notify,
        ):
            result = await client.call(
                model="claude-sonnet-4-6",
                system="sys",
                messages=[{"role": "user", "content": "hi"}],
                agent_name="trader",
                allow_fallback=False,
            )

        assert result.success is False
        state = get_llm_path_state()
        assert state["healthy"] is False
        assert "non-credit" not in (state["last_failure_reason"] or "")
        assert "credit balance" in (state["last_failure_reason"] or "").lower()
        mock_notify.assert_called_once()


# ── RateLimitError path: sustained 429 with no FALLBACK_CHAIN target left ─────


class TestRateLimitBroadenedCascade:
    @pytest.mark.asyncio
    async def test_sustained_rate_limit_on_haiku_falls_over_to_gemini(self, tmp_path, monkeypatch):
        """claude-haiku-4-5-20251001 has no FALLBACK_CHAIN target (None), so a
        sustained 429 used to break straight to total failure. It must now
        reach the cross-provider cascade instead."""
        client = _make_client(tmp_path, monkeypatch, GOOGLE_API_KEY="gemini-key")
        client.google_fallback_enabled = True

        rate_limit_err = RateLimitError(
            "rate limited",
            response=SimpleNamespace(
                status_code=429,
                headers={},
                request=SimpleNamespace(method="POST", url="https://api.anthropic.com/v1/messages"),
            ),
            body={"error": {"message": "rate limited"}},
        )

        async def _always_rate_limited(*args, **kwargs):
            raise rate_limit_err

        with (
            patch.object(client, "_call_with_retry", side_effect=_always_rate_limited),
            patch.object(client, "_call_google", AsyncMock(return_value=_gemini_response("flash-served"))),
        ):
            result = await client.call(
                model="claude-haiku-4-5-20251001",
                system="sys",
                messages=[{"role": "user", "content": "hi"}],
                agent_name="news_analyst",
                allow_fallback=True,
            )

        assert result.success is True
        assert result.content == "flash-served"
        assert client.google_fallback_count == 1


# ── APIStatusError/APIConnectionError path: 5xx / auth error ──────────────────


class TestAPIStatusErrorBroadenedCascade:
    @pytest.mark.asyncio
    async def test_persistent_5xx_on_haiku_falls_over_to_gemini(self, tmp_path, monkeypatch):
        """A persistent APIStatusError (real 503, not the credit-exhaustion
        signature) on a model with no FALLBACK_CHAIN target must reach the
        cross-provider cascade instead of failing immediately."""
        client = _make_client(tmp_path, monkeypatch, GOOGLE_API_KEY="gemini-key")
        client.google_fallback_enabled = True

        status_err = _fake_api_status_error(503, "Service Unavailable")

        async def _always_503(*args, **kwargs):
            raise status_err

        with (
            patch.object(client, "_call_with_retry", side_effect=_always_503),
            patch.object(client, "_call_google", AsyncMock(return_value=_gemini_response("served"))),
        ):
            result = await client.call(
                model="claude-haiku-4-5-20251001",
                system="sys",
                messages=[{"role": "user", "content": "hi"}],
                agent_name="news_analyst",
                allow_fallback=True,
            )

        assert result.success is True
        assert result.content == "served"

    @pytest.mark.asyncio
    async def test_auth_error_with_no_fallback_configured_marks_unhealthy_non_credit(
        self, tmp_path, monkeypatch
    ):
        """A persistent auth error (APIStatusError, 401) with no cross-provider
        legs configured must still terminate cleanly as a non-credit failure
        (not silently leave the health state untouched, and not send the
        credit-exhaustion-specific alert)."""
        from llm.client import get_llm_path_state

        client = _make_client(tmp_path, monkeypatch)  # no fallback keys configured

        status_err = _fake_api_status_error(401, "invalid x-api-key")

        async def _always_401(*args, **kwargs):
            raise status_err

        with (
            patch.object(client, "_call_with_retry", side_effect=_always_401),
            patch(
                "notifications.openclaw_notifier.notify_credits_exhausted",
                new=AsyncMock(return_value=True),
            ) as mock_notify,
        ):
            result = await client.call(
                model="claude-haiku-4-5-20251001",  # no FALLBACK_CHAIN target
                system="sys",
                messages=[{"role": "user", "content": "hi"}],
                agent_name="news_analyst",
                allow_fallback=True,
            )

        assert result.success is False
        state = get_llm_path_state()
        assert state["healthy"] is False
        mock_notify.assert_not_called()
