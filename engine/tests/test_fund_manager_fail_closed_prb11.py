"""
PRB-11 (2026-07-29): FundManagerAgent fails OPEN on exception (approved qty=1).

Same fail-open defect class as GT-49 (safety_layer.py's per-account kill-state
fix, PR #526): an exception during Fund Manager approval is an UNKNOWN
portfolio-level verdict, not evidence a trade is safe. "Unknown state" must
never resolve to "safe to trade."

Two independent fail-open sites existed and are both covered here:
  1. agents/fund_manager.py::FundManagerAgent._llm_approve's except block --
     an LLM/parse failure previously returned approved=True, final_quantity=1.
  2. agents/pipeline.py::TradingPipeline._run_fund_manager's except block --
     the real-caller wrapper around fund_manager.approve() had the identical
     defect for exceptions raised outside _llm_approve's own try (e.g. a
     malformed trade/risk decision dict).

Mirrors test_risk_safety_per_account.py::
test_db_exception_makes_real_caller_treat_account_as_halted -- traces the fix
from the low-level function up through the actual caller order-emission
paths use, not just the raw dict shape.
"""

from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.fund_manager import FundManagerAgent  # noqa: E402
from agents.pipeline import TradingPipeline  # noqa: E402


def _trade(symbol: str = "AAPL", action: str = "buy", quantity: int = 5) -> dict:
    return {
        "symbol": symbol,
        "action": action,
        "quantity": quantity,
        "limit_price": 200.0,
        "confidence": 0.8,
        "signal_score": 0.7,
    }


def _risk_approved(quantity: int = 5) -> dict:
    return {"approved": True, "modified_quantity": quantity, "reasoning": "ok"}


class TestLLMApproveExceptionFailsClosed:
    """FundManagerAgent._llm_approve's own except block (the site named in
    PRB-11's task description)."""

    @pytest.mark.asyncio
    async def test_llm_raises_returns_rejected_decision(self):
        llm = MagicMock()
        llm.call = AsyncMock(side_effect=RuntimeError("LLM transport dead"))
        agent = FundManagerAgent(llm_client=llm)

        decision = await agent._llm_approve(_trade(), _risk_approved(), {}, [])

        assert decision.approved is False
        assert decision.final_quantity == 0
        assert decision.priority == "skip"
        assert decision.requires_human_approval is True
        assert "LLM transport dead" in decision.reasoning

    @pytest.mark.asyncio
    async def test_unparseable_llm_response_returns_rejected_decision(self):
        """A malformed/unparseable LLM response (parse_llm_json raising
        LLMJsonError) is the same unknown-state class as a transport
        exception -- must also fail closed, not just raw connection errors.
        """
        from llm.client import LLMCallResult

        llm = MagicMock()
        llm.call = AsyncMock(
            return_value=LLMCallResult(
                success=True,
                model="gemini-2.5-flash",
                input_tokens=5,
                output_tokens=5,
                cost_usd=0.0,
                latency_ms=3,
                retries=0,
                content="not json at all, no braces here",
                error=None,
            )
        )
        agent = FundManagerAgent(llm_client=llm)

        decision = await agent._llm_approve(_trade(), _risk_approved(), {}, [])

        assert decision.approved is False
        assert decision.final_quantity == 0


class TestRealCallerApproveTreatsExceptionAsRejected:
    """Real-caller trace (PRB-11, mirrors GT-49's
    test_db_exception_makes_real_caller_treat_account_as_halted): the
    FundManagerAgent.approve() method is what TradingPipeline._run_fund_manager
    actually calls (see agents/pipeline.py:2129). Before the fix, an LLM
    exception here would have produced approved=True at qty=1 -- i.e. an
    unreadable Fund Manager verdict would have let the trade proceed. After
    the fix it must reject.
    """

    @pytest.mark.asyncio
    async def test_llm_exception_makes_real_caller_reject_the_trade(self):
        llm = MagicMock()
        llm.call = AsyncMock(side_effect=RuntimeError("LLM transport dead"))
        agent = FundManagerAgent(llm_client=llm)

        decision = await agent.approve(
            trade_decision=_trade(),
            risk_decision=_risk_approved(),
            portfolio={"total_value": 10_000.0, "available_cash": 5_000.0},
            open_positions=[],
        )

        assert decision.approved is False, (
            "FundManagerAgent.approve() must fail CLOSED (reject the trade) "
            "when the underlying LLM call raises, not fail open"
        )
        assert decision.final_quantity == 0

    @pytest.mark.asyncio
    async def test_fails_closed_regardless_of_require_human_approval_flag(self, monkeypatch):
        """PRB-11 explicitly flagged: this fail-open path was previously
        gated only by REQUIRE_HUMAN_APPROVAL. Prove the fix does NOT depend
        on that flag -- fails closed whether it's True or False, since
        requires_human_approval is a separate, orthogonal concern from
        approved/final_quantity (and, per signal_scanner.py's paper-mode
        bypass, REQUIRE_HUMAN_APPROVAL does not even gate auto-executed
        paper trades in this repo's current production configuration).
        """
        from config import settings as _cfg

        monkeypatch.setattr(_cfg, "REQUIRE_HUMAN_APPROVAL", False, raising=False)

        llm = MagicMock()
        llm.call = AsyncMock(side_effect=RuntimeError("LLM transport dead"))
        agent = FundManagerAgent(llm_client=llm)

        decision = await agent.approve(
            trade_decision=_trade(),
            risk_decision=_risk_approved(),
            portfolio={},
            open_positions=[],
        )

        assert decision.approved is False


class TestPipelineRunFundManagerWrapperFailsClosed:
    """The pipeline-level wrapper (_run_fund_manager) is a second,
    independent fail-open site guarding exceptions raised outside
    FundManagerAgent._llm_approve's own try block (e.g. a malformed
    trade/risk decision reaching fund_manager.approve() itself). Must
    independently fail closed even with fund_manager.py's own fix in place.
    """

    @pytest.fixture
    def pipeline(self):
        safety = MagicMock()
        safety.get_status.return_value = {"kill_switch_active": False}
        fund_manager = MagicMock()
        fund_manager.approve = AsyncMock(side_effect=RuntimeError("unexpected approve() failure"))
        return TradingPipeline(
            agents={"fund_manager": fund_manager}, safety_layer=safety, db_manager=None
        )

    @pytest.mark.asyncio
    async def test_exception_in_run_fund_manager_returns_rejected_dict(self, pipeline):
        errors: list = []
        fund_decision = await pipeline._run_fund_manager(
            trade_decision=_trade(),
            risk_decision=_risk_approved(),
            portfolio={},
            open_positions=[],
            errors=errors,
        )

        assert fund_decision["approved"] is False
        assert fund_decision["final_quantity"] == 0
        assert fund_decision["requires_human_approval"] is True
        assert errors  # the stage failure is still recorded for visibility

    @pytest.mark.asyncio
    async def test_rejected_dict_resolves_to_hold_for_non_bypass_symbol(self, pipeline):
        """Full loop: the fail-closed dict this wrapper now returns must
        actually resolve to a HOLD via _resolve_final_action for a symbol
        NOT in FUND_MANAGER_BYPASS_SYMBOLS (e.g. AAPL) -- proving the fix
        actually blocks order emission, not just changes a dict's shape.
        """
        errors: list = []
        trade = _trade(symbol="AAPL")
        risk = _risk_approved()
        fund_decision = await pipeline._run_fund_manager(
            trade_decision=trade,
            risk_decision=risk,
            portfolio={},
            open_positions=[],
            errors=errors,
        )
        action, qty, human = pipeline._resolve_final_action(trade, risk, fund_decision)

        assert action == "hold"
        assert qty == 0


class TestFundManagerBypassSymbolsBlastRadius:
    """PRB-11 context finding: MES bypasses Fund Manager review entirely via
    FUND_MANAGER_BYPASS_SYMBOLS. Confirms this fix's blast radius does NOT
    include MES -- _resolve_final_action ignores fund_decision entirely for
    bypass symbols and uses risk_decision directly, even when fund_decision
    is the fail-closed (rejected) dict this PR now produces. MES's own
    exposure to a fund-manager-stage bug is therefore already zero,
    independent of whether that stage fails open or closed.
    """

    @pytest.fixture
    def pipeline(self):
        safety = MagicMock()
        safety.get_status.return_value = {"kill_switch_active": False}
        return TradingPipeline(agents={}, safety_layer=safety, db_manager=None)

    def test_mes_ignores_fund_decision_even_when_rejected(self, pipeline):
        assert "MES" in pipeline.FUND_MANAGER_BYPASS_SYMBOLS
        trade = _trade(symbol="MES", quantity=2)
        risk = _risk_approved(quantity=2)
        # The exact fail-closed shape _run_fund_manager now returns on exception.
        rejected_fund_decision = {
            "approved": False,
            "final_quantity": 0,
            "priority": "skip",
            "requires_human_approval": True,
        }

        action, qty, human = pipeline._resolve_final_action(trade, risk, rejected_fund_decision)

        # MES bypasses fund_manager review -- risk-approved qty goes through
        # regardless of what fund_decision says (approved=False here would
        # have HELD a non-bypass symbol, per TestPipelineRunFundManagerWrapperFailsClosed).
        assert action == "buy"
        assert qty == 2
        assert human is False
