---
name: jarvis-cost-routing
description: Cost discipline for LLM calls inside jarvis-trader — model tier selection (haiku / sonnet / opus), budget gates in the advisor strategy, retry policy, and prompt caching. Documents the existing implementation in engine/agents/advisor_client.py, engine/llm/client.py, and engine/utils/token_optimizer.py as a runbook so future changes don't regress the cost model. Use when adding any LLM call path, tuning model thresholds, or reviewing an agent for cost regressions.
---

# jarvis-cost-routing

_Adapted from [affaan-m/everything-claude-code](https://github.com/affaan-m/everything-claude-code) `cost-aware-llm-pipeline` skill (MIT). The ECC original provides generic cost patterns; this version maps them onto the existing jarvis-trader implementation instead of proposing a new pipeline._

## When to use

- Adding any new LLM call site in `engine/`
- Tuning model-selection thresholds
- Reviewing an agent for cost regressions
- Debugging unexpectedly high Anthropic invoice
- Before inserting `opus` anywhere except safety-gated paths

## The four pillars

All four are **already implemented** in jarvis-trader. This skill is a runbook, not a design proposal.

| Pillar | jarvis-trader home |
|---|---|
| Model routing by task complexity | `engine/agents/advisor_client.py` (Opus advisor), `engine/agents/debate.py` (Sonnet researchers) |
| Immutable cost tracking | `engine/utils/token_optimizer.py` (Anthropic-specific) |
| Narrow retry logic | `engine/llm/client.py` (TokenProxy + retry policy, Track G) |
| Prompt caching | `engine/llm/client.py:36, 165, 364-370` (TokenProxy cache layer) |

## Model-tier policy (enforce on every new LLM call)

```
haiku  → Explore agents, orientation, search, codebase questions, file lookups
sonnet → Implementation agents, writing/fixing code, debate researchers, analysis synthesis
opus   → Planning agents, safety review, Tier 3 architecture decisions, inconclusive-debate arbiter
```

This matches `C:/Users/mattm/.claude/rules/workflow.md` — do NOT contradict it.

### Decision rule

Add to every new call site:

```python
# ❌ Wrong — hardcode sonnet for everything
client.messages.create(model="claude-sonnet-4-6", ...)

# ✅ Right — route by task
from engine.llm.client import get_client, route_model

model = route_model(
    task_kind="analysis",          # orientation | analysis | implementation | safety
    text_length=len(prompt),
    item_count=len(items),
)
client.messages.create(model=model, ...)
```

If `engine/llm/client.py` doesn't yet expose `route_model()`, you can inline the decision, but file a note to extract it.

## Budget gates — live in advisor_client

The Claude Advisor Strategy at `engine/agents/advisor_client.py:41-60` (Track F) only consults Opus when:

1. Debate is `inconclusive` (|score - threshold| <= 0.05), **or**
2. Proposed trade confidence < 0.5

Any new code that calls Opus outside of that gate requires a cost justification comment AND a Tier 3 review, because the Anthropic Apr 9 beta data shows ~11.9% cost reduction vs. un-gated Opus use with +2.7pp accuracy — those numbers only hold if the gate stays in place.

## Retry policy — defer to TokenProxy

`engine/utils/token_proxy.py` already implements:

- Prompt compression (collapse 3+ newlines, trailing whitespace, interior spaces)
- Response caching (300s TTL, 200-entry max, oldest-entry eviction)
- Context trimming
- Market data truncation
- Thread-safe singleton

**Do not add retry logic at the call site.** Route through TokenProxy and the retry policy lives there. If a new transient error class needs to be retryable, extend the tuple in `token_proxy.py` — do not duplicate the retry loop.

Pre-approved retryable errors: `APIConnectionError`, `RateLimitError`, `InternalServerError`. Never retry: `AuthenticationError`, `BadRequestError`, `PermissionDeniedError`.

## Prompt caching — required for >1024-token system prompts

If a system prompt is over ~1024 tokens, it MUST use `cache_control: {type: "ephemeral"}` on the large block. Pattern:

```python
messages = [{
    "role": "user",
    "content": [
        {"type": "text", "text": system_prompt,
         "cache_control": {"type": "ephemeral"}},  # <-- cache the big block
        {"type": "text", "text": user_input},       # <-- variable part
    ],
}]
```

Reference: `engine/llm/client.py:364-370` for the project-standard cache wrapping.

## Pricing reference (2026-04)

| Model | Input ($/1M) | Output ($/1M) | Relative | Use for |
|---|---|---|---|---|
| Haiku 4.5 | $0.80 | $4.00 | 1x | Explore, orientation, bulk classification |
| Sonnet 4.6 | $3.00 | $15.00 | ~4x | Research agents, implementation, analysis |
| Opus 4.7 (1M context) | $15.00 | $75.00 | ~19x | Safety review, advisor strategy, planning |

Parallel-agent cost implication (standing order = 10 agents):

- 10 × haiku Explore run ≈ $0.03–$0.30 per sweep
- 10 × sonnet implementation run ≈ $0.50–$5 per sweep
- 10 × opus run ≈ $8–$50 per sweep — **never do this without explicit authorization**

## Common cost-regression patterns (catch in review)

1. **Defaulted opus in a loop** — e.g., `for symbol in universe: opus.call()`. Almost always wrong. Haiku outer, opus inner on exception cases only.
2. **Missing cache control on long system prompt** — silent 3-5x cost multiplier on every call.
3. **Retry amplification** — retry loop wrapping another retry loop (e.g., both at call site and in TokenProxy).
4. **Oversized context window** — sending 200k tokens when 20k would suffice. Check `token_optimizer.py` trimming helpers.
5. **No force_model plumbing** — users can't override for testing. Expose `force_model: str | None = None` on every public LLM function.

## Integration with other skills

- **Before committing a new agent** — read this skill, verify the model tier matches task kind.
- **During `ce:review` / `code-reviewer`** — look specifically for the five regression patterns above.
- **After a sprint** — pull the Anthropic cost report and spot-check the model-mix percentage. Haiku should be >50% of calls by volume.

## Anti-patterns

- Hardcoding `"claude-sonnet-4-6"` throughout the codebase. Use module-level constants (`MODEL_SONNET`, `MODEL_HAIKU`, `MODEL_OPUS`) per `.claude/rules/coding-style.md`.
- Bypassing `TokenProxy` "because the prompt is short." TokenProxy is a safety layer, not just a cost optimizer.
- Treating retries as free. Every retry is a full billable call.
- Using Opus where Sonnet suffices "to be safe." That's not safer; it's just more expensive and slower.

## Attribution

Original patterns: [affaan-m/everything-claude-code](https://github.com/affaan-m/everything-claude-code) `cost-aware-llm-pipeline` skill (MIT). This file maps the patterns onto jarvis-trader's existing implementation (Tracks F/G, 2026-04-10) rather than proposing a new pipeline. Full analysis: `docs/repo-integrations/affaan-m__everything-claude-code.md`.
