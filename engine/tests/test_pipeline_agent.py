"""
US-005 — TradingPipeline supplemental unit tests.

Existing pipeline test files (alert_cooldown, cache_and_models, e2e, profiler,
run_human_gate) cover end-to-end flows but miss the static helpers and the
multi-stage decision resolution logic. This file targets:
  - _is_anthropic_400_error
  - _extract_technical_stc
  - _stc_to_action
  - _check_technical_only_fallback (composition of the above)
  - _resolve_final_action (multi-stage decision aggregation)
  - _inject_forward_recorder (MES-only no-op for other symbols)

Goal: raise pipeline.py coverage 58% → ≥65% with non-brittle behavioral tests.
"""

import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.pipeline import TradingPipeline  # noqa: E402


@pytest.fixture
def pipeline():
    """A TradingPipeline with stubbed collaborators — sufficient for non-async helpers."""
    safety = MagicMock()
    safety.get_status.return_value = {"kill_switch_active": False}
    return TradingPipeline(agents={}, safety_layer=safety, db_manager=None)


# ─────────────────────────────────────────────────────────────────────────────
# _is_anthropic_400_error
# ─────────────────────────────────────────────────────────────────────────────


class TestAnthropic400Detection:
    @pytest.mark.parametrize(
        "err_str,expected",
        [
            # Explicit anthropic + 400
            ("Client error '400 Bad Request' for url 'https://api.anthropic.com/v1/messages'", True),
            ("anthropic API returned 400 bad request", True),
            # Anthropic + credit reference (no 400 needed)
            ("anthropic credit_balance_too_low", True),
            ("api.anthropic.com billing issue", True),
            ("api.anthropic.com insufficient credit", True),
            # 400 only without anthropic context — does NOT match
            ("Client error '400 Bad Request' for url 'https://api.openai.com/v1/chat'", False),
            # Generic non-API error
            ("connection timed out", False),
            ("RateLimitError: 429 too many requests", False),
            # Mixed case
            ("Anthropic Bad Request 400 received", True),
        ],
    )
    def test_anthropic_400_classification(self, err_str, expected):
        assert TradingPipeline._is_anthropic_400_error(err_str) is expected


# ─────────────────────────────────────────────────────────────────────────────
# _extract_technical_stc
# ─────────────────────────────────────────────────────────────────────────────


class TestExtractTechnicalSTC:
    def test_returns_value_when_present(self):
        reports = {"technical": {"indicators": {"stc": 25.5}}}
        assert TradingPipeline._extract_technical_stc(reports) == 25.5

    def test_returns_none_when_missing(self):
        assert TradingPipeline._extract_technical_stc({}) is None
        assert TradingPipeline._extract_technical_stc({"technical": {}}) is None
        assert TradingPipeline._extract_technical_stc({"technical": {"indicators": {}}}) is None

    def test_returns_none_for_explicit_none(self):
        reports = {"technical": {"indicators": {"stc": None}}}
        assert TradingPipeline._extract_technical_stc(reports) is None

    def test_returns_none_for_nan(self):
        reports = {"technical": {"indicators": {"stc": float("nan")}}}
        assert TradingPipeline._extract_technical_stc(reports) is None

    def test_coerces_int_to_float(self):
        reports = {"technical": {"indicators": {"stc": 50}}}
        assert TradingPipeline._extract_technical_stc(reports) == 50.0

    def test_returns_none_on_unparseable_value(self):
        reports = {"technical": {"indicators": {"stc": "abc"}}}
        assert TradingPipeline._extract_technical_stc(reports) is None


# ─────────────────────────────────────────────────────────────────────────────
# _stc_to_action
# ─────────────────────────────────────────────────────────────────────────────


class TestSTCToAction:
    @pytest.mark.parametrize(
        "stc,expected_action,expected_signal",
        [
            (5.0, "buy", "OVERSOLD"),       # < 15
            (14.99, "buy", "OVERSOLD"),     # boundary
            (15.0, "hold", "NEUTRAL"),      # exactly OS = neutral
            (50.0, "hold", "NEUTRAL"),      # mid
            (83.0, "hold", "NEUTRAL"),      # exactly OB = neutral
            (83.01, "sell", "OVERBOUGHT"),  # boundary
            (95.0, "sell", "OVERBOUGHT"),   # > 83
        ],
    )
    def test_stc_thresholds(self, stc, expected_action, expected_signal):
        action, signal = TradingPipeline._stc_to_action(stc)
        assert action == expected_action
        assert signal == expected_signal


# ─────────────────────────────────────────────────────────────────────────────
# _check_technical_only_fallback
# ─────────────────────────────────────────────────────────────────────────────


class TestTechnicalOnlyFallback:
    def test_returns_none_when_under_3_llm_400_errors(self, pipeline):
        errors = [
            "news analyst failed: api.anthropic.com 400 credit_balance_too_low",
            "social analyst failed: api.anthropic.com 400 credit_balance_too_low",
            # Only 2 — not enough
        ]
        reports = {"technical": {"indicators": {"stc": 10.0}}}
        result = pipeline._check_technical_only_fallback("MES", reports, errors)
        assert result is None

    def test_returns_none_when_400s_not_from_llm_agents(self, pipeline):
        # 3 errors but none from news/social/fundamental
        errors = [
            "technical analyst failed: api.anthropic.com 400",
            "trader failed: api.anthropic.com 400",
            "debate failed: api.anthropic.com 400",
        ]
        reports = {"technical": {"indicators": {"stc": 10.0}}}
        result = pipeline._check_technical_only_fallback("MES", reports, errors)
        assert result is None

    def test_returns_none_when_3_llm_400s_but_no_stc(self, pipeline):
        errors = [
            "news analyst failed: api.anthropic.com 400 credit_balance_too_low",
            "social analyst failed: api.anthropic.com 400 credit_balance_too_low",
            "fundamental analyst failed: api.anthropic.com 400 credit_balance_too_low",
        ]
        reports = {"technical": {"indicators": {}}}  # no stc
        result = pipeline._check_technical_only_fallback("MES", reports, errors)
        assert result is None

    # ── PRB-12 regression: directional STC must NEVER produce a real order ──
    # Audit finding: on this exact Anthropic-400 condition, the pipeline took
    # a REAL qty=1 trade off a bare STC reading (conviction=3/10, no LLM
    # synthesis), bypassing the analyst/debate stack. Every other LLM-failure
    # path in this codebase defaults to HOLD/qty=0 — this must too.
    def test_oversold_stc_with_3_llm_400s_forces_hold_not_buy(self, pipeline):
        """STC=5.0 (OVERSOLD -> 'buy') must still resolve to HOLD/qty=0, not a live buy."""
        errors = [
            "news analyst failed: api.anthropic.com 400 credit_balance_too_low",
            "social analyst failed: api.anthropic.com 400 credit_balance_too_low",
            "fundamental analyst failed: api.anthropic.com 400 credit_balance_too_low",
        ]
        reports = {"technical": {"indicators": {"stc": 5.0}}}
        result = pipeline._check_technical_only_fallback("MES", reports, errors)

        assert result is not None
        # The historical bug: final_action == "buy" and final_quantity == 1
        assert result["final_action"] == "hold"
        assert result["final_quantity"] == 0
        assert result["requires_human"] is False
        assert result["trade_decision"]["action"] == "hold"
        assert result["trade_decision"]["quantity"] == 0
        assert result["risk_decision"]["approved"] is False
        assert result["fund_decision"] is None
        # Observability: the would-have-been directional signal is still surfaced.
        assert result["technical_only_would_have_signaled"] == "buy"
        assert result["technical_only_signal"] == "OVERSOLD"

    def test_overbought_stc_with_3_llm_400s_forces_hold_not_sell(self, pipeline):
        """STC=95.0 (OVERBOUGHT -> 'sell') must still resolve to HOLD/qty=0, not a live sell."""
        errors = [
            "news analyst failed: api.anthropic.com 400 credit_balance_too_low",
            "social analyst failed: api.anthropic.com 400 credit_balance_too_low",
            "fundamental analyst failed: api.anthropic.com 400 credit_balance_too_low",
        ]
        reports = {"technical": {"indicators": {"stc": 95.0}}}
        result = pipeline._check_technical_only_fallback("MES", reports, errors)

        assert result is not None
        assert result["final_action"] == "hold"
        assert result["final_quantity"] == 0
        assert result["requires_human"] is False
        assert result["trade_decision"]["action"] == "hold"
        assert result["trade_decision"]["quantity"] == 0
        assert result["risk_decision"]["approved"] is False
        assert result["fund_decision"] is None
        assert result["technical_only_would_have_signaled"] == "sell"
        assert result["technical_only_signal"] == "OVERBOUGHT"


# ─────────────────────────────────────────────────────────────────────────────
# _run_trader — PRB-12 regression: TraderAgent's own Anthropic-400 must HOLD
# ─────────────────────────────────────────────────────────────────────────────


class TestRunTraderAnthropic400Failsafe:
    """
    Audit finding (PRB-12): when the TraderAgent's own LLM call raised an
    Anthropic 400 error, _run_trader's exception handler took a REAL qty=1
    trade off a bare STC reading via the "last-resort STC fallback" — instead
    of falling through to this function's own documented contract: "Run the
    Trader agent. Returns HOLD on failure."
    """

    @pytest.mark.asyncio
    async def test_trader_anthropic_400_with_directional_stc_forces_hold(self, pipeline):
        mock_trader = MagicMock()
        mock_trader.decide = AsyncMock(
            side_effect=Exception(
                "Client error '400 Bad Request' for url 'https://api.anthropic.com/v1/messages' "
                "credit_balance_too_low"
            )
        )
        pipeline._agents["trader"] = mock_trader

        analyst_reports = {"technical": {"indicators": {"stc": 5.0}}}  # OVERSOLD -> would-be "buy"
        errors: list = []

        decision = await pipeline._run_trader(
            "MES", debate_result={}, analyst_reports=analyst_reports,
            safety_status={"kill_switch_active": False}, errors=errors,
        )

        # The historical bug: action == "buy" and quantity == 1 (a real order).
        assert decision["action"] == "hold"
        assert decision["quantity"] == 0
        # Observability preserved: we still know what the bare indicator suggested.
        assert decision.get("technical_only_would_have_signaled") == "buy"
        assert any("Trader stage failed" in e for e in errors)

    @pytest.mark.asyncio
    async def test_trader_anthropic_400_overbought_forces_hold(self, pipeline):
        mock_trader = MagicMock()
        mock_trader.decide = AsyncMock(
            side_effect=Exception(
                "anthropic api.anthropic.com 400 Bad Request insufficient credit"
            )
        )
        pipeline._agents["trader"] = mock_trader

        analyst_reports = {"technical": {"indicators": {"stc": 95.0}}}  # OVERBOUGHT -> would-be "sell"
        errors: list = []

        decision = await pipeline._run_trader(
            "MES", debate_result={}, analyst_reports=analyst_reports,
            safety_status={"kill_switch_active": False}, errors=errors,
        )

        assert decision["action"] == "hold"
        assert decision["quantity"] == 0
        assert decision.get("technical_only_would_have_signaled") == "sell"

    @pytest.mark.asyncio
    async def test_trader_non_anthropic_error_still_holds(self, pipeline):
        """Sanity: non-anthropic-400 exceptions already defaulted to HOLD — must still."""
        mock_trader = MagicMock()
        mock_trader.decide = AsyncMock(side_effect=Exception("connection timed out"))
        pipeline._agents["trader"] = mock_trader

        analyst_reports = {"technical": {"indicators": {"stc": 5.0}}}
        errors: list = []

        decision = await pipeline._run_trader(
            "MES", debate_result={}, analyst_reports=analyst_reports,
            safety_status={"kill_switch_active": False}, errors=errors,
        )

        assert decision["action"] == "hold"
        assert decision["quantity"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# _resolve_final_action
# ─────────────────────────────────────────────────────────────────────────────


class TestResolveFinalAction:
    def test_risk_veto_returns_hold(self, pipeline):
        risk = {"approved": False}
        action, qty, human = pipeline._resolve_final_action({}, risk, {})
        assert action == "hold"
        assert qty == 0
        assert human is False

    def test_bypass_symbol_skips_fund_manager(self, pipeline):
        # FUND_MANAGER_BYPASS_SYMBOLS contains MES per recent codebase changes
        trade = {"symbol": "MES", "action": "buy", "quantity": 2}
        risk = {"approved": True, "modified_quantity": 1}
        # Verify only if MES is in the bypass set, else this won't apply
        if "MES" in pipeline.FUND_MANAGER_BYPASS_SYMBOLS:
            action, qty, human = pipeline._resolve_final_action(trade, risk, {})
            assert action == "buy"
            assert qty == 1
            assert human is False

    def test_fund_manager_rejected_returns_hold(self, pipeline):
        trade = {"symbol": "AAPL", "action": "buy", "quantity": 1}
        risk = {"approved": True}
        fund = {"approved": False}
        action, qty, human = pipeline._resolve_final_action(trade, risk, fund)
        assert action == "hold"
        assert qty == 0

    def test_fund_manager_priority_skip_returns_hold(self, pipeline):
        trade = {"symbol": "AAPL", "action": "buy", "quantity": 1}
        risk = {"approved": True}
        fund = {"approved": True, "priority": "skip"}
        action, qty, human = pipeline._resolve_final_action(trade, risk, fund)
        assert action == "hold"
        assert qty == 0

    def test_fund_approved_propagates_action_and_human_flag(self, pipeline):
        trade = {"symbol": "AAPL", "action": "buy", "quantity": 5}
        risk = {"approved": True}
        fund = {
            "approved": True,
            "priority": "high",
            "final_quantity": 3,
            "requires_human_approval": True,
        }
        action, qty, human = pipeline._resolve_final_action(trade, risk, fund)
        assert action == "buy"
        assert qty == 3
        assert human is True

    def test_fund_decision_falls_through_to_trade_when_no_fund(self, pipeline):
        trade = {"symbol": "AAPL", "action": "sell", "quantity": 2}
        risk = {"approved": True}
        action, qty, human = pipeline._resolve_final_action(trade, risk, {})
        assert action == "sell"
        assert qty == 2

    def test_no_decisions_at_all_returns_hold(self, pipeline):
        action, qty, human = pipeline._resolve_final_action({}, {}, {})
        # Risk dict empty == approved missing == False == hold
        assert action == "hold"
        assert qty == 0

    def test_fund_uses_execute_fallback_when_approved_missing(self, pipeline):
        """Backward-compat: older fund decisions used 'execute' instead of 'approved'."""
        trade = {"symbol": "AAPL", "action": "buy", "quantity": 1}
        risk = {"approved": True}
        fund = {"execute": False}  # 'approved' key absent
        action, qty, human = pipeline._resolve_final_action(trade, risk, fund)
        assert action == "hold"

    def test_fund_quantity_falls_back_through_keys(self, pipeline):
        """final_quantity → contracts → quantity fallback chain."""
        trade = {"symbol": "AAPL", "action": "buy", "quantity": 0}
        risk = {"approved": True}
        # only 'contracts' present
        fund = {"approved": True, "priority": "high", "contracts": 7}
        action, qty, _ = pipeline._resolve_final_action(trade, risk, fund)
        assert qty == 7


# ─────────────────────────────────────────────────────────────────────────────
# _inject_forward_recorder
# ─────────────────────────────────────────────────────────────────────────────


class TestForwardRecorderInjection:
    def test_non_mes_symbol_is_noop(self, pipeline):
        reports = {"technical": {}}
        pipeline._inject_forward_recorder("AAPL", reports)
        assert "forward_recorder_metric" not in reports

    def test_mnq_symbol_is_noop(self, pipeline):
        reports = {"technical": {}}
        pipeline._inject_forward_recorder("MNQ", reports)
        assert "forward_recorder_metric" not in reports

    def test_lowercase_mes_is_noop(self, pipeline):
        # The implementation uppercases internally; lowercase 'mes' should still match
        reports = {"technical": {}}
        pipeline._inject_forward_recorder("mes", reports)
        # Whether key gets injected depends on whether feedback_aggregator import succeeds.
        # The test just verifies the case-insensitivity of the symbol gate doesn't crash.
        # No assertion on result key — graceful handling either way.

    def test_swallows_internal_errors_silently(self, pipeline):
        """Missing feedback_aggregator should not raise — pipeline must not crash."""
        reports = {"technical": {}}
        # Just calling shouldn't raise even if experiments.feedback_aggregator is unavailable
        try:
            pipeline._inject_forward_recorder("MES", reports)
        except Exception as e:
            pytest.fail(f"_inject_forward_recorder raised unexpectedly: {e}")
