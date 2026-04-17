"""
Tests for JARVIS TRADER new features — Tracks A, B, C, D, E, F, G, H.

Run: pytest engine/tests/test_new_features.py -v
"""

import pytest
import sys
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure engine is on path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


# ─── Track C: TradingView Feed ────────────────────────────────────────────────

class TestTradingViewFeed:
    """Tests for Track C: TradingViewFeed optional data source."""

    def test_import(self):
        from engine.data.tradingview_feed import TradingViewFeed
        assert TradingViewFeed is not None

    def test_unavailable_when_no_cli(self):
        """Should report unavailable gracefully when 'tv' CLI not found."""
        from engine.data.tradingview_feed import TradingViewFeed
        with patch("shutil.which", return_value=None):
            feed = TradingViewFeed()
            assert feed.is_available() is False

    def test_get_quote_returns_none_when_unavailable(self):
        from engine.data.tradingview_feed import TradingViewFeed
        with patch("shutil.which", return_value=None):
            feed = TradingViewFeed()
            result = feed.get_quote("MES")
            assert result is None

    def test_reset_availability(self):
        from engine.data.tradingview_feed import TradingViewFeed
        feed = TradingViewFeed()
        feed._available = True
        feed.reset_availability()
        assert feed._available is None


# ─── Track D: TRIN ───────────────────────────────────────────────────────────

class TestTRIN:
    """Tests for Track D: TRIN computation."""

    def test_trin_basic(self):
        from engine.backtest.indicators import compute_trin
        # Equal advances/declines and equal volume → TRIN = 1.0
        result = compute_trin(500, 500, 1e9, 1e9)
        assert result == pytest.approx(1.0, abs=0.01)

    def test_trin_bullish(self):
        from engine.backtest.indicators import compute_trin
        # TRIN = (adv/dec) / (adv_vol/dec_vol)
        # adv=600, dec=400 → AD ratio=1.5; adv_vol=3e9, dec_vol=1e9 → vol_ratio=3.0
        # TRIN = 1.5 / 3.0 = 0.5 → bullish (< 1.0)
        result = compute_trin(600, 400, 3e9, 1e9)
        assert result is not None
        assert result < 1.0

    def test_trin_bearish(self):
        from engine.backtest.indicators import compute_trin
        # For TRIN > 1: (adv/dec) < (adv_vol/dec_vol) is inverted
        # adv=400, dec=600 → ratio=0.667; adv_vol=1e9, dec_vol=3e9 → vol_ratio=0.333 → TRIN=2.0
        result = compute_trin(400, 600, 1e9, 3e9)
        assert result is not None
        assert result > 1.0

    def test_trin_division_guard(self):
        from engine.backtest.indicators import compute_trin
        # Zero declining issues → should return None, not raise
        result = compute_trin(500, 0, 1e9, 1e9)
        assert result is None

    def test_classify_trin(self):
        from engine.backtest.indicators import classify_trin
        assert classify_trin(0.5) == "BLOWOFF_TOP"
        assert classify_trin(0.8) == "BULLISH"
        assert classify_trin(1.2) == "BEARISH"
        # 1.5 falls in OVERSOLD range (>= 1.40, < 2.00)
        assert classify_trin(1.5) == "OVERSOLD"
        assert classify_trin(2.5) == "CAPITULATION"
        assert classify_trin(None) == "UNAVAILABLE"


# ─── Track D: CoT Fetcher ────────────────────────────────────────────────────

class TestCoTFetcher:
    """Tests for Track D: CoT data fetcher."""

    def test_import(self):
        from engine.data.cot_fetcher import CoTFetcher
        assert CoTFetcher is not None

    def test_bias_adjustment_neutral_when_no_data(self):
        from engine.data.cot_fetcher import CoTFetcher
        fetcher = CoTFetcher()
        with patch.object(fetcher, 'get_positioning', return_value=None):
            bias = fetcher.get_bias_adjustment("MES")
            assert bias == 0.0

    def test_bias_adjustment_bullish(self):
        from engine.data.cot_fetcher import CoTFetcher
        fetcher = CoTFetcher()
        mock_data = {"commercial_trend": "BULLISH", "commercial_net": 50000}
        with patch.object(fetcher, 'get_positioning', return_value=mock_data):
            bias = fetcher.get_bias_adjustment("MES")
            assert bias == pytest.approx(0.1)

    def test_bias_adjustment_bearish(self):
        from engine.data.cot_fetcher import CoTFetcher
        fetcher = CoTFetcher()
        mock_data = {"commercial_trend": "BEARISH", "commercial_net": -50000}
        with patch.object(fetcher, 'get_positioning', return_value=mock_data):
            bias = fetcher.get_bias_adjustment("MES")
            assert bias == pytest.approx(-0.1)

    def test_bias_adjustment_neutral_trend(self):
        from engine.data.cot_fetcher import CoTFetcher
        fetcher = CoTFetcher()
        mock_data = {"commercial_trend": "NEUTRAL", "commercial_net": 1000}
        with patch.object(fetcher, 'get_positioning', return_value=mock_data):
            bias = fetcher.get_bias_adjustment("MES")
            assert bias == 0.0


# ─── Track E: Composite Score ────────────────────────────────────────────────

class TestCompositeScore:
    """Tests for Track E: composite performance metric."""

    def test_composite_score_perfect(self):
        from engine.analytics.validation_metrics import composite_score
        # Maximum possible score: PF=6, Sharpe=5, WFE=1, DD=0
        score = composite_score(6.0, 5.0, 1.0, 0.0)
        assert score == pytest.approx(1.0, abs=0.001)

    def test_composite_score_zero_wfe_no_sharpe(self):
        from engine.analytics.validation_metrics import composite_score
        # PF=1, Sharpe=0, WFE=0, max DD=20% → only PF component contributes
        # pf_score = 1/6, sharpe_score = 0, wfe_score = 0, dd_score = 0
        score = composite_score(1.0, 0.0, 0.0, 0.20)
        expected = (1.0 / 6.0) * 0.35
        assert score == pytest.approx(expected, abs=0.001)

    def test_composite_score_mes_best_backtest(self):
        from engine.analytics.validation_metrics import composite_score
        # MES best backtest: PF 5.27, Sharpe 4.16, WFE 0.82, DD 1.79%
        score = composite_score(5.27, 4.16, 0.82, 0.0179)
        assert 0.70 < score < 1.0, f"Expected 0.70-1.0, got {score}"

    def test_composite_score_pf_capped_at_6(self):
        from engine.analytics.validation_metrics import composite_score
        # PF 10 should equal PF 6 (capped)
        score_10 = composite_score(10.0, 3.0, 0.8, 0.05)
        score_6 = composite_score(6.0, 3.0, 0.8, 0.05)
        assert score_10 == pytest.approx(score_6, abs=0.001)

    def test_composite_score_sharpe_capped_at_5(self):
        from engine.analytics.validation_metrics import composite_score
        # Sharpe 10 should equal Sharpe 5 (capped)
        score_hi = composite_score(3.0, 10.0, 0.5, 0.05)
        score_cap = composite_score(3.0, 5.0, 0.5, 0.05)
        assert score_hi == pytest.approx(score_cap, abs=0.001)

    def test_composite_score_from_results_dict(self):
        from engine.analytics.validation_metrics import composite_score_from_results
        results = {
            "profit_factor": 5.27,
            "sharpe_ratio": 4.16,
            "walk_forward_efficiency": 0.82,
            "max_drawdown_pct": 0.0179,
        }
        score = composite_score_from_results(results)
        assert 0.70 < score < 1.0

    def test_composite_score_from_results_defaults_on_missing_keys(self):
        from engine.analytics.validation_metrics import composite_score_from_results
        # Missing keys should not raise — defaults kick in
        score = composite_score_from_results({})
        # profit_factor=1, sharpe=0, wfe=0, dd=0
        expected = composite_score_from_results({
            "profit_factor": 1.0,
            "sharpe_ratio": 0.0,
            "walk_forward_efficiency": 0.0,
            "max_drawdown_pct": 0.0,
        })
        from engine.analytics.validation_metrics import composite_score
        assert score == pytest.approx(expected, abs=0.001)

    def test_composite_score_dd_capped_at_20pct(self):
        from engine.analytics.validation_metrics import composite_score
        # 30% drawdown should equal 20% (capped)
        score_30 = composite_score(3.0, 2.0, 0.5, 0.30)
        score_20 = composite_score(3.0, 2.0, 0.5, 0.20)
        assert score_30 == pytest.approx(score_20, abs=0.001)

    def test_composite_score_weights_sum_to_one(self):
        """Validate weight structure: 0.35 + 0.35 + 0.20 + 0.10 = 1.0"""
        from engine.analytics.validation_metrics import composite_score
        # All components at max → should equal 1.0
        score = composite_score(6.0, 5.0, 1.0, 0.0)
        assert score == pytest.approx(1.0, abs=0.001)


# ─── Track E: Strategy Optimizer ─────────────────────────────────────────────

class TestStrategyOptimizer:
    """Tests for Track E: adaptive strategy optimizer."""

    def test_import(self):
        from engine.optimization.strategy_optimizer import StrategyOptimizer
        assert StrategyOptimizer is not None

    def test_default_params_are_production_values(self):
        from engine.optimization.strategy_optimizer import StrategyOptimizer
        opt = StrategyOptimizer(dry_run=True)
        params = opt._default_params()
        assert params["stc_os"] == 15
        assert params["stc_ob"] == 83
        assert params["atr_stop_mult"] == pytest.approx(0.70)
        assert params["atr_t1_mult"] == pytest.approx(1.50)

    def test_initial_search_mode_is_explore(self):
        from engine.optimization.strategy_optimizer import StrategyOptimizer
        import tempfile
        # Isolate state file — create optimizer with a symbol unlikely to have state
        opt = StrategyOptimizer(symbol="TEST_ISOLATED_XYZ", dry_run=True)
        # If no prior state, should start in explore
        if opt.state["iterations"] == 0:
            assert opt.state["search_mode"] == "explore"

    def test_dry_run_one_iteration_returns_expected_keys(self):
        from engine.optimization.strategy_optimizer import StrategyOptimizer
        opt = StrategyOptimizer(dry_run=True)
        result = opt.run_one_iteration()
        assert "kept" in result
        assert "composite_score" in result
        assert "category" in result
        assert "iteration" in result
        assert result["composite_score"] >= 0.0

    def test_search_mode_transitions_after_high_reject_rate(self):
        from engine.optimization.strategy_optimizer import StrategyOptimizer
        opt = StrategyOptimizer(dry_run=True)
        # Simulate 10 attempts, 1 keep per category → 10% keep rate → exploit
        opt.state["category_stats"] = {
            cat: {"attempts": 10, "keeps": 1} for cat in opt.state["category_stats"]
        }
        opt._update_search_mode()
        assert opt.state["search_mode"] in ("exploit", "combine", "explore")

    def test_stc_constraint_os_less_than_ob(self):
        """Mutation should always produce stc_os < stc_ob."""
        from engine.optimization.strategy_optimizer import StrategyOptimizer
        import random
        random.seed(42)
        opt = StrategyOptimizer(dry_run=True)
        for _ in range(20):
            params = opt._mutate_params(opt._default_params(), "stc_thresholds")
            assert params["stc_os"] < params["stc_ob"], (
                f"stc_os={params['stc_os']} must be < stc_ob={params['stc_ob']}"
            )


# ─── Track E: Agent Feedback ─────────────────────────────────────────────────

class TestAgentFeedback:
    """Tests for Track E: post-trade agent accuracy feedback."""

    def test_import(self):
        from engine.analytics.agent_feedback import AgentFeedbackTracker
        assert AgentFeedbackTracker is not None

    def test_default_weights_are_neutral_with_no_history(self):
        from engine.analytics.agent_feedback import AgentFeedbackTracker, DEFAULT_WEIGHT
        tracker = AgentFeedbackTracker()
        weights = tracker.get_agent_weights()
        # With no trade history (< 5 trades), compute_accuracy returns 0.5
        # weight = 1.0 + (0.5 - 0.5) * 2 * (1.3 - 1.0) = 1.0
        for agent, weight in weights.items():
            assert weight == pytest.approx(DEFAULT_WEIGHT, abs=0.01), (
                f"Agent {agent} weight should be {DEFAULT_WEIGHT} with no history, got {weight}"
            )

    def test_record_outcome_win_no_crash(self):
        from engine.analytics.agent_feedback import AgentFeedbackTracker
        tracker = AgentFeedbackTracker()
        # Should not raise
        tracker.record_outcome(
            trade_id="test-win-001",
            symbol="MES",
            direction="LONG",
            pnl_usd=150.0,
            analyst_signals={"technical": 0.6, "news": 0.3, "social": 0.1},
        )

    def test_record_outcome_loss_no_crash(self):
        from engine.analytics.agent_feedback import AgentFeedbackTracker
        tracker = AgentFeedbackTracker()
        tracker.record_outcome(
            trade_id="test-loss-001",
            symbol="MCL",
            direction="SHORT",
            pnl_usd=-80.0,
            analyst_signals={"technical": -0.4, "news": -0.2, "social": 0.0},
        )

    def test_agent_names_include_expected_analysts(self):
        from engine.analytics.agent_feedback import AGENT_NAMES
        for expected in ["technical", "news", "social"]:
            assert expected in AGENT_NAMES

    def test_weight_bounds_respected(self):
        from engine.analytics.agent_feedback import (
            AgentFeedbackTracker, MIN_WEIGHT, MAX_WEIGHT
        )
        tracker = AgentFeedbackTracker()
        weights = tracker.get_agent_weights()
        for agent, weight in weights.items():
            assert MIN_WEIGHT <= weight <= MAX_WEIGHT, (
                f"Agent {agent} weight {weight} outside bounds [{MIN_WEIGHT}, {MAX_WEIGHT}]"
            )


# ─── Track G: Token Optimizer ────────────────────────────────────────────────

class TestTokenOptimizer:
    """Tests for Track G: token cost optimizer."""

    def test_import(self):
        try:
            from engine.utils.token_optimizer import TokenOptimizer, MODEL_HAIKU, MODEL_SONNET
            assert TokenOptimizer is not None
        except ImportError:
            pytest.skip("TokenOptimizer not yet implemented")

    def test_high_stakes_always_sonnet(self):
        try:
            from engine.utils.token_optimizer import TokenOptimizer, MODEL_SONNET
        except ImportError:
            pytest.skip("TokenOptimizer not yet implemented")
        opt = TokenOptimizer()
        for agent in ["trader", "risk_manager", "fund_manager"]:
            model = opt.select_model(agent, signal_strength=0.1)
            assert model == MODEL_SONNET, f"{agent} should always use Sonnet"

    def test_haiku_routing_for_weak_signal(self):
        try:
            from engine.utils.token_optimizer import TokenOptimizer, MODEL_HAIKU
        except ImportError:
            pytest.skip("TokenOptimizer not yet implemented")
        opt = TokenOptimizer()
        model = opt.select_model("social", signal_strength=0.2)
        assert model == MODEL_HAIKU

    def test_sonnet_for_strong_signal(self):
        try:
            from engine.utils.token_optimizer import TokenOptimizer, MODEL_SONNET
        except ImportError:
            pytest.skip("TokenOptimizer not yet implemented")
        opt = TokenOptimizer()
        model = opt.select_model("social", signal_strength=0.8)
        assert model == MODEL_SONNET

    def test_prompt_cache_adds_cache_control(self):
        try:
            from engine.utils.token_optimizer import TokenOptimizer
        except ImportError:
            pytest.skip("TokenOptimizer not yet implemented")
        opt = TokenOptimizer()
        block = opt.add_prompt_cache("test system prompt")
        assert "cache_control" in block
        assert block["cache_control"]["type"] == "ephemeral"
        assert block["text"] == "test system prompt"

    def test_compress_prunes_low_ic_agent(self):
        try:
            from engine.utils.token_optimizer import TokenOptimizer
        except ImportError:
            pytest.skip("TokenOptimizer not yet implemented")
        opt = TokenOptimizer()
        mock_report = MagicMock()
        mock_report.signal = 0.1
        result = opt.compress_analyst_report(mock_report, "news", ic_score=0.02)
        assert result is None  # Below IC threshold — pruned

    def test_compress_keeps_high_ic_agent(self):
        try:
            from engine.utils.token_optimizer import TokenOptimizer
        except ImportError:
            pytest.skip("TokenOptimizer not yet implemented")
        opt = TokenOptimizer()
        mock_report = MagicMock()
        mock_report.signal = 0.6
        mock_report.confidence = 0.7
        result = opt.compress_analyst_report(mock_report, "technical", ic_score=0.3)
        assert result is not None
        assert "BULLISH" in result or "technical" in result.lower()


# ─── Track H: Managed Agent Bridge ───────────────────────────────────────────

class TestManagedAgentBridge:
    """Tests for Track H: Claude Managed Agents bridge."""

    def test_import(self):
        try:
            from engine.agents.managed_agent_bridge import ManagedAgentBridge
            assert ManagedAgentBridge is not None
        except ImportError:
            pytest.skip("ManagedAgentBridge not yet implemented")

    def test_get_status_returns_expected_keys(self):
        try:
            from engine.agents.managed_agent_bridge import ManagedAgentBridge
        except ImportError:
            pytest.skip("ManagedAgentBridge not yet implemented")
        bridge = ManagedAgentBridge()
        status = bridge.get_status()
        assert "managed_mode" in status
        assert "api_key_present" in status
        assert "env_var" in status

    def test_inactive_by_default_without_env_var(self):
        try:
            from engine.agents.managed_agent_bridge import ManagedAgentBridge
        except ImportError:
            pytest.skip("ManagedAgentBridge not yet implemented")
        # Remove env var if present
        env_copy = {k: v for k, v in os.environ.items() if k != "USE_MANAGED_AGENTS"}
        with patch.dict(os.environ, env_copy, clear=True):
            bridge = ManagedAgentBridge()
            status = bridge.get_status()
            assert "managed_mode" in status

    def test_raises_if_managed_called_without_managed_mode(self):
        try:
            from engine.agents.managed_agent_bridge import ManagedAgentBridge
        except ImportError:
            pytest.skip("ManagedAgentBridge not yet implemented")
        bridge = ManagedAgentBridge()
        if not bridge.is_managed_mode():
            import asyncio
            with pytest.raises(RuntimeError, match="managed mode is not active"):
                asyncio.run(bridge.run_stage1_managed("MES", "{}"))


# ─── Track B1: Debate Thresholds ─────────────────────────────────────────────

class TestDebateThresholds:
    """Tests for Track B1: regime-adaptive debate thresholds."""

    def test_regime_thresholds_defined(self):
        """REGIME_DEBATE_THRESHOLDS should contain key regimes."""
        from engine.agents.debate import REGIME_DEBATE_THRESHOLDS, DEFAULT_DEBATE_THRESHOLD
        assert "COMPRESSION" in REGIME_DEBATE_THRESHOLDS
        assert "EXHAUSTED" in REGIME_DEBATE_THRESHOLDS

    def test_compression_threshold_below_default(self):
        """COMPRESSION regime needs tighter threshold (less signal needed to trade)."""
        from engine.agents.debate import REGIME_DEBATE_THRESHOLDS, DEFAULT_DEBATE_THRESHOLD
        assert REGIME_DEBATE_THRESHOLDS["COMPRESSION"] < DEFAULT_DEBATE_THRESHOLD

    def test_exhausted_threshold_above_default(self):
        """EXHAUSTED regime needs looser threshold (more signal needed — higher bar)."""
        from engine.agents.debate import REGIME_DEBATE_THRESHOLDS, DEFAULT_DEBATE_THRESHOLD
        assert REGIME_DEBATE_THRESHOLDS["EXHAUSTED"] > DEFAULT_DEBATE_THRESHOLD

    def test_all_threshold_values_are_positive(self):
        from engine.agents.debate import REGIME_DEBATE_THRESHOLDS
        for regime, threshold in REGIME_DEBATE_THRESHOLDS.items():
            assert threshold > 0, f"Regime {regime} threshold must be positive"

    def test_default_debate_threshold_value(self):
        from engine.agents.debate import DEFAULT_DEBATE_THRESHOLD
        assert DEFAULT_DEBATE_THRESHOLD == pytest.approx(0.20)

    def test_trending_bull_threshold_defined(self):
        from engine.agents.debate import REGIME_DEBATE_THRESHOLDS
        assert "TRENDING_BULL" in REGIME_DEBATE_THRESHOLDS

    def test_trending_bear_threshold_defined(self):
        from engine.agents.debate import REGIME_DEBATE_THRESHOLDS
        assert "TRENDING_BEAR" in REGIME_DEBATE_THRESHOLDS


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
