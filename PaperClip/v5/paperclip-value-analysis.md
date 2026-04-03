# Paperclip — value analysis

*Grounded against the live `paperclipai/paperclip` repo as of April 2026.*

## One-line summary

Paperclip is the right tool once you have multiple agents, multiple goals, and need structure, visibility, cost control, and governance — not just another agent launcher.

## What problem it solves

| Without Paperclip | With Paperclip |
|-------------------|----------------|
| 20 Claude Code tabs open, no tracking of who does what | Tasks are ticket-based, sessions persist, every piece of work is visible |
| Manually gathering context to remind each bot what to do | Context flows from task → parent → project → company goal; agents always know why |
| Runaway agent loops waste hundreds of dollars of tokens | Monthly budgets per agent; hard-stop at 100%; warns at 80% |
| Recurring jobs need manual kicking off | Heartbeats run agents on a schedule; management supervises |
| No way to intervene in autonomous work | Board approvals, overrides, pause/terminate any agent at any time |
| Multiple ventures need separate deployments | One deployment, many companies, complete data isolation |

## Ranked features

### 1. Adapter-agnostic multi-agent orchestration
Supports Claude Code, Codex, Cursor, OpenClaw, Bash, HTTP/webhook — any runtime that can receive a heartbeat. This is a coordination layer, not a locked-in runtime.

### 2. Goal-linked task hierarchy with atomic checkout
Every task traces back to the company's top-level goal. Only one agent can own a task at a time; the `in_progress` transition is atomic. Prevents duplicate work without coordination logic.

### 3. Governance layer
Board approvals for hires and CEO strategy. All mutating actions in an immutable activity log. Designed for supervised autonomy, not unchecked automation.

### 4. Hard budget enforcement
`budget_monthly_cents` per agent. Auto-pause at 100%. `spent_monthly_cents` tracked in real time. Runaway loops are stopped at the platform level.

### 5. Multi-company isolation
One deployment, many companies. All data is company-scoped. First-order object in the data model — not an afterthought.

### 6. Zero-friction local start
`pnpm install && pnpm dev` — embedded PGlite, no Docker, no external DB required. Full stack up in one command.

### 7. Three control surfaces
- Web UI — company dashboard, org chart, issues, approvals, costs
- CLI — onboarding, worktrees, health checks, import/export
- REST API — programmatic control, agent API keys, agent run tokens

### 8. Plugin system for optional capabilities
Core stays thin. Optional features (rich chat, knowledge base, special UIs) go in plugins. The architecture explicitly avoids core bloat.

## When it's the right tool

- You manage more than one agent and need to track what everyone is doing
- You want agents running autonomously 24/7 with audit visibility and intervention capability
- You need cost controls that actually stop runaway loops
- You run multiple ventures or clients from one place
- You want governance (approvals, overrides, audit) over autonomous work

## When it may be more than you need

- Single agent, short session, one-off task — simpler runners are lighter
- You only need LLM calls, not org/task/budget management
- You want an instant prototype with no config

## What Paperclip explicitly is not (from PRODUCT.md)

- Not a general chat app or chatbot
- Not a code review tool
- Not a full Jira/GitHub replacement
- Not an enterprise RBAC platform (V1 is single-board-operator)
- Not an execution engine — it orchestrates; agents run externally

## Engineering quality signals

- TypeScript end-to-end (server + UI + CLI + packages)
- Drizzle ORM with typed schema + migrations
- Embedded PGlite for zero-config local dev
- Atomic checkout semantics in DB layer
- E2E and smoke tests
- Release automation with canary and stable tracks
- Active contribution: 1,557+ files, dated plan docs through March 2026
- MIT licensed, open source
