---
repo: Alishahryar1/free-claude-code
url: https://github.com/Alishahryar1/free-claude-code
stars: unverified (WebFetch summary reported 40.3k; not independently confirmed via API — treat as approximate)
language: Python (96.7%)
license: MIT
archived: false
pushed_at: unknown (not independently confirmed)
analyzed_at: 2026-07-15
recommendation: noise
surfaces_with_value: []
---

# Alishahryar1/free-claude-code

## Core value proposition

A local proxy server (`fcc-claude` / `fcc-codex` / `fcc-pi`) that intercepts Claude Code's
`ANTHROPIC_BASE_URL` / `ANTHROPIC_AUTH_TOKEN` and reroutes requests to 25+ third-party
cloud/local model providers, so a user can run the Claude Code CLI without an Anthropic
subscription. Ships an admin UI for switching providers/model tiers, plus Discord/Telegram/
IDE integrations and voice-note transcription for those chat surfaces.

## Surface analysis

### 1. Engine code
no-fit — not a trading strategy, signal, backtest, or risk component. Nothing under
`engine/` has any conceptual overlap.

### 2. Project rules
no-fit — no coding-discipline or safety-invariant content applicable to this project.

### 3. Project skills
dedup-skills — the only overlapping *concept* (LLM model-tier routing/cost control) is
already covered, for a different purpose, by `.claude/skills/jarvis-cost-routing` (haiku/
sonnet/opus tier selection for the pipeline's own advisor calls). That skill governs
*internal* engine LLM calls; this repo's routing swaps the backend behind the Claude Code
*CLI itself* — not something jarvis-trader's skill surface should absorb.

### 4. Slash commands
no-fit.

### 5. Subagents
no-fit.

### 6. Docs
no-fit — no runbook or architecture content relevant to a futures/options trading engine.

### 7. Dev tooling
no-fit — this repo's installers/CI harness a Claude-Code-proxy product, not a Python/
FastAPI trading engine's CI needs.

### 8. Dashboard
no-fit.

### 9. Ops / messaging
no-fit — jarvis-trader already has purpose-built Discord/Telegram notifiers
(`engine/notifications/discord_notifier.py`, `discord_webhook.py`, `telegram.py`) for
trade-signal and approval alerts. This repo's Discord/Telegram integration is a *chat
front-end for driving the coding-agent CLI itself*, an unrelated use case — not
duplicative in function, just not applicable here.

## Integration plan

No integrations proposed on any surface.

## License & attribution

MIT — not relevant since nothing is being adopted.

## Effort estimate

N/A (no-fit).

## Red flags

- **Purpose is to circumvent Anthropic's own authentication/billing.** The proxy's stated
  design is to intercept `ANTHROPIC_AUTH_TOKEN` / `ANTHROPIC_BASE_URL` so Claude Code talks
  to non-Anthropic backends instead of Anthropic's API — i.e., a subscription-bypass tool.
  Independent of trading-system fit, this is a Terms-of-Service / trust concern for any
  Claude Code session (this one included) to run or endorse, and it's flagged here rather
  than integrated regardless of any incidental technical merit.
- Star/fork counts above came from an automated WebFetch summarization pass, not a direct
  GitHub API call (this repo is outside this session's authorized GitHub scope, so
  `mcp__github__*` tools were not used against it) — treat the 40.3k figure as unverified.
- No trading-domain content whatsoever; this is a pure dev-tooling/proxy project for a
  different product surface (the Claude Code CLI itself, not jarvis-trader).

**Recommendation: classify as `noise` and do not integrate or install.**
