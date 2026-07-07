---
repo: gnekt/my-brain-is-full-crew
url: https://github.com/gnekt/My-Brain-Is-Full-Crew
stars: 2834
language: Shell
license: NOASSERTION
archived: false
pushed_at: 2026-04-12T19:26:57Z
analyzed_at: 2026-04-17
recommendation: partial-integrate
surfaces_with_value: [skills, docs]
---

# gnekt/my-brain-is-full-crew

## Core value proposition

Multi-platform AI agent crew (Claude Code, Gemini CLI, OpenCode, Codex CLI) that manages an Obsidian vault through conversational interface. 8+ specialized agents (Architect, Scribe, Sorter, Seeker, Connector, Librarian, Transcriber, Postman) plus 14 skills handle note capture, inbox triage, knowledge-graph discovery, email/calendar bridging, and custom agent creation. Targets overwhelmed knowledge workers, not traders.

## Surface analysis

### 1. Engine code
**no-fit** — The repo is a multi-platform agent framework (Shell + Node.js) that operates on Obsidian vaults. No trading strategy, market data, backtest harness, or risk logic. Architecture is incompatible with jarvis-trader's FastAPI+Python futures engine.

### 2. Project rules
**no-fit** — Crew's rules are knowledge-management discipline (PARA + Zettelkasten structure, note deduplication, contact sync). jarvis-trader's rules focus on trading safety (stop-loss invariants, regime filters, position sizing). No architectural overlap.

### 3. Project skills
**partial-integrate** — Crew's 14 skills are conversational workflows (onboarding, inbox triage, vault audit, transcription, email-triage, deadline-radar). jarvis-trader already has 8 domain-specific skills (repo-integrator, backtest-report, cost-routing, trader, etc.). However, the **dispatcher pattern + skill delegation logic** in Crew could inform a future `/skill-router` or `/multi-function-router` for jarvis-trader's own skill ecosystem. Currently jarvis-trader skills are invoked directly. Crew's "check skills first, fall through to agents" pattern is philosophically sound and could be formalized. **Effort to extract: M (2–8 hours)** — would require abstracting dispatcher logic from Crew into a reusable SKILL.md template.

### 4. Slash commands
**no-fit** — Crew's commands (`/onboarding`, `/create-agent`, `/email-triage`, `/deadline-radar`, `/contact-sync`) are all Obsidian/knowledge-management scoped. No trading or market-data relevance.

### 5. Subagents
**no-fit** — Crew's 8 agents (Architect, Scribe, Sorter, Seeker, Connector, Librarian, Transcriber, Postman) are knowledge-workers' personal assistants. jarvis-trader's debate agents (BullResearcher, BearResearcher, Advisor) are market-analysis specialists. Different problem domains; no code reuse.

### 6. Docs
**partial-integrate** — Crew's documentation on **multi-platform harness architecture** (Claude Code vs. Gemini CLI vs. OpenCode vs. Codex CLI with shared dispatcher) could inform jarvis-trader's own documentation on skill/agent platform portability. Specifically:
- `docs/codex-cli.md` — Windows WSL setup for Codex CLI (jarvis-trader also uses WSL OpenClaw gateway; this could cross-reference)
- Architecture diagrams showing dispatcher → skills → agents delegation
- Terms of Use + privacy disclaimers (Crew is explicit about personal data responsibility; jarvis-trader's FAQ could adopt similar transparency)

**Integration path**: Create `docs/runbooks/multi-platform-harness-notes.md` with references to Crew's approach + link to their codebase. **Effort: S (< 2 hours)** — synthesis, not code.

### 7. Dev tooling
**no-fit** — Crew's dev tools are shell scripts (`launchme.sh` installer, platform detection, config generation). jarvis-trader uses PM2 + pnpm + Python venv orchestration. Different stack, different CI/CD needs. Installer patterns are orthogonal.

### 8. Dashboard
**no-fit** — Crew has no dashboard (Obsidian vault IS the UI). jarvis-trader's Next.js dashboard displays portfolio, regime, P&L charts, live prices. No UI components to share.

### 9. Ops / messaging
**no-fit** — Crew's ops layer (scheduled tasks, email bridging, contact sync) are Obsidian-specific. jarvis-trader's ops (OpenClaw WhatsApp alerts, CME Globex market-hours gate, PM2 health checks) are trading-infrastructure scoped. No operational pattern overlap.

## Integration plan

### Recommendation: Defer to future session
gnekt/my-brain-is-full-crew has **no direct trading value** but offers **architectural insight** on multi-platform dispatcher patterns and transparency documentation. Integration is not urgent; jarvis-trader's immediate roadmap (portfolio-balancing, volatility-regime, ice-cream sandwich confluence) has higher ROI.

**If pursuing**:
1. **Short-term (S effort)**: Create `docs/runbooks/multi-platform-harness-notes.md` citing Crew's dispatcher-first design + WSL setup notes. No code changes.
2. **Medium-term (M effort)**: Extract Crew's skill-router pattern into a standalone `engine/dispatchers/` module if jarvis-trader's skill ecosystem grows beyond 8. Currently not needed — skills are invoked explicitly by user.
3. **Attribution**: If any code is adapted, add comment header linking to Crew's repo and license (currently NOASSERTION; treat as proprietary until owner clarifies).

## License & attribution

**License**: NOASSERTION (no LICENSE file in repo). Crew's README claims MIT badge but `license` field in GitHub API returns NOASSERTION. **Action**: Treat as proprietary. If integration proceeds, request explicit license clarification from `gnekt` (open issue on their repo). Do not copy code without written permission.

**Attribution location** (if code is adapted): Comment header in `engine/dispatchers/*` or `docs/runbooks/multi-platform-harness-notes.md`.

## Effort estimate

**No immediate integration.** Proposed efforts:
- **Documentation synthesis (S)**: < 2 hours — read Crew's dispatcher logic, summarize in jarvis-trader's context
- **Dispatcher pattern extraction (M)**: 2–8 hours — if skill ecosystem grows and router abstraction becomes valuable
- **Legal review**: 30 min — clarify license with gnekt before any code copy

## Red flags

1. **License ambiguity**: NOASSERTION on GitHub API despite MIT badge in README. Must clarify before copying code.
2. **Out of scope**: Crew is a personal-productivity framework. jarvis-trader is a futures-trading engine. Problem domains are orthogonal. Risk of scope creep if integration is forced.
3. **Maintenance risk**: Crew was last pushed 2026-04-12 (5 days old); active but early-stage project (created 2026-03-21). Stability unproven. Monitor for breaking changes in multi-platform harness before adopting patterns.
4. **Windows compatibility**: Crew's Codex CLI on Windows is experimental and recommended to run in WSL. jarvis-trader's Python engine runs natively on Windows + WSL; architecture differs.

## User decision

**No action required this session.** Document is filed for future reference. If you're expanding jarvis-trader's skill ecosystem or need multi-platform dispatcher abstraction, re-surface this repo. For now, focus is on trading roadmap.

Want to proceed with any of the `partial-integrate` items (dispatcher docs or harness notes), or close this?
