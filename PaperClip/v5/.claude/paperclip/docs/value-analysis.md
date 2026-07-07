# What makes Paperclip valuable

## One-line summary

Paperclip is the right tool once you have multiple agents, multiple goals, and need structure, visibility, cost control, and governance — not just another agent launcher.

## Core differentiators

### 1. Adapter-agnostic orchestration
Paperclip does not care what runtime your agents use. Built-in adapters include Claude Code, Codex, Cursor, OpenClaw, Bash, and HTTP/webhook. You bring your own agents; Paperclip is the coordination layer. This means it is useful across mixed-agent environments — no runtime lock-in.

### 2. Goal-linked task hierarchy
Every task traces back to the company's top-level goal through a chain of parent tasks. Agents always know *what* to do and *why* it matters. This is a structural guarantee, not a convention — tasks cannot exist outside the hierarchy.

### 3. Atomic single-assignee checkout
Only one agent can own a task at a time, and the transition to `in_progress` is atomic. This prevents duplicate work across parallel agent runs without any additional coordination logic on your side.

### 4. Hard budget enforcement
Paperclip tracks token/cost spend per agent and per company. It warns at 80% and hard-stops agents at 100% of their monthly budget. Runaway agent loops are one of the most common operational risks in multi-agent systems; Paperclip handles this at the platform level.

### 5. Governance layer with approvals and audit trail
Board approvals for hires and CEO strategy proposals are built in. All mutating actions are logged to an immutable activity trail. Most agent systems focus on execution convenience; Paperclip is explicitly designed around supervised autonomy.

### 6. Multi-company architecture
One deployment can run multiple companies with complete data isolation. This makes Paperclip materially more useful for agency, studio, or portfolio operations than single-workspace tools.

### 7. Fast local start
One command (`pnpm install && pnpm dev`) brings up the full stack with embedded PGlite — no Docker or external DB required. This dramatically reduces the infra friction for evaluation.

### 8. Three control surfaces
- **Web UI** — board/operator workflows, org chart, issue management
- **CLI** — instance setup, worktrees, onboarding, health checks
- **REST API** — programmatic control with company-scoped endpoints

## Ranked features

1. Adapter-agnostic multi-agent orchestration
2. Goal-linked task hierarchy with atomic checkout
3. Governance: approvals, overrides, immutable audit log
4. Hard budget enforcement + spend visibility
5. Multi-company isolation
6. Zero-friction local deployment
7. Three operator surfaces (UI + CLI + REST)
8. Plugin system for optional capabilities

## When Paperclip is the right tool

- You have more than one agent and need to track who is doing what
- You want agents running autonomously 24/7 but still want to audit and intervene
- You need cost controls that actually stop runaway loops
- You manage multiple ventures or clients from one control plane
- You want board-level governance (approvals, overrides) over autonomous work

## When it may be more than you need

- Single agent, single task, short session — simpler runners are lighter
- You only want LLM calls, not full org/task/budget management
- You need an instant prototype in 10 minutes with no config

## The repo's own boundaries (from PRODUCT.md)

Paperclip explicitly is **not**:
- A general chat app or chatbot
- A code review tool (that's GitHub/PR tooling)
- A full Jira/GitHub replacement
- An enterprise RBAC platform (V1 is single-board-operator)
