"""
Test suite for JarvisLLMClient and CostTracker.

Tests:
- Token cost calculation
- Cost tracking to SQLite
- Daily and monthly statistics
- Retry logic (mocked)
"""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from llm import JarvisLLMClient
from llm.cost_tracker import CostTracker


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    db_path = "/tmp/test_llm_costs.db"
    yield db_path
    # Cleanup
    Path(db_path).unlink(missing_ok=True)


@pytest.fixture
async def cost_tracker(temp_db):
    """Create a CostTracker instance."""
    tracker = CostTracker(db_path=temp_db)
    yield tracker
    await tracker.close()


@pytest.fixture
async def llm_client(temp_db):
    """Create a JarvisLLMClient instance."""
    client = JarvisLLMClient(api_key="test-key-12345", db_path=temp_db)
    yield client
    await client.close()


class TestCostCalculation:
    """Test cost calculation for different models."""

    def test_opus_cost_calculation(self, llm_client):
        """Test cost calculation for Opus model."""
        cost = llm_client._calculate_cost(
            model="claude-opus-4-7",
            input_tokens=100_000,  # 0.1M
            output_tokens=50_000,  # 0.05M
        )
        # Opus: $15 per MTok input + $75 per MTok output
        # Input: 0.1 * 15 = $1.50
        # Output: 0.05 * 75 = $3.75
        # Total: $5.25
        assert cost == pytest.approx(5.25, rel=0.01)

    def test_sonnet_cost_calculation(self, llm_client):
        """Test cost calculation for Sonnet model."""
        cost = llm_client._calculate_cost(
            model="claude-sonnet-4-6",
            input_tokens=100_000,
            output_tokens=50_000,
        )
        # Sonnet: $3 per MTok input + $15 per MTok output
        # Input: 0.1 * 3 = $0.30
        # Output: 0.05 * 15 = $0.75
        # Total: $1.05
        assert cost == pytest.approx(1.05, rel=0.01)

    def test_haiku_cost_calculation(self, llm_client):
        """Test cost calculation for Haiku model."""
        cost = llm_client._calculate_cost(
            model="claude-haiku-4-5-20251001",
            input_tokens=100_000,
            output_tokens=50_000,
        )
        # Haiku: $0.80 per MTok input + $4 per MTok output
        # Input: 0.1 * 0.80 = $0.08
        # Output: 0.05 * 4 = $0.20
        # Total: $0.28
        assert cost == pytest.approx(0.28, rel=0.01)


class TestCostTracking:
    """Test cost tracking to SQLite."""

    @pytest.mark.asyncio
    async def test_log_call(self, cost_tracker):
        """Test logging a single call."""
        await cost_tracker.log_call(
            timestamp=datetime.now(timezone.utc).isoformat(),
            model="claude-opus-4-7",
            input_tokens=100,
            output_tokens=50,
            cost_usd=1.50,
            latency_ms=1200,
            agent_name="technical_analyst",
            success=True,
        )

        # Query the database
        conn = sqlite3.connect(cost_tracker.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM llm_calls")
        count = cursor.fetchone()[0]
        conn.close()

        assert count == 1

    @pytest.mark.asyncio
    async def test_daily_summary(self, cost_tracker):
        """Test daily summary calculation."""
        now = datetime.now(timezone.utc)

        # Log multiple calls
        for i in range(5):
            await cost_tracker.log_call(
                timestamp=now.isoformat(),
                model="claude-opus-4-7",
                input_tokens=1000,
                output_tokens=500,
                cost_usd=0.05,
                latency_ms=800,
                agent_name="agent_" + str(i),
                success=i < 4,  # 4 successful, 1 failed
            )

        stats = await cost_tracker.get_daily_summary(days_back=0)

        assert stats["total_calls"] == 5
        assert stats["total_cost_usd"] == pytest.approx(0.25, rel=0.01)
        assert stats["success_rate"] == pytest.approx(0.8, rel=0.01)
        assert "claude-opus-4-7" in stats["per_model"]

    @pytest.mark.asyncio
    async def test_monthly_summary(self, cost_tracker):
        """Test monthly summary with daily breakdown."""
        now = datetime.now(timezone.utc)

        # Log 10 calls — normalise to midnight so all records fall before any
        # month_start timestamp computed inside get_monthly_summary (which uses
        # the current wall-clock time, not midnight).
        for i in range(10):
            await cost_tracker.log_call(
                timestamp=now.replace(
                    day=min(i + 1, 28), hour=0, minute=0, second=0, microsecond=0
                ).isoformat(),
                model="claude-sonnet-4-6",
                input_tokens=500,
                output_tokens=200,
                cost_usd=0.02,
                latency_ms=600,
                agent_name="news_analyst",
                success=True,
            )

        stats = await cost_tracker.get_monthly_summary(months_back=0)

        assert stats["total_calls"] == 10
        assert stats["total_cost_usd"] == pytest.approx(0.20, rel=0.01)
        assert len(stats["daily_breakdown"]) > 0
        assert "claude-sonnet-4-6" in stats["per_model"]


class TestFallbackChain:
    """Test model fallback behavior."""

    def test_fallback_chain_mapping(self, llm_client):
        """Test that fallback chain is correctly defined."""
        assert llm_client.FALLBACK_CHAIN["claude-opus-4-7"] == "claude-sonnet-4-6"
        assert llm_client.FALLBACK_CHAIN["claude-sonnet-4-6"] == "claude-haiku-4-5-20251001"
        assert llm_client.FALLBACK_CHAIN["claude-haiku-4-5-20251001"] is None


class TestLLMCallResult:
    """Test LLM call result handling."""

    def test_successful_call_result(self, llm_client):
        """Test result structure for successful calls."""
        from llm.client import LLMCallResult

        result = LLMCallResult(
            success=True,
            model="claude-opus-4-7",
            input_tokens=100,
            output_tokens=50,
            cost_usd=0.10,
            latency_ms=800,
            retries=0,
            content="Test response",
        )

        assert result.success is True
        assert result.model == "claude-opus-4-7"
        assert result.input_tokens == 100
        assert result.latency_ms == 800

    def test_failed_call_result(self, llm_client):
        """Test result structure for failed calls."""
        from llm.client import LLMCallResult

        result = LLMCallResult(
            success=False,
            model="claude-opus-4-7",
            input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
            latency_ms=5000,
            retries=3,
            error="Rate limit exceeded",
        )

        assert result.success is False
        assert result.retries == 3
        assert "Rate limit" in result.error


class TestGeminiPrimaryRouting:
    """Tests for proactive Gemini primary routing (non-decision agents)."""

    def test_gemini_primary_agents_set(self, llm_client):
        """Enrichment agents are in GEMINI_PRIMARY_AGENTS."""
        expected = {
            "news_analyst",
            "social_analyst",
            "deep_analyzer",
            "technical_analyst",
            "fundamental_analyst",
            "hermes-upgrade-classifier",
            "bookmark_clusterer",
            "kairos_dreaming",
        }
        assert expected == llm_client.GEMINI_PRIMARY_AGENTS

    def test_decision_agents_use_gemini_pro(self, llm_client):
        """Trade-decision agents route to Gemini 2.5-pro (GEMINI_PRO_AGENTS),
        not the cheaper flash enrichment set (2026-07-02, Amo cost-reduction)."""
        for agent in ("trader", "risk_manager", "fund_manager", "bull_researcher", "bear_researcher"):
            assert agent in llm_client.GEMINI_PRO_AGENTS
            assert agent not in llm_client.GEMINI_PRIMARY_AGENTS

    async def test_gemini_primary_routes_enrichment_agent(self, llm_client, monkeypatch):
        """call() uses Gemini primary when agent_name is in GEMINI_PRIMARY_AGENTS."""
        from types import SimpleNamespace
        from unittest.mock import AsyncMock

        llm_client.provider = "anthropic"
        llm_client.google_fallback_enabled = True
        llm_client.google_api_key = "fake-google-key"

        fake_result = SimpleNamespace(
            usage=SimpleNamespace(input_tokens=10, output_tokens=5),
            content=[SimpleNamespace(text="gemini response")],
        )
        mock_call_google = AsyncMock(return_value=fake_result)
        mock_call_with_retry = AsyncMock()
        monkeypatch.setattr(llm_client, "_call_google", mock_call_google)
        monkeypatch.setattr(llm_client, "_call_with_retry", mock_call_with_retry)

        result = await llm_client.call(
            model="claude-sonnet-4-6",
            system="summarize this news",
            messages=[{"role": "user", "content": "NVDA up 5%"}],
            agent_name="news_analyst",
        )

        mock_call_google.assert_called_once()
        mock_call_with_retry.assert_not_called()
        assert result.success is True
        assert result.model == "gemini-2.5-flash"

    async def test_gemini_failure_falls_through_to_anthropic(self, llm_client, monkeypatch):
        """When Gemini primary fails, call() falls through to Anthropic retry loop."""
        from types import SimpleNamespace
        from unittest.mock import AsyncMock

        llm_client.provider = "anthropic"
        llm_client.google_fallback_enabled = True
        llm_client.google_api_key = "fake-google-key"

        mock_call_google = AsyncMock(side_effect=RuntimeError("Gemini timeout"))
        anthropic_result = SimpleNamespace(
            usage=SimpleNamespace(input_tokens=12, output_tokens=6),
            content=[SimpleNamespace(text="anthropic response")],
        )
        mock_call_with_retry = AsyncMock(return_value=anthropic_result)
        monkeypatch.setattr(llm_client, "_call_google", mock_call_google)
        monkeypatch.setattr(llm_client, "_call_with_retry", mock_call_with_retry)

        result = await llm_client.call(
            model="claude-sonnet-4-6",
            system="summarize this news",
            messages=[{"role": "user", "content": "NVDA up 5%"}],
            agent_name="news_analyst",
        )

        mock_call_google.assert_called_once()
        mock_call_with_retry.assert_called_once()
        assert result.success is True
        assert result.model == "claude-sonnet-4-6"

    def test_non_primary_agent_skips_gemini(self, llm_client):
        """Agents in neither Gemini set are NOT routed to Gemini proactively."""
        for agent in ("unknown", "some_other_agent"):
            assert agent not in llm_client.GEMINI_PRIMARY_AGENTS
            assert agent not in llm_client.GEMINI_PRO_AGENTS

    async def test_gemini_pro_routes_decision_agent(self, llm_client, monkeypatch):
        """call() routes a decision agent to gemini-2.5-pro (not flash)."""
        from types import SimpleNamespace
        from unittest.mock import AsyncMock

        llm_client.provider = "anthropic"
        llm_client.google_fallback_enabled = True
        llm_client.google_api_key = "fake-google-key"

        fake_result = SimpleNamespace(
            usage=SimpleNamespace(input_tokens=10, output_tokens=5),
            content=[SimpleNamespace(text="gemini pro response")],
        )
        mock_call_google = AsyncMock(return_value=fake_result)
        mock_call_with_retry = AsyncMock()
        monkeypatch.setattr(llm_client, "_call_google", mock_call_google)
        monkeypatch.setattr(llm_client, "_call_with_retry", mock_call_with_retry)

        result = await llm_client.call(
            model="claude-sonnet-4-6",
            system="decide the trade",
            messages=[{"role": "user", "content": "MES setup"}],
            agent_name="trader",
        )

        mock_call_google.assert_called_once()
        # The proactive-Gemini call must use the pro model for a decision agent.
        assert mock_call_google.call_args.kwargs.get("model") == "gemini-2.5-pro"
        mock_call_with_retry.assert_not_called()
        assert result.success is True
        assert result.model == "gemini-2.5-pro"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
