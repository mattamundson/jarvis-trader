---
repo: Polymarket/agents
url: https://github.com/Polymarket/agents
stars: 3094
language: Python
license: MIT
archived: false
analyzed_at: 2026-04-19
recommendation: partial-integrate
surfaces_with_value: [engine-code, docs]
---

# Polymarket/agents

## Core value proposition

Official Polymarket agent framework. Clean modular architecture
(connectors / polymarket core / application / utils) with a reusable
`Executor` orchestration pattern and `Prompter` prompt-template system.
Pydantic models for type safety (`SimpleMarket`, `SimpleEvent`).
3094 stars, but last push Nov 2024 — starting to go stale.

## License

**MIT** — free to port with attribution.

## 9-surface grid

| # | Surface | Classification | Finding |
|---|---|---|---|
| 1 | Engine code | partial-integrate | `Executor` orchestration pattern + `Prompter` abstraction → could simplify prompt mgmt in `engine/agents/rules/agent_prompts.py`. Multi-connector architecture maps to jarvis-trader's multi-datasource needs |
| 2 | Project rules | no-fit | — |
| 3 | Skills | no-fit | — |
| 4 | Slash commands | no-fit | — |
| 5 | Subagents | no-fit | — |
| 6 | Docs | partial-integrate | Document the Executor/Prompter decomposition at `docs/strategy/prompt-abstractions.md` if jarvis-trader ever feels prompt-mgmt pain |
| 7 | Dev tooling | no-fit | Standard Python; nothing unique |
| 8 | Dashboard | no-fit | — |
| 9 | Ops | no-fit | — |

## Transferable patterns

1. **`Prompter` abstraction** — prompt templates as first-class objects with
   variable substitution. Currently jarvis-trader embeds prompts in
   agent classes. Port only if prompt management starts fighting us.
2. **`Executor` orchestration** — LLM interaction wrapper with timeout,
   retry, metrics. Partially duplicated by `engine/llm/client.py:JarvisLLMClient`
   + `engine/utils/token_proxy.py`. Don't re-port; check for gaps instead.
3. **Multi-datasource composition** — Chroma (vector RAG) + Gamma API +
   news/web-search connectors. jarvis-trader has similar shape via
   market_data + tradingview_feed + cot_fetcher + sector_rotation.
   Mostly already covered.

## Red flags

- **Stale** — last pushed Nov 2024, 48+ open issues. Audit any copied
  patterns against current best practices.
- **Hardcoded env vars** (wallets, API keys) — don't carry over.
- **Crude token estimation** (char/4) — jarvis-trader already has better
  via `engine/utils/token_proxy.py`.
- **Limited error handling in trading execution paths** — Polymarket CLOB
  is permissive; futures execution via IB Gateway is not. **Do NOT port
  their execution resilience patterns** wholesale.

## Effort

Patterns-only, no code copy: **S (2-4h)** if prompt-mgmt pain emerges.
Currently **defer** — existing jarvis-trader primitives cover most of it.
