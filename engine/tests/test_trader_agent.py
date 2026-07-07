"""
US-004 — TraderAgent unit test suite.

Targets pure functions exhaustively (parametrized) + the async `decide()`
orchestrator with mocked LLM/db. Pre-existing files (test_trader_corey_contradiction,
test_trader_forward_recorder_prompt) cover narrow scenarios; this file fills the
broad-coverage gap to raise trader.py from 23% → ~70% line coverage.
"""

import os
import sys
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.trader import (  # noqa: E402
    TradeDecision,
    TraderAgent,
    _detect_corey_contradiction,
)
from utils.position_sizing import PositionSizeResult  # noqa: E402

# ── Shared factories ───────────────────────────────────────────────────────────


def _make_position_size(contracts: int = 2, reasoning: str = "fixed-fractional 1%") -> PositionSizeResult:
    return PositionSizeResult(
        contracts=contracts,
        risk_per_trade=100.0,
        stop_distance=5.0,
        dollar_risk_per_contract=50.0,
        account_value=10_000.0,
        symbol="MES",
        reasoning=reasoning,
    )


def _make_safety_status(killed: bool = False, equity: float = 10_000.0, **kwargs) -> dict:
    base = {
        "kill_switch_active": killed,
        "kill_switch_reason": "manual" if killed else None,
        "current_equity": equity,
    }
    base.update(kwargs)
    return base


def _make_analyst_reports(atr: float = 5.0) -> dict:
    return {
        "technical": {
            "indicators": {"atr": atr},
            "signal": 0.5,
        },
        "news": {"signal": 0.3},
        "social": {"signal": 0.4},
        "fundamental": {"signal": 0.2},
    }


def _make_debate_result(verdict: str = "BULL_WINS", bull: float = 7.0, bear: float = 3.0) -> dict:
    return {
        "verdict": verdict,
        "bull_score": bull,
        "bear_score": bear,
        "regime": "trending",
    }


@pytest.fixture
def trader():
    """TraderAgent with no LLM client — for pure-function tests that don't call decide()."""
    llm = MagicMock()
    llm.api_key = "test-key"
    return TraderAgent(llm_client=llm, db_manager=None)


# ─────────────────────────────────────────────────────────────────────────────
# TradeDecision.to_dict
# ─────────────────────────────────────────────────────────────────────────────


class TestTradeDecisionSerialization:
    def _decision(self, **overrides) -> TradeDecision:
        defaults = {
            "symbol": "MES",
            "action": "buy",
            "quantity": 2,
            "order_type": "market",
            "time_in_force": "day",
            "limit_price": None,
            "stop_price": 5750.0,
            "entry_price": 5800.0,
            "target_1": 5850.0,
            "target_2": 5900.0,
            "atr_used": 5.0,
            "rr_ratio": 1.0,
            "signal_score": 0.5,
            "confidence": 0.7,
            "reasoning": "bullish breakout",
            "risk_notes": "watch VIX",
        }
        defaults.update(overrides)
        return TradeDecision(**defaults)

    def test_to_dict_round_trips_all_required_fields(self):
        d = self._decision()
        result = d.to_dict()
        assert result["symbol"] == "MES"
        assert result["action"] == "buy"
        assert result["quantity"] == 2
        assert result["target_1"] == 5850.0
        assert result["confidence"] == 0.7

    def test_to_dict_serializes_timestamp_as_iso_string(self):
        d = self._decision()
        result = d.to_dict()
        # Must be parseable back
        datetime.fromisoformat(result["timestamp"])

    def test_to_dict_preserves_none_for_optional_prices(self):
        d = self._decision(limit_price=None, stop_price=None, target_1=None, target_2=None)
        result = d.to_dict()
        assert result["limit_price"] is None
        assert result["stop_price"] is None
        assert result["target_1"] is None
        assert result["target_2"] is None

    def test_to_dict_default_sizing_method_is_fixed_fractional(self):
        d = self._decision()
        assert d.to_dict()["sizing_method"] == "fixed_fractional"


# ─────────────────────────────────────────────────────────────────────────────
# _compute_confluence_multiplier
# ─────────────────────────────────────────────────────────────────────────────


class TestConfluenceMultiplier:
    """Six-bin agreement ladder + neutral fallback + signal-field priority."""

    @pytest.mark.parametrize(
        "agent_signals,direction,expected",
        [
            # All 4 agree LONG → 4/4 = 100% → 1.5
            ({"a": 1.0, "b": 1.0, "c": 1.0, "d": 1.0}, "LONG", 1.5),
            # 4 of 5 agree LONG → 80% → 1.5
            ({"a": 1.0, "b": 1.0, "c": 1.0, "d": 1.0, "e": -1.0}, "LONG", 1.5),
            # 3 of 5 agree → 60% → 1.0
            ({"a": 1.0, "b": 1.0, "c": 1.0, "d": -1.0, "e": -1.0}, "LONG", 1.0),
            # 2 of 5 → 40% → 0.75
            ({"a": 1.0, "b": 1.0, "c": -1.0, "d": -1.0, "e": -1.0}, "LONG", 0.75),
            # 1 of 5 → 20% → 0.5
            ({"a": 1.0, "b": -1.0, "c": -1.0, "d": -1.0, "e": -1.0}, "LONG", 0.5),
            # 1 of 6 → 16.7% → 0.25 (the lone-voice tier)
            ({"a": 1.0, "b": -1.0, "c": -1.0, "d": -1.0, "e": -1.0, "f": -1.0}, "LONG", 0.25),
            # 0 of 4 agree → 0%
            ({"a": -1.0, "b": -1.0, "c": -1.0, "d": -1.0}, "LONG", 0.0),
            # All 4 agree SHORT
            ({"a": -1.0, "b": -1.0, "c": -1.0, "d": -1.0}, "SHORT", 1.5),
        ],
    )
    def test_confluence_ratio_bins(self, trader, agent_signals, direction, expected):
        reports = {name: {"signal": sig} for name, sig in agent_signals.items()}
        assert trader._compute_confluence_multiplier(reports, direction) == expected

    def test_no_signals_returns_neutral_one_point_zero(self, trader):
        """Empty reports = no penalty/boost, return 1.0."""
        assert trader._compute_confluence_multiplier({}, "LONG") == 1.0

    def test_reports_without_signal_field_skipped(self, trader):
        reports = {"a": {"unrelated": "data"}, "b": {"signal": 1.0}}
        # Only 'b' counts: 1/1 LONG → 100% → 1.5
        assert trader._compute_confluence_multiplier(reports, "LONG") == 1.5

    def test_hidden_pivots_excluded_from_confluence(self, trader):
        reports = {
            "hidden_pivots": {"signal": -1.0},  # would dilute if counted
            "a": {"signal": 1.0},
            "b": {"signal": 1.0},
        }
        # 2/2 = 100% → 1.5 (hidden_pivots ignored)
        assert trader._compute_confluence_multiplier(reports, "LONG") == 1.5

    def test_uses_bias_field_when_signal_absent(self, trader):
        reports = {"a": {"bias": 1.0}, "b": {"bias": 1.0}}
        assert trader._compute_confluence_multiplier(reports, "LONG") == 1.5

    def test_uses_sentiment_score_field_when_others_absent(self, trader):
        reports = {"a": {"sentiment_score": 1.0}, "b": {"sentiment_score": 1.0}}
        assert trader._compute_confluence_multiplier(reports, "LONG") == 1.5

    def test_invalid_signal_type_skipped(self, trader):
        reports = {"a": {"signal": "not-a-number"}, "b": {"signal": 1.0}}
        # 1/1 = 100% → 1.5
        assert trader._compute_confluence_multiplier(reports, "LONG") == 1.5

    def test_attribute_access_works_on_dataclass_like_objects(self, trader):
        class Report:
            signal = 1.0

        reports = {"a": Report(), "b": Report()}
        assert trader._compute_confluence_multiplier(reports, "LONG") == 1.5

    def test_short_direction_inverts_agreement(self, trader):
        reports = {"a": {"signal": -1.0}, "b": {"signal": -1.0}, "c": {"signal": 1.0}}
        # 2/3 SHORT-aligned = 66.7% → 1.0
        assert trader._compute_confluence_multiplier(reports, "SHORT") == 1.0

    def test_zero_signal_neither_bull_nor_bear(self, trader):
        # signal=0 counts toward `total` but neither direction
        reports = {"a": {"signal": 0.0}, "b": {"signal": 1.0}}
        # LONG: 1/2 agreements = 50% → 0.75
        assert trader._compute_confluence_multiplier(reports, "LONG") == 0.75


# ─────────────────────────────────────────────────────────────────────────────
# _hold_decision
# ─────────────────────────────────────────────────────────────────────────────


class TestHoldDecision:
    def test_action_is_hold(self, trader):
        d = trader._hold_decision("MES", "test reason", "test risk")
        assert d.action == "hold"

    def test_quantity_zero_and_prices_null(self, trader):
        d = trader._hold_decision("MES", "r", "n")
        assert d.quantity == 0
        assert d.limit_price is None
        assert d.stop_price is None
        assert d.entry_price is None
        assert d.target_1 is None
        assert d.target_2 is None
        assert d.atr_used is None
        assert d.rr_ratio is None

    def test_signal_and_confidence_zero(self, trader):
        d = trader._hold_decision("MES", "r", "n")
        assert d.signal_score == 0.0
        assert d.confidence == 0.0

    def test_reasoning_and_risk_notes_propagate(self, trader):
        d = trader._hold_decision("MNQ", "explanation here", "risk explanation")
        assert d.reasoning == "explanation here"
        assert d.risk_notes == "risk explanation"
        assert d.symbol == "MNQ"

    def test_time_in_force_defaults_to_day(self, trader):
        d = trader._hold_decision("MES", "r", "n")
        assert d.time_in_force == "day"
        assert d.order_type == "market"


# ─────────────────────────────────────────────────────────────────────────────
# _parse_decision
# ─────────────────────────────────────────────────────────────────────────────


class TestParseDecision:
    def test_invalid_action_coerced_to_hold(self, trader):
        result = {"action": "frenzy", "quantity": 5}
        d = trader._parse_decision("MES", result)
        assert d.action == "hold"

    def test_hold_action_zeroes_quantity(self, trader):
        result = {"action": "hold", "quantity": 99}
        d = trader._parse_decision("MES", result)
        assert d.quantity == 0

    def test_buy_quantity_capped_by_position_size(self, trader):
        result = {"action": "buy", "quantity": 10}
        ps = _make_position_size(contracts=2)
        d = trader._parse_decision("MES", result, position_size=ps)
        assert d.quantity == 2

    def test_buy_lower_than_size_falls_back_to_size(self, trader):
        # If LLM says 0 contracts on a 'buy', code re-fills from sizing
        result = {"action": "buy", "quantity": 0}
        ps = _make_position_size(contracts=3)
        d = trader._parse_decision("MES", result, position_size=ps)
        assert d.quantity == 3

    def test_invalid_order_type_coerced_to_market(self, trader):
        result = {"action": "buy", "quantity": 1, "order_type": "yolo"}
        d = trader._parse_decision("MES", result)
        assert d.order_type == "market"

    def test_invalid_tif_coerced_to_day(self, trader):
        result = {"action": "buy", "quantity": 1, "time_in_force": "forever"}
        d = trader._parse_decision("MES", result)
        assert d.time_in_force == "day"

    def test_inverted_buy_stop_corrected_via_atr(self, trader):
        # Buy with stop ABOVE entry → must be corrected below entry
        result = {
            "action": "buy",
            "quantity": 1,
            "entry_price": 5800.0,
            "stop_price": 5850.0,  # wrong side
            "atr_used": 5.0,
        }
        d = trader._parse_decision("MES", result)
        # MES stop_atr=1.0, so corrected stop = 5800 - (1.0 * 5.0) = 5795
        assert d.stop_price == 5795.0

    def test_inverted_sell_stop_corrected_via_atr(self, trader):
        result = {
            "action": "sell",
            "quantity": 1,
            "entry_price": 5800.0,
            "stop_price": 5750.0,  # wrong side for sell
            "atr_used": 5.0,
        }
        d = trader._parse_decision("MES", result)
        # MES stop_atr=1.0, sell stop = 5800 + 5 = 5805
        assert d.stop_price == 5805.0

    def test_inverted_stop_no_atr_nulled(self, trader):
        result = {
            "action": "buy",
            "quantity": 1,
            "entry_price": 5800.0,
            "stop_price": 5850.0,
            "atr_used": None,
        }
        d = trader._parse_decision("MES", result)
        assert d.stop_price is None

    def test_correct_stop_unchanged(self, trader):
        result = {
            "action": "buy",
            "quantity": 1,
            "entry_price": 5800.0,
            "stop_price": 5790.0,  # correctly below entry
            "atr_used": 5.0,
        }
        d = trader._parse_decision("MES", result)
        assert d.stop_price == 5790.0

    def test_rr_recomputed_server_side(self, trader):
        # entry=100, stop=95, target=110 → risk=5 reward=10 → R:R=2.0
        result = {
            "action": "buy",
            "quantity": 1,
            "entry_price": 100.0,
            "stop_price": 95.0,
            "target_1": 110.0,
            "rr_ratio": 0.0,  # LLM lied
        }
        d = trader._parse_decision("MES", result)
        assert d.rr_ratio == 2.0

    def test_rr_skipped_when_risk_zero(self, trader):
        # entry == stop, no recompute → preserve LLM value
        result = {
            "action": "buy",
            "quantity": 1,
            "entry_price": 100.0,
            "stop_price": 100.0,
            "target_1": 110.0,
            "rr_ratio": 1.5,
        }
        d = trader._parse_decision("MES", result)
        assert d.rr_ratio == 1.5

    def test_signal_score_and_confidence_propagated(self, trader):
        result = {
            "action": "buy",
            "quantity": 1,
            "signal_score": 0.8,
            "confidence": 0.9,
        }
        d = trader._parse_decision("MES", result)
        assert d.signal_score == 0.8
        assert d.confidence == 0.9

    def test_default_signal_and_confidence_when_missing(self, trader):
        d = trader._parse_decision("MES", {"action": "buy", "quantity": 1})
        assert d.signal_score == 0.0
        assert d.confidence == 0.5

    def test_reasoning_appends_sizing_block_when_position_size_present(self, trader):
        result = {"action": "buy", "quantity": 1, "reasoning": "bullish setup"}
        ps = _make_position_size(contracts=1, reasoning="1 contract for 1% risk")
        d = trader._parse_decision("MES", result, position_size=ps)
        assert "[Position Sizing]" in d.reasoning
        assert "1 contract for 1% risk" in d.reasoning
        assert "bullish setup" in d.reasoning

    def test_reasoning_no_sizing_block_for_hold(self, trader):
        result = {"action": "hold", "quantity": 0, "reasoning": "mixed signals"}
        ps = _make_position_size(contracts=1)
        d = trader._parse_decision("MES", result, position_size=ps)
        assert "[Position Sizing]" not in d.reasoning

    def test_sizing_method_passed_through(self, trader):
        result = {"action": "buy", "quantity": 1}
        d = trader._parse_decision("MES", result, sizing_method="half_kelly")
        assert d.sizing_method == "half_kelly"


# ─────────────────────────────────────────────────────────────────────────────
# _forward_recorder_section
# ─────────────────────────────────────────────────────────────────────────────


class TestForwardRecorderSection:
    def test_none_metric_returns_empty(self):
        assert TraderAgent._forward_recorder_section(None) == ""

    def test_non_dict_metric_returns_empty(self):
        assert TraderAgent._forward_recorder_section("garbage") == ""
        assert TraderAgent._forward_recorder_section(123) == ""

    def test_present_metric_renders_block(self):
        metric = {
            "hit_rate": 0.62,
            "samples": 30,
            "degraded": False,
            "last_hypothesis": {
                "date": "2026-04-23",
                "entry_hypothesis_side": "LONG",
                "open_price": 5800.0,
                "entry_hypothesis_reason": "gap up",
            },
        }
        block = TraderAgent._forward_recorder_section(metric)
        assert "FORWARD-RECORDER FEEDBACK" in block
        assert "0.62" in block
        assert "LONG" in block
        assert "gap up" in block
        assert "degraded" not in block

    def test_degraded_metric_includes_warning(self):
        metric = {"hit_rate": 0.5, "samples": 3, "degraded": True, "last_hypothesis": None}
        block = TraderAgent._forward_recorder_section(metric)
        assert "degraded" in block.lower()
        assert "No prior session hypothesis" in block

    def test_missing_hit_rate_renders_na(self):
        metric = {"samples": 10, "degraded": False, "last_hypothesis": None}
        block = TraderAgent._forward_recorder_section(metric)
        assert "N/A" in block


# ─────────────────────────────────────────────────────────────────────────────
# decide() async orchestrator
# ─────────────────────────────────────────────────────────────────────────────


class TestDecideOrchestrator:
    @pytest.mark.asyncio
    async def test_kill_switch_short_circuits_to_hold(self, trader):
        decision = await trader.decide(
            symbol="MES",
            debate_result=_make_debate_result(),
            analyst_reports=_make_analyst_reports(),
            safety_status=_make_safety_status(killed=True),
        )
        assert decision.action == "hold"
        assert decision.quantity == 0
        assert "Kill switch is active" in decision.reasoning

    @pytest.mark.asyncio
    async def test_kill_switch_includes_reason_in_decision(self, trader):
        status = _make_safety_status(killed=True, kill_switch_reason="daily_loss_limit")
        decision = await trader.decide(
            symbol="MES",
            debate_result=_make_debate_result(),
            analyst_reports=_make_analyst_reports(),
            safety_status=status,
        )
        assert "daily_loss_limit" in decision.reasoning

    @pytest.mark.asyncio
    async def test_llm_exception_falls_back_to_hold(self, trader):
        trader._llm.call = AsyncMock(side_effect=RuntimeError("network down"))
        if True:
            decision = await trader.decide(
                symbol="MES",
                debate_result=_make_debate_result(),
                analyst_reports=_make_analyst_reports(),
                safety_status=_make_safety_status(),
            )
            assert decision.action == "hold"
            assert "LLM" in decision.reasoning or "failed" in decision.reasoning.lower()

    @pytest.mark.asyncio
    async def test_zero_atr_warns_but_continues(self, trader):
        """ATR=0 logs a warning but doesn't raise — trader still calls LLM."""
        trader._llm.call = AsyncMock(side_effect=RuntimeError("forced"))
        if True:
            # Force LLM to raise so we land in the fallback HOLD; we just want to
            # confirm decide() doesn't crash on missing ATR.
            reports = _make_analyst_reports(atr=0.0)
            decision = await trader.decide(
                symbol="MES",
                debate_result=_make_debate_result(),
                analyst_reports=reports,
                safety_status=_make_safety_status(),
            )
            assert decision.action == "hold"

    @pytest.mark.asyncio
    async def test_missing_equity_falls_back_to_default_10k(self, trader):
        """current_equity=None → default $10K; trader still proceeds (LLM mocked to fail)."""
        trader._llm.call = AsyncMock(side_effect=RuntimeError("forced"))
        if True:
            status = {"kill_switch_active": False}  # no current_equity key at all
            decision = await trader.decide(
                symbol="MES",
                debate_result=_make_debate_result(),
                analyst_reports=_make_analyst_reports(),
                safety_status=status,
            )
            # Should still produce a HOLD via the LLM-failure fallback, not crash
            assert decision.action == "hold"


class TestDecideLLMTransport:
    """B1 regression (2026-06-10): the decision call MUST route through
    JarvisLLMClient.call() so the Vertex->Gemini->OpenAI fallback chain applies.
    A raw httpx POST to api.anthropic.com here meant every decision failed 400
    while Anthropic credits were exhausted."""

    def _success_result(self):
        from llm.client import LLMCallResult

        content = (
            '{"action": "buy", "quantity": 1, "order_type": "market", '
            '"time_in_force": "day", "entry_price": 5800.0, "stop_price": 5750.0, '
            '"target_1": 5850.0, "confidence": 0.8, "signal_score": 0.6, '
            '"reasoning": "test path"}'
        )
        return LLMCallResult(
            success=True,
            model="gemini-2.5-flash",
            input_tokens=10,
            output_tokens=10,
            cost_usd=0.0,
            latency_ms=5,
            retries=0,
            content=content,
        )

    @pytest.mark.asyncio
    async def test_decision_routes_through_llm_client(self, trader):
        """decide() must invoke self._llm.call (fallback-owning client), not raw httpx."""
        trader._llm.call = AsyncMock(return_value=self._success_result())
        trader._apply_tool_inspection = AsyncMock(
            side_effect=lambda **kw: (kw["decision"], False)
        )
        with patch("agents.trader._get_advisor", return_value=None):
            decision = await trader.decide(
                symbol="MES",
                debate_result=_make_debate_result(),
                analyst_reports=_make_analyst_reports(),
                safety_status=_make_safety_status(),
            )
        assert trader._llm.call.await_count == 1
        kwargs = trader._llm.call.await_args.kwargs
        assert kwargs["agent_name"] == "trader"
        assert kwargs["model"] == TraderAgent.MODEL
        # A successful (fallback-served) call must NOT degrade to LLM-failure HOLD
        assert "Trader LLM call failed" not in decision.reasoning

    @pytest.mark.asyncio
    async def test_llm_result_failure_falls_back_to_hold(self, trader):
        """result.success=False (all providers down) -> fail-safe HOLD preserved."""
        from llm.client import LLMCallResult

        failed = LLMCallResult(
            success=False,
            model="claude-sonnet-4-6",
            input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
            latency_ms=5,
            retries=2,
            content="",
            error="credit balance is too low",
        )
        trader._llm.call = AsyncMock(return_value=failed)
        decision = await trader.decide(
            symbol="MES",
            debate_result=_make_debate_result(),
            analyst_reports=_make_analyst_reports(),
            safety_status=_make_safety_status(),
        )
        assert decision.action == "hold"
        assert decision.quantity == 0
        assert "failed" in decision.reasoning.lower()

    def test_no_direct_anthropic_post_in_trader_source(self):
        """Source-level guard: trader.py must not POST api.anthropic.com directly."""
        import inspect

        import agents.trader as trader_mod

        source = inspect.getsource(trader_mod)
        assert "api.anthropic.com" not in source


# ─────────────────────────────────────────────────────────────────────────────
# _detect_corey_contradiction (extra coverage on top of existing tests)
# ─────────────────────────────────────────────────────────────────────────────


class TestCoreyContradictionExtra:
    """Adjacent edge cases not in test_trader_corey_contradiction.py."""

    def test_briefing_without_corey_bias_returns_none(self):
        analyst = {"discord_briefing": {"corey_bias": None}}
        assert _detect_corey_contradiction("buy", analyst) is None

    def test_missing_directional_bias_returns_none(self):
        analyst = {"discord_briefing": {"corey_bias": {"conviction": 0.9}}}
        # bias defaults to "" → no match against bullish/bearish
        assert _detect_corey_contradiction("buy", analyst) is None

    def test_uppercase_action_no_match(self):
        # Action gating is strict on lowercase 'buy'/'sell'
        analyst = {"discord_briefing": {"corey_bias": {"directional_bias": "bearish", "conviction": 0.9}}}
        assert _detect_corey_contradiction("BUY", analyst) is None

    def test_threshold_at_exactly_0_71_fires(self):
        analyst = {"discord_briefing": {"corey_bias": {"directional_bias": "bearish", "conviction": 0.71}}}
        result = _detect_corey_contradiction("buy", analyst)
        assert result is not None
        assert result["conviction"] == 0.71
