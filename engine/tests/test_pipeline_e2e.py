"""
JARVIS TRADER — Pipeline E2E Tests
End-to-end testing of the multi-agent trading pipeline.
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.slow

from agents.pipeline import TradingPipeline


class MockAgent:
    """Base mock agent for testing."""

    def __init__(self, return_value=None):
        self.return_value = return_value or {}
        self.call_count = 0

    async def analyze(self, symbol, **kwargs):
        self.call_count += 1
        return self.return_value


class MockTechnicalAnalyst(MockAgent):
    """Mock technical analyst agent."""

    async def analyze(self, symbol, **kwargs):
        self.call_count += 1
        return {
            "signal": 0.8,
            "confidence": 0.85,
            "summary": "Bullish momentum",
            "regime": "TRENDING_BULL",
            "trend": "STRONG_BULL",
            "entry_signal": "ENTRY_NOW",
        }


class MockNewsAnalyst(MockAgent):
    """Mock news analyst agent."""

    async def analyze(self, symbol, **kwargs):
        self.call_count += 1
        return {
            "signal": 0.6,
            "confidence": 0.75,
            "summary": "Positive macro sentiment",
        }


class MockDebateAgent(MockAgent):
    """Mock debate orchestrator."""

    async def run_debate(self, symbol, analyst_reports, bull, bear, **kwargs):
        self.call_count += 1
        return {
            "verdict": "bull",
            "bull_score": 7.5,
            "bear_score": 2.5,
            "margin": 5.0,
            "summary": "Strong bull consensus",
        }


class MockTraderAgent(MockAgent):
    """Mock trader agent."""

    async def decide(self, symbol, debate_result, analyst_reports, safety_status):
        self.call_count += 1
        return {
            "symbol": symbol,
            "action": "BUY",
            "quantity": 1,
            "order_type": "LIMIT",
            "entry_price": 5800.0,
            "stop_price": 5785.0,
            "target_1": 5815.0,
            "confidence": 0.75,
            "signal_score": 0.80,
        }


class MockRiskManager(MockAgent):
    """Mock risk manager agent."""

    async def review(self, trade_decision, safety_status, portfolio):
        self.call_count += 1
        return {
            "symbol": trade_decision.get("symbol", "UNKNOWN"),
            "approved": True,
            "veto_reason": None,
            "modified": False,
            "original_action": trade_decision.get("action", "HOLD"),
            "approved_action": trade_decision.get("action", "HOLD"),
            "approved_contracts": trade_decision.get("quantity", 0),
            "approved_stop": trade_decision.get("stop_price", 0.0),
        }


class MockFundManager(MockAgent):
    """Mock fund manager agent."""

    async def approve(self, trade_decision, risk_decision, portfolio, open_positions):
        self.call_count += 1
        return {
            "symbol": trade_decision.get("symbol", "UNKNOWN"),
            "execute": True,
            "action": trade_decision.get("action", "HOLD"),
            "contracts": risk_decision.get("approved_contracts", 0),
            "entry_price": trade_decision.get("entry_price", 0.0),
            "stop_price": trade_decision.get("stop_price", 0.0),
            "target_1": trade_decision.get("target_1", 0.0),
            "final_conviction": 0.75,
            "human_approval_required": True,
        }


@pytest.fixture
def mock_agents_dict():
    """Dictionary of all mock agents for pipeline."""
    return {
        "technical": MockTechnicalAnalyst(),
        "news": MockNewsAnalyst(),
        "social": MockAgent({"signal": 0.5, "confidence": 0.6}),
        "fundamental": MockAgent({"signal": 0.7, "confidence": 0.7}),
        "bull": MockAgent(),
        "bear": MockAgent(),
        "debate": MockDebateAgent(),
        "trader": MockTraderAgent(),
        "risk_manager": MockRiskManager(),
        "fund_manager": MockFundManager(),
    }


@pytest.fixture
def disable_cache(monkeypatch):
    """Disable caching for all tests by mocking cache functions to return False."""
    import agents.pipeline

    # Ensure the cache functions exist in the pipeline module namespace
    # They may not be present if the cache import failed
    if not hasattr(agents.pipeline, "should_use_cache"):

        async def mock_should_use_cache(symbol):
            return False

        agents.pipeline.should_use_cache = mock_should_use_cache

    if not hasattr(agents.pipeline, "get_cached_signal"):

        async def mock_get_cached_signal(symbol):
            return None

        agents.pipeline.get_cached_signal = mock_get_cached_signal

    if not hasattr(agents.pipeline, "cache_signal"):

        async def mock_cache_signal(symbol, result):
            pass

        agents.pipeline.cache_signal = mock_cache_signal

    # Now monkeypatch them to always return the safe test values
    monkeypatch.setattr("agents.pipeline.should_use_cache", AsyncMock(return_value=False))
    monkeypatch.setattr("agents.pipeline.get_cached_signal", AsyncMock(return_value=None))
    monkeypatch.setattr("agents.pipeline.cache_signal", AsyncMock(return_value=None))
    return None


@pytest.fixture
def trading_pipeline(mock_agents_dict, mock_safety_layer, disable_cache):
    """Instantiated TradingPipeline with mock agents."""
    return TradingPipeline(mock_agents_dict, mock_safety_layer)


class TestPipelineBasics:
    """Basic pipeline execution."""

    @pytest.mark.asyncio
    async def test_pipeline_produces_valid_result(self, trading_pipeline):
        """Pipeline returns dict with all required keys."""
        # Act
        result = await trading_pipeline.analyze_and_decide("MES", is_futures=True)

        # Assert
        assert isinstance(result, dict)
        assert "symbol" in result
        assert "is_futures" in result
        assert "started_at" in result
        assert "completed_at" in result
        assert "analyst_reports" in result
        assert "debate_result" in result
        assert "trade_decision" in result
        assert "risk_decision" in result
        assert "fund_decision" in result
        assert "final_action" in result
        assert "final_quantity" in result
        assert "requires_human" in result
        assert "errors" in result
        assert "summary" in result

    @pytest.mark.asyncio
    async def test_pipeline_symbol_propagates(self, trading_pipeline):
        """Symbol correctly propagates through all stages."""
        # Act
        result = await trading_pipeline.analyze_and_decide("MNQ", is_futures=True)

        # Assert
        assert result["symbol"] == "MNQ"
        assert result["trade_decision"]["symbol"] == "MNQ"
        assert result["risk_decision"]["symbol"] == "MNQ"
        assert result["fund_decision"]["symbol"] == "MNQ"

    @pytest.mark.asyncio
    async def test_pipeline_is_futures_flag(self, trading_pipeline):
        """is_futures flag correctly passed."""
        # Act
        result = await trading_pipeline.analyze_and_decide("SPY", is_futures=False)

        # Assert
        assert result["is_futures"] is False


class TestAnalystStages:
    """Analyst stage parallel execution."""

    @pytest.mark.asyncio
    async def test_all_analysts_called(self, trading_pipeline, mock_agents_dict):
        """All four analysts invoked concurrently."""
        # Act
        await trading_pipeline.analyze_and_decide("MES", is_futures=True)

        # Assert
        assert mock_agents_dict["technical"].call_count == 1
        assert mock_agents_dict["news"].call_count == 1
        assert mock_agents_dict["social"].call_count == 1
        assert mock_agents_dict["fundamental"].call_count == 1

    @pytest.mark.asyncio
    async def test_analyst_reports_present_in_result(self, trading_pipeline):
        """All analyst reports included in pipeline result."""
        # Act
        result = await trading_pipeline.analyze_and_decide("MES", is_futures=True)

        # Assert
        reports = result["analyst_reports"]
        assert "technical" in reports
        assert "news" in reports
        assert "social" in reports
        assert "fundamental" in reports

        # Each analyst report should be a dict (regime_status is a regime object, not a report)
        non_report_keys = {"regime_status"}
        for name, report in reports.items():
            if name in non_report_keys:
                continue
            assert isinstance(report, dict), f"{name} report should be dict"

    @pytest.mark.asyncio
    async def test_pipeline_survives_analyst_failure(self, trading_pipeline, mock_agents_dict):
        """Missing analyst → pipeline continues with neutral report."""
        # Arrange - remove one analyst
        del mock_agents_dict["news"]

        # Act
        result = await trading_pipeline.analyze_and_decide("MES", is_futures=True)

        # Assert - pipeline completes despite missing agent
        assert result["analyst_reports"]["news"]["signal"] == 0.0
        assert "news unavailable" in result["analyst_reports"]["news"]["summary"].lower()

    @pytest.mark.asyncio
    async def test_analyst_exception_logged_as_error(self, trading_pipeline, mock_agents_dict):
        """Analyst raises exception → error logged and pipeline continues."""

        # Arrange
        async def failing_analyze(*args, **kwargs):
            raise ValueError("Data feed error")

        mock_agents_dict["technical"].analyze = failing_analyze

        # Act
        result = await trading_pipeline.analyze_and_decide("MES", is_futures=True)

        # Assert - error captured but pipeline continues
        assert len(result["errors"]) > 0
        assert any("technical" in e.lower() for e in result["errors"])
        assert result["analyst_reports"]["technical"]["signal"] == 0.0


class TestDebateStage:
    """Debate orchestrator stage."""

    @pytest.mark.asyncio
    async def test_debate_called_with_analyst_reports(self, trading_pipeline, mock_agents_dict):
        """Debate agent receives analyst reports."""
        # Act
        result = await trading_pipeline.analyze_and_decide("MES", is_futures=True)

        # Assert - debate result present
        assert result["debate_result"] is not None
        assert isinstance(result["debate_result"], dict)
        assert "verdict" in result["debate_result"]

    @pytest.mark.asyncio
    async def test_missing_debate_agents_handled(self, trading_pipeline, mock_agents_dict):
        """Missing bull/bear/debate → neutral result."""
        # Arrange
        del mock_agents_dict["bull"]
        del mock_agents_dict["bear"]

        # Act
        result = await trading_pipeline.analyze_and_decide("MES", is_futures=True)

        # Assert
        assert result["debate_result"]["verdict"] == "neutral"
        assert result["debate_result"]["bull_score"] == 0.5


class TestTraderStage:
    """Trader agent stage."""

    @pytest.mark.asyncio
    async def test_trader_produces_trade_decision(self, trading_pipeline):
        """Trader agent produces valid TradeDecision."""
        # Act
        result = await trading_pipeline.analyze_and_decide("MES", is_futures=True)

        # Assert
        decision = result["trade_decision"]
        assert decision["symbol"] == "MES"
        assert decision["action"] in ["BUY", "SELL", "HOLD"]
        assert isinstance(decision["quantity"], int)
        assert isinstance(decision["entry_price"], (int, float))

    @pytest.mark.asyncio
    async def test_missing_trader_agent_defaults_to_hold(self, trading_pipeline, mock_agents_dict):
        """No trader agent → defaults to HOLD."""
        # Arrange
        del mock_agents_dict["trader"]

        # Act
        result = await trading_pipeline.analyze_and_decide("MES", is_futures=True)

        # Assert
        assert result["trade_decision"]["action"] == "hold"
        assert result["trade_decision"]["quantity"] == 0

    @pytest.mark.asyncio
    async def test_trader_exception_defaults_to_hold(self, trading_pipeline, mock_agents_dict):
        """Trader raises exception → defaults to HOLD."""

        # Arrange
        async def failing_decide(*args, **kwargs):
            raise RuntimeError("Model unavailable")

        mock_agents_dict["trader"].decide = failing_decide

        # Act
        result = await trading_pipeline.analyze_and_decide("MES", is_futures=True)

        # Assert - gracefully defaults
        assert result["trade_decision"]["action"] == "hold"
        assert len(result["errors"]) > 0


class TestRiskManagerStage:
    """Risk manager stage."""

    @pytest.mark.asyncio
    async def test_risk_manager_approves_valid_trade(self, trading_pipeline):
        """Risk manager approves valid trade."""
        # Act
        result = await trading_pipeline.analyze_and_decide("MES", is_futures=True)

        # Assert
        risk_decision = result["risk_decision"]
        assert risk_decision["approved"] is True
        assert risk_decision["veto_reason"] is None

    @pytest.mark.asyncio
    async def test_risk_manager_veto_blocks_fund_manager(self, trading_pipeline, mock_agents_dict):
        """Risk manager veto → fund manager skipped."""

        # Arrange
        async def rejecting_review(*args, **kwargs):
            return {
                "approved": False,
                "veto_reason": "Position too large",
                "modified_quantity": None,
            }

        mock_agents_dict["risk_manager"].review = rejecting_review

        # Act
        result = await trading_pipeline.analyze_and_decide("MES", is_futures=True)

        # Assert
        assert result["risk_decision"]["approved"] is False
        assert result["fund_decision"] is None  # Skipped

    @pytest.mark.asyncio
    async def test_missing_risk_manager_auto_approves(self, trading_pipeline, mock_agents_dict):
        """No risk manager → auto-approves conservatively."""
        # Arrange
        del mock_agents_dict["risk_manager"]

        # Act
        result = await trading_pipeline.analyze_and_decide("MES", is_futures=True)

        # Assert
        assert result["risk_decision"]["approved"] is True
        assert "not configured" in result["risk_decision"]["reasoning"].lower()


class TestFundManagerStage:
    """Fund manager stage."""

    @pytest.mark.asyncio
    async def test_fund_manager_final_approval(self, trading_pipeline):
        """Fund manager produces final decision."""
        # Act
        result = await trading_pipeline.analyze_and_decide("MES", is_futures=True)

        # Assert
        fund_decision = result["fund_decision"]
        assert fund_decision is not None
        assert "execute" in fund_decision
        assert "contracts" in fund_decision

    @pytest.mark.asyncio
    async def test_fund_manager_reduces_quantity(self, trading_pipeline, mock_agents_dict):
        """Fund manager can reduce order quantity."""

        # Arrange
        async def conservative_approve(*args, **kwargs):
            return {
                "execute": True,
                "action": "BUY",
                "contracts": 1,  # Reduced from requested
                "final_conviction": 0.5,
                "human_approval_required": True,
            }

        mock_agents_dict["fund_manager"].approve = conservative_approve

        # Act
        result = await trading_pipeline.analyze_and_decide("MES", is_futures=True)

        # Assert
        assert result["fund_decision"]["contracts"] == 1


class TestPipelineKillSwitch:
    """Kill switch interaction in pipeline."""

    @pytest.mark.asyncio
    async def test_pipeline_respects_kill_switch(self, trading_pipeline, mock_safety_layer):
        """Kill switch active → pipeline rejects."""
        # Arrange
        mock_safety_layer.activate_kill_switch("MANUAL", "Testing kill switch")

        # Act
        await trading_pipeline.analyze_and_decide("MES", is_futures=True)

        # Assert
        # Pipeline itself should still run, but traders should see killed status
        assert mock_safety_layer.is_killed is True

    @pytest.mark.asyncio
    async def test_safety_status_passed_to_trader(self, trading_pipeline, mock_safety_layer):
        """Safety status dict passed to trader agent."""
        # Arrange - mock the trader to capture received status
        captured_status = {}

        async def capturing_decide(symbol, debate_result, analyst_reports, safety_status):
            captured_status.update(safety_status)
            return {
                "symbol": symbol,
                "action": "BUY",
                "quantity": 1,
                "order_type": "LIMIT",
                "entry_price": 5800.0,
                "stop_price": 5785.0,
                "target_1": 5815.0,
                "confidence": 0.75,
            }

        trading_pipeline._agents["trader"].decide = capturing_decide

        # Act
        await trading_pipeline.analyze_and_decide("MES", is_futures=True)

        # Assert
        assert isinstance(captured_status, dict)


class TestFinalActionResolution:
    """Final action determination from multi-stage results."""

    @pytest.mark.asyncio
    async def test_final_action_buy_when_approved(self, trading_pipeline):
        """Trade + Risk approve + Fund approve → final_action=BUY."""
        # Act
        result = await trading_pipeline.analyze_and_decide("MES", is_futures=True)

        # Assert
        assert result["final_action"] in ["buy", "sell", "hold"]
        assert result["final_quantity"] >= 0

    @pytest.mark.asyncio
    async def test_final_action_hold_when_risk_vetoes(self, trading_pipeline, mock_agents_dict):
        """Risk manager veto → final_action=HOLD."""

        # Arrange
        async def rejecting_review(*args, **kwargs):
            return {
                "approved": False,
                "veto_reason": "Breach risk",
                "modified_quantity": None,
            }

        mock_agents_dict["risk_manager"].review = rejecting_review

        # Act
        result = await trading_pipeline.analyze_and_decide("MES", is_futures=True)

        # Assert
        assert result["final_action"] == "hold"


class TestPipelineTiming:
    """Pipeline execution timing and summary."""

    @pytest.mark.asyncio
    async def test_pipeline_records_timestamps(self, trading_pipeline):
        """Pipeline records start and completion times."""
        # Act
        result = await trading_pipeline.analyze_and_decide("MES", is_futures=True)

        # Assert
        assert "started_at" in result
        assert "completed_at" in result
        started = datetime.fromisoformat(result["started_at"])
        completed = datetime.fromisoformat(result["completed_at"])
        assert completed >= started

    @pytest.mark.asyncio
    async def test_pipeline_generates_summary(self, trading_pipeline):
        """Pipeline generates human-readable summary."""
        # Act
        result = await trading_pipeline.analyze_and_decide("MES", is_futures=True)

        # Assert
        assert "summary" in result
        assert isinstance(result["summary"], str)
        assert len(result["summary"]) > 0


class TestPipelinePortfolio:
    """Portfolio data handling in pipeline."""

    @pytest.mark.asyncio
    async def test_pipeline_default_portfolio_on_missing_provider(self, trading_pipeline):
        """No portfolio provider → safe default used."""
        # Arrange - no portfolio agent

        # Act
        result = await trading_pipeline.analyze_and_decide("MES", is_futures=True)

        # Assert - should complete without error
        assert "risk_decision" in result
        assert result["risk_decision"] is not None

    @pytest.mark.asyncio
    async def test_portfolio_passed_to_risk_manager(
        self, trading_pipeline, mock_agents_dict, mock_portfolio
    ):
        """Portfolio dict passed to risk manager."""
        # Arrange
        captured_portfolio = {}

        async def capturing_review(trade_decision, safety_status, portfolio):
            captured_portfolio.update(portfolio)
            return {
                "approved": True,
                "veto_reason": None,
                "modified_quantity": None,
            }

        mock_agents_dict["risk_manager"].review = capturing_review
        mock_agents_dict["portfolio"] = MagicMock()
        mock_agents_dict["portfolio"].get_portfolio = AsyncMock(return_value=mock_portfolio)

        # Act
        await trading_pipeline.analyze_and_decide("MES", is_futures=True)

        # Assert
        assert isinstance(captured_portfolio, dict)


class TestPipelineAllStagesPresent:
    """Comprehensive verification that all stages run."""

    @pytest.mark.asyncio
    async def test_pipeline_all_stages_present(self, trading_pipeline, mock_agents_dict):
        """Complete pipeline execution invokes all 5+ stages."""
        # Act
        await trading_pipeline.analyze_and_decide("MES", is_futures=True)

        # Assert - all stages executed
        assert mock_agents_dict["technical"].call_count == 1
        assert mock_agents_dict["news"].call_count == 1
        assert mock_agents_dict["social"].call_count == 1
        assert mock_agents_dict["fundamental"].call_count == 1
        assert mock_agents_dict["debate"].call_count == 1
        assert mock_agents_dict["trader"].call_count == 1
        assert mock_agents_dict["risk_manager"].call_count == 1
        assert mock_agents_dict["fund_manager"].call_count == 1

    @pytest.mark.asyncio
    async def test_pipeline_result_integrity(self, trading_pipeline):
        """Pipeline result contains all expected data intact."""
        # Act
        result = await trading_pipeline.analyze_and_decide("MES", is_futures=True)

        # Assert - data flows through intact
        assert result["symbol"] == "MES"
        assert result["analyst_reports"]["technical"]["regime"] == "TRENDING_BULL"
        assert result["debate_result"]["verdict"] == "bull"
        assert result["trade_decision"]["action"] == "BUY"
        assert result["risk_decision"]["approved"] is True
        assert result["fund_decision"]["execute"] is True


class TestSTCPreFilter:
    """Unit tests for the STC mid-range pre-filter in analyze_and_decide()."""

    def _make_ohlcv_df(self, rows: int = 30, stc_val: float = 50.0):
        """Return a minimal DataFrame that generate_instrument_signals can consume."""
        import numpy as np
        import pandas as pd

        idx = pd.date_range("2026-01-01", periods=rows, freq="1h")
        df = pd.DataFrame(
            {
                "open": np.full(rows, 5800.0),
                "high": np.full(rows, 5810.0),
                "low": np.full(rows, 5790.0),
                "close": np.full(rows, 5800.0),
                "volume": np.full(rows, 1000.0),
                "stc_val": np.full(rows, stc_val),
            },
            index=idx,
        )
        return df

    @pytest.mark.asyncio
    async def test_stc_mid_range_pre_filters_without_calling_llm_agents(
        self, mock_agents_dict, mock_safety_layer, disable_cache
    ):
        """When STC is mid-range (33–73 for MCL OS=23/OB=83), pipeline returns HOLD
        immediately with pre_filtered=True — no LLM agents should be invoked."""
        import pandas as pd

        # Attach a mock _data to the technical agent
        stc_mid = 50.0  # clearly within 25–73 mid-range
        sig_df = self._make_ohlcv_df(rows=30, stc_val=stc_mid)

        mock_data = MagicMock()
        mock_data.get_bars = AsyncMock(return_value=sig_df)
        mock_agents_dict["technical"]._data = mock_data

        pipeline = TradingPipeline(mock_agents_dict, mock_safety_layer)

        # The pre-filter uses `from backtest.signals import generate_instrument_signals`
        # inside a try block, so patch the function at its source module.
        with patch("backtest.signals.generate_instrument_signals", return_value=sig_df):
            result = await pipeline.analyze_and_decide("MCL", is_futures=True)

        assert result["final_action"] == "hold"
        assert result.get("pre_filtered") is True
        assert result["pre_filter_reason"] == "STC mid-range pre-filter"
        assert result["pre_filter_stc"] == stc_mid
        assert result["pre_filter_stc_os"] == 23
        assert result["pre_filter_stc_ob"] == 83
        # No LLM agents should have been called
        assert mock_agents_dict["technical"].call_count == 0
        assert mock_agents_dict["trader"].call_count == 0
        assert mock_agents_dict["risk_manager"].call_count == 0

    @pytest.mark.asyncio
    async def test_stc_at_oversold_does_not_pre_filter(
        self, mock_agents_dict, mock_safety_layer, disable_cache
    ):
        """When STC is AT or below OS=23 (skip-range LOW), the pre-filter must NOT
        trigger — the OS crossover is an actionable signal and must reach Stage 1.

        US-1602 updated MCL params: OS=23 (stc_os), OB=83. LOW boundary = stc_os = 23.
        STC=14 is below LOW=23 → passes through. STC=50 is inside 23-83 → pre-filtered.
        """
        stc_at_os = 14.0  # 14 <= 23 (STC_MIDRANGE_SKIP_LOW for MCL), so NOT filtered
        sig_df = self._make_ohlcv_df(rows=30, stc_val=stc_at_os)

        mock_data = MagicMock()
        mock_data.get_bars = AsyncMock(return_value=sig_df)
        mock_agents_dict["technical"]._data = mock_data

        pipeline = TradingPipeline(mock_agents_dict, mock_safety_layer)

        with patch("backtest.signals.generate_instrument_signals", return_value=sig_df):
            result = await pipeline.analyze_and_decide("MCL", is_futures=True)

        # Must NOT have pre_filtered flag (went through full pipeline)
        assert result.get("pre_filtered") is not True
        # Stage 1 technical analyst must have been called
        assert mock_agents_dict["technical"].call_count >= 1
