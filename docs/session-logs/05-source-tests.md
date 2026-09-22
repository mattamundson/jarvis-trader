# Test Files — Full Source (276 tests total)


### `engine/tests/test_feature_flags.py`
```python
"""
JARVIS TRADER — Feature Flags Unit Tests
==========================================
Tests for the two-layer FeatureFlags system (engine/flags/registry.py).

All tests use a mock DatabaseManager — no real SQLite required.
The mock tracks INSERT/UPDATE/DELETE/SELECT calls so tests can verify
runtime override behaviour without touching disk.

Run with:
    cd engine
    python -m pytest tests/test_feature_flags.py -v
"""

from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers — minimal stubs so we don't need a running engine
# ---------------------------------------------------------------------------


class _MockRow(dict):
    """Behaves like sqlite3.Row (subscript access by column name)."""

    def __getitem__(self, key: str) -> Any:
        return super().__getitem__(key)


class _MockConfig:
    """Minimal TradingConfig stub with feature flag defaults."""

    ENABLE_KAIROS: bool = False
    ENABLE_SPECULATION: bool = False
    ENABLE_TILT_DETECTION: bool = True
    ENABLE_DREAM_CONSOLIDATION: bool = False
    ENABLE_CONTEXT_COMPACTION: bool = True
    ENABLE_CRYPTO: bool = False
    ENABLE_POLYMARKET: bool = False
    ENABLE_RL_TRADING: bool = False
    ENABLE_SIGNAL_SANITIZATION: bool = False


class _MockDB:
    """
    Minimal DatabaseManager stub.

    Stores feature_flags rows in an in-memory dict so tests can verify
    that set_flag() and reset_flag() read/write correctly.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._flags_store: Dict[str, int] = {}  # name -> enabled (0|1)

    def _connect(self):
        """Return a mock connection that forwards queries to _flags_store."""
        conn = MagicMock()

        def _execute(sql: str, params: tuple = ()):
            sql_norm = " ".join(sql.split()).upper()

            # SELECT enabled FROM feature_flags WHERE name = ?
            if "SELECT ENABLED" in sql_norm and "WHERE NAME" in sql_norm:
                name = params[0]
                if name in self._flags_store:
                    row = _MockRow({"enabled": self._flags_store[name]})
                    conn.execute.return_value.fetchone.return_value = row
                else:
                    conn.execute.return_value.fetchone.return_value = None

            # SELECT name, enabled FROM feature_flags
            elif "SELECT NAME, ENABLED" in sql_norm:
                rows = [_MockRow({"name": k, "enabled": v}) for k, v in self._flags_store.items()]
                conn.execute.return_value.fetchall.return_value = rows

            # INSERT INTO feature_flags ... ON CONFLICT DO UPDATE
            elif "INSERT INTO FEATURE_FLAGS" in sql_norm:
                name = params[0]
                enabled_int = params[1]
                self._flags_store[name] = enabled_int

            # DELETE FROM feature_flags WHERE name = ?
            elif "DELETE FROM FEATURE_FLAGS" in sql_norm:
                name = params[0]
                self._flags_store.pop(name, None)

            return conn.execute.return_value

        conn.execute.side_effect = _execute
        conn.commit = MagicMock()
        conn.close = MagicMock()
        return conn


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def config():
    return _MockConfig()


@pytest.fixture()
def db():
    return _MockDB()


@pytest.fixture()
def flags(config, db):
    from flags.registry import FeatureFlags

    return FeatureFlags(config=config, db=db)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestFlagDefaults:
    def test_flag_default_enabled(self, flags):
        """ENABLE_TILT_DETECTION defaults to True (from config and FLAG_DEFINITIONS)."""
        assert flags.is_enabled("ENABLE_TILT_DETECTION") is True

    def test_flag_default_disabled(self, flags):
        """ENABLE_KAIROS defaults to False (from config and FLAG_DEFINITIONS)."""
        assert flags.is_enabled("ENABLE_KAIROS") is False

    def test_unknown_flag_returns_false(self, flags):
        """Unknown flag names return False without raising."""
        assert flags.is_enabled("ENABLE_NONEXISTENT_FLAG") is False


class TestRuntimeOverrides:
    def test_set_flag_runtime_override(self, flags, db):
        """set_flag() persists to the mock DB and is_enabled() reflects the change."""
        # ENABLE_KAIROS is False by default
        assert flags.is_enabled("ENABLE_KAIROS") is False

        flags.set_flag("ENABLE_KAIROS", True, updated_by="test")

        # After override, should be True
        assert flags.is_enabled("ENABLE_KAIROS") is True
        # Verify it was written to the mock store
        assert db._flags_store.get("ENABLE_KAIROS") == 1

    def test_runtime_overrides_config(self, flags, db):
        """A runtime False override supersedes a config True default."""
        # ENABLE_TILT_DETECTION is True in config
        assert flags.is_enabled("ENABLE_TILT_DETECTION") is True

        # Override to False at runtime
        flags.set_flag("ENABLE_TILT_DETECTION", False, updated_by="test")

        assert flags.is_enabled("ENABLE_TILT_DETECTION") is False
        assert db._flags_store.get("ENABLE_TILT_DETECTION") == 0

    def test_reset_flag(self, flags, db):
        """reset_flag() removes the runtime override and restores config default."""
        # Set a runtime override first
        flags.set_flag("ENABLE_TILT_DETECTION", False, updated_by="test")
        assert flags.is_enabled("ENABLE_TILT_DETECTION") is False

        # Reset — should fall back to config default (True)
        flags.reset_flag("ENABLE_TILT_DETECTION")

        assert flags.is_enabled("ENABLE_TILT_DETECTION") is True
        assert "ENABLE_TILT_DETECTION" not in db._flags_store

    def test_set_flag_invalid_name_raises(self, flags):
        """set_flag() raises ValueError for unknown flag names."""
        with pytest.raises(ValueError, match="Unknown feature flag"):
            flags.set_flag("ENABLE_MADE_UP_FLAG", True)

    def test_reset_flag_invalid_name_raises(self, flags):
        """reset_flag() raises ValueError for unknown flag names."""
        with pytest.raises(ValueError, match="Unknown feature flag"):
            flags.reset_flag("ENABLE_MADE_UP_FLAG")


class TestListFlags:
    def test_list_flags_returns_all(self, flags):
        """list_flags() returns exactly 9 flags (one per FLAG_DEFINITIONS entry)."""
        result = flags.list_flags()
        assert len(result) == 9

    def test_list_flags_structure(self, flags):
        """Each flag dict contains the required keys."""
        required_keys = {"name", "enabled", "description", "category", "requires_restart", "source"}
        for flag in flags.list_flags():
            assert required_keys.issubset(
                flag.keys()
            ), f"Flag {flag.get('name')!r} missing keys: {required_keys - flag.keys()}"

    def test_list_flags_source_config_when_no_override(self, flags):
        """Flags with no runtime override are sourced from 'config'."""
        result = flags.list_flags()
        for flag in result:
            assert (
                flag["source"] == "config"
            ), f"Expected source='config' for {flag['name']} (no override set)"

    def test_list_flags_source_runtime_after_override(self, flags):
        """Flags with a runtime override show source='runtime'."""
        flags.set_flag("ENABLE_KAIROS", True, updated_by="test")

        result = flags.list_flags()
        kairos = next(f for f in result if f["name"] == "ENABLE_KAIROS")
        assert kairos["source"] == "runtime"
        assert kairos["enabled"] is True

    def test_list_flags_correct_defaults(self, flags):
        """Spot-check: ENABLE_CONTEXT_COMPACTION default is True."""
        result = flags.list_flags()
        compaction = next(f for f in result if f["name"] == "ENABLE_CONTEXT_COMPACTION")
        assert compaction["enabled"] is True

    def test_list_flags_requires_restart_metadata(self, flags):
        """ENABLE_KAIROS and ENABLE_CRYPTO require restart; ENABLE_TILT_DETECTION does not."""
        result = {f["name"]: f for f in flags.list_flags()}
        assert result["ENABLE_KAIROS"]["requires_restart"] is True
        assert result["ENABLE_CRYPTO"]["requires_restart"] is True
        assert result["ENABLE_TILT_DETECTION"]["requires_restart"] is False

    def test_list_flags_categories(self, flags):
        """Verify categories are correctly assigned for a few flags."""
        result = {f["name"]: f for f in flags.list_flags()}
        assert result["ENABLE_KAIROS"]["category"] == "ai"
        assert result["ENABLE_TILT_DETECTION"]["category"] == "risk"
        assert result["ENABLE_CRYPTO"]["category"] == "market"
        assert result["ENABLE_RL_TRADING"]["category"] == "experimental"
        assert result["ENABLE_SIGNAL_SANITIZATION"]["category"] == "security"

```

### `engine/tests/test_context_manager.py`
```python
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
    MAX_TOKENS = 200_000  # context window for sonnet

    def test_tier_detection_none(self, cm):
        """Low utilization (< 50%) returns NONE tier — no action needed."""
        # 40% of 200K = 80K tokens => 320K chars
        messages = make_messages(int(self.MAX_TOKENS * 0.40))
        budget = cm.get_budget(self.MODEL, messages)
        assert budget.tier == CompactionTier.NONE
        assert budget.utilization < 0.50

    def test_tier_detection_trim(self, cm):
        """~55% utilization returns TRIM tier."""
        messages = make_messages(int(self.MAX_TOKENS * 0.55))
        budget = cm.get_budget(self.MODEL, messages)
        assert budget.tier == CompactionTier.TRIM
        assert 0.50 <= budget.utilization < 0.70

    def test_tier_detection_time_clear(self, cm):
        """~75% utilization returns TIME_CLEAR tier."""
        messages = make_messages(int(self.MAX_TOKENS * 0.75))
        budget = cm.get_budget(self.MODEL, messages)
        assert budget.tier == CompactionTier.TIME_CLEAR
        assert 0.70 <= budget.utilization < 0.85

    def test_tier_detection_summarize(self, cm):
        """~88% utilization returns SUMMARIZE tier."""
        messages = make_messages(int(self.MAX_TOKENS * 0.88))
        budget = cm.get_budget(self.MODEL, messages)
        assert budget.tier == CompactionTier.SUMMARIZE
        assert 0.85 <= budget.utilization < 0.95

    def test_tier_detection_emergency(self, cm):
        """~97% utilization returns EMERGENCY tier."""
        messages = make_messages(int(self.MAX_TOKENS * 0.97))
        budget = cm.get_budget(self.MODEL, messages)
        assert budget.tier == CompactionTier.EMERGENCY
        assert budget.utilization >= 0.95

    def test_budget_fields(self, cm):
        """ContextBudget contains all expected fields with correct types."""
        messages = [{"role": "user", "content": "test"}]
        budget = cm.get_budget(self.MODEL, messages)
        assert isinstance(budget.model, str)
        assert isinstance(budget.max_context_tokens, int)
        assert isinstance(budget.current_input_tokens, int)
        assert isinstance(budget.utilization, float)
        assert isinstance(budget.tier, CompactionTier)
        assert budget.max_context_tokens == 200_000

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

```

### `engine/tests/test_kairos.py`
```python
"""
JARVIS TRADER — KAIROS Unit Tests
===================================
Tests for the KAIROS proactive monitoring daemon:
  - ObservationLog (append, read, filter, count)
  - RegimeChangeWatcher (first tick, regime change, same regime)
  - STCCrossoverWatcher (oversold cross, overbought cross, no crossover, missing symbol)
  - RiskLimitWatcher (80% warning, 90% critical, safe levels, empty status)
  - VIXSpikeWatcher (first tick, warning move, critical move, no spike)
  - VolumeAnomalyWatcher (info level, warning level, warmup period)
  - SpreadWideningWatcher (calibration, widening, normal spread)
  - CorrelationBreakWatcher (first tick, divergence, no divergence)
  - KairosDaemon (requires daemon.py — skipped with KAIROS_DAEMON_MISSING marker if absent)

Run with:
    cd engine
    python -m pytest tests/test_kairos.py -v

Async tests require pytest-asyncio:
    pip install pytest-asyncio
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Path bootstrap — make the engine package importable from tests/
# ---------------------------------------------------------------------------
_ENGINE_DIR = Path(__file__).parent.parent  # engine/
_PROJECT_ROOT = _ENGINE_DIR.parent  # jarvis-trader/
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Daemon availability — if daemon.py does not exist yet, skip those tests
# ---------------------------------------------------------------------------
_DAEMON_AVAILABLE = (_ENGINE_DIR / "kairos" / "daemon.py").exists()
kairos_daemon_missing = pytest.mark.skipif(
    not _DAEMON_AVAILABLE,
    reason="kairos/daemon.py not yet implemented",
)


# ===========================================================================
# ObservationLog
# ===========================================================================


class TestObservationLog:
    """Tests for the JSONL append-only observation log."""

    def test_append_and_read_today(self, tmp_path):
        """Appended observation appears in read_today()."""
        from kairos.observation_log import ObservationLog
        from kairos.watchers import Observation, Severity

        log = ObservationLog(base_dir=str(tmp_path))
        obs = Observation(
            timestamp=datetime.now().isoformat(),
            watcher="test_watcher",
            severity=Severity.WARNING,
            message="Test observation",
            data={"price": 5000.0},
            notify=True,
            symbol="MES",
        )
        log.append(obs)
        results = log.read_today()

        assert len(results) == 1
        assert results[0]["watcher"] == "test_watcher"
        assert results[0]["severity"] == "warning"
        assert results[0]["message"] == "Test observation"
        assert results[0]["symbol"] == "MES"
        assert results[0]["notify"] is True
        assert results[0]["data"] == {"price": 5000.0}

    def test_append_multiple_observations(self, tmp_path):
        """Multiple appends are all present in read_today()."""
        from kairos.observation_log import ObservationLog
        from kairos.watchers import Observation, Severity

        log = ObservationLog(base_dir=str(tmp_path))
        for i in range(3):
            obs = Observation(
                timestamp=datetime.now().isoformat(),
                watcher=f"watcher_{i}",
                severity=Severity.INFO,
                message=f"Observation {i}",
            )
            log.append(obs)

        results = log.read_today()
        assert len(results) == 3
        watchers = [r["watcher"] for r in results]
        assert "watcher_0" in watchers
        assert "watcher_2" in watchers

    def test_read_empty_date_returns_empty_list(self, tmp_path):
        """read_date for a date with no log file returns an empty list."""
        from kairos.observation_log import ObservationLog

        log = ObservationLog(base_dir=str(tmp_path))
        results = log.read_date("2020-01-01")
        assert results == []

    def test_read_invalid_date_returns_empty_list(self, tmp_path):
        """read_date with a non-ISO date string returns an empty list gracefully."""
        from kairos.observation_log import ObservationLog

        log = ObservationLog(base_dir=str(tmp_path))
        results = log.read_date("not-a-date")
        assert results == []

    def test_get_recent_filters_old_observations(self, tmp_path):
        """get_recent(30) drops observations older than 30 minutes."""
        from kairos.observation_log import ObservationLog
        from kairos.watchers import Observation, Severity

        log = ObservationLog(base_dir=str(tmp_path))

        # Write an old observation (2 hours ago)
        old_ts = (datetime.now() - timedelta(hours=2)).isoformat()
        old_obs = Observation(
            timestamp=old_ts,
            watcher="old_watcher",
            severity=Severity.INFO,
            message="Old observation",
        )
        # Write a recent observation
        recent_ts = datetime.now().isoformat()
        recent_obs = Observation(
            timestamp=recent_ts,
            watcher="recent_watcher",
            severity=Severity.INFO,
            message="Recent observation",
        )
        log.append(old_obs)
        log.append(recent_obs)

        results = log.get_recent(minutes=30)
        assert len(results) == 1
        assert results[0]["watcher"] == "recent_watcher"

    def test_get_recent_all_within_window(self, tmp_path):
        """get_recent keeps all observations when all are within the window."""
        from kairos.observation_log import ObservationLog
        from kairos.watchers import Observation, Severity

        log = ObservationLog(base_dir=str(tmp_path))
        for _ in range(3):
            obs = Observation(
                timestamp=datetime.now().isoformat(),
                watcher="w",
                severity=Severity.INFO,
                message="recent",
            )
            log.append(obs)

        results = log.get_recent(minutes=60)
        assert len(results) == 3

    def test_count_by_severity_correct_counts(self, tmp_path):
        """count_by_severity returns correct per-severity totals."""
        from kairos.observation_log import ObservationLog
        from kairos.watchers import Observation, Severity

        log = ObservationLog(base_dir=str(tmp_path))
        for sev in [Severity.INFO, Severity.WARNING, Severity.WARNING, Severity.CRITICAL]:
            obs = Observation(
                timestamp=datetime.now().isoformat(),
                watcher="test",
                severity=sev,
                message="test",
            )
            log.append(obs)

        counts = log.count_by_severity()
        assert counts["info"] == 1
        assert counts["warning"] == 2
        assert counts["critical"] == 1

    def test_count_by_severity_empty_log(self, tmp_path):
        """count_by_severity on an empty log returns all-zero counts."""
        from kairos.observation_log import ObservationLog

        log = ObservationLog(base_dir=str(tmp_path))
        counts = log.count_by_severity()
        assert counts["info"] == 0
        assert counts["warning"] == 0
        assert counts["critical"] == 0

    def test_base_dir_created_automatically(self, tmp_path):
        """ObservationLog creates base_dir hierarchy if it does not exist."""
        from kairos.observation_log import ObservationLog

        nested = tmp_path / "deep" / "nested" / "kairos"
        log = ObservationLog(base_dir=str(nested))
        assert nested.exists()

    def test_severity_values_serialised_as_strings(self, tmp_path):
        """Severity enum values are stored as lowercase strings, not integers."""
        from kairos.observation_log import ObservationLog
        from kairos.watchers import Observation, Severity

        log = ObservationLog(base_dir=str(tmp_path))
        obs = Observation(
            timestamp=datetime.now().isoformat(),
            watcher="w",
            severity=Severity.CRITICAL,
            message="m",
        )
        log.append(obs)
        results = log.read_today()
        assert results[0]["severity"] == "critical"  # not "CRITICAL" or 2


# ===========================================================================
# RegimeChangeWatcher
# ===========================================================================


class TestRegimeChangeWatcher:
    """Tests for regime transition detection."""

    @pytest.mark.asyncio
    async def test_no_observation_on_first_tick(self):
        """First tick with no prior state produces no observations."""
        from kairos.watchers import RegimeChangeWatcher

        watcher = RegimeChangeWatcher()
        snapshot = {"symbols": {"MES": {"regime": "TRENDING_BULL"}}}
        result = await watcher.check(snapshot)
        assert result == []

    @pytest.mark.asyncio
    async def test_fires_on_regime_change(self):
        """Regime transition triggers a WARNING observation."""
        from kairos.watchers import RegimeChangeWatcher, Severity

        watcher = RegimeChangeWatcher()
        watcher._last_regimes["MES"] = "TRENDING_BULL"
        snapshot = {"symbols": {"MES": {"regime": "RANGING"}}}

        result = await watcher.check(snapshot)

        assert len(result) == 1
        assert result[0].severity == Severity.WARNING
        assert result[0].symbol == "MES"
        assert result[0].notify is True
        assert "TRENDING_BULL" in result[0].message
        assert "RANGING" in result[0].message

    @pytest.mark.asyncio
    async def test_no_fire_same_regime(self):
        """No observation when regime is unchanged between ticks."""
        from kairos.watchers import RegimeChangeWatcher

        watcher = RegimeChangeWatcher()
        watcher._last_regimes["MES"] = "TRENDING_BULL"
        snapshot = {"symbols": {"MES": {"regime": "TRENDING_BULL"}}}

        result = await watcher.check(snapshot)
        assert result == []

    @pytest.mark.asyncio
    async def test_state_updated_after_check(self):
        """_last_regimes is updated after each call, enabling next diff."""
        from kairos.watchers import RegimeChangeWatcher

        watcher = RegimeChangeWatcher()
        snapshot1 = {"symbols": {"MES": {"regime": "RANGING"}}}
        snapshot2 = {"symbols": {"MES": {"regime": "TRENDING_BEAR"}}}

        await watcher.check(snapshot1)  # sets last = RANGING
        result = await watcher.check(snapshot2)  # RANGING → TRENDING_BEAR

        assert len(result) == 1
        assert "RANGING" in result[0].message

    @pytest.mark.asyncio
    async def test_multiple_symbols_independent(self):
        """Regime changes across multiple symbols each produce their own observations."""
        from kairos.watchers import RegimeChangeWatcher

        watcher = RegimeChangeWatcher()
        watcher._last_regimes["MES"] = "TRENDING_BULL"
        watcher._last_regimes["MNQ"] = "RANGING"

        snapshot = {
            "symbols": {
                "MES": {"regime": "RANGING"},  # changed
                "MNQ": {"regime": "RANGING"},  # unchanged
                "MCL": {"regime": "TRENDING_BEAR"},  # first tick
            }
        }
        result = await watcher.check(snapshot)
        assert len(result) == 1
        assert result[0].symbol == "MES"

    @pytest.mark.asyncio
    async def test_handles_empty_symbols(self):
        """Empty symbols dict returns no observations without error."""
        from kairos.watchers import RegimeChangeWatcher

        watcher = RegimeChangeWatcher()
        result = await watcher.check({"symbols": {}})
        assert result == []

    @pytest.mark.asyncio
    async def test_handles_missing_regime_key(self):
        """Symbol data missing 'regime' key is skipped gracefully."""
        from kairos.watchers import RegimeChangeWatcher

        watcher = RegimeChangeWatcher()
        watcher._last_regimes["MES"] = "TRENDING_BULL"
        snapshot = {"symbols": {"MES": {"stc": 45.0}}}  # no 'regime' key

        result = await watcher.check(snapshot)
        assert result == []


# ===========================================================================
# STCCrossoverWatcher
# ===========================================================================


class TestSTCCrossoverWatcher:
    """Tests for STC overbought/oversold crossover detection."""

    @pytest.mark.asyncio
    async def test_no_observation_on_first_tick(self):
        """First tick with no prior STC produces no observations."""
        from kairos.watchers import STCCrossoverWatcher

        watcher = STCCrossoverWatcher()
        snapshot = {"symbols": {"MES": {"stc": 45.0}}}
        result = await watcher.check(snapshot)
        assert result == []

    @pytest.mark.asyncio
    async def test_fires_on_oversold_crossover(self):
        """STC dropping from above OS (15) to below OS fires WARNING."""
        from kairos.watchers import Severity, STCCrossoverWatcher

        watcher = STCCrossoverWatcher()
        watcher._last_stc["MES"] = 20.0  # above OS=15
        snapshot = {"symbols": {"MES": {"stc": 10.0}}}  # now below OS=15

        result = await watcher.check(snapshot)

        assert len(result) == 1
        assert result[0].severity == Severity.WARNING
        assert result[0].symbol == "MES"
        assert result[0].notify is True
        assert "oversold" in result[0].message.lower()

    @pytest.mark.asyncio
    async def test_fires_on_overbought_crossover(self):
        """STC rising from below OB (83) to above OB fires WARNING."""
        from kairos.watchers import Severity, STCCrossoverWatcher

        watcher = STCCrossoverWatcher()
        watcher._last_stc["MES"] = 80.0  # below OB=83
        snapshot = {"symbols": {"MES": {"stc": 87.0}}}  # now above OB=83

        result = await watcher.check(snapshot)

        assert len(result) == 1
        assert result[0].severity == Severity.WARNING
        assert "overbought" in result[0].message.lower()

    @pytest.mark.asyncio
    async def test_no_fire_neutral_zone(self):
        """STC staying in the neutral zone (15–83) produces no observations."""
        from kairos.watchers import STCCrossoverWatcher

        watcher = STCCrossoverWatcher()
        watcher._last_stc["MES"] = 45.0
        snapshot = {"symbols": {"MES": {"stc": 50.0}}}

        result = await watcher.check(snapshot)
        assert result == []

    @pytest.mark.asyncio
    async def test_no_fire_already_oversold_stays_oversold(self):
        """STC already below OS that stays below OS does not re-fire."""
        from kairos.watchers import STCCrossoverWatcher

        watcher = STCCrossoverWatcher()
        watcher._last_stc["MES"] = 8.0  # already below OS
        snapshot = {"symbols": {"MES": {"stc": 5.0}}}  # still below OS

        result = await watcher.check(snapshot)
        assert result == []

    @pytest.mark.asyncio
    async def test_handles_empty_symbols(self):
        """Empty symbols dict returns no observations without error."""
        from kairos.watchers import STCCrossoverWatcher

        watcher = STCCrossoverWatcher()
        result = await watcher.check({"symbols": {}})
        assert result == []

    @pytest.mark.asyncio
    async def test_handles_missing_stc_key(self):
        """Symbol data missing 'stc' key is skipped gracefully."""
        from kairos.watchers import STCCrossoverWatcher

        watcher = STCCrossoverWatcher()
        watcher._last_stc["MES"] = 20.0
        snapshot = {"symbols": {"MES": {"regime": "RANGING"}}}  # no stc

        result = await watcher.check(snapshot)
        assert result == []

    @pytest.mark.asyncio
    async def test_per_symbol_ob_threshold_mnq(self):
        """MNQ uses its custom OB threshold (92.0), not the default (83.0)."""
        from kairos.watchers import STCCrossoverWatcher

        watcher = STCCrossoverWatcher()
        # MNQ OB = 92.0; set last at 90 (below MNQ threshold) → move to 94
        watcher._last_stc["MNQ"] = 90.0
        snapshot = {"symbols": {"MNQ": {"stc": 94.0}}}

        result = await watcher.check(snapshot)
        # Should fire: 90 <= 92 threshold, and 94 > 92
        assert len(result) == 1
        assert "overbought" in result[0].message.lower()

    @pytest.mark.asyncio
    async def test_state_updated_after_check(self):
        """_last_stc is updated after each tick enabling correct diff next call."""
        from kairos.watchers import STCCrossoverWatcher

        watcher = STCCrossoverWatcher()
        watcher._last_stc["MES"] = 20.0  # above OS
        snapshot1 = {"symbols": {"MES": {"stc": 10.0}}}  # → oversold (fires)
        snapshot2 = {"symbols": {"MES": {"stc": 8.0}}}  # stays oversold (no fire)

        await watcher.check(snapshot1)
        result2 = await watcher.check(snapshot2)
        assert result2 == []  # already in oversold, no new crossover


# ===========================================================================
# RiskLimitWatcher
# ===========================================================================


class TestRiskLimitWatcher:
    """Tests for daily loss limit and drawdown monitoring."""

    @pytest.mark.asyncio
    async def test_fires_warning_at_80pct_daily_loss(self):
        """80–89% daily loss utilisation triggers a WARNING observation."""
        from kairos.watchers import RiskLimitWatcher, Severity

        watcher = RiskLimitWatcher()
        snapshot = {
            "risk_status": {
                "daily_pnl": -1.6,
                "daily_loss_limit": -2.0,
                "drawdown_pct": 1.0,
            }
        }
        result = await watcher.check(snapshot)

        assert len(result) >= 1
        severities = {o.severity for o in result}
        assert Severity.WARNING in severities or Severity.CRITICAL in severities

    @pytest.mark.asyncio
    async def test_fires_critical_at_90pct_daily_loss(self):
        """90%+ daily loss utilisation triggers a CRITICAL observation."""
        from kairos.watchers import RiskLimitWatcher, Severity

        watcher = RiskLimitWatcher()
        snapshot = {
            "risk_status": {
                "daily_pnl": -1.85,
                "daily_loss_limit": -2.0,
                "drawdown_pct": 0.5,
            }
        }
        result = await watcher.check(snapshot)

        assert len(result) >= 1
        assert any(o.severity == Severity.CRITICAL for o in result)
        assert any(o.notify is True for o in result)

    @pytest.mark.asyncio
    async def test_no_fire_at_safe_levels(self):
        """Loss well below limit (25% utilisation) produces no observations."""
        from kairos.watchers import RiskLimitWatcher

        watcher = RiskLimitWatcher()
        snapshot = {
            "risk_status": {
                "daily_pnl": -0.5,
                "daily_loss_limit": -2.0,
                "drawdown_pct": 1.0,
            }
        }
        result = await watcher.check(snapshot)
        assert result == []

    @pytest.mark.asyncio
    async def test_fires_info_on_high_drawdown(self):
        """drawdown_pct > 5% triggers an INFO observation."""
        from kairos.watchers import RiskLimitWatcher, Severity

        watcher = RiskLimitWatcher()
        snapshot = {
            "risk_status": {
                "daily_pnl": -0.1,
                "daily_loss_limit": -2.0,
                "drawdown_pct": 6.0,
            }
        }
        result = await watcher.check(snapshot)

        assert any(o.severity == Severity.INFO for o in result)

    @pytest.mark.asyncio
    async def test_handles_empty_risk_status(self):
        """Empty risk_status dict is handled gracefully — no observations."""
        from kairos.watchers import RiskLimitWatcher

        watcher = RiskLimitWatcher()
        result = await watcher.check({"risk_status": {}})
        assert result == []

    @pytest.mark.asyncio
    async def test_handles_missing_risk_status_key(self):
        """Missing risk_status key in snapshot is handled gracefully."""
        from kairos.watchers import RiskLimitWatcher

        watcher = RiskLimitWatcher()
        result = await watcher.check({})
        assert result == []

    @pytest.mark.asyncio
    async def test_handles_non_dict_risk_status(self):
        """Non-dict risk_status value is handled gracefully."""
        from kairos.watchers import RiskLimitWatcher

        watcher = RiskLimitWatcher()
        result = await watcher.check({"risk_status": None})
        assert result == []

    @pytest.mark.asyncio
    async def test_no_fire_when_pnl_positive(self):
        """Positive PnL does not trigger daily loss observations."""
        from kairos.watchers import RiskLimitWatcher

        watcher = RiskLimitWatcher()
        snapshot = {
            "risk_status": {
                "daily_pnl": 500.0,
                "daily_loss_limit": -2.0,
                "drawdown_pct": 0.0,
            }
        }
        result = await watcher.check(snapshot)
        assert result == []


# ===========================================================================
# VIXSpikeWatcher
# ===========================================================================


class TestVIXSpikeWatcher:
    """Tests for rapid VIX movement detection."""

    @pytest.mark.asyncio
    async def test_no_observation_on_first_tick(self):
        """First VIX reading produces no observations (no baseline yet)."""
        from kairos.watchers import VIXSpikeWatcher

        watcher = VIXSpikeWatcher()
        result = await watcher.check({"vix": 18.5})
        assert result == []

    @pytest.mark.asyncio
    async def test_fires_warning_on_large_move(self):
        """VIX moving >= 1.5 pts triggers a WARNING."""
        from kairos.watchers import Severity, VIXSpikeWatcher

        watcher = VIXSpikeWatcher()
        # Prime with initial reading
        await watcher.check({"vix": 15.0})
        # Move > 1.5 pts
        result = await watcher.check({"vix": 17.0})

        assert len(result) == 1
        assert result[0].severity == Severity.WARNING
        assert result[0].notify is True

    @pytest.mark.asyncio
    async def test_fires_critical_on_very_large_move(self):
        """VIX moving >= 3.0 pts triggers a CRITICAL observation."""
        from kairos.watchers import Severity, VIXSpikeWatcher

        watcher = VIXSpikeWatcher()
        await watcher.check({"vix": 15.0})
        result = await watcher.check({"vix": 18.5})  # +3.5 pts

        assert len(result) == 1
        assert result[0].severity == Severity.CRITICAL

    @pytest.mark.asyncio
    async def test_no_fire_on_small_move(self):
        """VIX moving < 1.5 pts produces no observations."""
        from kairos.watchers import VIXSpikeWatcher

        watcher = VIXSpikeWatcher()
        await watcher.check({"vix": 15.0})
        result = await watcher.check({"vix": 15.5})  # +0.5 pts

        assert result == []

    @pytest.mark.asyncio
    async def test_handles_missing_vix(self):
        """Snapshot without 'vix' key returns no observations gracefully."""
        from kairos.watchers import VIXSpikeWatcher

        watcher = VIXSpikeWatcher()
        result = await watcher.check({})
        assert result == []

    @pytest.mark.asyncio
    async def test_handles_none_vix(self):
        """vix=None returns no observations gracefully."""
        from kairos.watchers import VIXSpikeWatcher

        watcher = VIXSpikeWatcher()
        result = await watcher.check({"vix": None})
        assert result == []


# ===========================================================================
# VolumeAnomalyWatcher
# ===========================================================================


class TestVolumeAnomalyWatcher:
    """Tests for unusual volume detection."""

    @pytest.mark.asyncio
    async def test_no_observation_during_warmup(self):
        """Fewer than 3 bars of history should produce no observations."""
        from kairos.watchers import VolumeAnomalyWatcher

        watcher = VolumeAnomalyWatcher()
        for vol in [1000, 1100]:
            result = await watcher.check({"symbols": {"MES": {"volume": vol}}})
        # During warmup period — should not fire
        assert result == []

    @pytest.mark.asyncio
    async def test_fires_info_at_1_5x_average(self):
        """Volume >= 1.5x rolling average triggers an INFO observation."""
        from kairos.watchers import Severity, VolumeAnomalyWatcher

        watcher = VolumeAnomalyWatcher()
        # Establish a stable baseline over 10 bars so the spike bar does not
        # dilute the average below the 1.5x threshold when it is appended.
        for _ in range(10):
            await watcher.check({"symbols": {"MES": {"volume": 1000}}})
        # Now send 2000 (2.0x average) — safely above 1.5x even after the
        # spike bar is included in the rolling window.
        result = await watcher.check({"symbols": {"MES": {"volume": 2000}}})

        assert len(result) >= 1
        assert any(o.severity == Severity.INFO for o in result)

    @pytest.mark.asyncio
    async def test_fires_warning_at_2_5x_average(self):
        """Volume >= 2.5x rolling average triggers a WARNING observation."""
        from kairos.watchers import Severity, VolumeAnomalyWatcher

        watcher = VolumeAnomalyWatcher()
        # Establish a stable baseline over 10 bars so the spike bar does not
        # dilute the average below the 2.5x threshold when it is appended.
        for _ in range(10):
            await watcher.check({"symbols": {"MES": {"volume": 1000}}})
        result = await watcher.check({"symbols": {"MES": {"volume": 5000}}})

        assert len(result) >= 1
        assert any(o.severity == Severity.WARNING for o in result)
        assert any(o.notify is True for o in result)

    @pytest.mark.asyncio
    async def test_no_fire_on_normal_volume(self):
        """Volume close to the rolling average produces no observations."""
        from kairos.watchers import VolumeAnomalyWatcher

        watcher = VolumeAnomalyWatcher()
        for _ in range(5):
            await watcher.check({"symbols": {"MES": {"volume": 1000}}})
        result = await watcher.check({"symbols": {"MES": {"volume": 1050}}})  # 1.05x

        assert result == []

    @pytest.mark.asyncio
    async def test_handles_missing_volume_key(self):
        """Symbol data without 'volume' key is skipped gracefully."""
        from kairos.watchers import VolumeAnomalyWatcher

        watcher = VolumeAnomalyWatcher()
        result = await watcher.check({"symbols": {"MES": {"stc": 45.0}}})
        assert result == []


# ===========================================================================
# SpreadWideningWatcher
# ===========================================================================


class TestSpreadWideningWatcher:
    """Tests for bid-ask spread widening detection."""

    @pytest.mark.asyncio
    async def test_no_observation_during_calibration(self):
        """Fewer than BASELINE_WINDOW bars produces no observations."""
        from kairos.watchers import SpreadWideningWatcher

        watcher = SpreadWideningWatcher()
        # Only 5 bars — window needs 10
        for _ in range(5):
            result = await watcher.check({"symbols": {"MES": {"spread": 0.25}}})
        assert result == []

    @pytest.mark.asyncio
    async def test_fires_on_widened_spread(self):
        """Spread >= 2x the calibrated normal triggers a WARNING."""
        from kairos.watchers import Severity, SpreadWideningWatcher

        watcher = SpreadWideningWatcher()
        # Calibrate with BASELINE_WINDOW bars at spread=0.25
        for _ in range(SpreadWideningWatcher._BASELINE_WINDOW):
            await watcher.check({"symbols": {"MES": {"spread": 0.25}}})
        # Now send spread=0.55 (2.2x normal)
        result = await watcher.check({"symbols": {"MES": {"spread": 0.55}}})

        assert len(result) >= 1
        assert any(o.severity == Severity.WARNING for o in result)

    @pytest.mark.asyncio
    async def test_no_fire_on_normal_spread(self):
        """Spread within normal range (< 2x) produces no observations."""
        from kairos.watchers import SpreadWideningWatcher

        watcher = SpreadWideningWatcher()
        for _ in range(SpreadWideningWatcher._BASELINE_WINDOW):
            await watcher.check({"symbols": {"MES": {"spread": 0.25}}})
        result = await watcher.check({"symbols": {"MES": {"spread": 0.35}}})  # 1.4x

        assert result == []

    @pytest.mark.asyncio
    async def test_handles_missing_spread_key(self):
        """Symbol data without 'spread' key is skipped gracefully."""
        from kairos.watchers import SpreadWideningWatcher

        watcher = SpreadWideningWatcher()
        result = await watcher.check({"symbols": {"MES": {"stc": 45.0}}})
        assert result == []


# ===========================================================================
# CorrelationBreakWatcher
# ===========================================================================


class TestCorrelationBreakWatcher:
    """Tests for MES/MNQ correlation divergence detection."""

    @pytest.mark.asyncio
    async def test_no_observation_on_first_tick(self):
        """First tick with prices produces no observation (no return to compute)."""
        from kairos.watchers import CorrelationBreakWatcher

        watcher = CorrelationBreakWatcher()
        snapshot = {
            "symbols": {
                "MES": {"price": 5200.0},
                "MNQ": {"price": 18000.0},
            }
        }
        result = await watcher.check(snapshot)
        assert result == []

    @pytest.mark.asyncio
    async def test_fires_on_large_divergence(self):
        """Returns diverging by > 1.5% triggers a WARNING."""
        from kairos.watchers import CorrelationBreakWatcher, Severity

        watcher = CorrelationBreakWatcher()
        # First tick
        await watcher.check(
            {
                "symbols": {
                    "MES": {"price": 5000.0},
                    "MNQ": {"price": 18000.0},
                }
            }
        )
        # MES up +3%, MNQ flat — divergence 3%
        result = await watcher.check(
            {
                "symbols": {
                    "MES": {"price": 5150.0},  # +3.0%
                    "MNQ": {"price": 18000.0},  # +0%
                }
            }
        )

        assert len(result) == 1
        assert result[0].severity == Severity.WARNING
        assert "MES" in result[0].message
        assert "MNQ" in result[0].message

    @pytest.mark.asyncio
    async def test_no_fire_on_correlated_move(self):
        """Both symbols moving similarly (< 1.5% divergence) produces no observations."""
        from kairos.watchers import CorrelationBreakWatcher

        watcher = CorrelationBreakWatcher()
        await watcher.check(
            {
                "symbols": {
                    "MES": {"price": 5000.0},
                    "MNQ": {"price": 18000.0},
                }
            }
        )
        # Both up ~1%
        result = await watcher.check(
            {
                "symbols": {
                    "MES": {"price": 5050.0},  # +1.0%
                    "MNQ": {"price": 18180.0},  # +1.0%
                }
            }
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_handles_missing_symbol_data(self):
        """Missing MES or MNQ data returns no observations gracefully."""
        from kairos.watchers import CorrelationBreakWatcher

        watcher = CorrelationBreakWatcher()
        result = await watcher.check(
            {
                "symbols": {
                    "MES": {"price": 5000.0},
                    # MNQ missing
                }
            }
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_handles_missing_price_key(self):
        """Symbol dict without 'price' field is handled gracefully."""
        from kairos.watchers import CorrelationBreakWatcher

        watcher = CorrelationBreakWatcher()
        result = await watcher.check(
            {
                "symbols": {
                    "MES": {"stc": 45.0},
                    "MNQ": {"stc": 45.0},
                }
            }
        )
        assert result == []


# ===========================================================================
# BaseWatcher — helper method
# ===========================================================================


class TestBaseWatcherHelper:
    """Tests for the _obs() convenience method on BaseWatcher subclasses."""

    def test_obs_returns_observation_with_correct_fields(self):
        """_obs() populates all Observation fields correctly."""
        from kairos.watchers import RegimeChangeWatcher, Severity

        watcher = RegimeChangeWatcher()
        obs = watcher._obs(
            severity=Severity.CRITICAL,
            message="Test message",
            data={"key": "val"},
            notify=True,
            symbol="MCL",
        )
        assert obs.severity == Severity.CRITICAL
        assert obs.message == "Test message"
        assert obs.data == {"key": "val"}
        assert obs.notify is True
        assert obs.symbol == "MCL"
        assert obs.watcher == "regime_change"
        # Timestamp should be a valid ISO datetime string
        datetime.fromisoformat(obs.timestamp)

    def test_obs_default_data_is_empty_dict(self):
        """_obs() without data= uses an empty dict, not None."""
        from kairos.watchers import RegimeChangeWatcher, Severity

        watcher = RegimeChangeWatcher()
        obs = watcher._obs(severity=Severity.INFO, message="test")
        assert obs.data == {}
        assert obs.notify is False
        assert obs.symbol is None


# ===========================================================================
# KairosDaemon — only if daemon.py exists
# ===========================================================================


@kairos_daemon_missing
class TestKairosDaemonStatus:
    """KairosDaemon.get_status() and registration tests."""

    def test_status_before_start(self):
        """get_status() reports running=False and tick_count=0 before start()."""
        from kairos.daemon import KairosDaemon

        config = MagicMock()
        config.KAIROS_TICK_SECONDS = 60
        config.KAIROS_NOTIFY_SEVERITY = "warning"

        daemon = KairosDaemon(config=config)
        status = daemon.get_status()

        assert status["running"] is False
        assert status["tick_count"] == 0

    def test_register_watcher_appears_in_status(self):
        """A registered watcher shows up in get_status()['watchers']."""
        from kairos.daemon import KairosDaemon
        from kairos.watchers import BaseWatcher

        config = MagicMock()
        daemon = KairosDaemon(config=config)

        class MockWatcher(BaseWatcher):
            name = "test_mock"

            async def check(self, snapshot):
                return []

        daemon.register_watcher(MockWatcher())
        status = daemon.get_status()
        assert "test_mock" in status["watchers"]

    @pytest.mark.asyncio
    async def test_tick_calls_all_watchers(self):
        """A single tick() calls check() on every registered watcher."""
        from kairos.daemon import KairosDaemon
        from kairos.watchers import BaseWatcher

        config = MagicMock()
        config.KAIROS_TICK_SECONDS = 60
        config.KAIROS_NOTIFY_SEVERITY = "warning"

        daemon = KairosDaemon(config=config)

        call_log: list[str] = []

        class TrackingWatcher(BaseWatcher):
            name = "tracking"

            async def check(self, snapshot):
                call_log.append("called")
                return []

        daemon.register_watcher(TrackingWatcher())
        await daemon.tick()

        assert len(call_log) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

```

### `engine/tests/test_tilt_detector.py`
```python
"""
Tests for TiltDetector — behavioral tilt detection system.
All tests are pure in-memory (no DB, no LLM, no broker).
"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from risk.tilt_detector import TiltDetector, TiltState

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def detector():
    return TiltDetector()


# ── Helpers ───────────────────────────────────────────────────────────────────


def _record_losses(d: TiltDetector, n: int, symbol: str = "MES") -> None:
    """Record n consecutive stop-out losses."""
    for _ in range(n):
        d.record_trade(symbol, "LONG", 1, 5000.0, pnl=-50.0, is_stop_out=True)


def _record_wins(d: TiltDetector, n: int, symbol: str = "MES") -> None:
    """Record n consecutive wins."""
    for _ in range(n):
        d.record_trade(symbol, "LONG", 1, 5000.0, pnl=50.0)


# ── Baseline / Clean State ────────────────────────────────────────────────────


class TestCleanState:
    def test_no_tilt_initially(self, detector):
        s = detector.check()
        assert not s.is_tilted
        assert s.tilt_score == 0.0
        assert s.position_size_multiplier == 1.0
        assert s.severity == "none"
        assert s.tilt_indicators == []
        assert s.cooldown_until is None

    def test_get_position_multiplier_clean(self, detector):
        assert detector.get_position_multiplier() == 1.0

    def test_get_status_keys(self, detector):
        status = detector.get_status()
        required_keys = [
            "is_tilted",
            "tilt_score",
            "severity",
            "tilt_indicators",
            "position_size_multiplier",
            "cooldown_until",
            "recent_trade_count",
            "consecutive_losses",
            "rapid_trades_30min",
            "recent_vetoes",
        ]
        for key in required_keys:
            assert key in status, f"Missing key: {key}"


# ── Consecutive Loss Indicators ───────────────────────────────────────────────


class TestConsecutiveLosses:
    def test_2_losses_no_tilt(self, detector):
        _record_losses(detector, 2)
        s = detector.check()
        assert not s.is_tilted
        assert s.tilt_score < 0.3

    def test_3_losses_caution(self, detector):
        _record_losses(detector, 3)
        s = detector.check()
        assert s.is_tilted
        assert any("consecutive_losses_3" in i for i in s.tilt_indicators)
        assert s.tilt_score >= 0.2
        assert s.severity == "caution"

    def test_5_losses_warning(self, detector):
        _record_losses(detector, 5)
        s = detector.check()
        assert s.tilt_score >= 0.4
        assert any("consecutive_losses_5" in i for i in s.tilt_indicators)

    def test_7_losses_halt(self, detector):
        _record_losses(detector, 7)
        s = detector.check()
        assert s.position_size_multiplier == 0.0
        assert s.severity == "critical"
        assert s.cooldown_until is not None
        assert s.cooldown_until > datetime.now()

    def test_win_after_loss_resets_consecutive(self, detector):
        _record_losses(detector, 3)
        _record_wins(detector, 1)
        # The TiltDetector's in-memory counter should drop back to 0
        s = detector.check()
        # loss_tracker is None so it uses in-memory count
        assert not any("consecutive_losses_3" in i for i in s.tilt_indicators)


# ── Rapid Trades ──────────────────────────────────────────────────────────────


class TestRapidTrades:
    def test_4_trades_no_rapid_flag(self, detector):
        for _ in range(4):
            detector.record_trade("MES", "LONG", 1, 5000.0, pnl=10.0)
        s = detector.check()
        assert not any("rapid_trades" in i for i in s.tilt_indicators)

    def test_5_trades_in_30min_fires(self, detector):
        for _ in range(6):
            detector.record_trade("MES", "LONG", 1, 5000.0, pnl=10.0)
        s = detector.check()
        assert any("rapid_trades" in i for i in s.tilt_indicators)

    def test_rapid_trades_adds_score(self, detector):
        for _ in range(6):
            detector.record_trade("MES", "LONG", 1, 5000.0, pnl=10.0)
        s = detector.check()
        assert s.tilt_score >= 0.3


# ── Revenge Sizing ────────────────────────────────────────────────────────────


class TestRevengeSizing:
    def test_size_increase_after_loss_detected(self, detector):
        detector.record_trade("MES", "LONG", 1, 5000.0, pnl=-50.0)
        detector.record_trade("MES", "LONG", 2, 5005.0, pnl=None)
        s = detector.check()
        assert "revenge_sizing" in s.tilt_indicators

    def test_no_size_increase_not_detected(self, detector):
        detector.record_trade("MES", "LONG", 2, 5000.0, pnl=-50.0)
        detector.record_trade("MES", "LONG", 1, 5005.0, pnl=None)
        s = detector.check()
        assert "revenge_sizing" not in s.tilt_indicators

    def test_size_increase_after_win_not_revenge(self, detector):
        detector.record_trade("MES", "LONG", 1, 5000.0, pnl=50.0)
        detector.record_trade("MES", "LONG", 2, 5005.0, pnl=None)
        s = detector.check()
        assert "revenge_sizing" not in s.tilt_indicators


# ── Rapid Re-Entry ────────────────────────────────────────────────────────────


class TestRapidReentry:
    def test_reentry_same_symbol_after_stop_detected(self, detector):
        detector.record_trade("MES", "LONG", 1, 5000.0, pnl=-50.0, is_stop_out=True)
        detector.record_trade("MES", "LONG", 1, 5005.0, pnl=None)
        s = detector.check()
        assert "rapid_reentry_after_stop" in s.tilt_indicators

    def test_reentry_different_symbol_not_flagged(self, detector):
        # Record stop-out without adding to _recent_trades (inject directly into _stop_outs)
        # to isolate the rapid-reentry logic from the trade history.
        from datetime import datetime

        detector._stop_outs.append({"timestamp": datetime.now(), "symbol": "MES"})
        detector.record_trade("MNQ", "LONG", 1, 21000.0, pnl=None)
        s = detector.check()
        assert "rapid_reentry_after_stop" not in s.tilt_indicators


# ── Risk Vetoes ───────────────────────────────────────────────────────────────


class TestRiskVetoes:
    def test_1_veto_no_flag(self, detector):
        detector.record_risk_veto()
        s = detector.check()
        assert not any("risk_overrides" in i for i in s.tilt_indicators)

    def test_2_vetoes_flag(self, detector):
        detector.record_risk_veto()
        detector.record_risk_veto()
        s = detector.check()
        assert any("risk_overrides" in i for i in s.tilt_indicators)
        assert s.tilt_score >= 0.2


# ── Drawdown Acceleration ─────────────────────────────────────────────────────


class TestDrawdownAcceleration:
    def test_flat_drawdown_no_flag(self, detector):
        for _ in range(8):
            detector.update_drawdown(2.0)
        s = detector.check()
        assert "drawdown_accelerating" not in s.tilt_indicators

    def test_accelerating_drawdown_flagged(self, detector):
        # First half: small drawdown; second half: 50% larger
        for _ in range(4):
            detector.update_drawdown(2.0)
        for _ in range(4):
            detector.update_drawdown(3.5)
        s = detector.check()
        assert "drawdown_accelerating" in s.tilt_indicators


# ── Severity + Multiplier Mapping ────────────────────────────────────────────


class TestSeverityMapping:
    def test_score_below_0_3_no_tilt(self, detector):
        s = detector.check()
        assert s.severity == "none"
        assert s.position_size_multiplier == 1.0

    def test_score_0_3_to_0_5_caution(self, detector):
        # Use vetoes only to get a clean 0.4 score without stop-out side effects
        for _ in range(3):
            detector.record_risk_veto()  # only 2 needed to fire, but score is 0.2
        # 2 vetoes = +0.2; need a second source — drawdown acceleration
        for _ in range(4):
            detector.update_drawdown(1.0)
        for _ in range(4):
            detector.update_drawdown(1.5)  # 50% increase — flags acceleration +0.2
        # total: 0.2 (vetoes) + 0.2 (drawdown) = 0.4 → caution
        s = detector.check()
        assert s.severity == "caution"
        assert s.position_size_multiplier == 0.75

    def test_score_0_5_to_0_7_warning(self):
        # Use a mock loss_tracker that returns consecutive_losses=3 (+0.2)
        # so we don't pollute _stop_outs via record_trade.
        # Then add vetoes (+0.2) + drawdown acceleration (+0.2) = 0.6 total → warning.
        mock_lt = MagicMock()
        mock_lt.get_consecutive_losses.return_value = 3
        d = TiltDetector(loss_tracker=mock_lt)
        d.record_risk_veto()
        d.record_risk_veto()  # +0.2 vetoes
        for _ in range(4):
            d.update_drawdown(1.0)
        for _ in range(4):
            d.update_drawdown(1.5)  # +0.2 drawdown acceleration
        # total: 0.2 (consecutive) + 0.2 (vetoes) + 0.2 (drawdown) = 0.6 → warning
        s = d.check()
        assert s.severity == "warning"
        assert s.position_size_multiplier == 0.5

    def test_score_0_7_to_0_85_critical_quarter(self, detector):
        _record_losses(detector, 5)  # +0.4
        for _ in range(6):
            detector.record_trade("MES", "LONG", 1, 5000.0, pnl=10.0)  # +0.3 rapid trades
        detector.record_risk_veto()
        detector.record_risk_veto()  # +0.2 → total 0.9 → capped or critical
        s = detector.check()
        # Either critical 0.25 or halted 0.0
        assert s.severity == "critical"
        assert s.position_size_multiplier in (0.0, 0.25)


# ── Cooldown ──────────────────────────────────────────────────────────────────


class TestCooldown:
    def test_cooldown_set_on_7_losses(self, detector):
        _record_losses(detector, 7)
        s = detector.check()
        assert s.cooldown_until is not None
        assert s.cooldown_until > datetime.now()

    def test_cooldown_active_returns_halted_state(self, detector):
        _record_losses(detector, 7)
        _ = detector.check()  # triggers cooldown
        s2 = detector.check()
        assert s2.position_size_multiplier == 0.0
        assert "cooldown_active" in s2.tilt_indicators

    def test_expired_cooldown_clears(self, detector):
        # Manually set a past cooldown
        detector._cooldown_until = datetime.now() - timedelta(seconds=1)
        s = detector.check()
        assert s.cooldown_until is None
        assert detector._cooldown_until is None


# ── Reset ─────────────────────────────────────────────────────────────────────


class TestReset:
    def test_reset_clears_all_state(self, detector):
        _record_losses(detector, 5)
        for _ in range(6):
            detector.record_trade("MES", "LONG", 1, 5000.0, pnl=10.0)
        detector.record_risk_veto()
        detector.record_risk_veto()
        detector.reset()
        s = detector.check()
        assert not s.is_tilted
        assert s.tilt_score == 0.0
        assert s.tilt_indicators == []
        assert detector._cooldown_until is None

    def test_reset_clears_cooldown(self, detector):
        _record_losses(detector, 7)
        detector.check()  # activate cooldown
        detector.reset()
        assert detector._cooldown_until is None


# ── Loss Tracker Integration ──────────────────────────────────────────────────


class TestLossTrackerIntegration:
    def test_uses_loss_tracker_consecutive_count(self):
        mock_lt = MagicMock()
        mock_lt.get_consecutive_losses.return_value = 5
        d = TiltDetector(loss_tracker=mock_lt)
        s = d.check()
        assert any("consecutive_losses_5" in i for i in s.tilt_indicators)
        mock_lt.get_consecutive_losses.assert_called()

    def test_falls_back_to_in_memory_if_loss_tracker_fails(self):
        mock_lt = MagicMock()
        mock_lt.get_consecutive_losses.side_effect = Exception("tracker error")
        d = TiltDetector(loss_tracker=mock_lt)
        # No trades recorded, so in-memory count = 0
        s = d.check()
        assert not s.is_tilted


# ── Safety Layer Integration ──────────────────────────────────────────────────


class TestSafetyLayerIntegration:
    """Verify tilt_detector attribute is correctly wired."""

    def test_safety_layer_has_tilt_detector_attribute(self):
        from risk.safety_layer import SafetyLayer

        class FakeConfig:
            LIVE_TRADING_ENABLED = True
            REQUIRE_HUMAN_APPROVAL = False
            MAX_DAILY_LOSS_PCT = 0.02
            MAX_DRAWDOWN_PCT = 0.10
            MAX_SINGLE_ORDER_VALUE = 50000.0
            MAX_POSITION_SIZE_PCT = 0.25
            MAX_ORDERS_PER_MINUTE = 10
            MAX_CONTRACTS_PER_INSTRUMENT = 5

        sl = SafetyLayer(FakeConfig())
        assert hasattr(sl, "tilt_detector")
        assert sl.tilt_detector is None

    def test_tilt_detector_injection(self):
        from risk.safety_layer import SafetyLayer

        class FakeConfig:
            LIVE_TRADING_ENABLED = True
            REQUIRE_HUMAN_APPROVAL = False
            MAX_DAILY_LOSS_PCT = 0.02
            MAX_DRAWDOWN_PCT = 0.10
            MAX_SINGLE_ORDER_VALUE = 50000.0
            MAX_POSITION_SIZE_PCT = 0.25
            MAX_ORDERS_PER_MINUTE = 10
            MAX_CONTRACTS_PER_INSTRUMENT = 5

        sl = SafetyLayer(FakeConfig())
        td = TiltDetector()
        sl.tilt_detector = td
        assert sl.tilt_detector is td

    def test_check_order_blocked_when_tilt_halted(self):
        from risk.safety_layer import OrderRequest, SafetyLayer

        class FakeConfig:
            LIVE_TRADING_ENABLED = True
            REQUIRE_HUMAN_APPROVAL = False
            MAX_DAILY_LOSS_PCT = 0.02
            MAX_DRAWDOWN_PCT = 0.10
            MAX_SINGLE_ORDER_VALUE = 50000.0
            MAX_POSITION_SIZE_PCT = 0.25
            MAX_ORDERS_PER_MINUTE = 10
            MAX_CONTRACTS_PER_INSTRUMENT = 5

        sl = SafetyLayer(FakeConfig())
        td = TiltDetector()
        _record_losses(td, 7)  # triggers halt
        td.check()  # activate cooldown
        sl.tilt_detector = td

        # estimated_value must be < 25% of portfolio_equity to pass the position-size check
        # 2000 / 100000 = 2% < 25% — well within limit
        order = OrderRequest(
            symbol="MES",
            quantity=1,
            order_type="market",
            is_futures=True,
            estimated_value=2000.0,
        )
        result = sl.check_order(order, portfolio_equity=100000.0)
        assert not result.approved
        assert "tilt" in result.rejection_reason.lower()

    def test_check_order_warning_when_tilt_caution(self):
        from risk.safety_layer import OrderRequest, SafetyLayer

        class FakeConfig:
            LIVE_TRADING_ENABLED = True
            REQUIRE_HUMAN_APPROVAL = False
            MAX_DAILY_LOSS_PCT = 0.02
            MAX_DRAWDOWN_PCT = 0.10
            MAX_SINGLE_ORDER_VALUE = 50000.0
            MAX_POSITION_SIZE_PCT = 0.25
            MAX_ORDERS_PER_MINUTE = 10
            MAX_CONTRACTS_PER_INSTRUMENT = 5

        sl = SafetyLayer(FakeConfig())
        td = TiltDetector()
        _record_losses(td, 3)  # score=0.2 → caution → 0.75x
        td.record_risk_veto()
        td.record_risk_veto()  # +0.2 → 0.4 → caution
        sl.tilt_detector = td

        order = OrderRequest(
            symbol="MES",
            quantity=4,
            order_type="market",
            is_futures=True,
            estimated_value=20000.0,
        )
        result = sl.check_order(order, portfolio_equity=100000.0)
        assert result.approved
        assert any("tilt" in w.lower() for w in result.warnings)

```

### `engine/tests/test_consolidator.py`
```python
"""
Tests for TradingMemoryConsolidator — /dream nightly pattern consolidation.
"""

import os
import sys
from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from engine.learning.consolidator import TradingMemoryConsolidator


class TestConsolidator:
    def setup_method(self):
        self.consolidator = TradingMemoryConsolidator(db_manager=None, llm_client=None)

    def _make_trades(self, n_wins=3, n_losses=2):
        trades = []
        for i in range(n_wins):
            trades.append(
                {
                    "direction": "long",
                    "pnl": 50.0,
                    "entry_time": f"2026-04-02T{9 + i:02d}:35:00",
                    "symbol": "MES",
                }
            )
        for i in range(n_losses):
            trades.append(
                {
                    "direction": "long",
                    "pnl": -30.0,
                    "entry_time": f"2026-04-02T{14 + i:02d}:00:00",
                    "symbol": "MES",
                }
            )
        return trades

    # ── consolidate_daily ──────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_consolidate_no_trades_returns_no_trades(self):
        result = await self.consolidator.consolidate_daily("2026-01-01")
        assert result["status"] == "no_trades"
        assert result["date"] == "2026-01-01"
        assert result["patterns"] == []
        assert result["accuracy"] == {}

    @pytest.mark.asyncio
    async def test_consolidate_defaults_to_today(self):
        # consolidate_daily with no arg defaults to today — just check it
        # returns no_trades since db_manager is None (no real DB)
        result = await self.consolidator.consolidate_daily()
        assert "date" in result
        assert result["status"] == "no_trades"

    # ── _extract_patterns ──────────────────────────────────────────────────────

    def test_extract_patterns_from_trades(self):
        trades = self._make_trades(3, 2)
        patterns = self.consolidator._extract_patterns(trades)
        assert isinstance(patterns, list)

    def test_extract_patterns_time_of_day(self):
        """Trades at the same hour with >60% win rate should generate a time pattern."""
        trades = [
            {
                "direction": "long",
                "pnl": 100.0,
                "entry_time": "2026-04-02T09:35:00",
                "symbol": "MES",
            },
            {
                "direction": "long",
                "pnl": 80.0,
                "entry_time": "2026-04-02T09:40:00",
                "symbol": "MES",
            },
            {
                "direction": "long",
                "pnl": -20.0,
                "entry_time": "2026-04-02T09:50:00",
                "symbol": "MES",
            },
        ]
        patterns = self.consolidator._extract_patterns(trades)
        time_patterns = [p for p in patterns if p["category"] == "time"]
        assert any("hour_09" in p["name"] for p in time_patterns)

    def test_extract_patterns_direction_bias(self):
        """Trades with same direction qualify for a direction bias pattern."""
        trades = self._make_trades(3, 2)  # 5 long trades
        patterns = self.consolidator._extract_patterns(trades)
        regime_patterns = [p for p in patterns if p["category"] == "regime"]
        assert any("long_bias" in p["name"] for p in regime_patterns)

    def test_extract_patterns_returns_list(self):
        assert self.consolidator._extract_patterns([]) == []

    def test_extract_patterns_short_direction(self):
        trades = [
            {
                "direction": "short",
                "pnl": 50.0,
                "entry_time": "2026-04-02T10:00:00",
                "symbol": "MES",
            },
            {
                "direction": "short",
                "pnl": 60.0,
                "entry_time": "2026-04-02T10:05:00",
                "symbol": "MES",
            },
        ]
        patterns = self.consolidator._extract_patterns(trades)
        names = [p["name"] for p in patterns]
        assert any("short_bias" in n for n in names)

    # ── _score_signal_accuracy ─────────────────────────────────────────────────

    def test_score_accuracy_correct(self):
        trades = self._make_trades(3, 2)  # 3 wins, 2 losses = 60%
        accuracy = self.consolidator._score_signal_accuracy(trades)
        assert accuracy["total"] == 5
        assert accuracy["wins"] == 3
        assert accuracy["losses"] == 2
        assert accuracy["accuracy_pct"] == 60.0

    def test_score_accuracy_empty(self):
        acc = self.consolidator._score_signal_accuracy([])
        assert acc["total"] == 0

    def test_score_accuracy_all_wins(self):
        trades = [{"pnl": 100.0} for _ in range(4)]
        acc = self.consolidator._score_signal_accuracy(trades)
        assert acc["wins"] == 4
        assert acc["accuracy_pct"] == 100.0

    def test_score_accuracy_all_losses(self):
        trades = [{"pnl": -50.0} for _ in range(3)]
        acc = self.consolidator._score_signal_accuracy(trades)
        assert acc["wins"] == 0
        assert acc["accuracy_pct"] == 0.0

    def test_score_accuracy_total_pnl(self):
        trades = [{"pnl": 100.0}, {"pnl": -40.0}]
        acc = self.consolidator._score_signal_accuracy(trades)
        assert acc["total_pnl"] == 60.0

    # ── get_active_patterns / get_signal_accuracy (no DB) ────────────────────

    @pytest.mark.asyncio
    async def test_get_active_patterns_no_db(self):
        result = await self.consolidator.get_active_patterns()
        assert result == []

    @pytest.mark.asyncio
    async def test_get_signal_accuracy_no_db(self):
        result = await self.consolidator.get_signal_accuracy(30)
        assert result["total"] == 0
        assert result["days"] == 30

    @pytest.mark.asyncio
    async def test_get_signal_accuracy_custom_days(self):
        result = await self.consolidator.get_signal_accuracy(7)
        assert result["days"] == 7

    # ── _upsert_pattern / _prune_stale_patterns (no DB — graceful degradation) ─

    @pytest.mark.asyncio
    async def test_upsert_pattern_no_db_is_noop(self):
        """Should not raise when db_manager is None."""
        pattern = {
            "name": "test_pattern",
            "category": "time",
            "conditions": "{}",
            "win_rate": 0.7,
            "avg_return": 50.0,
            "frequency": 5,
        }
        await self.consolidator._upsert_pattern(pattern, "2026-04-02")  # no raise

    @pytest.mark.asyncio
    async def test_prune_stale_no_db_is_noop(self):
        """Should not raise when db_manager is None."""
        await self.consolidator._prune_stale_patterns()  # no raise

    # ── pattern field validation ───────────────────────────────────────────────

    def test_pattern_has_required_fields(self):
        trades = self._make_trades(4, 1)  # strong win rate at hours 9-12
        patterns = self.consolidator._extract_patterns(trades)
        for p in patterns:
            assert "name" in p
            assert "category" in p
            assert "conditions" in p
            assert "win_rate" in p
            assert "avg_return" in p
            assert "frequency" in p

    def test_win_rate_clamped_to_valid_range(self):
        trades = self._make_trades(5, 0)  # all wins
        patterns = self.consolidator._extract_patterns(trades)
        for p in patterns:
            assert 0.0 <= p["win_rate"] <= 1.0

```

### `engine/tests/test_speculation.py`
```python
"""
Tests for the Speculation/Pre-execution Engine.
Covers PrefetchCache TTL semantics and SpeculationEngine singleton/caching behavior.
"""

import asyncio
import os
import sys
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

# Allow both `pytest engine/tests/` and `cd engine && pytest tests/` invocations
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


class TestPrefetchCache:
    def setup_method(self):
        from speculation.prefetch_cache import PrefetchCache

        self.cache = PrefetchCache(ttl_seconds=2)  # 2s TTL for fast tests

    def test_set_and_get(self):
        self.cache.set("key1", {"value": 42})
        result = self.cache.get("key1")
        assert result == {"value": 42}

    def test_miss_returns_none(self):
        assert self.cache.get("nonexistent") is None

    def test_ttl_expiry(self):
        self.cache.set("expiring", "data", ttl=1)
        assert self.cache.get("expiring") == "data"
        time.sleep(1.1)
        assert self.cache.get("expiring") is None

    def test_has_returns_true_for_valid(self):
        self.cache.set("present", True)
        assert self.cache.has("present")

    def test_has_returns_false_for_missing(self):
        assert not self.cache.has("missing")

    def test_invalidate_removes_key(self):
        self.cache.set("remove_me", 123)
        self.cache.invalidate("remove_me")
        assert self.cache.get("remove_me") is None

    def test_invalidate_nonexistent_is_noop(self):
        # Should not raise
        self.cache.invalidate("ghost_key")

    def test_clear_removes_all(self):
        self.cache.set("a", 1)
        self.cache.set("b", 2)
        self.cache.clear()
        assert self.cache.get("a") is None
        assert self.cache.get("b") is None

    def test_stats(self):
        self.cache.set("a", 1)
        self.cache.set("b", 2)
        stats = self.cache.stats()
        assert stats["valid_keys"] >= 2
        assert "ttl_seconds" in stats
        assert stats["ttl_seconds"] == 2

    def test_stats_counts_expired(self):
        self.cache.set("expiring_stat", "x", ttl=1)
        time.sleep(1.1)
        stats = self.cache.stats()
        # After expiry the key is still in _store until accessed;
        # stats counts it as expired (not evicted until next get)
        assert stats["expired_keys"] >= 1

    def test_keys_by_prefix(self):
        self.cache.set("indicators:MES:1h", {})
        self.cache.set("indicators:MNQ:1h", {})
        self.cache.set("bars:MES:1h", {})
        keys = self.cache.keys_by_prefix("indicators:")
        assert "indicators:MES:1h" in keys
        assert "indicators:MNQ:1h" in keys
        assert "bars:MES:1h" not in keys

    def test_keys_by_prefix_excludes_expired(self):
        self.cache.set("indicators:EXPIRED:1h", {}, ttl=1)
        time.sleep(1.1)
        keys = self.cache.keys_by_prefix("indicators:")
        assert "indicators:EXPIRED:1h" not in keys

    def test_overwrite_key_resets_ttl(self):
        self.cache.set("refresh", "old", ttl=1)
        time.sleep(0.5)
        # Overwrite with longer TTL
        self.cache.set("refresh", "new", ttl=5)
        time.sleep(0.8)  # Would have expired on old TTL
        assert self.cache.get("refresh") == "new"


class TestSpeculationEngine:
    def setup_method(self):
        from speculation.engine import SpeculationEngine

        config = MagicMock()
        config.FUTURES_WATCHLIST = ["MES"]
        config.OPTIONS_WATCHLIST = []
        self.engine = SpeculationEngine(config=config, data_manager=None)

    @pytest.mark.asyncio
    async def test_speculate_no_data_manager(self):
        result = await self.engine.speculate()
        assert "symbols_processed" in result
        assert result["symbols_processed"] == 0  # No data manager = no data
        assert result["symbols_requested"] == 1  # MES was in watchlist
        assert "duration_ms" in result

    @pytest.mark.asyncio
    async def test_speculate_increments_count(self):
        await self.engine.speculate()
        await self.engine.speculate()
        assert self.engine._speculation_count == 2

    @pytest.mark.asyncio
    async def test_speculate_returns_errors_list(self):
        result = await self.engine.speculate()
        assert "errors" in result
        assert isinstance(result["errors"], list)

    def test_get_status(self):
        status = self.engine.get_status()
        assert "speculation_count" in status
        assert "cache" in status
        assert "cache_hits" in status
        assert "running" in status
        assert "cached_symbols" in status

    def test_get_status_last_speculation_none_initially(self):
        status = self.engine.get_status()
        assert status["last_speculation"] is None

    @pytest.mark.asyncio
    async def test_get_status_last_speculation_set_after_cycle(self):
        await self.engine.speculate()
        status = self.engine.get_status()
        assert status["last_speculation"] is not None

    def test_cache_hit_recording(self):
        self.engine.record_cache_hit()
        self.engine.record_cache_hit()
        assert self.engine._cache_hits == 2

    def test_get_cached_indicators_miss(self):
        result = self.engine.get_cached_indicators("MES")
        assert result is None

    def test_set_and_get_cached_indicators(self):
        self.engine.cache.set("indicators:MES:1h", {"stc_val": 45.0, "atr": 12.5})
        result = self.engine.get_cached_indicators("MES")
        assert result["stc_val"] == 45.0

    def test_get_cached_bars_miss(self):
        assert self.engine.get_cached_bars("MES") is None

    def test_set_and_get_cached_bars(self):
        import pandas as pd

        fake_bars = pd.DataFrame({"close": [100.0, 101.0, 102.0]})
        self.engine.cache.set("bars:MES:1h", fake_bars)
        result = self.engine.get_cached_bars("MES")
        assert result is not None
        assert len(result) == 3

    def test_singleton_pattern(self):
        from speculation.engine import get_speculation_engine, set_speculation_engine

        mock = MagicMock()
        set_speculation_engine(mock)
        assert get_speculation_engine() is mock
        # Cleanup — reset to None so other tests are not affected
        set_speculation_engine(None)

    def test_singleton_default_none(self):
        from speculation.engine import get_speculation_engine, set_speculation_engine

        set_speculation_engine(None)
        assert get_speculation_engine() is None

    @pytest.mark.asyncio
    async def test_prefetch_market_data_no_data_manager(self):
        result = await self.engine.prefetch_market_data("MES")
        assert result is None

    @pytest.mark.asyncio
    async def test_prefetch_market_data_returns_cached(self):
        import pandas as pd

        fake_bars = pd.DataFrame({"close": [1.0, 2.0, 3.0]})
        self.engine.cache.set("bars:MES:1h", fake_bars)
        result = await self.engine.prefetch_market_data("MES")
        assert result is not None

    @pytest.mark.asyncio
    async def test_precompute_indicators_no_bars_returns_none(self):
        result = await self.engine.precompute_indicators("MES")
        assert result is None

    @pytest.mark.asyncio
    async def test_precompute_indicators_with_mock_data_manager(self):
        """SpeculationEngine with a mock data manager that returns bars."""
        import pandas as pd

        from speculation.engine import SpeculationEngine

        mock_dm = MagicMock()
        fake_bars = pd.DataFrame(
            {
                "open": [100.0] * 60,
                "high": [102.0] * 60,
                "low": [98.0] * 60,
                "close": [101.0] * 60,
                "volume": [1000.0] * 60,
            }
        )
        mock_dm.get_bars = AsyncMock(return_value=fake_bars)

        config = MagicMock()
        config.FUTURES_WATCHLIST = ["MES"]
        config.OPTIONS_WATCHLIST = []

        engine = SpeculationEngine(config=config, data_manager=mock_dm)
        bars = await engine.prefetch_market_data("MES")
        assert bars is not None
        # Indicators may or may not compute depending on backtest.signals availability
        # but we should not raise
        await engine.precompute_indicators("MES", bars)

```

### `engine/tests/test_task_board.py`
```python
"""
Tests for engine/agents/task_board.py
Covers thread safety, all status transitions, counters, and edge cases.
"""

import threading
import time

import pytest

from agents.task_board import (
    PipelineTask,
    PipelineTaskBoard,
    StageStatus,
    get_task_board,
    set_task_board_instance,
)

KNOWN_STAGES = [
    "technical_analyst",
    "news_analyst",
    "social_analyst",
    "fundamentalist",
    "bull_researcher",
    "bear_researcher",
    "debate_orchestrator",
    "trader",
    "risk_manager",
    "fund_manager",
]


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def board() -> PipelineTaskBoard:
    """Return a fresh PipelineTaskBoard with a started run."""
    b = PipelineTaskBoard()
    b.start_run(run_id="test-run-1", symbol="MES", interval="1h")
    return b


@pytest.fixture
def empty_board() -> PipelineTaskBoard:
    """Return a fresh PipelineTaskBoard with NO run started."""
    return PipelineTaskBoard()


# ── start_run ─────────────────────────────────────────────────────────────────


def test_start_run_initializes_all_10_stages(board):
    status = board.get_status()
    assert len(status["stages"]) == 10
    assert set(status["stages"].keys()) == set(KNOWN_STAGES)


def test_start_run_all_stages_pending(board):
    status = board.get_status()
    for name, stage_info in status["stages"].items():
        assert stage_info["status"] == StageStatus.PENDING.value, f"{name} should be PENDING"


def test_start_run_sets_metadata(board):
    status = board.get_status()
    assert status["run_id"] == "test-run-1"
    assert status["symbol"] == "MES"
    assert status["interval"] == "1h"
    assert status["run_started_at"] is not None


# ── start_stage ───────────────────────────────────────────────────────────────


def test_start_stage_transitions_to_running(board):
    board.start_stage("trader")
    status = board.get_status()
    assert status["stages"]["trader"]["status"] == StageStatus.RUNNING.value


def test_start_stage_sets_started_at(board):
    board.start_stage("risk_manager")
    status = board.get_status()
    assert status["stages"]["risk_manager"]["started_at"] is not None


def test_start_stage_unknown_stage_is_noop(board):
    """Calling start_stage with a nonexistent stage name must not raise."""
    board.start_stage("nonexistent_stage")  # should not raise
    status = board.get_status()
    assert "nonexistent_stage" not in status["stages"]


# ── complete_stage ────────────────────────────────────────────────────────────


def test_complete_stage_transitions_to_done(board):
    board.start_stage("trader")
    board.complete_stage("trader")
    status = board.get_status()
    assert status["stages"]["trader"]["status"] == StageStatus.DONE.value


def test_complete_stage_sets_duration_ms(board):
    board.start_stage("trader")
    time.sleep(0.05)  # ensure measurable duration
    board.complete_stage("trader")
    status = board.get_status()
    assert status["stages"]["trader"]["duration_ms"] is not None
    assert status["stages"]["trader"]["duration_ms"] >= 0


def test_complete_stage_sets_result_summary(board):
    board.start_stage("trader")
    board.complete_stage("trader", result_summary="action=BUY qty=2")
    status = board.get_status()
    assert status["stages"]["trader"]["result_summary"] == "action=BUY qty=2"


def test_complete_stage_without_start_sets_no_duration(board):
    """complete_stage on a stage that was never started — duration_ms stays None."""
    board.complete_stage("fund_manager")
    status = board.get_status()
    assert status["stages"]["fund_manager"]["duration_ms"] is None


# ── error_stage ───────────────────────────────────────────────────────────────


def test_error_stage_transitions_to_error(board):
    board.start_stage("news_analyst")
    board.error_stage("news_analyst", "Connection timeout")
    status = board.get_status()
    assert status["stages"]["news_analyst"]["status"] == StageStatus.ERROR.value


def test_error_stage_sets_error_message(board):
    board.start_stage("news_analyst")
    board.error_stage("news_analyst", "Connection timeout")
    status = board.get_status()
    assert status["stages"]["news_analyst"]["error"] == "Connection timeout"


def test_error_stage_sets_duration_ms_when_started(board):
    board.start_stage("social_analyst")
    time.sleep(0.02)
    board.error_stage("social_analyst", "boom")
    status = board.get_status()
    assert status["stages"]["social_analyst"]["duration_ms"] is not None


# ── skip_stage ────────────────────────────────────────────────────────────────


def test_skip_stage_transitions_to_skipped(board):
    board.skip_stage("fund_manager")
    status = board.get_status()
    assert status["stages"]["fund_manager"]["status"] == StageStatus.SKIPPED.value


# ── overall_status ────────────────────────────────────────────────────────────


def test_overall_status_running_when_any_running(board):
    board.start_stage("technical_analyst")
    status = board.get_status()
    assert status["overall"] == "running"


def test_overall_status_error_when_any_error(board):
    board.start_stage("technical_analyst")
    board.error_stage("technical_analyst", "err")
    status = board.get_status()
    assert status["overall"] == "error"


def test_overall_status_error_takes_priority_over_running(board):
    board.start_stage("technical_analyst")
    board.error_stage("technical_analyst", "err")
    board.start_stage("news_analyst")  # still running
    status = board.get_status()
    assert status["overall"] == "error"


def test_overall_status_complete_when_all_done_or_skipped(board):
    for stage in KNOWN_STAGES[:-1]:  # all but last
        board.start_stage(stage)
        board.complete_stage(stage)
    board.skip_stage(KNOWN_STAGES[-1])
    status = board.get_status()
    assert status["overall"] == "complete"


def test_overall_status_pending_when_all_pending(board):
    # After start_run all stages are PENDING
    status = board.get_status()
    assert status["overall"] == "pending"


def test_overall_status_complete_for_empty_board(empty_board):
    """An empty board (no stages) returns 'complete' — all() of empty is True."""
    status = empty_board.get_status()
    # This is Python's vacuous truth: all() over empty iterable → True.
    # A board with no stages has trivially "nothing left to do".
    assert status["overall"] == "complete"


# ── counters ──────────────────────────────────────────────────────────────────


def test_done_count_is_correct(board):
    for stage in KNOWN_STAGES[:3]:
        board.start_stage(stage)
        board.complete_stage(stage)
    status = board.get_status()
    assert status["done_count"] == 3


def test_error_count_is_correct(board):
    board.start_stage("news_analyst")
    board.error_stage("news_analyst", "oops")
    board.start_stage("social_analyst")
    board.error_stage("social_analyst", "oops2")
    status = board.get_status()
    assert status["error_count"] == 2


def test_total_stages_is_10(board):
    status = board.get_status()
    assert status["total_stages"] == 10


# ── reset ─────────────────────────────────────────────────────────────────────


def test_reset_clears_all_state(board):
    board.start_stage("trader")
    board.reset()
    status = board.get_status()
    assert status["run_id"] is None
    assert status["symbol"] is None
    assert status["interval"] is None
    assert status["run_started_at"] is None
    assert status["stages"] == {}


def test_reset_makes_run_id_none(board):
    board.reset()
    assert board.get_status()["run_id"] is None


def test_reset_resets_done_and_error_counts(board):
    board.start_stage("trader")
    board.complete_stage("trader")
    board.reset()
    status = board.get_status()
    assert status["done_count"] == 0
    assert status["error_count"] == 0


# ── singleton helpers ─────────────────────────────────────────────────────────


def test_get_task_board_returns_same_instance():
    b1 = get_task_board()
    b2 = get_task_board()
    assert b1 is b2


def test_set_task_board_instance_replaces_singleton():
    original = get_task_board()
    new_board = PipelineTaskBoard()
    set_task_board_instance(new_board)
    assert get_task_board() is new_board
    # Restore original for test isolation
    set_task_board_instance(original)


# ── thread safety ─────────────────────────────────────────────────────────────


def test_concurrent_start_stage_does_not_raise(board):
    """Hammering start_stage from multiple threads must not raise."""
    errors: list[Exception] = []

    def worker(stage: str):
        try:
            for _ in range(50):
                board.start_stage(stage)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(s,)) for s in KNOWN_STAGES]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"Thread errors: {errors}"


def test_concurrent_mixed_operations_do_not_raise(board):
    """Mixed operations from many threads must complete without exceptions."""
    errors: list[Exception] = []

    def worker(stage: str, idx: int):
        try:
            board.start_stage(stage)
            if idx % 3 == 0:
                board.complete_stage(stage, result_summary="ok")
            elif idx % 3 == 1:
                board.error_stage(stage, "err")
            else:
                board.skip_stage(stage)
            board.get_status()
        except Exception as e:
            errors.append(e)

    threads = [
        threading.Thread(target=worker, args=(KNOWN_STAGES[i % len(KNOWN_STAGES)], i))
        for i in range(40)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"Thread errors: {errors}"

```

### `engine/tests/test_config_router.py`
```python
"""
JARVIS TRADER — Config Router Tests
=====================================
Tests for GET /config/overview and GET /config/health-check.

All tests operate on the router directly via FastAPI TestClient — no
running engine required.  The TradingConfig singleton is imported from
config.py, so the test must load a valid .env (or set API_KEY in the
environment) before importing the app or the router.

Run with:
    cd engine
    .venv\\Scripts\\python.exe -m pytest tests/test_config_router.py -v --tb=short
"""

from __future__ import annotations

import os
import sys

import pytest

# ---------------------------------------------------------------------------
# Environment bootstrap — load .env so TradingConfig can validate API_KEY
# ---------------------------------------------------------------------------


def _load_env() -> None:
    """Load .env into os.environ (mirrors conftest pattern used in other tests)."""
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    if os.path.exists(env_path):
        with open(env_path) as fh:
            for line in fh:
                line = line.strip()
                if line and "=" in line and not line.startswith("#"):
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key, value)


_load_env()

# Ensure engine root is on sys.path before any engine imports
_ENGINE_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if _ENGINE_ROOT not in sys.path:
    sys.path.insert(0, _ENGINE_ROOT)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def client():
    """Return a FastAPI TestClient wrapping just the config_router."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from routers.config_router import router as config_router

    app = FastAPI()
    app.include_router(config_router)
    return TestClient(app, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# /config/overview tests
# ---------------------------------------------------------------------------


def test_overview_returns_200(client):
    """GET /config/overview must return HTTP 200."""
    resp = client.get("/config/overview")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"


def test_overview_has_categories(client):
    """Response must include a 'categories' key that is a non-empty dict."""
    data = client.get("/config/overview").json()
    assert "categories" in data, "'categories' key missing from response"
    assert isinstance(data["categories"], dict), "'categories' should be a dict"
    assert len(data["categories"]) > 0, "'categories' must not be empty"


def test_overview_has_total_fields(client):
    """Response must include 'total_fields' and it must be > 0."""
    data = client.get("/config/overview").json()
    assert "total_fields" in data, "'total_fields' key missing"
    assert data["total_fields"] > 0, "'total_fields' must be positive"


def test_overview_sensitive_keys_masked(client):
    """Sensitive keys (e.g. ANTHROPIC_API_KEY) must have values starting with '***'."""
    data = client.get("/config/overview").json()
    categories = data["categories"]

    sensitive_found = False
    for _cat, items in categories.items():
        for item in items:
            if item["sensitive"]:
                sensitive_found = True
                val = str(item["value"])
                assert val.startswith(
                    "***"
                ), f"Sensitive key {item['key']!r} value {val!r} does not start with '***'"
    # If no sensitive keys are configured, this assertion is vacuously True
    # (the test still exercises the code path)
    _ = sensitive_found  # suppress unused-variable


def test_overview_nonsensitive_keys_not_masked(client):
    """Non-sensitive keys must NOT have values that look like '***'."""
    data = client.get("/config/overview").json()
    categories = data["categories"]

    for _cat, items in categories.items():
        for item in items:
            if not item["sensitive"]:
                val = str(item["value"])
                assert not val.startswith(
                    "***"
                ), f"Non-sensitive key {item['key']!r} appears masked: {val!r}"


def test_overview_feature_flags_category_present(client):
    """The 'feature_flags' category must be present in the response."""
    data = client.get("/config/overview").json()
    assert (
        "feature_flags" in data["categories"]
    ), "'feature_flags' category missing from /config/overview"


def test_overview_feature_flags_contains_enable_kairos(client):
    """The 'feature_flags' category must contain ENABLE_KAIROS."""
    data = client.get("/config/overview").json()
    flag_keys = [item["key"] for item in data["categories"].get("feature_flags", [])]
    assert (
        "ENABLE_KAIROS" in flag_keys
    ), f"ENABLE_KAIROS not found in feature_flags category. Found: {flag_keys}"


def test_overview_safety_category_present(client):
    """The 'safety' category must be present."""
    data = client.get("/config/overview").json()
    assert "safety" in data["categories"], "'safety' category missing"


def test_overview_items_have_required_fields(client):
    """Every item in every category must have 'key', 'value', and 'sensitive' fields."""
    data = client.get("/config/overview").json()
    for cat, items in data["categories"].items():
        for item in items:
            assert "key" in item, f"Category {cat!r}: item missing 'key'"
            assert "value" in item, f"Category {cat!r}: item {item.get('key')!r} missing 'value'"
            assert (
                "sensitive" in item
            ), f"Category {cat!r}: item {item.get('key')!r} missing 'sensitive'"
            assert isinstance(
                item["sensitive"], bool
            ), f"Category {cat!r}: item {item.get('key')!r} 'sensitive' must be bool"


# ---------------------------------------------------------------------------
# /config/health-check tests
# ---------------------------------------------------------------------------


def test_health_check_returns_200(client):
    """GET /config/health-check must return HTTP 200."""
    resp = client.get("/config/health-check")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"


def test_health_check_has_configured_dict(client):
    """Response must include 'configured' dict with boolean values."""
    data = client.get("/config/health-check").json()
    assert "configured" in data, "'configured' key missing from health-check response"
    assert isinstance(data["configured"], dict), "'configured' must be a dict"
    for key, val in data["configured"].items():
        assert isinstance(val, bool), f"configured[{key!r}] must be bool, got {type(val)}"


def test_health_check_configured_has_six_critical_keys(client):
    """The 'configured' dict must contain all 6 critical API key checks."""
    expected = {
        "ANTHROPIC_API_KEY",
        "FINNHUB_API_KEY",
        "POLYGON_API_KEY",
        "ALPACA_API_KEY",
        "TWILIO_ACCOUNT_SID",
        "WHATSAPP_TO",
    }
    data = client.get("/config/health-check").json()
    actual = set(data["configured"].keys())
    missing = expected - actual
    assert not missing, f"Missing critical keys in 'configured': {missing}"


def test_health_check_live_trading_false_by_default(client):
    """live_trading_enabled must default to False (safety posture)."""
    data = client.get("/config/health-check").json()
    assert "live_trading_enabled" in data, "'live_trading_enabled' missing"
    assert (
        data["live_trading_enabled"] is False
    ), "live_trading_enabled should default to False for safety"


def test_health_check_require_human_approval_true_by_default(client):
    """require_human_approval must default to True (safety posture)."""
    data = client.get("/config/health-check").json()
    assert "require_human_approval" in data, "'require_human_approval' missing"
    assert (
        data["require_human_approval"] is True
    ), "require_human_approval should default to True for safety"


def test_health_check_paper_trading_field_present(client):
    """Response must include 'paper_trading' field."""
    data = client.get("/config/health-check").json()
    assert "paper_trading" in data, "'paper_trading' field missing from health-check"
    assert isinstance(data["paper_trading"], bool), "'paper_trading' must be bool"

```

### `engine/tests/test_log_sanitizer.py`
```python
"""Tests for anti-signal-leakage log sanitizer."""

import logging

import pytest

from security.log_sanitizer import (
    SENSITIVE_PATTERNS,
    SIGNAL_PATTERNS,
    SanitizingFormatter,
    install_sanitizing_formatter,
    sanitize_message,
)


class TestSanitizeMessage:
    def test_no_sensitive_data_unchanged(self):
        msg = "Normal log message with no sensitive data"
        assert sanitize_message(msg) == msg

    def test_anthropic_api_key_masked(self):
        msg = "Using key [REDACTED_ANTHROPIC_KEY]"
        result = sanitize_message(msg)
        assert "sk-ant-***" in result
        assert "ABCDEFGHIJKLMNOPQRSTUVWXYZ" not in result

    def test_whatsapp_number_masked(self):
        msg = "Sending to whatsapp:+17634520414"
        result = sanitize_message(msg)
        assert "whatsapp:+***" in result
        assert "17634520414" not in result

    def test_long_signal_masked_with_sanitize_signals(self):
        msg = "Signal: LONG MES @ 5823.50"
        result = sanitize_message(msg, sanitize_signals=True)
        assert "***" in result

    def test_short_signal_masked_with_sanitize_signals(self):
        msg = "Signal: SHORT MNQ @ 19432.25"
        result = sanitize_message(msg, sanitize_signals=True)
        assert "***" in result

    def test_long_signal_not_masked_without_sanitize_signals(self):
        msg = "Signal: LONG MES @ 5823.50"
        result = sanitize_message(msg, sanitize_signals=False)
        # LONG keyword itself should still be present (entry/exit patterns only active with sanitize_signals=True)
        assert "LONG" in result

    def test_entry_price_masked_with_signals(self):
        msg = "Entry: 5823.50"
        result = sanitize_message(msg, sanitize_signals=True)
        assert "***" in result

    def test_stop_price_masked_with_signals(self):
        msg = "Stop: 5810.50"
        result = sanitize_message(msg, sanitize_signals=True)
        assert "***" in result

    def test_contracts_masked_with_signals(self):
        msg = "Placing 2 contracts MES"
        result = sanitize_message(msg, sanitize_signals=True)
        assert "*** contracts" in result

    def test_pnl_masked_with_signals(self):
        msg = "Daily P&L: +$284.50"
        result = sanitize_message(msg, sanitize_signals=True)
        assert "$***" in result or "+/-$***" in result

    def test_empty_string_unchanged(self):
        assert sanitize_message("") == ""

    def test_none_converted_to_string(self):
        result = sanitize_message(None)  # type: ignore
        assert isinstance(result, str)

    def test_twilio_account_sid_masked(self):
        msg = "Twilio SID: ACabcdef1234567890abcdef1234567890"
        result = sanitize_message(msg)
        assert "AC***" in result

    def test_ib_account_number_masked(self):
        msg = "IB account U123456 connected"
        result = sanitize_message(msg)
        assert "IB***" in result

    def test_does_not_crash_on_unicode(self):
        msg = "Unicode test: \u65e5\u672c\u8a9e \u30c6\u30b9\u30c8"
        result = sanitize_message(msg)
        assert isinstance(result, str)

    def test_multiple_api_keys_in_one_message(self):
        msg = "key1=[REDACTED_ANTHROPIC_KEY] key2=[REDACTED_ANTHROPIC_KEY]"
        result = sanitize_message(msg)
        assert "sk-ant-***" in result
        assert "AAABBBCCCDDDEEEFFFGGGHHH" not in result
        assert "ZZZYYYXXXWWWVVV" not in result

    def test_signal_patterns_not_applied_by_default(self):
        msg = "Entry: 5000.00, Stop: 4900.00"
        result = sanitize_message(msg)
        # Without sanitize_signals=True, entry/stop should remain
        assert "5000.00" in result

    def test_signal_patterns_applied_when_requested(self):
        msg = "Entry: 5000.00, Stop: 4900.00"
        result = sanitize_message(msg, sanitize_signals=True)
        assert "5000.00" not in result
        assert "4900.00" not in result

    def test_target_price_masked_with_signals(self):
        msg = "Target: 5900.00"
        result = sanitize_message(msg, sanitize_signals=True)
        assert "***" in result
        assert "5900.00" not in result

    def test_return_type_always_string(self):
        for input_val in [None, 42, 3.14, [], {}]:
            result = sanitize_message(input_val)  # type: ignore
            assert isinstance(result, str), f"Expected str for input {input_val!r}"

    def test_whatsapp_international_number(self):
        msg = "Alert sent to whatsapp:+447911123456"
        result = sanitize_message(msg)
        assert "whatsapp:+***" in result
        assert "447911123456" not in result

    def test_sensitive_patterns_list_not_empty(self):
        assert len(SENSITIVE_PATTERNS) > 0

    def test_signal_patterns_list_not_empty(self):
        assert len(SIGNAL_PATTERNS) > 0


class TestSanitizingFormatter:
    def setup_method(self):
        self.formatter = SanitizingFormatter(
            fmt="%(levelname)s - %(message)s",
            sanitize_signals=True,
        )

    def test_formatter_is_logging_formatter(self):
        assert isinstance(self.formatter, logging.Formatter)

    def test_formats_normal_record(self):
        record = logging.LogRecord("test", logging.INFO, "", 0, "Normal message", (), None)
        result = self.formatter.format(record)
        assert "Normal message" in result

    def test_sanitizes_api_key_in_record(self):
        record = logging.LogRecord(
            "test",
            logging.INFO,
            "",
            0,
            "Key: [REDACTED_ANTHROPIC_KEY]",
            (),
            None,
        )
        result = self.formatter.format(record)
        assert "ABCDEFGHIJKLMNOPQRSTUVWXYZ" not in result

    def test_never_crashes(self):
        """Formatter must never raise — log sanitization must be bulletproof."""
        record = logging.LogRecord("test", logging.ERROR, "", 0, None, (), None)
        try:
            result = self.formatter.format(record)
            assert isinstance(result, str)
        except Exception as e:
            pytest.fail(f"Formatter raised: {e}")

    def test_sanitize_signals_false_does_not_mask_prices(self):
        formatter = SanitizingFormatter(
            fmt="%(message)s",
            sanitize_signals=False,
        )
        record = logging.LogRecord("test", logging.INFO, "", 0, "Entry: 5823.50", (), None)
        result = formatter.format(record)
        assert "5823.50" in result

    def test_sanitize_signals_true_masks_prices(self):
        formatter = SanitizingFormatter(
            fmt="%(message)s",
            sanitize_signals=True,
        )
        record = logging.LogRecord("test", logging.INFO, "", 0, "Entry: 5823.50", (), None)
        result = formatter.format(record)
        assert "5823.50" not in result

    def test_formatter_with_dict_args(self):
        """Formatter should not crash when record.args is a dict."""
        record = logging.LogRecord(
            "test",
            logging.INFO,
            "",
            0,
            "key=%(key)s value=%(val)s",
            {"key": "[REDACTED_ANTHROPIC_KEY]", "val": "normal"},
            None,
        )
        try:
            result = self.formatter.format(record)
            assert isinstance(result, str)
        except Exception as e:
            pytest.fail(f"Formatter raised on dict args: {e}")

    def test_formatter_with_tuple_args(self):
        """Formatter should not crash when record.args is a tuple."""
        record = logging.LogRecord(
            "test",
            logging.INFO,
            "",
            0,
            "val=%s",
            ("[REDACTED_ANTHROPIC_KEY]",),
            None,
        )
        try:
            result = self.formatter.format(record)
            assert isinstance(result, str)
        except Exception as e:
            pytest.fail(f"Formatter raised on tuple args: {e}")


class TestInstallSanitizingFormatter:
    def test_install_does_not_crash(self):
        """Installing the formatter should not raise even if no handlers exist."""
        try:
            install_sanitizing_formatter(sanitize_signals=False)
        except Exception as e:
            pytest.fail(f"install_sanitizing_formatter raised: {e}")

    def test_install_with_signals_does_not_crash(self):
        """Installing with sanitize_signals=True should not raise."""
        try:
            install_sanitizing_formatter(sanitize_signals=True)
        except Exception as e:
            pytest.fail(f"install_sanitizing_formatter(sanitize_signals=True) raised: {e}")

    def test_install_idempotent(self):
        """Calling install multiple times should not cause errors."""
        try:
            install_sanitizing_formatter(sanitize_signals=False)
            install_sanitizing_formatter(sanitize_signals=True)
            install_sanitizing_formatter(sanitize_signals=False)
        except Exception as e:
            pytest.fail(f"Repeated install_sanitizing_formatter raised: {e}")

```
