"""
JARVIS TRADER — Pipeline Context Manager
==========================================
Implements a 4-tier context compaction strategy to prevent LLM context window
overflow during multi-agent pipeline runs.

Tier thresholds (by token utilization):
  NONE      < 50%  — no action needed
  TRIM     50-70%  — strip raw OHLCV arrays from message content
  TIME_CLEAR 70-85% — also remove stale analyst results (> 10 min old)
  SUMMARIZE 85-95% — also LLM-summarize prior stages via Haiku
  EMERGENCY  > 95% — keep only system prompt + last 2 messages

Usage:
    cm = PipelineContextManager(llm_client=client)
    cm.reset_for_pipeline_run()
    budget = cm.get_budget(model, messages)
    if budget.tier > CompactionTier.NONE:
        messages = cm.compact_messages(messages, budget.tier, model)
        messages = await cm.maybe_summarize(messages, model)
    stats = cm.get_stats()
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import IntEnum
from typing import Optional

logger = logging.getLogger(__name__)


class CompactionTier(IntEnum):
    NONE = 0  # < 50% — no action
    TRIM = 1  # 50-70% — strip raw OHLCV arrays
    TIME_CLEAR = 2  # 70-85% — remove stale analyst results
    SUMMARIZE = 3  # 85-95% — LLM-summarize prior stages (Haiku)
    EMERGENCY = 4  # > 95% — keep only system prompt + last 2 messages


@dataclass
class ContextBudget:
    """Snapshot of current token usage and recommended compaction tier."""

    model: str
    max_context_tokens: int
    current_input_tokens: int
    utilization: float  # 0.0 to 1.0
    tier: CompactionTier


@dataclass
class CompactionEvent:
    """Record of a single compaction action for statistics tracking."""

    timestamp: str
    tier: CompactionTier
    tokens_before: int
    tokens_after: int
    tokens_saved: int
    pipeline_run_id: Optional[str] = None


class PipelineContextManager:
    """
    Manages LLM context across a pipeline run.
    Applies tiered compaction to prevent context overflow and maintain quality.

    This class is optional — inject it into TradingPipeline via context_manager
    parameter. If not injected, the pipeline operates exactly as before.

    Thread safety: each pipeline run should call reset_for_pipeline_run() first.
    The instance is safe to reuse across sequential runs.
    """

    # Model context windows (tokens)
    CONTEXT_WINDOWS = {
        "claude-opus-4-7": 1_000_000,
        "claude-opus-4-6": 1_000_000,
        "claude-sonnet-4-6": 1_000_000,
        "claude-haiku-4-5-20251001": 200_000,
    }
    DEFAULT_CONTEXT_WINDOW = 200_000

    # Compaction tier thresholds (utilization fraction)
    # Tuned for 1M-token models: keeps costs bounded by compacting at absolute
    # token counts (~200K, ~300K, ~400K, ~500K) rather than % of full window.
    TIER_THRESHOLDS = {
        CompactionTier.TRIM: 0.20,  # ~200K tokens
        CompactionTier.TIME_CLEAR: 0.30,  # ~300K tokens
        CompactionTier.SUMMARIZE: 0.40,  # ~400K tokens
        CompactionTier.EMERGENCY: 0.50,  # ~500K tokens
    }

    # Time-based clearing: remove analyst results older than this many minutes
    STALE_ANALYSIS_MINUTES = 10

    def __init__(self, llm_client=None, config=None):
        """
        Args:
            llm_client: Optional JarvisLLMClient — required only for SUMMARIZE tier.
                        If None, SUMMARIZE tier falls back to TIME_CLEAR behavior.
            config: Optional TradingConfig instance. When provided, enables per-agent
                    token limits and prompt caching controls. When None, safe defaults
                    are used (cache_control enabled, default token limits).
        """
        self._client = llm_client
        self._compaction_events: list[CompactionEvent] = []
        self._pipeline_start_time: Optional[datetime] = None
        self._agent_timestamps: dict[str, datetime] = {}  # agent_name -> completion time
        self._cache_control_applied: int = 0  # tracks cache_control applications this session

        # Minimal config shim so methods work without a real TradingConfig
        if config is None:

            class _DefaultConfig:
                ENABLE_CONTEXT_COMPACTION = True
                AGENT_MAX_TOKENS: dict = {}

            self.config = _DefaultConfig()
        else:
            self.config = config

    # ── Token Estimation ───────────────────────────────────────────────────────

    @staticmethod
    def estimate_tokens(messages: list[dict]) -> int:
        """
        Rough token estimate: ~4 chars per token for English text.

        This is intentionally fast — it avoids calling the tokenizer.
        Accuracy is sufficient for tier detection (within ~20%).
        """
        total_chars = sum(len(str(m.get("content", ""))) for m in messages)
        return max(total_chars // 4, 1)

    # ── Budget Calculation ─────────────────────────────────────────────────────

    def get_budget(self, model: str, messages: list[dict]) -> ContextBudget:
        """
        Calculate current context budget and determine the appropriate tier.

        Args:
            model: Model name (used to look up context window size)
            messages: Current message list

        Returns:
            ContextBudget with utilization fraction and recommended tier
        """
        max_tokens = self.CONTEXT_WINDOWS.get(model, self.DEFAULT_CONTEXT_WINDOW)
        current_tokens = self.estimate_tokens(messages)
        utilization = current_tokens / max_tokens

        tier = CompactionTier.NONE
        # Check from highest to lowest — stop at first threshold exceeded
        for t in [
            CompactionTier.EMERGENCY,
            CompactionTier.SUMMARIZE,
            CompactionTier.TIME_CLEAR,
            CompactionTier.TRIM,
        ]:
            if utilization >= self.TIER_THRESHOLDS[t]:
                tier = t
                break

        return ContextBudget(
            model=model,
            max_context_tokens=max_tokens,
            current_input_tokens=current_tokens,
            utilization=utilization,
            tier=tier,
        )

    # ── Compaction Dispatch ────────────────────────────────────────────────────

    def compact_messages(
        self,
        messages: list[dict],
        tier: CompactionTier,
        model: str,
    ) -> list[dict]:
        """
        Apply synchronous compaction strategy. Returns compacted message list.

        Note: SUMMARIZE tier requires async — call maybe_summarize() separately
        after this method for the LLM-based summarization step.

        Args:
            messages: Current message list
            tier: Compaction tier to apply (from get_budget())
            model: Model name (used for logging only here)

        Returns:
            New (potentially smaller) message list
        """
        if tier == CompactionTier.NONE:
            return messages

        tokens_before = self.estimate_tokens(messages)

        if tier == CompactionTier.TRIM:
            messages = self._trim_ohlcv_data(messages)

        elif tier == CompactionTier.TIME_CLEAR:
            messages = self._trim_ohlcv_data(messages)
            messages = self._clear_stale_analysis(messages)

        elif tier == CompactionTier.SUMMARIZE:
            # Sync portion — async summarization happens in maybe_summarize()
            messages = self._trim_ohlcv_data(messages)
            messages = self._clear_stale_analysis(messages)

        elif tier == CompactionTier.EMERGENCY:
            # Keep only system message(s) + last 2 non-system messages
            system_msgs = [m for m in messages if m.get("role") == "system"]
            other_msgs = [m for m in messages if m.get("role") != "system"]
            messages = system_msgs + (other_msgs[-2:] if other_msgs else [])
            logger.warning(
                f"EMERGENCY context compaction triggered for {model}. "
                f"Kept {len(messages)} messages ({len(system_msgs)} system + "
                f"{len(messages) - len(system_msgs)} other)."
            )

        tokens_after = self.estimate_tokens(messages)
        event = CompactionEvent(
            timestamp=datetime.now().isoformat(),
            tier=tier,
            tokens_before=tokens_before,
            tokens_after=tokens_after,
            tokens_saved=tokens_before - tokens_after,
        )
        self._compaction_events.append(event)

        logger.info(
            f"Context compaction tier={tier.name}: "
            f"{tokens_before} -> {tokens_after} tokens "
            f"({event.tokens_saved} saved, {event.tokens_saved / max(tokens_before, 1):.1%} reduction)"
        )

        return messages

    # ── OHLCV Trimming ─────────────────────────────────────────────────────────

    def _trim_ohlcv_data(self, messages: list[dict]) -> list[dict]:
        """
        Remove raw OHLCV arrays from messages, keeping summaries.

        Targets JSON arrays with 4-6 numbers per element — the classic
        [timestamp, open, high, low, close, volume] pattern.  Replaces
        sequences of 5+ such arrays with a placeholder token.
        """
        import re

        # Pattern explanation:
        # \[              — opening bracket of first sub-array
        # \s*\d+\.?\d*   — first number (timestamp or OHLCV value)
        # (?:,\s*\d+...)  — 3 to 5 more numbers (OHLCV fields)
        # \]              — closing bracket
        # (?:,\s*\[...]){5,}  — followed by 5+ more identical arrays
        ohlcv_pattern = re.compile(
            r"\[\s*\d+\.?\d*"
            r"(?:,\s*\d+\.?\d*){3,5}"
            r"\s*\]"
            r"(?:\s*,\s*\[\s*\d+\.?\d*(?:,\s*\d+\.?\d*){3,5}\s*\]){5,}"
        )

        trimmed = []
        for msg in messages:
            content = str(msg.get("content", ""))
            new_content = ohlcv_pattern.sub("[... OHLCV data trimmed ...]", content)
            trimmed.append({**msg, "content": new_content})
        return trimmed

    # ── Stale Analysis Clearing ────────────────────────────────────────────────

    def _clear_stale_analysis(self, messages: list[dict]) -> list[dict]:
        """
        Remove analyst stage messages older than STALE_ANALYSIS_MINUTES.

        Messages are considered stale only when they carry a _jarvis_timestamp
        metadata key (set by mark_agent_message()). Untagged messages are kept.
        System messages are always preserved.
        """
        cutoff = datetime.now() - timedelta(minutes=self.STALE_ANALYSIS_MINUTES)
        result = []

        for msg in messages:
            # Always keep system messages
            if msg.get("role") == "system":
                result.append(msg)
                continue

            # Only drop messages that have an explicit jarvis timestamp AND are stale
            meta_time = msg.get("_jarvis_timestamp")
            if meta_time:
                try:
                    msg_time = datetime.fromisoformat(meta_time)
                    if msg_time < cutoff:
                        agent = msg.get("_jarvis_agent", "unknown")
                        logger.debug(
                            f"Dropping stale analyst message from {agent} "
                            f"(age: {(datetime.now() - msg_time).total_seconds():.0f}s)"
                        )
                        continue  # Drop this stale message
                except (ValueError, TypeError):
                    pass  # Malformed timestamp — keep the message

            result.append(msg)

        return result

    # ── Message Tagging ────────────────────────────────────────────────────────

    def mark_agent_message(self, messages: list[dict], agent_name: str) -> list[dict]:
        """
        Tag messages with timestamp metadata for stale detection.

        Call this when adding analyst results to the message list so that
        TIME_CLEAR compaction can identify and remove them later.

        Args:
            messages: Messages to tag
            agent_name: Name of the agent that produced these messages

        Returns:
            New list with _jarvis_timestamp and _jarvis_agent fields added
        """
        now = datetime.now().isoformat()
        self._agent_timestamps[agent_name] = datetime.now()
        return [{**m, "_jarvis_timestamp": now, "_jarvis_agent": agent_name} for m in messages]

    # ── Prompt Caching ─────────────────────────────────────────────────────────

    def add_cache_control_to_system_prompt(self, messages: list[dict]) -> list[dict]:
        """
        Add cache_control to the first user message content to enable prompt caching.

        Anthropic caches the first 1024+ tokens. This dramatically cuts cost for
        repeated pipeline runs using the same system prompts (up to ~90% savings on
        cached portions). cache_control is applied to the first user-role message so
        that Anthropic caches the system prompt context alongside it.

        Only applied when ENABLE_CONTEXT_COMPACTION is True.
        Returns a new list (does not mutate input).
        """
        if not self.config.ENABLE_CONTEXT_COMPACTION:
            return messages

        result = []
        cached = False
        for msg in messages:
            if not cached and msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, str):
                    new_msg = dict(msg)
                    new_msg["content"] = [
                        {
                            "type": "text",
                            "text": content,
                            "cache_control": {"type": "ephemeral"},
                        }
                    ]
                    result.append(new_msg)
                    cached = True
                    self._cache_control_applied += 1
                    logger.debug(
                        f"Prompt cache_control applied to first user message "
                        f"(total applications this session: {self._cache_control_applied})"
                    )
                    continue
            result.append(msg)
        return result

    def get_agent_max_tokens(self, agent_name: str) -> int:
        """
        Return per-agent max_tokens from config, defaulting to 1500.

        Args:
            agent_name: The agent identifier (e.g. "technical_analyst", "trader")

        Returns:
            Integer token limit for the specified agent
        """
        limits = getattr(self.config, "AGENT_MAX_TOKENS", {})
        return limits.get(agent_name, 1500)

    # ── Async Summarization ────────────────────────────────────────────────────

    async def maybe_summarize(self, messages: list[dict], model: str) -> list[dict]:
        """
        If at SUMMARIZE tier, use Haiku to compress prior stages into a summary.

        This is the async complement to compact_messages() for the SUMMARIZE tier.
        Safe to call regardless of tier — it will no-op if below threshold.

        Args:
            messages: Current (already sync-compacted) message list
            model: Model currently in use (to determine budget)

        Returns:
            Potentially further-compressed message list
        """
        if not self._client:
            return messages

        budget = self.get_budget(model, messages)
        if budget.tier < CompactionTier.SUMMARIZE:
            return messages

        non_system = [m for m in messages if m.get("role") != "system"]
        if len(non_system) < 3:
            # Not enough content to meaningfully summarize
            return messages

        summary_prompt = (
            "Summarize the following trading analysis context in under 200 words.\n"
            "Keep: key signals, regime state, any trade recommendations, risk flags.\n"
            "Drop: raw numbers, repetitive analysis, OHLCV data.\n\n"
            "Context to summarize:\n" + json.dumps(non_system[-10:], indent=2)[:4000]
        )

        try:
            result = await self._client.call(
                model="claude-haiku-4-5-20251001",
                system="You are a concise trading context summarizer.",
                messages=[{"role": "user", "content": summary_prompt}],
                max_tokens=300,
                agent_name="context_manager_summarizer",
            )

            if not result.success:
                logger.warning(f"Context summarization LLM call failed: {result.error}")
                return messages

            # Extract text from result — handle both LLMCallResult.content (str)
            # and raw dict response shapes
            if hasattr(result, "content") and isinstance(result.content, str):
                summary_content = result.content
            elif isinstance(result, dict):
                summary_content = result.get("content", [{}])[0].get("text", "")
            else:
                summary_content = str(result)

            system_msgs = [m for m in messages if m.get("role") == "system"]
            compressed = system_msgs + [
                {
                    "role": "assistant",
                    "content": f"[Context summary from prior analysis]: {summary_content}",
                }
            ]

            tokens_before = self.estimate_tokens(messages)
            tokens_after = self.estimate_tokens(compressed)
            logger.info(
                f"LLM context summarization: {tokens_before} -> {tokens_after} tokens "
                f"({tokens_before - tokens_after} saved)"
            )
            return compressed

        except Exception as e:
            logger.error(f"Context summarization failed unexpectedly: {e}")
            return messages

    # ── Statistics ─────────────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        """
        Return compaction statistics for dashboard display.

        Returns:
            Dict with total events, per-tier counts, tokens saved, recent events
        """
        tier_counts = {t.name: 0 for t in CompactionTier}
        total_saved = 0

        for event in self._compaction_events:
            tier_counts[event.tier.name] += 1
            total_saved += event.tokens_saved

        return {
            "total_compaction_events": len(self._compaction_events),
            "tier_counts": tier_counts,
            "total_tokens_saved": total_saved,
            "cache_control_applied": self._cache_control_applied,
            "recent_events": [
                {
                    "tier": e.tier.name,
                    "saved": e.tokens_saved,
                    "ts": e.timestamp,
                }
                for e in self._compaction_events[-10:]
            ],
        }

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def reset_for_pipeline_run(self) -> None:
        """
        Call at the start of each pipeline run to reset per-run state.

        Does NOT reset the compaction_events list — those accumulate across
        all runs. Clears per-run agent timestamps and sets pipeline start time.
        """
        self._agent_timestamps.clear()
        self._pipeline_start_time = datetime.now()
        logger.debug("PipelineContextManager reset for new pipeline run")
