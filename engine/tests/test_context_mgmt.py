"""Tests for context_mgmt module."""
import pytest

from utils.context_mgmt import (
    COMPACT_THRESHOLD,
    compact_messages,
    drop_tool_responses,
    needs_compaction,
)


class TestNeedsCompaction:
    """Test needs_compaction threshold detection."""

    def test_needs_compaction_under_threshold(self):
        """700/1000 is under 0.80 threshold, should return False."""
        assert needs_compaction(700, 1000) is False

    def test_needs_compaction_at_threshold(self):
        """800/1000 is at 0.80 threshold, should return True."""
        assert needs_compaction(800, 1000) is True

    def test_needs_compaction_zero_limit(self):
        """Division by zero should return False, not crash."""
        assert needs_compaction(100, 0) is False


class TestDropToolResponses:
    """Test drop_tool_responses progressive elision."""

    def test_drop_tool_responses_drops_from_middle(self):
        """Given 10 tool messages and drop_ratio=0.5, middle 5 should be elided."""
        messages = [
            {"role": "user", "content": "start"},
            *[{"role": "tool", "content": f"tool {i}"} for i in range(10)],
            {"role": "user", "content": "end"},
        ]

        result = drop_tool_responses(messages, drop_ratio=0.5)

        # Should have same length
        assert len(result) == len(messages)

        # Count elided tool messages
        elided_count = sum(
            1 for msg in result if msg.get("content") == "[tool output elided for context compaction]"
        )

        # Should have dropped approximately 5 (50% of 10)
        assert elided_count == 5

        # First and last user messages should be unchanged
        assert result[0] == {"role": "user", "content": "start"}
        assert result[-1] == {"role": "user", "content": "end"}


class TestCompactMessages:
    """Test compact_messages algorithm."""

    @pytest.fixture
    def messages(self):
        """Create a message list with system prompt and 20 user messages."""
        return [
            {"role": "system", "content": "You are a trader."},
            *[{"role": "user", "content": f"msg {i}"} for i in range(20)],
        ]

    def test_compact_messages_below_threshold_no_change(self, messages):
        """Messages below threshold should return unchanged with flag=False."""
        result_messages, was_compacted = compact_messages(
            messages, current_tokens=700, context_limit=1000
        )
        assert result_messages == messages
        assert was_compacted is False

    def test_compact_messages_preserves_system_prompt(self, messages):
        """System message at index 0 should always be kept verbatim."""
        result_messages, was_compacted = compact_messages(
            messages, current_tokens=900, context_limit=1000
        )
        assert was_compacted is True
        assert result_messages[0] == {"role": "system", "content": "You are a trader."}

    def test_compact_messages_preserves_last_two_exchanges(self, messages):
        """Last 4 messages (2 user + 2 assistant) should be kept verbatim."""
        # Extend with assistant messages to form exchanges
        messages.extend([
            {"role": "assistant", "content": "response 1"},
            {"role": "user", "content": "msg 20"},
            {"role": "assistant", "content": "response 2"},
        ])

        result_messages, was_compacted = compact_messages(
            messages, current_tokens=900, context_limit=1000
        )
        assert was_compacted is True

        # Last 4 messages (of user/assistant role) should be in the result
        # Find last 4 user/assistant messages from original
        last_four = [m for m in messages[-4:] if m.get("role") in ("user", "assistant")]

        # Check that these messages appear in result (not necessarily at exact indices)
        result_content = [m.get("content") for m in result_messages]
        for msg in last_four:
            assert msg.get("content") in result_content

    def test_compact_messages_uses_summarizer_when_provided(self, messages):
        """If summarizer provided, its output should appear in result."""
        def mock_summarizer(msgs):
            return "MOCK_SUMMARY"

        result_messages, was_compacted = compact_messages(
            messages,
            current_tokens=900,
            context_limit=1000,
            summarizer=mock_summarizer,
        )
        assert was_compacted is True

        # Find the summary message
        summary_found = False
        for msg in result_messages:
            if "MOCK_SUMMARY" in msg.get("content", ""):
                summary_found = True
                break

        assert summary_found, "Summarizer output not found in result"

    def test_compact_messages_short_conversation_keeps_literal_messages(self):
        """Short conversations should not be replaced by a generated summary."""
        messages = [
            {"role": "system", "content": "You are a trader."},
            {"role": "user", "content": "A" * 5000},
            {"role": "assistant", "content": "B" * 5000},
            {"role": "user", "content": "C" * 5000},
        ]

        result_messages, was_compacted = compact_messages(
            messages,
            current_tokens=200000,
            context_limit=1000,
        )

        assert was_compacted is True
        assert result_messages[0] == messages[0]
        assert result_messages[1:] == messages[1:]
