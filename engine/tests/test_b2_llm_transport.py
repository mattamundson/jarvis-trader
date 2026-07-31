"""
B2 regression (2026-06-10): RiskManagerAgent._llm_review and
FundManagerAgent._llm_approve MUST route through JarvisLLMClient.call()
so the Vertex->Gemini->OpenAI fallback chain applies. Raw httpx POSTs
straight at the Anthropic REST endpoint failed 400 on credit exhaustion.
Fail-safe semantics: risk approves w/ risk_score=0.8 on total failure
(RiskManagerAgent's own internal fallback — unchanged by PRB-11; the
pipeline-level _run_risk_manager wrapper around this agent independently
fails CLOSED on exception, see agents/pipeline.py::_run_risk_manager).
Fund Manager now fails CLOSED (rejects, qty=0) with forced human approval
on total LLM failure (PRB-11, 2026-07-29, mirrors GT-49) — previously it
silently approved at qty<=1, the same fail-open defect class as the
2026-06-15 inert-kill-switch incident.
"""

import inspect
import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.fund_manager import FundManagerAgent  # noqa: E402
from agents.risk_manager import RiskManagerAgent  # noqa: E402
from llm.client import LLMCallResult  # noqa: E402


def _result(success: bool, content: str = "", error: str = "") -> LLMCallResult:
    return LLMCallResult(
        success=success,
        model="gemini-2.5-flash",
        input_tokens=5,
        output_tokens=5,
        cost_usd=0.0,
        latency_ms=3,
        retries=0,
        content=content,
        error=error or None,
    )


def _trade() -> dict:
    return {
        "symbol": "MES",
        "action": "buy",
        "quantity": 1,
        "limit_price": 5800.0,
        "stop_price": 5750.0,
    }


class TestRiskManagerTransport:
    @pytest.mark.asyncio
    async def test_llm_review_routes_through_client(self):
        llm = MagicMock()
        llm.call = AsyncMock(
            return_value=_result(
                True,
                content='{"approved": true, "reasoning": "ok", "risk_score": 0.2}',
            )
        )
        agent = RiskManagerAgent(llm_client=llm)
        decision = await agent._llm_review(_trade(), {}, {})
        assert llm.call.await_count == 1
        kwargs = llm.call.await_args.kwargs
        assert kwargs["agent_name"] == "risk_manager"
        assert kwargs["model"] == RiskManagerAgent.MODEL
        assert decision.approved is True

    @pytest.mark.asyncio
    async def test_llm_review_failure_keeps_failsafe(self):
        """Total LLM failure -> approve conservatively, risk_score 0.8 flag."""
        llm = MagicMock()
        llm.call = AsyncMock(return_value=_result(False, error="credit balance is too low"))
        agent = RiskManagerAgent(llm_client=llm)
        decision = await agent._llm_review(_trade(), {}, {})
        assert decision.approved is True
        assert decision.risk_score == 0.8
        assert "failed" in decision.reasoning.lower()

    def test_no_direct_anthropic_post_in_source(self):
        import agents.risk_manager as mod

        assert "api.anthropic.com" not in inspect.getsource(mod)


class TestFundManagerTransport:
    @pytest.mark.asyncio
    async def test_llm_approve_routes_through_client(self):
        llm = MagicMock()
        llm.call = AsyncMock(
            return_value=_result(
                True,
                content=(
                    '{"approved": true, "final_quantity": 1, "priority": "immediate",'
                    ' "portfolio_impact": "minimal", "reasoning": "ok"}'
                ),
            )
        )
        agent = FundManagerAgent(llm_client=llm)
        decision = await agent._llm_approve(_trade(), {}, {}, [])
        assert llm.call.await_count == 1
        kwargs = llm.call.await_args.kwargs
        assert kwargs["agent_name"] == "fund_manager"
        assert kwargs["model"] == FundManagerAgent.MODEL
        assert decision.approved is True

    @pytest.mark.asyncio
    async def test_llm_approve_failure_fails_closed(self):
        """PRB-11 (2026-07-29, mirrors GT-49): total LLM failure -> REJECTED
        (approved=False, qty=0), not a silent qty<=1 approval. An unreadable/
        failed Fund Manager verdict is an UNKNOWN state, not a safe one —
        forced human approval is still set so the failure surfaces to Matt.
        """
        llm = MagicMock()
        llm.call = AsyncMock(return_value=_result(False, error="credit balance is too low"))
        agent = FundManagerAgent(llm_client=llm)
        decision = await agent._llm_approve(_trade(), {}, {}, [])
        assert decision.approved is False
        assert decision.final_quantity == 0
        assert decision.requires_human_approval is True

    def test_no_direct_anthropic_post_in_source(self):
        import agents.fund_manager as mod

        assert "api.anthropic.com" not in inspect.getsource(mod)
