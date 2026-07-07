"""Regression: TraderAgent prompt must include forward-recorder feedback.

Background: P0.5 injected `forward_recorder_metric` into analyst_reports
via `TradingPipeline._inject_forward_recorder` (commit b602371). Bull/Bear
researchers `json.dumps` the full dict so they see the metric for free,
but TraderAgent._build_prompt cherry-picks technical/news/social/fundamental
and previously dropped the metric. This test locks the integration gap
against regressions — if a future refactor strips the FORWARD-RECORDER
section from the prompt, the metric stops reaching the decision-making
agent and the unit tests on _inject_forward_recorder would still pass.
"""

from agents.trader import TraderAgent


class TestForwardRecorderSection:
    """The static helper renders the block only when a valid metric is present."""

    def test_absent_metric_yields_empty_string(self):
        assert TraderAgent._forward_recorder_section(None) == ""

    def test_non_dict_metric_yields_empty_string(self):
        # Defensive: a stray scalar or string should not crash the prompt build.
        assert TraderAgent._forward_recorder_section("not a dict") == ""
        assert TraderAgent._forward_recorder_section(42) == ""

    def test_healthy_metric_renders_hit_rate_and_last_hypothesis(self):
        block = TraderAgent._forward_recorder_section(
            {
                "hit_rate": 0.7,
                "samples": 10,
                "degraded": False,
                "last_hypothesis": {
                    "date": "2026-04-21",
                    "entry_hypothesis_side": "long",
                    "open_price": 6388.25,
                    "entry_hypothesis_reason": "corey=bullish conv=0.70",
                },
            }
        )
        assert "FORWARD-RECORDER FEEDBACK" in block
        assert "0.70" in block
        assert "last 10 sessions" in block
        assert "degraded" not in block.lower()  # healthy sample, no warning
        assert "2026-04-21" in block
        assert "long" in block
        assert "6388.25" in block
        assert "corey=bullish" in block

    def test_degraded_flag_surfaces_warning(self):
        block = TraderAgent._forward_recorder_section(
            {
                "hit_rate": 0.5,
                "samples": 2,
                "degraded": True,
                "last_hypothesis": None,
            }
        )
        assert "degraded: sample size < 5" in block
        assert "No prior session hypothesis" in block

    def test_none_hit_rate_renders_na(self):
        # Empty history: aggregator returns None; must not crash f-string.
        block = TraderAgent._forward_recorder_section(
            {
                "hit_rate": None,
                "samples": 0,
                "degraded": True,
                "last_hypothesis": None,
            }
        )
        assert "N/A" in block
        assert "last 0 sessions" in block


class TestBuildPromptIncludesSection:
    """End-to-end: the full _build_prompt wiring actually emits the section.

    This is the integration gap _forward_recorder_section alone cannot cover:
    a future refactor could remove the `{self._forward_recorder_section(...)}`
    call site from _build_prompt while leaving the helper intact, and the
    static-helper tests above would still pass while the metric silently
    stopped reaching the LLM.
    """

    def _make_agent(self) -> TraderAgent:
        # TraderAgent's __init__ has external deps (safety, client, etc);
        # sidestep by constructing with __new__ since _build_prompt only
        # reads instance-independent constants (_SYMBOL_ATR_PARAMS etc).
        return TraderAgent.__new__(TraderAgent)

    def _make_position_size(self):
        # Minimal PositionSizeResult substitute — _build_prompt reads
        # .contracts, .risk_per_trade, .stop_distance, .dollar_risk_per_contract,
        # .reasoning. Use a namespace so we don't have to import the real one.
        from types import SimpleNamespace

        return SimpleNamespace(
            contracts=1,
            risk_per_trade=100.0,
            stop_distance=2.5,
            dollar_risk_per_contract=12.50,
            reasoning="test fixture",
        )

    def _minimal_analyst_reports(self) -> dict:
        return {
            "technical": {"signal": "long", "confidence": 0.6, "current_price": 6388.25},
            "news": {"signal": "neutral", "confidence": 0.5},
            "social": {"signal": "neutral", "confidence": 0.5},
            "fundamental": {"signal": "neutral", "confidence": 0.5},
        }

    def _minimal_debate(self) -> dict:
        return {"verdict": "LONG", "bull_score": 7.0, "bear_score": 3.0}

    def _minimal_safety(self) -> dict:
        return {
            "current_equity": 10_000.0,
            "daily_pnl": 0.0,
            "drawdown_pct": 0.0,
            "live_trading_enabled": False,
        }

    def test_prompt_includes_section_when_metric_present(self):
        agent = self._make_agent()
        reports = self._minimal_analyst_reports()
        reports["forward_recorder_metric"] = {
            "hit_rate": 0.6,
            "samples": 8,
            "degraded": False,
            "last_hypothesis": {
                "date": "2026-04-21",
                "entry_hypothesis_side": "long",
                "open_price": 6388.25,
                "entry_hypothesis_reason": "corey=bullish",
            },
        }
        prompt = agent._build_prompt(
            "MES",
            self._minimal_debate(),
            reports,
            self._minimal_safety(),
            self._make_position_size(),
        )
        assert "FORWARD-RECORDER FEEDBACK" in prompt
        assert "last 8 sessions" in prompt
        assert "0.60" in prompt

    def test_prompt_omits_section_when_metric_absent(self):
        # Non-MES path or missing metric — section header must not leak in.
        agent = self._make_agent()
        prompt = agent._build_prompt(
            "SPY",
            self._minimal_debate(),
            self._minimal_analyst_reports(),  # no forward_recorder_metric
            self._minimal_safety(),
            self._make_position_size(),
        )
        assert "FORWARD-RECORDER FEEDBACK" not in prompt
