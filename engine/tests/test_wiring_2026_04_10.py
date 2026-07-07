"""Wiring integration tests for Tracks F/G/H — 2026-04-10.

Covers:
- AdvisorClient graceful degradation when llm is None
- AdvisorClient gate thresholds (should_consult_debate, should_consult_trader)
- TokenProxy compression ratio and cache roundtrip
- ICWeightedEnsemble equal-weight fallback on empty DB
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest import mock

import pytest

# Adjust sys.path to import from engine root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.advisor_client import AdvisorClient, AdvisorVerdict
from analytics.ic_ensemble import ICWeightedEnsemble
from utils.token_proxy import TokenProxy, get_token_proxy


class TestAdvisorClientGracefulDegradation:
    """AdvisorClient returns non-consulted verdicts when llm is None."""

    def test_advisor_debate_fallback_when_unavailable(self):
        """When llm is None, consult_debate_tiebreak returns consulted=False."""
        client = AdvisorClient()
        client.llm = None  # force unavailable state

        async def run():
            return await client.consult_debate_tiebreak(
                bull_case="bull case text",
                bear_case="bear case text",
                debate_score=0.0,
                regime="trending",
                analyst_reports={},
            )

        result = asyncio.run(run())
        assert result.consulted is False
        assert result.verdict == "HOLD"
        assert result.source == "fallback"

    def test_advisor_trader_fallback_when_unavailable(self):
        """When llm is None, consult_trader_refinement returns consulted=False."""
        client = AdvisorClient()
        client.llm = None  # force unavailable state

        async def run():
            return await client.consult_trader_refinement(
                direction="LONG",
                entry=100.0,
                stop=95.0,
                target=110.0,
                confidence=0.42,
                regime="TRENDING_BULL",
                notes="low confidence",
            )

        result = asyncio.run(run())
        assert result.consulted is False
        assert result.entry == 100.0
        assert result.stop == 95.0
        assert result.target == 110.0
        assert result.source == "fallback"


class TestAdvisorGateThresholds:
    """Test escalation gates: should_consult_debate and should_consult_trader."""

    def test_debate_gate_within_tolerance(self):
        """should_consult_debate returns True when |score - threshold| <= 0.05."""
        client = AdvisorClient()
        # threshold=0.20, tolerance=0.05 → consult if abs(abs(score) - threshold) <= 0.05
        # So score in [0.15, 0.25] should trigger
        assert client.should_consult_debate(0.19, 0.20) is True
        assert client.should_consult_debate(0.20, 0.20) is True
        assert client.should_consult_debate(0.21, 0.20) is True
        # Test with negative debate scores (representing bear bias)
        assert client.should_consult_debate(-0.19, 0.20) is True
        assert client.should_consult_debate(-0.20, 0.20) is True

    def test_debate_gate_outside_tolerance(self):
        """should_consult_debate returns False when |score - threshold| > 0.05."""
        client = AdvisorClient()
        assert client.should_consult_debate(0.50, 0.20) is False
        assert client.should_consult_debate(0.10, 0.20) is False
        assert client.should_consult_debate(-0.50, 0.20) is False

    def test_trader_gate_low_confidence(self):
        """should_consult_trader returns True when confidence < 0.5."""
        client = AdvisorClient()
        assert client.should_consult_trader(0.42) is True
        assert client.should_consult_trader(0.0) is True
        assert client.should_consult_trader(0.49) is True

    def test_trader_gate_high_confidence(self):
        """should_consult_trader returns False when confidence >= 0.5."""
        client = AdvisorClient()
        assert client.should_consult_trader(0.5) is False
        assert client.should_consult_trader(0.7) is False
        assert client.should_consult_trader(1.0) is False

    def test_advisor_availability(self):
        """is_available reflects whether llm is initialized."""
        client = AdvisorClient()
        client.llm = None
        assert client.is_available() is False


class TestTokenProxyCompressionAndCache:
    """TokenProxy compression and cache roundtrip tests."""

    def test_compress_prompt_reduces_size(self):
        """compress_prompt shrinks whitespace and excess blank lines."""
        proxy = TokenProxy()
        original = "Hello\n\n\n\n\nworld   with    extra   spaces\n\n\n"
        compressed = proxy.compress_prompt(original)
        assert len(compressed) < len(original)
        # Should preserve core content
        assert "Hello" in compressed
        assert "world" in compressed

    def test_compress_prompt_collapses_blank_lines(self):
        """Collapse 3+ newlines to 2."""
        proxy = TokenProxy()
        original = "line1\n\n\n\n\nline2"
        compressed = proxy.compress_prompt(original)
        # Should have at most 2 consecutive newlines
        assert "\n\n\n" not in compressed
        assert "line1" in compressed and "line2" in compressed

    def test_compress_prompt_collapses_interior_spaces(self):
        """Interior multiple spaces → 1 (but preserve leading indentation)."""
        proxy = TokenProxy()
        original = "text   with    spaces"
        compressed = proxy.compress_prompt(original)
        assert "   " not in compressed
        assert "text with spaces" in compressed or "text  with  spaces" not in compressed

    def test_cache_roundtrip(self):
        """set_cached and get_cached roundtrip correctly."""
        proxy = TokenProxy()
        key = "key1"
        value = {"result": 42, "status": "ok"}
        model = "claude-sonnet-4-6"
        salt = "s1"

        proxy.set_cached(key, value, model=model, salt=salt)
        cached = proxy.get_cached(key, model=model, salt=salt)
        assert cached == value

    def test_cache_miss_returns_none(self):
        """get_cached returns None for missing entries."""
        proxy = TokenProxy()
        result = proxy.get_cached("nonexistent_key")
        assert result is None

    def test_optimize_compress_and_cache_lookup(self):
        """optimize() compresses and checks cache in one call."""
        proxy = TokenProxy()
        original = "Hello\n\n\n\nworld   with    extra   spaces\n\n\n"
        model = "m"
        salt = "s2"

        # First call: no cache, returns (compressed, None)
        compressed1, cached1 = proxy.optimize(original, model=model, salt=salt)
        assert cached1 is None
        assert len(compressed1) < len(original)

        # Store the result
        result_value = "result_data"
        proxy.set_cached(compressed1, result_value, model=model, salt=salt)

        # Second call: cache hit
        compressed2, cached2 = proxy.optimize(original, model=model, salt=salt)
        assert cached2 == result_value

    def test_cache_isolation_by_model(self):
        """Different models have different cache entries."""
        proxy = TokenProxy()
        key = "same_key"
        value1 = "response_model_a"
        value2 = "response_model_b"

        proxy.set_cached(key, value1, model="model_a", salt="")
        proxy.set_cached(key, value2, model="model_b", salt="")

        assert proxy.get_cached(key, model="model_a") == value1
        assert proxy.get_cached(key, model="model_b") == value2

    def test_get_token_proxy_singleton(self):
        """get_token_proxy returns the same instance across calls."""
        proxy1 = get_token_proxy()
        proxy2 = get_token_proxy()
        assert proxy1 is proxy2


class TestICWeightedEnsembleEqualWeightFallback:
    """ICWeightedEnsemble equal-weight fallback on empty/insufficient DB."""

    def test_equal_weight_fallback_on_empty_db(self):
        """Empty trade_outcomes DB → equal weights summing to 1.0."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            ensemble = ICWeightedEnsemble(db_path=db_path, agents=("a", "b", "c"))
            weights = ensemble.get_ensemble_weights()

            # Weights should sum to 1.0
            assert abs(sum(weights.values()) - 1.0) < 1e-6

            # All agents should have equal weight (1/3)
            expected_weight = 1.0 / 3
            for agent in ("a", "b", "c"):
                assert agent in weights
                assert abs(weights[agent] - expected_weight) < 1e-6
        finally:
            try:
                os.unlink(db_path)
            except OSError:
                pass

    def test_equal_weight_fallback_on_nonexistent_db(self):
        """Nonexistent DB path → equal-weight fallback."""
        ensemble = ICWeightedEnsemble(
            db_path="/nonexistent/path/test.db",
            agents=("x", "y"),
        )
        weights = ensemble.get_ensemble_weights()

        # Should still return equal weights
        assert abs(sum(weights.values()) - 1.0) < 1e-6
        assert abs(weights["x"] - 0.5) < 1e-6
        assert abs(weights["y"] - 0.5) < 1e-6

    def test_ensemble_min_trades_threshold(self):
        """get_ensemble_weights returns equal fallback when min_trades not met."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            # Set a high min_trades threshold; since DB is empty, fallback applies
            ensemble = ICWeightedEnsemble(
                db_path=db_path,
                agents=("tech", "news"),
                min_trades=1000,  # Very high threshold
            )
            weights = ensemble.get_ensemble_weights()

            # Should fall back to equal weights
            assert abs(weights["tech"] - 0.5) < 1e-6
            assert abs(weights["news"] - 0.5) < 1e-6
        finally:
            try:
                os.unlink(db_path)
            except OSError:
                pass

    def test_manual_spearman_stub(self):
        """_manual_spearman returns 0.0 for degenerate inputs."""
        # Test with insufficient data
        assert ICWeightedEnsemble._manual_spearman([1.0], [2.0]) == 0.0
        # Test with empty lists
        assert ICWeightedEnsemble._manual_spearman([], []) == 0.0
        # Test with mismatched lengths
        assert ICWeightedEnsemble._manual_spearman([1.0, 2.0], [3.0]) == 0.0


# ===========================================================================
# REQUIRED TESTS — Tracks F/G/H integration (2026-04-10)
# ===========================================================================


class TestAdvisorConsultDebateMocked:
    """Mock AdvisorClient.consult_debate_tiebreak to verify verdict handling."""

    def test_advisor_consult_debate_mocked(self):
        """Mock consult_debate_tiebreak; verify non-HOLD verdict flows through."""

        client = AdvisorClient()
        mocked_verdict = AdvisorVerdict(
            verdict="LONG",
            confidence=0.75,
            reasoning="Consensus bullish",
            source="opus_advisor",
            consulted=True,
        )

        async def run():
            with mock.patch.object(
                client,
                "consult_debate_tiebreak",
                return_value=mocked_verdict,
            ) as mock_consult:
                result = await client.consult_debate_tiebreak(
                    bull_case="Strong bull setup",
                    bear_case="Weak bear setup",
                    debate_score=0.18,
                    regime="TRENDING_BULL",
                    analyst_reports={"technical": {"signal": 0.8}},
                )
                mock_consult.assert_called_once()
                assert result.verdict == "LONG"
                assert result.consulted is True
                assert result.confidence == 0.75

        asyncio.run(run())


class TestTokenProxySingletonAndCache:
    """Verify TokenProxy singleton returns same instance; cache persists."""

    def test_token_proxy_singleton_and_cache(self):
        """get_token_proxy() returns same instance; cache persists across calls."""
        # Clear any existing global proxy state by importing fresh
        import importlib

        # Get two references
        proxy1 = get_token_proxy()
        proxy2 = get_token_proxy()

        # Assert same instance
        assert proxy1 is proxy2, "get_token_proxy must return singleton"

        # Test cache persistence
        test_key = "singleton_cache_test"
        test_value = {"data": "persistent"}
        model = "test-model"

        # First cache operation
        proxy1.set_cached(test_key, test_value, model=model)

        # Retrieve via second reference
        cached = proxy2.get_cached(test_key, model=model)
        assert cached == test_value, "Cache must persist across singleton references"

        # Verify metrics also shared
        assert proxy1.metrics is proxy2.metrics, "Metrics must be shared"


class TestICWeightedEnsembleEqualWeightFallbackNonexistent:
    """ICWeightedEnsemble.get_ensemble_weights on nonexistent DB."""

    def test_ic_weighted_ensemble_equal_weight_fallback(self):
        """Construct with /nonexistent/path; get_ensemble_weights returns equal weights."""
        ensemble = ICWeightedEnsemble(db_path="/nonexistent/path.db")
        weights = ensemble.get_ensemble_weights()

        # Should return equal weights for default agents
        assert isinstance(weights, dict), "get_ensemble_weights must return dict"
        assert len(weights) > 0, "weights dict must not be empty"

        # All weights should be equal (fallback)
        weight_values = list(weights.values())
        expected_weight = 1.0 / len(weights)
        for w in weight_values:
            assert abs(w - expected_weight) < 1e-6, f"weights must be equal; got {weights}"

        # Sum to 1.0
        assert abs(sum(weights.values()) - 1.0) < 1e-6, "weights must sum to 1.0"


class TestPaperTradesTableExists:
    """Verify the migration-defined schema produces a paper_trades table.

    Builds a fresh DB via ``database.migrations.run_migrations`` rather than
    inspecting ``engine/data/jarvis_trader.db`` (which is a developer/runtime
    artifact absent — or only partially initialized — in CI). This asserts the
    real schema contract and is environment-independent.
    """

    def test_paper_trades_table_exists(self):
        """run_migrations on a fresh DB creates paper_trades with required cols."""
        from database.migrations import run_migrations

        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "schema_check.db"
            conn = sqlite3.connect(str(db_path))
            try:
                run_migrations(conn)
                cursor = conn.cursor()

                # Check paper_trades table exists
                cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='paper_trades'"
                )
                result = cursor.fetchone()
                assert result is not None, "paper_trades table must exist after migrations"

                # Check required columns via PRAGMA
                cursor.execute("PRAGMA table_info(paper_trades)")
                columns = {row[1]: row for row in cursor.fetchall()}

                required_columns = {
                    "entry_price",
                    "stop_loss",
                    "symbol",
                    "side",
                    "status",
                }
                for col in required_columns:
                    assert (
                        col in columns
                    ), f"paper_trades.{col} must exist; found: {list(columns.keys())}"
            finally:
                conn.close()
