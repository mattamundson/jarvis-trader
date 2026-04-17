---
repo: addyosmani/agent-skills
url: https://github.com/addyosmani/agent-skills
stars: 16530
language: Shell
license: MIT
archived: false
pushed_at: 2026-04-16T03:05:33Z
analyzed_at: 2026-04-17
recommendation: partial-integrate
surfaces_with_value: [rules, skills, docs]
---

# addyosmani/agent-skills

## Core value proposition

Production-grade engineering skills for AI coding agents: 20 structured workflows covering spec-driven development, test-driven development, code review, security hardening, CI/CD, and launch procedures. Encodes senior engineer discipline from Google's SWE culture. Entry points: 7 slash commands (`/spec`, `/plan`, `/build`, `/test`, `/review`, `/code-simplify`, `/ship`) that auto-activate relevant skills.

## Surface analysis

### 1. Engine code
`no-fit` — Repo contains no trading signals, backtesting logic, risk models, or agent implementations for jarvis-trader's domain. The skills are meta-workflows for building software, not trading-specific agents or indicators.

### 2. Project rules
`integrate-now` — `agent-skills/` contains disciplined engineering principles (spec-before-code, test-first, five-axis code review, Hyrum's Law, Chesterton's Fence, Shift Left in CI/CD, deprecation-as-liability, anti-rationalization tables) that align with jarvis-trader's `meta-discipline.md` and safety invariants. Core applicable skills: `spec-driven-development`, `test-driven-development` (Red-Green-Refactor, test pyramid 80/15/5, Beyonce Rule), `code-review-and-quality` (change sizing ~100 lines, severity labels), `security-and-hardening` (OWASP Top 10, secrets management, auth patterns), `git-workflow-and-versioning` (trunk-based, atomic commits, change-as-save-point), `code-simplification` (Chesterton's Fence), `deprecation-and-migration` (code-as-liability mindset, compulsory vs advisory patterns). These directly complement `meta-discipline.md:4` (verifiable goals before loops) and `safety.md` (safety-critical invariants). Minimal redundancy risk — jarvis-trader's existing rules focus on assumptions/simplicity/surgical changes and safety; agent-skills brings comprehensive discipline covering spec, testing, review speed norms, and deprecation lifecycle.

### 3. Project skills
`partial-integrate` — Repo contains 20 reusable skills. Immediate candidates: `spec-driven-development/SKILL.md`, `test-driven-development/SKILL.md`, `code-review-and-quality/SKILL.md`, `security-and-hardening/SKILL.md`. These are packaged as `.claude/skills/*/SKILL.md` with frontmatter (name, description, when-to-use) and step-by-step workflows. However, jarvis-trader already has 7 custom skills (agent-debate-explain, backtest-report, jarvis-trader, last30days, pm2-doctor, repo-integrator) tailored to trading domain. Integration requires: (a) audit existing jarvis skills for overlap with agent-skills offerings; (b) adapt general engineering skills to trading context (e.g., `test-driven-development` → focus on backtest invariants, signal correctness, risk checks rather than generic unit tests); (c) decide on naming/namespacing to avoid collision (e.g., `/test` command conflicts with existing `/test` if any). **Dependency**: Requires explicit user decision on skill consolidation strategy. Red flag: `agent-skills` ships 7 slash commands; jarvis-trader already uses `/jarvis-*` custom commands — namespace collision risk if both imported as-is.

### 4. Slash commands
`partial-integrate` — Repo exports 7 slash commands at `.claude/commands/`: `/spec`, `/plan`, `/build`, `/test`, `/review`, `/code-simplify`, `/ship`. Jarvis-trader has custom commands in `.claude/commands/` (jarvis-commit-with-receipts, jarvis-ib-gateway-health, jarvis-kill-switch-check, jarvis-morning-brief, and others). No name collision, but `/test` may conflict if jarvis-trader reserves it for trading-specific testing (backtest, paper trade validation). Integration path: Import agent-skills commands as-is (MIT-licensed) or adapt them to trading context. **Dependency**: User must decide if `/spec` and `/plan` are useful alongside jarvis-trader's custom workflows, or if they add cognitive load without ROI.

### 5. Subagents
`dedup-skills` — Repo defines 3 specialist personas (code-reviewer, test-engineer, security-auditor) as `agents/*.md` agents. Jarvis-trader's debate.py, pipeline.py, trader.py already include multi-agent decision-making (bull_researcher, bear_researcher, advisor_client). Personas serve similar function (targeted reviews). Shipped via skills, not separate agents. No new architectural value.

### 6. Docs
`partial-integrate` — Repo includes supporting references: `references/testing-patterns.md` (test structure, naming, mocking, React/API/E2E examples, anti-patterns), `references/security-checklist.md` (pre-commit checks, auth, input validation, CORS, OWASP), `references/performance-checklist.md` (Core Web Vitals, frontend/backend checklists), `references/accessibility-checklist.md` (keyboard nav, screen readers, ARIA). Jarvis-trader touches testing (engine/tests/ has 129 files, ~1484 passing tests) and security (engine/risk/, kill-switch, trade invariants), but lacks formalized checklists. Testing patterns + security checklist are directly applicable. Performance checklist is web-focused (Core Web Vitals); jarvis-trader has engine/analytics/ (backtesting performance) but not frontend latency concerns. Accessibility checklist applies only to dashboard (Tailwind-based React components). **Integration scope**: Copy testing-patterns.md and security-checklist.md as-is; adapt perf/a11y references to dashboard-only context.

### 7. Dev tooling
`dedup-skills` — Repo includes `.claude/hooks/` (session lifecycle), `.github/workflows/` (CI/CD reference), `ecosystem.config.js` patterns (PM2), pre-commit hooks. Jarvis-trader already has ecosystem.config.js (PM2 config), GitHub Actions, and pre-commit orchestration. Generic workflows don't add value over existing setup. `ci-cd-and-automation/SKILL.md` (Shift Left, feature flags, quality gates) is conceptually aligned with jarvis-trader's backtest-before-trade and kill-switch patterns but not a tool integration.

### 8. Dashboard
`no-fit` — Agent-skills `skills/frontend-ui-engineering/SKILL.md` covers component architecture, design systems, state management, responsive design, WCAG 2.1 AA. Jarvis-trader's dashboard is already built (Tailwind React at dashboard/components/, dashboard/lib/). Skill applies to *building* or *modifying* UI, not analyzing existing code. Value is workflow guidance, not components. If Matt wants to refactor dashboard UI patterns, the skill is a good reference, but no code integration.

### 9. Ops / messaging
`no-fit` — Agent-skills does not cover trading-specific notification patterns, order execution, market data pipelines, or monitoring. Jarvis-trader has `engine/notifications/` (OpenClaw, WhatsApp, Discord), `engine/schedulers/` (crons), and alert infrastructure. Skill contains general CI/CD and launch checklists (feature flag lifecycle, rollback procedures, monitoring setup) but nothing trading-specific.

## Integration plan

### Rules — integrate-now
**Files to adapt**: 
- Create `.claude/rules/engineering-discipline.md` synthesizing agent-skills' core principles (spec-before-code, test-first, five-axis review, Hyrum's Law, Chesterton's Fence, Shift Left, deprecation-as-liability) adapted to trading context (e.g., spec = signal spec, test = backtest + paper trade invariants, deprecation = signal deprecation with migration window).
- Update `.claude/rules/testing.md` to inline testing patterns from agent-skills `references/testing-patterns.md`, focusing on engine/tests/ anatomy and backtest verification gates.
- Update `.claude/rules/safety.md` to reference security-checklist.md sections on auth, secrets management, and trade-execution boundaries.

**Effort**: M (4–6 hours) — read agent-skills docs end-to-end, synthesize into 2–3 new rule files, no code changes.

### Skills — partial-integrate (decision gate)
**Recommended approach**: Do NOT auto-import all 20 skills. Instead, cherry-pick 3–4 that matt explicitly requests (e.g., spec-driven-development, test-driven-development). Rationale: jarvis-trader's domain is narrow (futures trading), and generic engineering skills add cognitive overhead without ROI on every task. Code review and security hardening are solid candidates; UI/frontend engineering and CI/CD automation are lower priority.

**If proceeding**: Copy `agent-skills/skills/<name>/SKILL.md` to `.claude/skills/<name>/SKILL.md` per-skill, preserving MIT attribution. Namespace as `spec-driven` (not `/spec`) to avoid command collision. Test by invoking from chat: `/spec-driven [request]`.

**Effort**: S (2 hours per skill) — copy, test, no adaptation needed.

### Slash commands — defer
**Rationale**: Agent-skills `/spec`, `/plan`, `/build`, `/test`, `/review`, `/code-simplify`, `/ship` are generic software dev commands. Jarvis-trader's custom commands (`jarvis-morning-brief`, `jarvis-kill-switch-check`) are domain-specific and more valuable to Matt. Adding 7 generic commands creates command-line clutter without clear ROI.

**Defer condition**: Revisit if Matt explicitly requests a general-purpose spec workflow (e.g., "I want a /spec command for designing new signals").

### Docs — partial-integrate
**Files to port**:
- `agent-skills/references/testing-patterns.md` → `.claude/references/testing-patterns-addy.md` (or merge into existing testing.md)
- `agent-skills/references/security-checklist.md` → `.claude/references/security-checklist-addy.md` (or append to safety.md)

**Effort**: S (1–2 hours) — copy markdown as-is, add attribution header.

## License & attribution

**License**: MIT. Agent-skills is MIT-licensed; all adaptations inherit MIT.

**Attribution**: File headers in any integrated files:

```markdown
_Adapted from [addyosmani/agent-skills](https://github.com/addyosmani/agent-skills) (MIT).
Core concepts: [concept list]. See original repo for full skill definitions._
```

Commit message (if shipping): `chore: integrate agent-skills principles into rules + references (MIT, addyosmani)`.

## Effort estimate

- **Rules synthesis** (engineering-discipline.md, testing.md update, safety.md update): **M** (4–6 hours)
- **Skills (if proceeding)**: **S per skill** (2 hours × n skills)
- **Docs (checklists)**: **S** (1–2 hours)
- **Total baseline (rules + docs)**: **M** (6–8 hours)
- **Total + skills + commands** (full integration): **L** (1–2 days)

## Red flags

1. **Skill/command namespace collision**: Agent-skills exports 7 generic commands and 20 skills. Importing all creates cognitive overhead. Matt must decide on curation strategy.
2. **Frontend-heavy skill bias**: 3 of 20 skills are UI/frontend-focused (frontend-ui-engineering, browser-testing-with-devtools, accessibility). Jarvis-trader's dashboard is less critical than engine; FE skills may not be cost-effective unless dashboard refactor is planned.
3. **Generic vs. domain-specific**: Agent-skills is purpose-built for general software dev teams. Jarvis-trader is narrow (futures trading). Rules synthesis is low-risk; skill/command import requires filtering to avoid noise.
4. **Deprecation skill mismatch**: Agent-skills emphasizes code deprecation and feature flag lifecycle (appropriate for multi-service teams). Jarvis-trader has 2 live instruments (MCL, MNQ); feature-flag infrastructure isn't needed. Deprecation principles (migrations, compulsory vs advisory) are sound but may be premature.

## Recommendation summary

Agent-skills delivers high value on **rules** (engineering discipline, testing patterns, security checklist) and moderate value on **skills** (if curated to 3–4 most relevant). Minimal value on commands, subagents, or dev tooling. **Recommendation: partial-integrate**. Start with rules synthesis (engineering-discipline.md) and documentation (testing-patterns, security-checklist references), skip commands/all-20-skills unless explicitly requested. Integration effort: M (6–8 hrs for rules + docs baseline).
