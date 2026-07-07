"""
Test suite for the hard wall-clock ceiling on single LLM provider calls.

Background (2026-06-04): a single technical_analyst Gemini call ran ~3.9h
(logged latency 13981666ms) and froze the entire async pipeline for ~13h of
wall-clock — no scans, no decisions, no trades — because the per-read httpx
timeout never tripped on a stalled connection. The fix wraps every provider
dispatch in JarvisLLMClient.call() with asyncio.wait_for(ceiling), so no single
call can exceed LLM_CALL_HARD_TIMEOUT_SECONDS regardless of transport state.

These tests verify:
  - the ceiling is configurable (env override, invalid/non-positive fallback);
  - _bounded() returns fast results and raises LLMHardTimeoutError on breach,
    cancelling the underlying coroutine;
  - call() does NOT hang when the proactive Gemini path stalls — it times out
    and falls through to the next provider.
"""

import asyncio
import time

import pytest

from llm import JarvisLLMClient
from llm.client import (
    _DEFAULT_LLM_HARD_TIMEOUT_SECONDS,
    LLMHardTimeoutError,
    SimpleNamespace,
)


def _make_client(tmp_path, monkeypatch, **env):
    """Construct a JarvisLLMClient with a clean env (provider=anthropic)."""
    monkeypatch.setenv("JARVIS_LLM_PROVIDER", env.pop("JARVIS_LLM_PROVIDER", "anthropic"))
    monkeypatch.delenv("LLM_CALL_HARD_TIMEOUT_SECONDS", raising=False)
    for key, val in env.items():
        monkeypatch.setenv(key, val)
    db_path = str(tmp_path / "timeout_costs.db")
    return JarvisLLMClient(api_key="test-key-12345", db_path=db_path)


# ── Config parsing ───────────────────────────────────────────────────────────


class TestCeilingConfig:
    def test_default_ceiling(self, tmp_path, monkeypatch):
        client = _make_client(tmp_path, monkeypatch)
        assert client._llm_hard_timeout_seconds == _DEFAULT_LLM_HARD_TIMEOUT_SECONDS

    def test_env_override(self, tmp_path, monkeypatch):
        client = _make_client(tmp_path, monkeypatch, LLM_CALL_HARD_TIMEOUT_SECONDS="45")
        assert client._llm_hard_timeout_seconds == 45.0

    def test_invalid_env_falls_back_to_default(self, tmp_path, monkeypatch):
        client = _make_client(tmp_path, monkeypatch, LLM_CALL_HARD_TIMEOUT_SECONDS="not-a-number")
        assert client._llm_hard_timeout_seconds == _DEFAULT_LLM_HARD_TIMEOUT_SECONDS

    def test_zero_falls_back_to_default(self, tmp_path, monkeypatch):
        client = _make_client(tmp_path, monkeypatch, LLM_CALL_HARD_TIMEOUT_SECONDS="0")
        assert client._llm_hard_timeout_seconds == _DEFAULT_LLM_HARD_TIMEOUT_SECONDS

    def test_negative_falls_back_to_default(self, tmp_path, monkeypatch):
        client = _make_client(tmp_path, monkeypatch, LLM_CALL_HARD_TIMEOUT_SECONDS="-10")
        assert client._llm_hard_timeout_seconds == _DEFAULT_LLM_HARD_TIMEOUT_SECONDS


# ── _bounded() behavior ──────────────────────────────────────────────────────


class TestBounded:
    @pytest.mark.asyncio
    async def test_returns_result_when_fast(self, tmp_path, monkeypatch):
        client = _make_client(tmp_path, monkeypatch)
        client._llm_hard_timeout_seconds = 2.0

        async def quick():
            await asyncio.sleep(0.01)
            return "ok"

        result = await client._bounded(
            quick(), what="unit", model="m", agent_name="a"
        )
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_raises_on_timeout_quickly(self, tmp_path, monkeypatch):
        client = _make_client(tmp_path, monkeypatch)
        client._llm_hard_timeout_seconds = 0.2

        async def hang():
            await asyncio.sleep(30)
            return "never"

        start = time.monotonic()
        with pytest.raises(LLMHardTimeoutError):
            await client._bounded(hang(), what="unit", model="m", agent_name="a")
        elapsed = time.monotonic() - start
        # Must fire near the ceiling, nowhere near the 30s sleep.
        assert elapsed < 3.0

    @pytest.mark.asyncio
    async def test_cancels_underlying_coroutine(self, tmp_path, monkeypatch):
        client = _make_client(tmp_path, monkeypatch)
        client._llm_hard_timeout_seconds = 0.2
        cancelled = {"hit": False}

        async def hang():
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                cancelled["hit"] = True
                raise

        with pytest.raises(LLMHardTimeoutError):
            await client._bounded(hang(), what="unit", model="m", agent_name="a")
        # Give the cancellation a tick to propagate.
        await asyncio.sleep(0.05)
        assert cancelled["hit"] is True

    @pytest.mark.asyncio
    async def test_falls_back_to_module_default_without_init(self):
        """Clients built via __new__ (some tests/low-level callers) still bound."""
        client = JarvisLLMClient.__new__(JarvisLLMClient)  # no __init__
        assert not hasattr(client, "_llm_hard_timeout_seconds")

        async def quick():
            return "ok"

        # Does not raise AttributeError; uses module default ceiling.
        result = await client._bounded(quick(), what="unit", model="m", agent_name="a")
        assert result == "ok"


# ── call() integration: a stuck Gemini primary must not hang ─────────────────


class TestCallDoesNotHang:
    @pytest.mark.asyncio
    async def test_stuck_gemini_primary_times_out_and_falls_through(
        self, tmp_path, monkeypatch
    ):
        client = _make_client(tmp_path, monkeypatch)
        client._llm_hard_timeout_seconds = 0.2
        # Force the proactive-Gemini branch for our agent.
        client.google_fallback_enabled = True
        client.GEMINI_PRIMARY_AGENTS = {"technical_analyst"}

        gemini_started = {"hit": False}

        async def stuck_gemini(*args, **kwargs):
            gemini_started["hit"] = True
            await asyncio.sleep(30)  # simulate the 2026-06-04 hang
            raise AssertionError("should have been cancelled")

        async def fake_anthropic(*args, **kwargs):
            return SimpleNamespace(
                usage=SimpleNamespace(input_tokens=10, output_tokens=5),
                content=[SimpleNamespace(text="anthropic-result")],
            )

        monkeypatch.setattr(client, "_call_google", stuck_gemini)
        monkeypatch.setattr(client, "_call_with_retry", fake_anthropic)

        start = time.monotonic()
        result = await client.call(
            model="claude-haiku-4-5-20251001",
            system="sys",
            messages=[{"role": "user", "content": "hi"}],
            agent_name="technical_analyst",
            compact=False,
        )
        elapsed = time.monotonic() - start

        assert gemini_started["hit"] is True
        assert result.success is True
        assert result.content == "anthropic-result"
        # The whole call must complete near the 0.2s ceiling, not the 30s hang.
        assert elapsed < 5.0
