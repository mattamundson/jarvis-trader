"""Context compaction utilities ported from Goose's context_mgmt module.

Threshold-triggered message summarization and progressive tool-response
eviction for LLM conversation histories. Standalone — no engine imports.
"""
from typing import Callable, Optional

COMPACT_THRESHOLD = 0.80  # trigger compaction when usage ratio hits this

def _approx_tokens_from_messages(messages: list[dict]) -> int:
    """Very rough token estimate based on text length."""
    total_chars = 0
    for message in messages:
        content = message.get("content", "")
        if isinstance(content, str):
            total_chars += len(content)
        elif isinstance(content, dict):
            total_chars += len(str(content))
        else:
            total_chars += len(str(content))
    return max(1, total_chars // 4)


def needs_compaction(current_tokens: int, context_limit: int) -> bool:
    """Return True when current_tokens / context_limit >= COMPACT_THRESHOLD."""
    if context_limit <= 0:
        return False
    return (current_tokens / context_limit) >= COMPACT_THRESHOLD


def drop_tool_responses(messages: list[dict], drop_ratio: float) -> list[dict]:
    """Progressively empty tool-response payloads from the middle of the message list.

    drop_ratio in [0.0, 1.0]. 0.0 = drop nothing, 1.0 = drop all tool responses.
    Drops from the middle outward so recent and earliest context is preserved.
    A "tool response" is any message with role == "tool" OR content that looks
    like a tool_result dict.
    """
    # Find all tool response indices
    tool_indices = []
    for i, msg in enumerate(messages):
        is_tool_msg = msg.get("role") == "tool"
        is_tool_result = isinstance(msg.get("content"), dict) and "tool_use_id" in msg.get("content", {})
        if is_tool_msg or is_tool_result:
            tool_indices.append(i)

    if not tool_indices:
        return messages

    # Compute how many to drop
    num_to_drop = round(len(tool_indices) * drop_ratio)
    if num_to_drop == 0:
        return messages

    # Pick from middle outward
    indices_to_drop = set()
    center = len(tool_indices) // 2
    for offset in range(num_to_drop):
        # Alternate left and right from center
        if offset % 2 == 0:
            idx = center - offset // 2
        else:
            idx = center + (offset + 1) // 2

        if 0 <= idx < len(tool_indices):
            indices_to_drop.add(tool_indices[idx])

    # Apply elision
    result = []
    for i, msg in enumerate(messages):
        if i in indices_to_drop:
            elided = msg.copy()
            elided["content"] = "[tool output elided for context compaction]"
            result.append(elided)
        else:
            result.append(msg)

    return result


def compact_messages(
    messages: list[dict],
    current_tokens: int,
    context_limit: int,
    summarizer: Optional[Callable[[list[dict]], str]] = None,
) -> tuple[list[dict], bool]:
    """Compact a message list if usage exceeds COMPACT_THRESHOLD.

    Algorithm (port of Goose crates/goose/src/context_mgmt/mod.rs):
      1. If not needs_compaction(), return (messages, False).
      2. Always keep: messages[0] if role == "system", plus the last 2 user/
         assistant exchanges (up to 4 messages from the tail).
      3. Summarize the middle section by calling summarizer(middle_messages).
         If summarizer is None, fall back to a deterministic text summary:
         "Prior context summary: <N messages elided, roles: ...>".
      4. Return (new_messages, True).

    The summarized block is inserted as:
      {"role": "user", "content": "Prior context summary: <summary>"}

    If after summarization the messages still exceed the threshold, progressively
    invoke drop_tool_responses with ratio 0.1, 0.2, 0.5, 1.0 until under threshold
    (caller can check needs_compaction() on the result to decide if further action
    is required).
    """
    # Step 1: Check if compaction needed
    if not needs_compaction(current_tokens, context_limit):
        return (messages, False)

    # Step 2: Identify sections to keep
    # Keep system message at index 0 if present
    system_end = 0
    if messages and messages[0].get("role") == "system":
        system_end = 1

    # Keep last 2 user/assistant exchanges (up to 4 messages from tail)
    user_assistant_indices = [
        i for i, msg in enumerate(messages[system_end:], start=system_end)
        if msg.get("role") in ("user", "assistant")
    ]
    if len(user_assistant_indices) <= 4:
        return (messages, True)

    tail_start = len(messages)
    count = 0
    for i in range(len(messages) - 1, system_end - 1, -1):
        if messages[i].get("role") in ("user", "assistant"):
            count += 1
            if count >= 4:
                tail_start = i
                break

    # Step 3: Summarize middle section
    middle_messages = messages[system_end:tail_start]

    if summarizer:
        summary = summarizer(middle_messages)
    else:
        # Deterministic fallback
        roles = [msg.get("role", "unknown") for msg in middle_messages]
        role_summary = ", ".join(dict.fromkeys(roles))  # unique roles in order
        summary = f"Prior context summary: {len(middle_messages)} messages elided, roles: {role_summary}"

    # Build new message list
    new_messages = []
    if system_end > 0:
        new_messages.append(messages[0])
    new_messages.append({"role": "user", "content": f"Prior context summary: {summary}"})
    new_messages.extend(messages[tail_start:])

    # Step 4: If still over threshold, progressively drop tool responses
    for drop_ratio in [0.1, 0.2, 0.5, 1.0]:
        new_messages = drop_tool_responses(new_messages, drop_ratio)
        if not needs_compaction(_approx_tokens_from_messages(new_messages), context_limit):
            break

    return (new_messages, True)





