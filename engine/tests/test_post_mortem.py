"""
Regression tests for PostTradeAnalyzer.analyze_trade's LLM routing.

analyze_trade() previously bypassed JarvisLLMClient.call() and hit the raw
Anthropic SDK client directly (self.llm.client.messages.create(...)), the
same bug class found in DebateOrchestrator._score_confluence: any
Anthropic-specific failure (credit exhaustion, rate limit) failed the
post-mortem outright instead of failing over to Gemini/OpenAI via .call()'s
built-in provider chain. No coverage existed for this function before.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.post_mortem import PostTradeAnalyzer  # noqa: E402
from llm.client import LLMCallResult  # noqa: E402


def _result(success=True, content="", error=None):
    return LLMCallResult(
        success=success,
        model="claude-sonnet-4-6",
        input_tokens=10,
        output_tokens=10,
        cost_usd=0.001,
        latency_ms=100,
        retries=0,
        content=content,
        error=error,
    )


class _FakeLLMClient:
    def __init__(self, result=None, raises=None):
        self._result = result
        self._raises = raises
        self.calls = []

    async def call(self, **kwargs):
        self.calls.append(kwargs)
        if self._raises is not None:
            raise self._raises
        return self._result


_TRADE = {
    "symbol": "MES",
    "side": "long",
    "quantity": 1,
    "entry_price": 5300.0,
    "exit_price": 5320.0,
    "pnl": 100.0,
    "exit_reason": "target",
}


class TestAnalyzeTradeRouting:
    @pytest.mark.asyncio
    async def test_routes_through_call_not_raw_client(self):
        """analyze_trade must call llm.call(...), never llm.client.messages.create(...)."""
        fake = _FakeLLMClient(
            result=_result(content='{"analysis": "x", "what_worked": "y", "what_failed": "z", "lesson": "w"}')
        )
        analyzer = PostTradeAnalyzer(db_manager=None, llm_client=fake)

        await analyzer.analyze_trade("t1", _TRADE, {})

        assert len(fake.calls) == 1
        assert fake.calls[0]["agent_name"] == "post_mortem"

    @pytest.mark.asyncio
    async def test_successful_analysis_returns_parsed_fields(self):
        fake = _FakeLLMClient(
            result=_result(
                content=(
                    '{"analysis": "Trend followed through", "what_worked": "entry timing", '
                    '"what_failed": "none", "lesson": "hold longer"}'
                )
            )
        )
        analyzer = PostTradeAnalyzer(db_manager=None, llm_client=fake)

        result = await analyzer.analyze_trade("t1", _TRADE, {})

        assert result["analysis"] == "Trend followed through"
        assert result["lesson"] == "hold longer"
        assert "error" not in result

    @pytest.mark.asyncio
    async def test_llm_call_failure_returns_safe_error_dict(self):
        """When .call() reports success=False (e.g. every provider in the
        fallback chain failed), the original safe {"error": ...} contract
        must be preserved -- never raise out of analyze_trade."""
        fake = _FakeLLMClient(result=_result(success=False, error="all providers exhausted"))
        analyzer = PostTradeAnalyzer(db_manager=None, llm_client=fake)

        result = await analyzer.analyze_trade("t1", _TRADE, {})

        assert "error" in result

    @pytest.mark.asyncio
    async def test_malformed_json_response_returns_safe_error_dict(self):
        fake = _FakeLLMClient(result=_result(content="not valid json at all"))
        analyzer = PostTradeAnalyzer(db_manager=None, llm_client=fake)

        result = await analyzer.analyze_trade("t1", _TRADE, {})

        assert "error" in result

    @pytest.mark.asyncio
    async def test_call_raising_returns_safe_error_dict(self):
        fake = _FakeLLMClient(raises=RuntimeError("connection reset"))
        analyzer = PostTradeAnalyzer(db_manager=None, llm_client=fake)

        result = await analyzer.analyze_trade("t1", _TRADE, {})

        assert "error" in result
