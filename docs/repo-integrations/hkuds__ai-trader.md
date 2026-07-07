---
repo: HKUDS/AI-Trader
url: https://github.com/HKUDS/AI-Trader
stars: 13439
language: Python
license: null (missing)
archived: false
pushed_at: 2026-04-10T17:21:03Z
analyzed_at: 2026-04-17
recommendation: noise
surfaces_with_value: []
---

# HKUDS/AI-Trader

## Core value proposition
AI-Trader is a live social trading platform where AI agents publish trading signals, copy trades from top performers, and collaborate via debates — essentially a Twitter/Discord for algorithmic traders. It includes paper trading with Polymarket and a dashboard for following performers.

## Surface analysis

### 1. Engine code
**no-fit** — AI-Trader's engine is a Django/FastAPI web service for signal publishing, copy-trade execution, and leaderboards. jarvis-trader is a standalone CME futures trader (MCL/MNQ/MES). Zero code carryover; architecturally orthogonal.

### 2. Project rules
**no-fit** — No specific rules or safety invariants proposed by the repo.

### 3. Project skills
**no-fit** — AI-Trader publishes agent onboarding skills (e.g., `skills/ai4trade/SKILL.md`) for registration on the platform. jarvis-trader has no use for platform integration; internal agent orchestration is already wired via `engine/agents/pipeline.py` and `engine/agents/debate.py`.

### 4. Slash commands
**no-fit** — Platform commands like `/copytrade` and `/tradesync` are scoped to the AI-Trader social ecosystem, not trading logic.

### 5. Subagents
**no-fit** — AI-Trader does not define novel agent patterns. Its "agents" are external traders registering on the platform, not reusable specialist roles.

### 6. Docs
**no-fit** — Documentation covers platform usage (signal publishing, account setup, leaderboards). No trading technique, operational pattern, or architecture concept relevant to jarvis-trader.

### 7. Dev tooling
**no-fit** — No CI patterns, PM2 configurations, pre-commit hooks, or shell utilities applicable to jarvis-trader.

### 8. Dashboard
**dedup-engine** — AI-Trader has a React dashboard for leaderboards and copy-trade management. jarvis-trader already has a dashboard (`dashboard/`) for position monitoring, regime analysis, and agent feedback. No new patterns.

### 9. Ops / messaging
**no-fit** — AI-Trader's notification system is for platform events (signal published, copy trade executed, follower gained). jarvis-trader's ops are trade-execution alerts (BUY/SELL signals, approvals, settlement) routed via OpenClaw/WhatsApp. Different problem domain.

## Integration plan
No integrations. The repo is orthogonal to jarvis-trader's architecture and trading scope. It is a platform, not a technique.

## License & attribution
License field is null; no LICENSE file mentioned in README. Treat as proprietary per skill rules. Code integration is not applicable.

## Effort estimate
N/A — no integration path identified.

## Red flags
- **Scope mismatch**: AI-Trader is a B2B/B2C SaaS platform for multi-agent signal aggregation and copy trading. jarvis-trader is a proprietary single-agent futures trader for Matt. Integrating would mean:
  - Publishing signals to a public platform (conflicts with stealth strategy requirement)
  - Copying external agent trades (conflicts with proprietary signal pipeline)
  - Running dashboard leaderboards (out of scope for paper-trading phase)
- **No technique**: The repo offers no new signal, risk check, consensus mechanism, or agent pattern beyond what jarvis-trader already has. Its "multi-agent debate" is users publishing independent signals, not a unified reasoning framework. jarvis-trader's debate stack (`bull_researcher`, `bear_researcher`, `technical_analyst`, `advisor_client`, `ic_ensemble`) is structurally and semantically unrelated.
- **Archived categorization inaccuracy in prior digest**: The 2026-04-17 digest classified this as "noise — not a technique" because it's a copy-trading social platform. That classification is **correct and stands**. The present analysis **agrees with the dedup decision**; no change to prior recommendation.

## Upstream research reference
See `docs/digest/ml-ai-synthesis.md:53` for the original dedup rationale.
