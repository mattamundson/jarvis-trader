"""
Test suite for the Kimi K3 last-resort fallback in JarvisLLMClient.

Covers (2026-07-21): Kimi K3 is the FINAL leg of the credit-exhaustion cascade,
after Vertex -> Gemini -> OpenAI. It fires for ANY agent (including the
enrichment analysts pinned to gemini-flash) when every cheaper provider is dead
at once -- the exact outage on 2026-07-21 that left the analyst tier
enrichment-blind (Gemini spend-capped, Anthropic credit-dead, OpenAI quota-dead
simultaneously).

- Init: kimi_fallback_enabled toggles correctly with key / JARVIS_LLM_KIMI_FALLBACK.
- Chain: Anthropic credit-exhaustion -> Gemini fail -> OpenAI fail -> Kimi fires.
- Short-circuit: OpenAI success means Kimi is never called.
- Retry-on-primary-failure (2026-07-24): an agent that already tried Kimi as its
  decision primary and failed DOES retry Kimi as the last resort -- the elapsed
  cascade time often clears Kimi's tight per-key rate limit.
- Disabled: with the flag off, the cascade ends unhealthy as before (no Kimi leg).
- Visibility: Kimi is listed in providers_configured as a real redundancy leg.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from llm import JarvisLLMClient


def _make_client(tmp_path, monkeypatch, **env):
    """Construct JarvisLLMClient with a controlled env for Kimi last-resort tests."""
    monkeypatch.setenv("JARVIS_LLM_PROVIDER", env.pop("JARVIS_LLM_PROVIDER", "anthropic"))
    # Clear every provider/routing var so the shell (which may have real keys
    # loaded via load-secrets) can't leak into the test and change routing.
    for key in (
        "MOONSHOT_API_KEY",
        "MOONSHOT_ENDPOINT",
        "JARVIS_LLM_KIMI_FALLBACK",
        "OPENAI_API_KEY",
        "OPENAI_ENDPOINT",
        "JARVIS_LLM_OPENAI_FALLBACK",
        "GOOGLE_API_KEY",
        "JARVIS_LLM_GOOGLE_FALLBACK",
        "JARVIS_LLM_VERTEX_FAILOVER",
        "JARVIS_CLAUDE_USE_VERTEX",
        "JARVIS_DECISION_PRIMARY",
    ):
        monkeypatch.delenv(key, raising=False)
    for key, val in env.items():
        monkeypatch.setenv(key, val)
    db_path = str(tmp_path / "kimi_lastresort_costs.db")
    return JarvisLLMClient(api_key="test-anthropic-key", db_path=db_path)


def _credit_exhaustion_error():
    """The exception _call_with_retry raises on Anthropic credit exhaustion.

    Wrapped as a plain Exception so call()'s `except Exception` block triggers
    the provider cascade rather than the retry-then-tier-downgrade path.
    """
    return Exception("Your credit balance is too low to complete this request.")


def _kimi_response(text="HOLD"):
    return SimpleNamespace(
        usage=SimpleNamespace(input_tokens=120, output_tokens=60),
        content=[SimpleNamespace(text=text)],
    )


# ── Init / flag tests ─────────────────────────────────────────────────────────


class TestKimiLastResortInit:
    def test_disabled_when_no_key(self, tmp_path, monkeypatch):
        client = _make_client(tmp_path, monkeypatch)
        assert client.kimi_fallback_enabled is False
        assert client.kimi_api_key == ""

    def test_enabled_when_key_present(self, tmp_path, monkeypatch):
        client = _make_client(tmp_path, monkeypatch, MOONSHOT_API_KEY="fake-kimi-key")
        assert client.kimi_fallback_enabled is True
        assert client.kimi_api_key == "fake-kimi-key"

    def test_disabled_by_flag_zero(self, tmp_path, monkeypatch):
        client = _make_client(
            tmp_path,
            monkeypatch,
            MOONSHOT_API_KEY="fake-kimi-key",
            JARVIS_LLM_KIMI_FALLBACK="0",
        )
        assert client.kimi_fallback_enabled is False

    def test_disabled_by_flag_false(self, tmp_path, monkeypatch):
        client = _make_client(
            tmp_path,
            monkeypatch,
            MOONSHOT_API_KEY="fake-kimi-key",
            JARVIS_LLM_KIMI_FALLBACK="false",
        )
        assert client.kimi_fallback_enabled is False

    def test_fallback_count_starts_at_zero(self, tmp_path, monkeypatch):
        client = _make_client(tmp_path, monkeypatch, MOONSHOT_API_KEY="fake-kimi-key")
        assert client.kimi_fallback_count == 0


# ── Visibility: Kimi listed as a wired redundancy leg ─────────────────────────


class TestKimiInProviderSummary:
    def test_kimi_listed_in_configured_when_enabled(self, tmp_path, monkeypatch):
        from llm.client import _LLM_PATH_STATE

        _make_client(tmp_path, monkeypatch, MOONSHOT_API_KEY="fake-kimi-key")
        assert "kimi" in _LLM_PATH_STATE["providers_configured"]

    def test_kimi_absent_when_no_key(self, tmp_path, monkeypatch):
        from llm.client import _LLM_PATH_STATE

        _make_client(tmp_path, monkeypatch)
        assert "kimi" not in _LLM_PATH_STATE["providers_configured"]


# ── Fallback chain integration ────────────────────────────────────────────────


class TestKimiLastResortChain:
    @pytest.mark.asyncio
    async def test_kimi_fires_when_all_cheaper_providers_fail(self, tmp_path, monkeypatch):
        """The real 2026-07-21 outage: an enrichment analyst goes blind on
        Anthropic (credit) + Gemini (cap) + OpenAI (quota) -> Kimi rescues it."""
        client = _make_client(
            tmp_path,
            monkeypatch,
            GOOGLE_API_KEY="gemini-key",
            OPENAI_API_KEY="sk-openai-key",
            MOONSHOT_API_KEY="fake-kimi-key",
        )
        client.google_fallback_enabled = True
        client.openai_fallback_enabled = True
        client.kimi_fallback_enabled = True

        kimi_mock = AsyncMock(return_value=_kimi_response("Fundamentals: neutral"))

        with (
            patch.object(client, "_call_with_retry", side_effect=_credit_exhaustion_error()),
            patch.object(client, "_call_google", side_effect=RuntimeError("Gemini spend cap")),
            patch.object(client, "_call_openai", side_effect=RuntimeError("OpenAI quota")),
            patch.object(client, "_call_kimi", kimi_mock),
        ):
            result = await client.call(
                model="claude-haiku-4-5-20251001",
                system="sys",
                messages=[{"role": "user", "content": "fundamentals?"}],
                agent_name="fundamental_analyst",
            )

        assert result.success is True
        assert result.model == "kimi-k3"
        assert result.content == "Fundamentals: neutral"
        assert client.kimi_fallback_count == 1
        kimi_mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_kimi_served_by_marks_active_provider(self, tmp_path, monkeypatch):
        """served_by='kimi' propagates to the module path-state active_provider."""
        from llm.client import _LLM_PATH_STATE

        client = _make_client(
            tmp_path,
            monkeypatch,
            GOOGLE_API_KEY="gemini-key",
            OPENAI_API_KEY="sk-openai-key",
            MOONSHOT_API_KEY="fake-kimi-key",
        )
        client.google_fallback_enabled = True
        client.openai_fallback_enabled = True
        client.kimi_fallback_enabled = True

        with (
            patch.object(client, "_call_with_retry", side_effect=_credit_exhaustion_error()),
            patch.object(client, "_call_google", side_effect=RuntimeError("gemini")),
            patch.object(client, "_call_openai", side_effect=RuntimeError("openai")),
            patch.object(client, "_call_kimi", AsyncMock(return_value=_kimi_response())),
        ):
            result = await client.call(
                model="claude-haiku-4-5-20251001",
                system="sys",
                messages=[{"role": "user", "content": "news?"}],
                agent_name="news_analyst",
            )

        assert result.success is True
        assert _LLM_PATH_STATE["active_provider"] == "kimi"
        assert _LLM_PATH_STATE["healthy"] is True

    @pytest.mark.asyncio
    async def test_kimi_not_called_when_openai_succeeds(self, tmp_path, monkeypatch):
        """If OpenAI succeeds, the last-resort Kimi leg must not fire."""
        client = _make_client(
            tmp_path,
            monkeypatch,
            GOOGLE_API_KEY="gemini-key",
            OPENAI_API_KEY="sk-openai-key",
            MOONSHOT_API_KEY="fake-kimi-key",
        )
        client.google_fallback_enabled = True
        client.openai_fallback_enabled = True
        client.kimi_fallback_enabled = True

        openai_ns = SimpleNamespace(
            usage=SimpleNamespace(input_tokens=70, output_tokens=30),
            content=[SimpleNamespace(text="News: quiet")],
        )
        kimi_mock = AsyncMock()

        with (
            patch.object(client, "_call_with_retry", side_effect=_credit_exhaustion_error()),
            patch.object(client, "_call_google", side_effect=RuntimeError("gemini down")),
            patch.object(client, "_call_openai", AsyncMock(return_value=openai_ns)),
            patch.object(client, "_call_kimi", kimi_mock),
        ):
            result = await client.call(
                model="claude-haiku-4-5-20251001",
                system="sys",
                messages=[{"role": "user", "content": "news?"}],
                agent_name="news_analyst",
            )

        assert result.success is True
        assert result.content == "News: quiet"
        kimi_mock.assert_not_awaited()
        assert client.kimi_fallback_count == 0

    @pytest.mark.asyncio
    async def test_kimi_retried_when_agent_used_kimi_primary_and_still_dead(
        self, tmp_path, monkeypatch
    ):
        """A decision agent on JARVIS_DECISION_PRIMARY=kimi-k3 tries Kimi once
        (up top). When that fails and Anthropic/Vertex/Gemini/OpenAI are also
        dead, the last-resort leg retries Kimi -- _call_kimi is called twice,
        total. If Kimi is still down both times, the cascade still ends
        unhealthy (2026-07-24: replaces the old no-double-fire guard, which
        removed the only remaining retry leg exactly when Kimi is the
        configured primary and transiently failed)."""
        client = _make_client(
            tmp_path,
            monkeypatch,
            GOOGLE_API_KEY="gemini-key",
            OPENAI_API_KEY="sk-openai-key",
            MOONSHOT_API_KEY="fake-kimi-key",
            JARVIS_DECISION_PRIMARY="kimi-k3",
        )
        client.google_fallback_enabled = True
        client.openai_fallback_enabled = True
        client.kimi_fallback_enabled = True

        kimi_mock = AsyncMock(side_effect=RuntimeError("kimi timeout"))

        with (
            patch.object(client, "_call_with_retry", side_effect=_credit_exhaustion_error()),
            patch.object(client, "_call_google", side_effect=RuntimeError("gemini down")),
            patch.object(client, "_call_openai", side_effect=RuntimeError("openai down")),
            patch.object(client, "_call_kimi", kimi_mock),
        ):
            result = await client.call(
                model="claude-sonnet-4-6",
                system="sys",
                messages=[{"role": "user", "content": "trade?"}],
                agent_name="trader",
            )

        assert result.success is False
        assert kimi_mock.await_count == 2  # decision-primary attempt + last-resort retry
        assert client.kimi_fallback_count == 0

    @pytest.mark.asyncio
    async def test_kimi_retry_recovers_after_primary_attempt_failed(self, tmp_path, monkeypatch):
        """A decision agent's Kimi-primary attempt fails transiently, but by
        the time the last-resort leg retries it, Kimi has recovered -- the
        retry rescues the call rather than ending the cascade unhealthy."""
        client = _make_client(
            tmp_path,
            monkeypatch,
            GOOGLE_API_KEY="gemini-key",
            OPENAI_API_KEY="sk-openai-key",
            MOONSHOT_API_KEY="fake-kimi-key",
            JARVIS_DECISION_PRIMARY="kimi-k3",
        )
        client.google_fallback_enabled = True
        client.openai_fallback_enabled = True
        client.kimi_fallback_enabled = True

        kimi_mock = AsyncMock(
            side_effect=[RuntimeError("kimi timeout"), _kimi_response("BUY")]
        )

        with (
            patch.object(client, "_call_with_retry", side_effect=_credit_exhaustion_error()),
            patch.object(client, "_call_google", side_effect=RuntimeError("gemini down")),
            patch.object(client, "_call_openai", side_effect=RuntimeError("openai down")),
            patch.object(client, "_call_kimi", kimi_mock),
        ):
            result = await client.call(
                model="claude-sonnet-4-6",
                system="sys",
                messages=[{"role": "user", "content": "trade?"}],
                agent_name="trader",
            )

        assert result.success is True
        assert result.content == "BUY"
        assert kimi_mock.await_count == 2
        assert client.kimi_fallback_count == 1

    @pytest.mark.asyncio
    async def test_disabled_flag_ends_unhealthy_without_kimi(self, tmp_path, monkeypatch):
        """Key present but JARVIS_LLM_KIMI_FALLBACK=0: Kimi never fires and the
        path ends unhealthy, exactly as before this leg existed."""
        from llm.client import _LLM_PATH_STATE, get_llm_path_state

        _LLM_PATH_STATE["healthy"] = True  # clean start; verify transition to False

        client = _make_client(
            tmp_path,
            monkeypatch,
            GOOGLE_API_KEY="gemini-key",
            OPENAI_API_KEY="sk-openai-key",
            MOONSHOT_API_KEY="fake-kimi-key",
            JARVIS_LLM_KIMI_FALLBACK="0",
        )
        client.google_fallback_enabled = True
        client.openai_fallback_enabled = True
        assert client.kimi_fallback_enabled is False

        kimi_mock = AsyncMock()

        with (
            patch.object(client, "_call_with_retry", side_effect=_credit_exhaustion_error()),
            patch.object(client, "_call_google", side_effect=RuntimeError("gemini down")),
            patch.object(client, "_call_openai", side_effect=RuntimeError("openai down")),
            patch.object(client, "_call_kimi", kimi_mock),
        ):
            result = await client.call(
                model="claude-haiku-4-5-20251001",
                system="sys",
                messages=[{"role": "user", "content": "news?"}],
                agent_name="news_analyst",
            )

        assert result.success is False
        kimi_mock.assert_not_awaited()
        assert get_llm_path_state()["healthy"] is False
