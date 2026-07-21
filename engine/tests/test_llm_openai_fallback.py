"""
Test suite for the OpenAI last-resort fallback in JarvisLLMClient.

Covers (Phase 3.6, 2026-06-06):
- Flag init: openai_fallback_enabled toggles correctly with key/env.
- OPENAI_FAILOVER_MAP: Opus/Sonnet → gpt-4o, Haiku → gpt-4o-mini.
- _call_openai(): parses the OpenAI choices/usage shape correctly.
- Fallback chain: Anthropic credit-exhaustion → Gemini failure → OpenAI fires.
- Chain short-circuits: Gemini success means OpenAI is never called.
- Cost table: gpt-4o and gpt-4o-mini are priced.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from llm import JarvisLLMClient


def _make_client(tmp_path, monkeypatch, **env):
    """Construct JarvisLLMClient with a controlled env for OpenAI tests."""
    monkeypatch.setenv("JARVIS_LLM_PROVIDER", env.pop("JARVIS_LLM_PROVIDER", "anthropic"))
    for key in (
        "OPENAI_API_KEY",
        "OPENAI_ENDPOINT",
        "JARVIS_LLM_OPENAI_FALLBACK",
        "OPENAI_TIMEOUT_SECONDS",
        "GOOGLE_API_KEY",
        "JARVIS_LLM_GOOGLE_FALLBACK",
        "JARVIS_LLM_VERTEX_FAILOVER",
        "JARVIS_CLAUDE_USE_VERTEX",
        # Kimi is now the final leg after OpenAI (2026-07-21); clear it so a
        # shell with the real Moonshot key loaded can't rescue the
        # "all-fallbacks-exhausted -> unhealthy" case and break this test.
        "MOONSHOT_API_KEY",
        "JARVIS_LLM_KIMI_FALLBACK",
    ):
        monkeypatch.delenv(key, raising=False)
    for key, val in env.items():
        monkeypatch.setenv(key, val)
    db_path = str(tmp_path / "openai_test_costs.db")
    return JarvisLLMClient(api_key="test-anthropic-key", db_path=db_path)


# ── Init / flag tests ─────────────────────────────────────────────────────────


class TestOpenAIFallbackInit:
    def test_disabled_when_no_key(self, tmp_path, monkeypatch):
        client = _make_client(tmp_path, monkeypatch)
        assert client.openai_fallback_enabled is False
        assert client.openai_api_key == ""

    def test_enabled_when_key_present(self, tmp_path, monkeypatch):
        client = _make_client(tmp_path, monkeypatch, OPENAI_API_KEY="sk-test-key")
        assert client.openai_fallback_enabled is True
        assert client.openai_api_key == "sk-test-key"

    def test_disabled_by_flag_zero(self, tmp_path, monkeypatch):
        client = _make_client(
            tmp_path,
            monkeypatch,
            OPENAI_API_KEY="sk-test-key",
            JARVIS_LLM_OPENAI_FALLBACK="0",
        )
        assert client.openai_fallback_enabled is False

    def test_disabled_by_flag_false(self, tmp_path, monkeypatch):
        client = _make_client(
            tmp_path,
            monkeypatch,
            OPENAI_API_KEY="sk-test-key",
            JARVIS_LLM_OPENAI_FALLBACK="false",
        )
        assert client.openai_fallback_enabled is False

    def test_default_endpoint(self, tmp_path, monkeypatch):
        client = _make_client(tmp_path, monkeypatch, OPENAI_API_KEY="sk-x")
        assert "openai.com" in client.openai_endpoint

    def test_custom_endpoint(self, tmp_path, monkeypatch):
        """Azure OpenAI or proxy endpoint override."""
        client = _make_client(
            tmp_path,
            monkeypatch,
            OPENAI_API_KEY="sk-x",
            OPENAI_ENDPOINT="https://my-azure.openai.azure.com/v1/chat/completions",
        )
        assert "azure" in client.openai_endpoint

    def test_fallback_count_starts_at_zero(self, tmp_path, monkeypatch):
        client = _make_client(tmp_path, monkeypatch, OPENAI_API_KEY="sk-x")
        assert client.openai_fallback_count == 0

    def test_ollama_provider_openai_key_still_configures(self, tmp_path, monkeypatch):
        """Ollama provider + OpenAI key: flag is enabled (key present, no override)."""
        client = _make_client(
            tmp_path,
            monkeypatch,
            JARVIS_LLM_PROVIDER="ollama",
            OPENAI_API_KEY="sk-x",
        )
        assert client.openai_fallback_enabled is True


# ── Failover map ──────────────────────────────────────────────────────────────


class TestOpenAIFailoverMap:
    def test_opus_maps_to_gpt4o(self, tmp_path, monkeypatch):
        client = _make_client(tmp_path, monkeypatch)
        assert client.OPENAI_FAILOVER_MAP["claude-opus-4-7"] == "gpt-4o"
        assert client.OPENAI_FAILOVER_MAP["claude-opus-4-6"] == "gpt-4o"

    def test_sonnet_maps_to_gpt4o(self, tmp_path, monkeypatch):
        # Sonnet is a decision-grade tier (trader/risk_manager/debate agents),
        # so it fails over to the equivalent-capability gpt-4o, NOT the cheap
        # gpt-4o-mini tier — matching the OPENAI_FAILOVER_MAP comment and the
        # GOOGLE_FAILOVER_MAP philosophy (Sonnet -> gemini-2.5-pro, the strong tier).
        client = _make_client(tmp_path, monkeypatch)
        assert client.OPENAI_FAILOVER_MAP["claude-sonnet-4-6"] == "gpt-4o"

    def test_haiku_maps_to_gpt4o_mini(self, tmp_path, monkeypatch):
        client = _make_client(tmp_path, monkeypatch)
        assert client.OPENAI_FAILOVER_MAP["claude-haiku-4-5-20251001"] == "gpt-4o-mini"

    def test_unknown_model_defaults_to_mini(self, tmp_path, monkeypatch):
        client = _make_client(tmp_path, monkeypatch)
        assert client.OPENAI_FAILOVER_MAP.get("some-unknown-model", "gpt-4o-mini") == "gpt-4o-mini"


# ── Cost table ────────────────────────────────────────────────────────────────


class TestOpenAICostTable:
    def test_gpt4o_is_priced(self, tmp_path, monkeypatch):
        client = _make_client(tmp_path, monkeypatch)
        assert "gpt-4o" in client.COST_PER_MTOK
        assert client.COST_PER_MTOK["gpt-4o"]["input"] > 0
        assert client.COST_PER_MTOK["gpt-4o"]["output"] > 0

    def test_gpt4o_mini_is_priced(self, tmp_path, monkeypatch):
        client = _make_client(tmp_path, monkeypatch)
        assert "gpt-4o-mini" in client.COST_PER_MTOK
        assert client.COST_PER_MTOK["gpt-4o-mini"]["input"] > 0

    def test_gpt4o_mini_cheaper_than_gpt4o(self, tmp_path, monkeypatch):
        client = _make_client(tmp_path, monkeypatch)
        assert (
            client.COST_PER_MTOK["gpt-4o-mini"]["input"] < client.COST_PER_MTOK["gpt-4o"]["input"]
        )

    def test_context_limits_set(self, tmp_path, monkeypatch):
        client = _make_client(tmp_path, monkeypatch)
        assert client.MODEL_CONTEXT_LIMITS.get("gpt-4o", 0) >= 128_000
        assert client.MODEL_CONTEXT_LIMITS.get("gpt-4o-mini", 0) >= 128_000


# ── _call_openai() unit tests ─────────────────────────────────────────────────


class TestCallOpenAI:
    @pytest.mark.asyncio
    async def test_parses_choices_and_usage(self, tmp_path, monkeypatch):
        client = _make_client(tmp_path, monkeypatch, OPENAI_API_KEY="sk-x")

        fake_response = MagicMock()
        fake_response.status_code = 200
        fake_response.json.return_value = {
            "choices": [{"message": {"content": "Signal: LONG"}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50},
        }
        fake_response.raise_for_status = MagicMock()

        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.post = AsyncMock(return_value=fake_response)

        with patch("llm.client.httpx.AsyncClient", return_value=mock_http):
            result = await client._call_openai(
                system="You are a trading analyst.",
                messages=[{"role": "user", "content": "Analyze MES."}],
                max_tokens=256,
                temperature=0.7,
                model="gpt-4o-mini",
            )

        assert result.content[0].text == "Signal: LONG"
        assert result.usage.input_tokens == 100
        assert result.usage.output_tokens == 50

    @pytest.mark.asyncio
    async def test_raises_when_no_key(self, tmp_path, monkeypatch):
        client = _make_client(tmp_path, monkeypatch)  # no OPENAI_API_KEY
        with pytest.raises(RuntimeError, match="openai_api_key not configured"):
            await client._call_openai(
                system="sys", messages=[], max_tokens=64, temperature=0.5, model="gpt-4o-mini"
            )

    @pytest.mark.asyncio
    async def test_raises_on_empty_choices(self, tmp_path, monkeypatch):
        client = _make_client(tmp_path, monkeypatch, OPENAI_API_KEY="sk-x")

        fake_response = MagicMock()
        fake_response.status_code = 200
        fake_response.json.return_value = {"choices": [], "usage": {}}
        fake_response.raise_for_status = MagicMock()

        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.post = AsyncMock(return_value=fake_response)

        with patch("llm.client.httpx.AsyncClient", return_value=mock_http):
            with pytest.raises(RuntimeError, match="missing choices"):
                await client._call_openai(
                    system="sys", messages=[], max_tokens=64, temperature=0.5, model="gpt-4o-mini"
                )

    @pytest.mark.asyncio
    async def test_system_added_as_first_message(self, tmp_path, monkeypatch):
        client = _make_client(tmp_path, monkeypatch, OPENAI_API_KEY="sk-x")
        captured_payload = {}

        async def fake_post(url, json=None, headers=None):
            captured_payload.update(json or {})
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            }
            resp.raise_for_status = MagicMock()
            return resp

        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.post = fake_post

        with patch("llm.client.httpx.AsyncClient", return_value=mock_http):
            await client._call_openai(
                system="Trade carefully.",
                messages=[{"role": "user", "content": "go"}],
                max_tokens=64,
                temperature=0.5,
                model="gpt-4o-mini",
            )

        assert captured_payload["messages"][0] == {
            "role": "system",
            "content": "Trade carefully.",
        }
        assert captured_payload["messages"][1] == {"role": "user", "content": "go"}


# ── Fallback chain integration ────────────────────────────────────────────────


def _credit_exhaustion_error():
    """Return the exception that the fixed _call_with_retry raises on credit exhaustion.

    _call_with_retry wraps APIStatusError(credit_balance_too_low) as a plain
    Exception so call()'s `except Exception` block triggers the fallback chain
    rather than the retry-then-tier-downgrade path.
    """
    return Exception("Your credit balance is too low to complete this request.")


class TestOpenAIFallbackChain:
    @pytest.mark.asyncio
    async def test_openai_fires_when_anthropic_and_gemini_both_fail(self, tmp_path, monkeypatch):
        """Full chain: Anthropic credit-exhaustion → Gemini exception → OpenAI succeeds."""
        client = _make_client(
            tmp_path,
            monkeypatch,
            GOOGLE_API_KEY="gemini-key",
            OPENAI_API_KEY="sk-openai-key",
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
    async def test_openai_not_called_when_gemini_succeeds(self, tmp_path, monkeypatch):
        """If Gemini succeeds, OpenAI must not be called."""
        client = _make_client(
            tmp_path,
            monkeypatch,
            GOOGLE_API_KEY="gemini-key",
            OPENAI_API_KEY="sk-openai-key",
        )
        client.google_fallback_enabled = True
        client.openai_fallback_enabled = True

        gemini_ns = SimpleNamespace(
            usage=SimpleNamespace(input_tokens=60, output_tokens=30),
            content=[SimpleNamespace(text="HOLD")],
        )

        openai_mock = AsyncMock()

        with (
            patch.object(client, "_call_with_retry", side_effect=_credit_exhaustion_error()),
            patch.object(client, "_call_google", AsyncMock(return_value=gemini_ns)),
            patch.object(client, "_call_openai", openai_mock),
        ):
            result = await client.call(
                model="claude-sonnet-4-6",
                system="sys",
                messages=[{"role": "user", "content": "signal?"}],
                agent_name="trader",
            )

        assert result.success is True
        openai_mock.assert_not_called()
        assert client.openai_fallback_count == 0

    @pytest.mark.asyncio
    async def test_openai_disabled_path_marks_unhealthy(self, tmp_path, monkeypatch):
        """With no OpenAI key, all fallbacks exhausted → llm path marked unhealthy."""
        from llm.client import _LLM_PATH_STATE, get_llm_path_state

        _LLM_PATH_STATE["healthy"] = True  # ensure clean start; test verifies transition to False

        client = _make_client(
            tmp_path,
            monkeypatch,
            GOOGLE_API_KEY="gemini-key",
            # No OPENAI_API_KEY
        )
        client.google_fallback_enabled = True
        assert client.openai_fallback_enabled is False

        with (
            patch.object(client, "_call_with_retry", side_effect=_credit_exhaustion_error()),
            patch.object(client, "_call_google", side_effect=RuntimeError("Gemini down")),
        ):
            result = await client.call(
                model="claude-sonnet-4-6",
                system="sys",
                messages=[{"role": "user", "content": "signal?"}],
                agent_name="trader",
            )

        assert result.success is False
        state = get_llm_path_state()
        assert state["healthy"] is False
