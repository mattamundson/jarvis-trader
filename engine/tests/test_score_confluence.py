"""
Regression tests for DebateOrchestrator._score_confluence's LLM routing.

_score_confluence previously bypassed the multi-provider model_router and
called a hardcoded raw Anthropic client directly. Any Anthropic-specific
failure (e.g. credit exhaustion) silently forced every debate to
INCONCLUSIVE/all-zero scores regardless of the real bull/bear scoring,
even while the rest of the pipeline (already routed through
_call_agent_llm / model_router) stayed healthy. The fix routes
_score_confluence through _call_agent_llm, the same provider-routed helper
_score_argument/_rebuttal already use.

These tests pin two behaviors:
  1. _score_confluence calls _call_agent_llm(agent, prompt) — not a raw
     Anthropic client — so it inherits the multi-provider fallback chain.
  2. The safe INCONCLUSIVE/all-zero fallback on failure is unchanged.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.debate import DebateOrchestrator  # noqa: E402

_DIMENSIONS = ("trend", "mean_rev", "breakout", "volatility", "macro", "sentiment")


class _FakeAgent:
    """Minimal stand-in exposing the _call_llm coroutine _call_agent_llm looks for first."""

    def __init__(self, response: str | None = None, raises: Exception | None = None):
        self._response = response
        self._raises = raises
        self.prompts_seen: list[str] = []

    async def _call_llm(self, prompt: str) -> str:
        self.prompts_seen.append(prompt)
        if self._raises is not None:
            raise self._raises
        return self._response


class TestScoreConfluenceRouting:
    @pytest.fixture
    def orch(self):
        return DebateOrchestrator()

    @pytest.mark.asyncio
    async def test_routes_through_call_agent_llm_not_raw_client(self, orch, monkeypatch):
        """_score_confluence must call the shared _call_agent_llm helper, passing the agent through."""
        calls = []

        async def fake_call_agent_llm(agent, prompt):
            calls.append((agent, prompt))
            return '{"direction": "BULL", "scores": {"trend": 0.8}}'

        monkeypatch.setattr("agents.debate._call_agent_llm", fake_call_agent_llm)

        sentinel_agent = object()
        direction, scores = await orch._score_confluence(
            sentinel_agent, "bull case text", "bear case text", {}
        )

        assert len(calls) == 1
        assert calls[0][0] is sentinel_agent
        assert direction == "BULL"
        assert scores["trend"] == 0.8

    @pytest.mark.asyncio
    async def test_directional_response_produces_real_nonzero_scores(self, orch):
        """A genuinely directional agent response must not collapse to INCONCLUSIVE/0.0."""
        agent = _FakeAgent(
            response=(
                '{"direction": "BEAR", "scores": {'
                '"trend": 0.7, "mean_rev": 0.3, "breakout": 0.6, '
                '"volatility": 0.5, "macro": 0.65, "sentiment": 0.8}}'
            )
        )

        direction, scores = await orch._score_confluence(agent, "bull case", "bear case", {})

        assert direction == "BEAR"
        assert set(scores.keys()) == set(_DIMENSIONS)
        assert all(scores[dim] > 0.0 for dim in _DIMENSIONS)
        # The fake agent's own _call_llm was actually invoked (proves the
        # agent-routed path ran, not a bypassed/mocked-away call).
        assert len(agent.prompts_seen) == 1

    @pytest.mark.asyncio
    async def test_agent_llm_failure_falls_back_to_safe_inconclusive(self, orch):
        """If _call_agent_llm raises (e.g. every provider in the chain fails), the
        original safe fallback — INCONCLUSIVE + all-zero scores — must be preserved."""
        agent = _FakeAgent(raises=RuntimeError("all providers exhausted"))

        direction, scores = await orch._score_confluence(agent, "bull case", "bear case", {})

        assert direction == "INCONCLUSIVE"
        assert scores == dict.fromkeys(_DIMENSIONS, 0.0)

    @pytest.mark.asyncio
    async def test_malformed_json_response_falls_back_to_safe_inconclusive(self, orch):
        """A non-JSON / garbage response from the LLM must not crash — same safe fallback."""
        agent = _FakeAgent(response="not valid json at all")

        direction, scores = await orch._score_confluence(agent, "bull case", "bear case", {})

        assert direction == "INCONCLUSIVE"
        assert scores == dict.fromkeys(_DIMENSIONS, 0.0)
