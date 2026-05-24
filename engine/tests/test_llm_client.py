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
    """Test per-agent Gemini primary routing (Phase 3.5)."""

    def test_empty_env_yields_empty_frozenset(self, monkeypatch, temp_db):
        """Absent JARVIS_LLM_GEMINI_AGENTS → no agents rerouted."""
        monkeypatch.delenv("JARVIS_LLM_GEMINI_AGENTS", raising=False)
        client = JarvisLLMClient(api_key="test-key", db_path=temp_db)
        assert client.gemini_primary_agents == frozenset()

    def test_env_var_parsed_correctly(self, monkeypatch, temp_db):
        """JARVIS_LLM_GEMINI_AGENTS is split on comma and stripped."""
        monkeypatch.setenv(
            "JARVIS_LLM_GEMINI_AGENTS", "news_analyst, social_analyst, deep_analyzer"
        )
        client = JarvisLLMClient(api_key="test-key", db_path=temp_db)
        assert client.gemini_primary_agents == frozenset(
            {"news_analyst", "social_analyst", "deep_analyzer"}
        )

    def test_default_gemini_model(self, monkeypatch, temp_db):
        """Default Gemini primary model is gemini-2.5-flash."""
        monkeypatch.delenv("JARVIS_LLM_GEMINI_PRIMARY_MODEL", raising=False)
        client = JarvisLLMClient(api_key="test-key", db_path=temp_db)
        assert client.gemini_primary_model == "gemini-2.5-flash"

    def test_custom_gemini_model_override(self, monkeypatch, temp_db):
        """JARVIS_LLM_GEMINI_PRIMARY_MODEL overrides the default."""
        monkeypatch.setenv("JARVIS_LLM_GEMINI_PRIMARY_MODEL", "gemini-2.0-flash")
        client = JarvisLLMClient(api_key="test-key", db_path=temp_db)
        assert client.gemini_primary_model == "gemini-2.0-flash"

    @pytest.mark.asyncio
    async def test_listed_agent_calls_google(self, monkeypatch, temp_db):
        """Agent in gemini_primary_agents routes to _call_google(), not Anthropic."""
        from types import SimpleNamespace
        from unittest.mock import AsyncMock

        monkeypatch.setenv("JARVIS_LLM_PROVIDER", "anthropic")
        monkeypatch.setenv("JARVIS_LLM_GEMINI_AGENTS", "news_analyst")
        monkeypatch.setenv("GOOGLE_API_KEY", "fake-google-key")

        client = JarvisLLMClient(api_key="test-key", db_path=temp_db)

        google_response = SimpleNamespace(
            usage=SimpleNamespace(input_tokens=100, output_tokens=50),
            content=[SimpleNamespace(text="Gemini says: market neutral")],
        )
        mock_google = AsyncMock(return_value=google_response)
        mock_anthropic = AsyncMock()
        client._call_google = mock_google
        client._call_with_retry = mock_anthropic

        result = await client.call(
            model="claude-sonnet-4-6",
            system="You are a news analyst.",
            messages=[{"role": "user", "content": "Analyze the news."}],
            agent_name="news_analyst",
            compact=False,
        )

        assert result.success is True
        assert result.model == "gemini-2.5-flash"
        mock_google.assert_called_once()
        mock_anthropic.assert_not_called()

    @pytest.mark.asyncio
    async def test_unlisted_agent_skips_google(self, monkeypatch, temp_db):
        """Agent NOT in gemini_primary_agents does not call _call_google()."""
        from unittest.mock import AsyncMock, patch

        monkeypatch.setenv("JARVIS_LLM_PROVIDER", "anthropic")
        monkeypatch.setenv("JARVIS_LLM_GEMINI_AGENTS", "news_analyst")
        monkeypatch.setenv("GOOGLE_API_KEY", "fake-google-key")

        client = JarvisLLMClient(api_key="test-key", db_path=temp_db)
        mock_google = AsyncMock()
        client._call_google = mock_google

        with patch.object(client, "_call_with_retry", side_effect=Exception("anthropic offline")):
            try:
                await client.call(
                    model="claude-sonnet-4-6",
                    system="You are a trader.",
                    messages=[{"role": "user", "content": "Should I trade?"}],
                    agent_name="trader",
                    compact=False,
                )
            except Exception:
                pass

        mock_google.assert_not_called()

    @pytest.mark.asyncio
    async def test_gemini_failure_falls_back_to_anthropic(self, monkeypatch, temp_db):
        """Gemini error triggers Anthropic fallback for listed agents."""
        from types import SimpleNamespace
        from unittest.mock import AsyncMock

        monkeypatch.setenv("JARVIS_LLM_PROVIDER", "anthropic")
        monkeypatch.setenv("JARVIS_LLM_GEMINI_AGENTS", "news_analyst")
        monkeypatch.setenv("GOOGLE_API_KEY", "fake-google-key")

        client = JarvisLLMClient(api_key="test-key", db_path=temp_db)

        anthropic_response = SimpleNamespace(
            usage=SimpleNamespace(input_tokens=80, output_tokens=30),
            content=[SimpleNamespace(text="Claude says: cautious")],
        )
        client._call_google = AsyncMock(side_effect=RuntimeError("Gemini 503"))
        client._call_with_retry = AsyncMock(return_value=anthropic_response)

        result = await client.call(
            model="claude-sonnet-4-6",
            system="You are a news analyst.",
            messages=[{"role": "user", "content": "Analyze the news."}],
            agent_name="news_analyst",
            compact=False,
        )

        assert result.success is True
        client._call_google.assert_called_once()
        client._call_with_retry.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
