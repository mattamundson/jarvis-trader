"""Regression: TraderAgent prompt must surface gate-v2 + recent-trade risk metrics.

Background: the LLM-facing trade-decision agent had no visibility into the
engine's own statistical-validation verdict (gate-v2: MC drawdown, DSR,
profit-factor CI) for the symbol it was trading, nor into a live Sharpe/
Sortino/Calmar snapshot from the symbol's own recent closed trades. Both
signals were already computed elsewhere (`backtest.gate_v2_policy` already
hard-gates paper order submission via `is_strategy_authorized()`) but never
reached the trader's prompt. This test locks the new
`_strategy_metrics_section` integration against regressions, mirroring the
style of `test_trader_forward_recorder_prompt.py`.

This is purely informational — no new hard veto is added here or tested here;
the existing hard gate in `backtest.gate_v2_policy` / `approval/service.py`
is untouched.
"""

from agents.trader import TraderAgent


class TestStrategyMetricsSection:
    """The static helper renders the block only when data is present."""

    def test_none_yields_empty_string(self):
        assert TraderAgent._strategy_metrics_section(None) == ""

    def test_both_sub_dicts_none_yields_empty_string(self):
        assert (
            TraderAgent._strategy_metrics_section({"recent": None, "validated": None})
            == ""
        )

    def test_all_three_sub_dicts_none_yields_empty_string(self):
        assert (
            TraderAgent._strategy_metrics_section(
                {"recent": None, "validated": None, "iv_rank": None}
            )
            == ""
        )

    def test_non_dict_yields_empty_string(self):
        assert TraderAgent._strategy_metrics_section("not a dict") == ""
        assert TraderAgent._strategy_metrics_section(42) == ""

    def test_recent_only_renders_sharpe_sortino_calmar_maxdd(self):
        block = TraderAgent._strategy_metrics_section(
            {
                "recent": {
                    "n_trades": 15,
                    "sharpe_ratio": 1.23,
                    "sortino_ratio": 1.55,
                    "calmar_ratio": 0.87,
                    "max_drawdown_pct": 0.042,
                    "win_rate": 0.6,
                    "profit_factor": 1.8,
                },
                "validated": None,
            }
        )
        assert "STRATEGY VALIDATION METRICS" in block
        assert "Sharpe=1.23" in block
        assert "Sortino=1.55" in block
        assert "Calmar=0.87" in block
        assert "MaxDD=4.2%" in block
        assert "15 closed trades" in block
        assert "no fresh verdict on file" in block.lower()

    def test_validated_only_renders_mc_dd_dsr_verdict(self):
        block = TraderAgent._strategy_metrics_section(
            {
                "recent": None,
                "validated": {
                    "symbol": "MES",
                    "verdict": "PASS",
                    "passed_via": "alt",
                    "mc_95th_dd_pct": 0.038,
                    "dsr": 0.42,
                    "pf_ci_lower": 1.15,
                    "wfo_consistency": "STRONG",
                    "age_days": 3.2,
                },
            }
        )
        assert "STRATEGY VALIDATION METRICS" in block
        assert "verdict=PASS" in block
        assert "passed_via=alt" in block
        assert "MC-95th-DD=3.8%" in block
        assert "DSR=0.42" in block
        assert "not enough closed trades" in block.lower()
        assert "already hard-gates paper order submission upstream" in block

    def test_both_present_renders_both_blocks(self):
        block = TraderAgent._strategy_metrics_section(
            {
                "recent": {
                    "n_trades": 12,
                    "sharpe_ratio": -0.5,
                    "sortino_ratio": -0.6,
                    "calmar_ratio": -0.1,
                    "max_drawdown_pct": 0.15,
                    "win_rate": 0.3,
                    "profit_factor": 0.7,
                },
                "validated": {
                    "symbol": "MGC",
                    "verdict": "FAIL",
                    "passed_via": None,
                    "mc_95th_dd_pct": 0.09,
                    "dsr": 0.02,
                    "pf_ci_lower": 0.8,
                    "wfo_consistency": "WEAK",
                    "age_days": 1.0,
                },
            }
        )
        assert "Sharpe=-0.50" in block
        assert "verdict=FAIL" in block
        assert "DSR=0.02" in block

    def test_verdict_insufficient_sample_renders(self):
        # INSUFFICIENT_SAMPLE is a valid non-PASS verdict (Init 2B) — must not
        # crash or be mistaken for a hard veto instruction in the rendered text.
        block = TraderAgent._strategy_metrics_section(
            {
                "recent": None,
                "validated": {
                    "symbol": "MNQ",
                    "verdict": "INSUFFICIENT_SAMPLE",
                    "passed_via": None,
                    "mc_95th_dd_pct": None,
                    "dsr": None,
                    "pf_ci_lower": None,
                    "wfo_consistency": None,
                    "age_days": 0.5,
                },
            }
        )
        assert "verdict=INSUFFICIENT_SAMPLE" in block
        assert "MC-95th-DD=N/A" in block
        assert "DSR=N/A" in block

    def test_iv_rank_only_renders_iv_rank_line(self):
        block = TraderAgent._strategy_metrics_section(
            {
                "recent": None,
                "validated": None,
                "iv_rank": {
                    "symbol": "MES",
                    "iv_rank": 72.0,
                    "interpretation": "elevated -- consider premium-selling bias",
                },
            }
        )
        assert "STRATEGY VALIDATION METRICS" in block
        assert "IV Rank: 72" in block
        assert "elevated" in block.lower()
        assert "premium-selling" in block.lower()
        # The other two sub-sections still fall back to their absent-data text.
        assert "not enough closed trades" in block.lower()
        assert "no fresh verdict on file" in block.lower()

    def test_iv_rank_low_renders_premium_buying_bias(self):
        block = TraderAgent._strategy_metrics_section(
            {
                "recent": None,
                "validated": None,
                "iv_rank": {
                    "symbol": "MGC",
                    "iv_rank": 18.0,
                    "interpretation": "low -- consider premium-buying bias",
                },
            }
        )
        assert "IV Rank: 18" in block
        assert "premium-buying" in block.lower()

    def test_iv_rank_absent_omits_iv_rank_line(self):
        block = TraderAgent._strategy_metrics_section(
            {
                "recent": {
                    "n_trades": 15,
                    "sharpe_ratio": 1.23,
                    "sortino_ratio": 1.55,
                    "calmar_ratio": 0.87,
                    "max_drawdown_pct": 0.042,
                    "win_rate": 0.6,
                    "profit_factor": 1.8,
                },
                "validated": None,
                "iv_rank": None,
            }
        )
        assert "IV Rank:" not in block

    def test_all_three_present_renders_all_blocks(self):
        block = TraderAgent._strategy_metrics_section(
            {
                "recent": {
                    "n_trades": 12,
                    "sharpe_ratio": -0.5,
                    "sortino_ratio": -0.6,
                    "calmar_ratio": -0.1,
                    "max_drawdown_pct": 0.15,
                    "win_rate": 0.3,
                    "profit_factor": 0.7,
                },
                "validated": {
                    "symbol": "MGC",
                    "verdict": "FAIL",
                    "passed_via": None,
                    "mc_95th_dd_pct": 0.09,
                    "dsr": 0.02,
                    "pf_ci_lower": 0.8,
                    "wfo_consistency": "WEAK",
                    "age_days": 1.0,
                },
                "iv_rank": {
                    "symbol": "MGC",
                    "iv_rank": 45.0,
                    "interpretation": "neutral -- no strong premium-selling/buying skew",
                },
            }
        )
        assert "Sharpe=-0.50" in block
        assert "verdict=FAIL" in block
        assert "IV Rank: 45" in block


class TestBuildPromptIncludesStrategyMetricsSection:
    """End-to-end: _build_prompt actually emits the section when data is present."""

    def _make_agent(self) -> TraderAgent:
        # TraderAgent.__init__ has external deps (safety, client, etc.);
        # sidestep by constructing with __new__ since _build_prompt only
        # reads instance-independent constants (_SYMBOL_ATR_PARAMS etc.).
        return TraderAgent.__new__(TraderAgent)

    def _make_position_size(self):
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

    def test_prompt_includes_section_when_strategy_metrics_present(self):
        agent = self._make_agent()
        prompt = agent._build_prompt(
            "MES",
            self._minimal_debate(),
            self._minimal_analyst_reports(),
            self._minimal_safety(),
            self._make_position_size(),
            strategy_metrics={
                "recent": {
                    "n_trades": 14,
                    "sharpe_ratio": 0.95,
                    "sortino_ratio": 1.1,
                    "calmar_ratio": 0.5,
                    "max_drawdown_pct": 0.06,
                    "win_rate": 0.55,
                    "profit_factor": 1.4,
                },
                "validated": {
                    "symbol": "MES",
                    "verdict": "PASS",
                    "passed_via": "alt",
                    "mc_95th_dd_pct": 0.03,
                    "dsr": 0.35,
                    "pf_ci_lower": 1.2,
                    "wfo_consistency": "MODERATE",
                    "age_days": 2.0,
                },
                "iv_rank": {
                    "symbol": "MES",
                    "iv_rank": 72.0,
                    "interpretation": "elevated -- consider premium-selling bias",
                },
            },
        )
        assert "STRATEGY VALIDATION METRICS" in prompt
        assert "Sharpe=0.95" in prompt
        assert "verdict=PASS" in prompt
        assert "IV Rank: 72" in prompt

    def test_prompt_omits_section_when_strategy_metrics_absent(self):
        agent = self._make_agent()
        prompt = agent._build_prompt(
            "SPY",
            self._minimal_debate(),
            self._minimal_analyst_reports(),
            self._minimal_safety(),
            self._make_position_size(),
        )
        assert "STRATEGY VALIDATION METRICS" not in prompt

    def test_prompt_omits_section_when_both_sub_dicts_none(self):
        agent = self._make_agent()
        prompt = agent._build_prompt(
            "SPY",
            self._minimal_debate(),
            self._minimal_analyst_reports(),
            self._minimal_safety(),
            self._make_position_size(),
            strategy_metrics={"recent": None, "validated": None},
        )
        assert "STRATEGY VALIDATION METRICS" not in prompt

    def test_prompt_omits_section_when_all_three_sub_dicts_none(self):
        agent = self._make_agent()
        prompt = agent._build_prompt(
            "SPY",
            self._minimal_debate(),
            self._minimal_analyst_reports(),
            self._minimal_safety(),
            self._make_position_size(),
            strategy_metrics={"recent": None, "validated": None, "iv_rank": None},
        )
        assert "STRATEGY VALIDATION METRICS" not in prompt

    def test_prompt_includes_section_when_only_iv_rank_present(self):
        agent = self._make_agent()
        prompt = agent._build_prompt(
            "MGC",
            self._minimal_debate(),
            self._minimal_analyst_reports(),
            self._minimal_safety(),
            self._make_position_size(),
            strategy_metrics={
                "recent": None,
                "validated": None,
                "iv_rank": {
                    "symbol": "MGC",
                    "iv_rank": 18.0,
                    "interpretation": "low -- consider premium-buying bias",
                },
            },
        )
        assert "STRATEGY VALIDATION METRICS" in prompt
        assert "IV Rank: 18" in prompt
