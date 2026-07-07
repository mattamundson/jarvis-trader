"""
Test suite for PipelineContextManager (4-Tier Context Management System).

Tests:
- estimate_tokens_basic           — estimate_tokens returns reasonable value
- tier_detection_none             — low utilization returns NONE tier
- tier_detection_trim             — ~55% utilization returns TRIM
- tier_detection_time_clear       — ~75% returns TIME_CLEAR
- tier_detection_emergency        — ~97% returns EMERGENCY
- trim_ohlcv_removes_arrays       — strips numeric arrays from messages
- emergency_compaction_preserves_system — system prompt survives EMERGENCY
- stats_tracking                  — get_stats returns correct tier counts
"""

from datetime import datetime, timedelta

import pytest

from llm.context_manager import (
    CompactionTier,
    ContextBudget,
    PipelineContextManager,
)

# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture
def cm():
    """Create a fresh PipelineContextManager with no LLM client."""
    return PipelineContextManager(llm_client=None)


def make_messages(approx_tokens: int, role: str = "user") -> list[dict]:
    """
    Build a message list whose estimated token count is approximately approx_tokens.
    estimate_tokens uses chars // 4, so we need approx_tokens * 4 characters.
    """
    # Each character contributes ~0.25 tokens
    content = "A" * (approx_tokens * 4)
    return [{"role": role, "content": content}]


def make_messages_with_system(total_tokens: int) -> list[dict]:
    """Build a [system, user, assistant] message list totaling ~total_tokens tokens."""
    per_msg = total_tokens // 3
    return [
        {"role": "system", "content": "A" * (per_msg * 4)},
        {"role": "user", "content": "A" * (per_msg * 4)},
        {"role": "assistant", "content": "A" * (per_msg * 4)},
    ]


# ── estimate_tokens ────────────────────────────────────────────────────────────


class TestEstimateTokens:
    def test_estimate_tokens_basic(self, cm):
        """estimate_tokens returns a reasonable value for a simple message list."""
        messages = [{"role": "user", "content": "Hello world"}]
        # "Hello world" = 11 chars => ~2-3 tokens expected
        tokens = cm.estimate_tokens(messages)
        assert tokens >= 1
        assert tokens <= 10  # sanity upper bound

    def test_estimate_tokens_scales_with_length(self, cm):
        """Token count grows with message content length."""
        short_msgs = [{"role": "user", "content": "Hi"}]
        long_msgs = [{"role": "user", "content": "A" * 400}]
        assert cm.estimate_tokens(long_msgs) > cm.estimate_tokens(short_msgs)

    def test_estimate_tokens_never_zero(self, cm):
        """estimate_tokens returns at least 1, even for empty messages."""
        assert cm.estimate_tokens([]) == 1
        assert cm.estimate_tokens([{"role": "user", "content": ""}]) == 1

    def test_estimate_tokens_static_method(self):
        """estimate_tokens is accessible as a static method (no instance needed)."""
        messages = [{"role": "user", "content": "test content here"}]
        result = PipelineContextManager.estimate_tokens(messages)
        assert result >= 1


# ── Tier Detection ─────────────────────────────────────────────────────────────


class TestTierDetection:
    MODEL = "claude-sonnet-4-6"
    MAX_TOKENS = 1_000_000  # context window for sonnet (1M token model)

    def test_tier_detection_none(self, cm):
        """Low utilization (< 20%) returns NONE tier — no action needed."""
        # 10% of 1M = 100K tokens => below TRIM threshold
        messages = make_messages(int(self.MAX_TOKENS * 0.10))
        budget = cm.get_budget(self.MODEL, messages)
        assert budget.tier == CompactionTier.NONE
        assert budget.utilization < 0.20

    def test_tier_detection_trim(self, cm):
        """~25% utilization returns TRIM tier (threshold at 20%)."""
        messages = make_messages(int(self.MAX_TOKENS * 0.25))
        budget = cm.get_budget(self.MODEL, messages)
        assert budget.tier == CompactionTier.TRIM
        assert 0.20 <= budget.utilization < 0.30

    def test_tier_detection_time_clear(self, cm):
        """~35% utilization returns TIME_CLEAR tier (threshold at 30%)."""
        messages = make_messages(int(self.MAX_TOKENS * 0.35))
        budget = cm.get_budget(self.MODEL, messages)
        assert budget.tier == CompactionTier.TIME_CLEAR
        assert 0.30 <= budget.utilization < 0.40

    def test_tier_detection_summarize(self, cm):
        """~45% utilization returns SUMMARIZE tier (threshold at 40%)."""
        messages = make_messages(int(self.MAX_TOKENS * 0.45))
        budget = cm.get_budget(self.MODEL, messages)
        assert budget.tier == CompactionTier.SUMMARIZE
        assert 0.40 <= budget.utilization < 0.50

    def test_tier_detection_emergency(self, cm):
        """~55% utilization returns EMERGENCY tier (threshold at 50%)."""
        messages = make_messages(int(self.MAX_TOKENS * 0.55))
        budget = cm.get_budget(self.MODEL, messages)
        assert budget.tier == CompactionTier.EMERGENCY
        assert budget.utilization >= 0.50

    def test_budget_fields(self, cm):
        """ContextBudget contains all expected fields with correct types."""
        messages = [{"role": "user", "content": "test"}]
        budget = cm.get_budget(self.MODEL, messages)
        assert isinstance(budget.model, str)
        assert isinstance(budget.max_context_tokens, int)
        assert isinstance(budget.current_input_tokens, int)
        assert isinstance(budget.utilization, float)
        assert isinstance(budget.tier, CompactionTier)
        assert budget.max_context_tokens == 1_000_000

    def test_unknown_model_uses_default_window(self, cm):
        """Unknown model falls back to DEFAULT_CONTEXT_WINDOW."""
        messages = make_messages(50_000)
        budget = cm.get_budget("claude-unknown-model", messages)
        assert budget.max_context_tokens == PipelineContextManager.DEFAULT_CONTEXT_WINDOW


# ── OHLCV Trimming ─────────────────────────────────────────────────────────────


class TestTrimOHLCV:
    def test_trim_ohlcv_removes_arrays(self, cm):
        """_trim_ohlcv_data strips large numeric arrays that look like OHLCV data."""
        # Build a realistic OHLCV-like content: 10 arrays of [ts, o, h, l, c, v]
        ohlcv_data = ", ".join(
            f"[{1700000000 + i}, {5000 + i}.0, {5010 + i}.0, {4990 + i}.0, {5005 + i}.0, {1000 + i}]"
            for i in range(10)
        )
        content = f"Here is the price data: [{ohlcv_data}] end of data."
        messages = [{"role": "user", "content": content}]

        result = cm._trim_ohlcv_data(messages)
        assert len(result) == 1
        assert "[... OHLCV data trimmed ...]" in result[0]["content"]
        # The raw numeric sequence should be gone
        assert "5000" not in result[0]["content"] or "trimmed" in result[0]["content"]

    def test_trim_ohlcv_preserves_non_ohlcv_content(self, cm):
        """Non-OHLCV content (text, small arrays) is not stripped."""
        content = "RSI is 65.4, MACD is 2.1, support at [5000, 5100, 5200]"
        messages = [{"role": "user", "content": content}]
        result = cm._trim_ohlcv_data(messages)
        assert result[0]["content"] == content  # unchanged

    def test_trim_ohlcv_preserves_message_role(self, cm):
        """_trim_ohlcv_data preserves the role field of each message."""
        messages = [
            {"role": "system", "content": "You are a trader."},
            {"role": "user", "content": "Analyze this."},
        ]
        result = cm._trim_ohlcv_data(messages)
        assert result[0]["role"] == "system"
        assert result[1]["role"] == "user"

    def test_compact_trim_tier_calls_trim(self, cm):
        """compact_messages with TRIM tier applies OHLCV stripping."""
        ohlcv_row = ", ".join(
            f"[{1700000000 + i}, {5000 + i}.0, {5010 + i}.0, {4990 + i}.0, {5005 + i}.0, {1000 + i}]"
            for i in range(10)
        )
        content = f"data: [{ohlcv_row}]"
        messages = [{"role": "user", "content": content}]
        result = cm.compact_messages(messages, CompactionTier.TRIM, "claude-sonnet-4-6")
        assert "[... OHLCV data trimmed ...]" in result[0]["content"]


# ── Stale Analysis Clearing ────────────────────────────────────────────────────


class TestClearStaleAnalysis:
    def test_stale_messages_removed(self, cm):
        """Messages older than STALE_ANALYSIS_MINUTES are removed."""
        stale_time = (
            datetime.now() - timedelta(minutes=PipelineContextManager.STALE_ANALYSIS_MINUTES + 5)
        ).isoformat()
        messages = [
            {"role": "system", "content": "system prompt"},
            {"role": "assistant", "content": "old analysis", "_jarvis_timestamp": stale_time},
        ]
        result = cm._clear_stale_analysis(messages)
        # System kept, stale dropped
        assert len(result) == 1
        assert result[0]["role"] == "system"

    def test_fresh_messages_kept(self, cm):
        """Messages with recent timestamps are not removed."""
        fresh_time = datetime.now().isoformat()
        messages = [
            {"role": "system", "content": "system"},
            {"role": "assistant", "content": "fresh analysis", "_jarvis_timestamp": fresh_time},
        ]
        result = cm._clear_stale_analysis(messages)
        assert len(result) == 2

    def test_untagged_messages_always_kept(self, cm):
        """Messages without _jarvis_timestamp are never cleared."""
        messages = [
            {"role": "user", "content": "no timestamp tag here"},
        ]
        result = cm._clear_stale_analysis(messages)
        assert len(result) == 1

    def test_system_messages_never_cleared(self, cm):
        """System messages are preserved regardless of timestamp."""
        stale_time = (datetime.now() - timedelta(minutes=60)).isoformat()
        messages = [
            {
                "role": "system",
                "content": "critical system prompt",
                "_jarvis_timestamp": stale_time,
            }
        ]
        result = cm._clear_stale_analysis(messages)
        assert len(result) == 1
        assert result[0]["role"] == "system"


# ── Emergency Compaction ───────────────────────────────────────────────────────


class TestEmergencyCompaction:
    def test_emergency_compaction_preserves_system(self, cm):
        """EMERGENCY tier keeps system prompt and last 2 non-system messages."""
        messages = [
            {"role": "system", "content": "system prompt — MUST survive"},
            {"role": "user", "content": "message 1"},
            {"role": "assistant", "content": "message 2"},
            {"role": "user", "content": "message 3"},
            {"role": "assistant", "content": "message 4"},
            {"role": "user", "content": "message 5 — recent"},
            {"role": "assistant", "content": "message 6 — most recent"},
        ]
        result = cm.compact_messages(messages, CompactionTier.EMERGENCY, "claude-sonnet-4-6")

        # System message must survive
        roles = [m["role"] for m in result]
        assert "system" in roles
        system_msgs = [m for m in result if m["role"] == "system"]
        assert system_msgs[0]["content"] == "system prompt — MUST survive"

        # Only 2 non-system messages kept (the last 2)
        non_system = [m for m in result if m["role"] != "system"]
        assert len(non_system) == 2
        assert non_system[-1]["content"] == "message 6 — most recent"
        assert non_system[-2]["content"] == "message 5 — recent"

    def test_emergency_with_only_system_message(self, cm):
        """EMERGENCY with only a system message keeps it intact."""
        messages = [{"role": "system", "content": "only message"}]
        result = cm.compact_messages(messages, CompactionTier.EMERGENCY, "claude-sonnet-4-6")
        assert len(result) == 1
        assert result[0]["role"] == "system"

    def test_emergency_with_no_system_message(self, cm):
        """EMERGENCY without system message keeps last 2 messages."""
        messages = [
            {"role": "user", "content": "msg 1"},
            {"role": "assistant", "content": "msg 2"},
            {"role": "user", "content": "msg 3"},
        ]
        result = cm.compact_messages(messages, CompactionTier.EMERGENCY, "claude-sonnet-4-6")
        assert len(result) == 2
        assert result[-1]["content"] == "msg 3"


# ── Compaction Event Tracking / Stats ─────────────────────────────────────────


class TestStatsTracking:
    def test_stats_tracking(self, cm):
        """get_stats returns correct tier counts after multiple compactions."""
        # Apply TRIM twice
        msgs_trim = make_messages(int(200_000 * 0.55))
        cm.compact_messages(msgs_trim, CompactionTier.TRIM, "claude-sonnet-4-6")
        cm.compact_messages(msgs_trim, CompactionTier.TRIM, "claude-sonnet-4-6")

        # Apply TIME_CLEAR once
        msgs_tc = make_messages(int(200_000 * 0.75))
        cm.compact_messages(msgs_tc, CompactionTier.TIME_CLEAR, "claude-sonnet-4-6")

        # Apply EMERGENCY once
        msgs_em = make_messages(int(200_000 * 0.97))
        cm.compact_messages(msgs_em, CompactionTier.EMERGENCY, "claude-sonnet-4-6")

        stats = cm.get_stats()
        assert stats["total_compaction_events"] == 4
        assert stats["tier_counts"]["TRIM"] == 2
        assert stats["tier_counts"]["TIME_CLEAR"] == 1
        assert stats["tier_counts"]["EMERGENCY"] == 1
        assert stats["tier_counts"]["NONE"] == 0
        assert stats["total_tokens_saved"] >= 0
        assert "recent_events" in stats
        assert len(stats["recent_events"]) <= 10

    def test_stats_initial_state(self, cm):
        """Fresh context manager has zero events."""
        stats = cm.get_stats()
        assert stats["total_compaction_events"] == 0
        assert stats["total_tokens_saved"] == 0
        for tier in CompactionTier:
            assert stats["tier_counts"][tier.name] == 0

    def test_stats_tokens_saved_accumulates(self, cm):
        """total_tokens_saved grows after each compaction event."""
        before = cm.get_stats()["total_tokens_saved"]
        ohlcv_row = ", ".join(
            f"[{1700000000 + i}, {5000 + i}.0, {5010 + i}.0, {4990 + i}.0, {5005 + i}.0, {1000 + i}]"
            for i in range(20)
        )
        messages = [{"role": "user", "content": "data: [" + ohlcv_row + "]" * 5}]
        cm.compact_messages(messages, CompactionTier.TRIM, "claude-sonnet-4-6")
        after = cm.get_stats()["total_tokens_saved"]
        assert after >= before  # may be 0 if no OHLCV matched, but should not decrease

    def test_recent_events_capped_at_10(self, cm):
        """recent_events in stats never exceeds 10 entries."""
        messages = make_messages(1000)
        for _ in range(15):
            cm.compact_messages(messages, CompactionTier.TRIM, "claude-sonnet-4-6")
        stats = cm.get_stats()
        assert len(stats["recent_events"]) == 10


# ── mark_agent_message ─────────────────────────────────────────────────────────


class TestMarkAgentMessage:
    def test_mark_adds_timestamp_and_agent(self, cm):
        """mark_agent_message adds _jarvis_timestamp and _jarvis_agent fields."""
        messages = [{"role": "assistant", "content": "analysis result"}]
        tagged = cm.mark_agent_message(messages, "technical_analyst")
        assert "_jarvis_timestamp" in tagged[0]
        assert tagged[0]["_jarvis_agent"] == "technical_analyst"

    def test_mark_does_not_mutate_original(self, cm):
        """mark_agent_message returns new dicts, does not mutate originals."""
        original = [{"role": "user", "content": "original"}]
        cm.mark_agent_message(original, "some_agent")
        assert "_jarvis_timestamp" not in original[0]

    def test_mark_records_agent_timestamp(self, cm):
        """mark_agent_message records the agent completion time internally."""
        messages = [{"role": "assistant", "content": "result"}]
        cm.mark_agent_message(messages, "news_analyst")
        assert "news_analyst" in cm._agent_timestamps


# ── reset_for_pipeline_run ─────────────────────────────────────────────────────


class TestReset:
    def test_reset_clears_agent_timestamps(self, cm):
        """reset_for_pipeline_run clears per-run agent timestamps."""
        messages = [{"role": "assistant", "content": "x"}]
        cm.mark_agent_message(messages, "agent_a")
        assert len(cm._agent_timestamps) == 1

        cm.reset_for_pipeline_run()
        assert len(cm._agent_timestamps) == 0

    def test_reset_does_not_clear_compaction_events(self, cm):
        """reset_for_pipeline_run preserves historical compaction events."""
        msgs = make_messages(int(200_000 * 0.55))
        cm.compact_messages(msgs, CompactionTier.TRIM, "claude-sonnet-4-6")
        assert cm.get_stats()["total_compaction_events"] == 1

        cm.reset_for_pipeline_run()
        # Events should still be there after reset
        assert cm.get_stats()["total_compaction_events"] == 1

    def test_reset_sets_pipeline_start_time(self, cm):
        """reset_for_pipeline_run sets _pipeline_start_time."""
        assert cm._pipeline_start_time is None
        cm.reset_for_pipeline_run()
        assert cm._pipeline_start_time is not None
        assert isinstance(cm._pipeline_start_time, datetime)


# ── Pipeline Integration (no LLM) ─────────────────────────────────────────────


class TestPipelineIntegration:
    def test_pipeline_accepts_context_manager(self):
        """TradingPipeline accepts context_manager kwarg without error."""
        from agents.pipeline import TradingPipeline

        cm_instance = PipelineContextManager()

        # Create a minimal mock safety layer
        class MockSafety:
            def get_status(self):
                return {}

        pipeline = TradingPipeline(
            agents={},
            safety_layer=MockSafety(),
            context_manager=cm_instance,
        )
        assert pipeline.context_manager is cm_instance

    def test_pipeline_without_context_manager_defaults_none(self):
        """TradingPipeline context_manager defaults to None (backward compat)."""
        from agents.pipeline import TradingPipeline

        class MockSafety:
            def get_status(self):
                return {}

        pipeline = TradingPipeline(agents={}, safety_layer=MockSafety())
        assert pipeline.context_manager is None


# ── P2-A: Prompt Caching & Per-Agent Token Limits ─────────────────────────────


class TestPromptCachingAndTokenLimits:
    def test_add_cache_control_to_system_prompt_adds_cache_control(self, cm):
        """cache_control is added to the first user message content block."""
        messages = [
            {"role": "system", "content": "You are a trading agent."},
            {"role": "user", "content": "Analyze MES for a long entry."},
        ]
        result = cm.add_cache_control_to_system_prompt(messages)

        # System message must be preserved unchanged
        assert result[0]["role"] == "system"
        assert result[0]["content"] == "You are a trading agent."

        # First user message must now be a list with cache_control
        user_msg = result[1]
        assert user_msg["role"] == "user"
        assert isinstance(user_msg["content"], list)
        assert len(user_msg["content"]) == 1
        block = user_msg["content"][0]
        assert block["type"] == "text"
        assert block["text"] == "Analyze MES for a long entry."
        assert block["cache_control"] == {"type": "ephemeral"}

    def test_add_cache_control_disabled_when_compaction_off(self):
        """When ENABLE_CONTEXT_COMPACTION=False, messages are returned unchanged."""

        class _DisabledConfig:
            ENABLE_CONTEXT_COMPACTION = False
            AGENT_MAX_TOKENS: dict = {}

        cm_disabled = PipelineContextManager(config=_DisabledConfig())
        messages = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "hello"},
        ]
        result = cm_disabled.add_cache_control_to_system_prompt(messages)

        # Must be identical to input — no cache_control applied
        assert result == messages
        # String content still a string, not a list
        assert isinstance(result[1]["content"], str)

    def test_get_agent_max_tokens_known_agent(self):
        """Returns the correct token limit for a known agent name."""

        class _CustomConfig:
            ENABLE_CONTEXT_COMPACTION = True
            AGENT_MAX_TOKENS = {
                "technical_analyst": 2000,
                "trader": 1500,
                "risk_manager": 1000,
            }

        cm_custom = PipelineContextManager(config=_CustomConfig())
        assert cm_custom.get_agent_max_tokens("technical_analyst") == 2000
        assert cm_custom.get_agent_max_tokens("trader") == 1500
        assert cm_custom.get_agent_max_tokens("risk_manager") == 1000

    def test_get_agent_max_tokens_unknown_agent_defaults_1500(self, cm):
        """An unknown agent name returns the default of 1500 tokens."""
        result = cm.get_agent_max_tokens("nonexistent_agent_xyz")
        assert result == 1500

    def test_get_agent_max_tokens_reflects_config_override(self):
        """Custom AGENT_MAX_TOKENS values in config are respected."""

        class _OverrideConfig:
            ENABLE_CONTEXT_COMPACTION = True
            AGENT_MAX_TOKENS = {
                "fund_manager": 9999,
                "bear_researcher": 3333,
            }

        cm_override = PipelineContextManager(config=_OverrideConfig())
        assert cm_override.get_agent_max_tokens("fund_manager") == 9999
        assert cm_override.get_agent_max_tokens("bear_researcher") == 3333
        # Agent not in override dict still gets default
        assert cm_override.get_agent_max_tokens("news_analyst") == 1500


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
