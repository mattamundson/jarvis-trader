---
repo: rohitg00/agentmemory
url: https://github.com/rohitg00/agentmemory
stars: 1713
language: TypeScript
license: Apache-2.0
archived: false
pushed_at: 2026-04-16T23:38:24Z
analyzed_at: 2026-04-17
recommendation: partial-integrate
surfaces_with_value: [rules, skills, dev-tooling, ops/messaging]
---

# rohitg00/agentmemory

## Core value proposition

agentmemory is a production-grade persistent memory engine for AI coding agents with 95.2% retrieval accuracy (vs 68.5% for mem0). It auto-captures session context via 12 hooks (zero manual effort), uses hybrid BM25 + vector + graph search with RRF fusion, and runs as a self-hosted MCP server with no external DB dependencies — reducing token footprint from 650K to 170K annually.

## Surface analysis

### 1. Engine code
**no-fit** — agentmemory is not a trading strategy, signal, agent, backtest harness, or risk component. It solves a cross-session context problem, not a market mechanics problem.

### 2. Project rules
**partial-integrate** — agentmemory's lifecycle management (4-tier consolidation, confidence scoring, decay, auto-forget) and multi-agent coordination patterns (MCP leases, signals for concurrent access) map to surfaces 5 & 9. The token-efficiency philosophy aligns with `.claude/rules/token-efficiency.md`, but agentmemory's "zero external DB" design + SQLite-only constraint is a doctrine shift from jarvis-trader's existing `.claude/rules/workflow.md` (which assumes local Python .venv and PM2 for agents). New rule file warranted only if user commits to agentmemory as the primary cross-session memory layer.

### 3. Project skills
**integrate-now** — Create `.claude/skills/agentmemory-integration/SKILL.md` to wire agentmemory's 12 hooks + MCP into Claude Code workflow. jarvis-trader already uses claude-mem (thedotmack/claude-mem) for cross-session memory; agentmemory adds auto-capture + vector search. Skill should document: (a) startup (npx @agentmemory/agentmemory on port 3111/3113), (b) Claude Code plugin install (rohitg00/agentmemory), (c) viewer at localhost:3113, (d) when to use vs. claude-mem (agentmemory for auto-capture of ephemeral session details; claude-mem for explicit YAML handoffs).

### 4. Slash commands
**defer** — Single-command context reloading (e.g., `/mem-session-recall`) is a genuine fit and blocks on surface 3 (skill must exist first to document the hook contract).

### 5. Subagents
**no-fit** — agentmemory is not a specialized reviewer or analyzer. It supports agents via MCP but does not replace the existing memory-curator or safety-reviewer agents.

### 6. Docs
**partial-integrate** — Add to `docs/architecture/MEMORY_STRATEGY.md` (new file) clarifying the two-tier memory stack: (a) claude-mem for explicit session handoffs (YAML, curated), (b) agentmemory for implicit auto-capture. This doc should cite agentmemory's benchmark vs competitors (95.2% recall vs 68.5% for mem0, 83.2% for Letta). Cross-reference `docs/session-logs/HANDOFF_TEMPLATE.md` to show integration points.

### 7. Dev tooling
**partial-integrate** — agentmemory includes `npx @agentmemory/agentmemory upgrade` for dependency sync and 12 auto-hooks (session_start, message_sent, message_received, etc.). ecosystem.config.js could run agentmemory as a parallel PM2 entry (name: "agentmemory", script: "npx", args: "@agentmemory/agentmemory"). Current PM2 ecosystem only includes jarvis-engine and jarvis-dashboard; adding agentmemory requires testing for port conflicts (3111/3113 are free) and hook ordering with existing startup scripts.

### 8. Dashboard
**no-fit** — agentmemory's real-time viewer (port 3113, web UI) is a standalone monitoring tool, not a component or lib intended for integration into jarvis-trader's Tailwind + React dashboard. The viewer serves its own purpose and should remain separate.

### 9. Ops / messaging
**defer** — agentmemory's 12 hooks include `message_sent`, `message_received`, and `session_end` triggers. Wiring these into `engine/notifications/openclaw_notifier.py` or `engine/schedulers/` for WhatsApp alerts on memory state changes (e.g., "memory consolidated, 3 obsolete facts auto-forgotten") is a genuine fit but requires: (a) MCP hook-to-HTTP bridge (agentmemory exposes tools, not raw events), (b) decision on whether to noise-gate memory mutations (every consolidation → alert fatigue), (c) OpenClaw plugin availability (agentmemory repo includes `integrations/openclaw/` but it's still in beta per 2026-04-16 tag).

## Integration plan

### Surface 3 (Skills) — Immediate
Create `C:/Users/mattm/ThinkorSwim/jarvis-trader/.claude/skills/agentmemory-integration/SKILL.md`:

1. Document startup: `npx @agentmemory/agentmemory` on port 3111 (API) and 3113 (viewer).
2. Document plugin install: `/plugin marketplace add rohitg00/agentmemory && /plugin install agentmemory`.
3. Document the two-tier memory contract: use claude-mem for explicit YAML handoffs at session end (`/vault-wrap-up`, `docs/session-logs/handoff-*.md`); use agentmemory for ephemeral details (code snippets read, decisions reconsidered, dead-end debugging sessions).
4. Include link to agentmemory's real-time viewer docs and note the 95.2% retrieval accuracy benchmark vs. alternatives.
5. Mention MCP tools exposed: memory_smart_search, memory_save, memory_sessions, memory_governance_delete, etc. (44 total).

### Surface 2 (Rules) — Defer
Only if user decides agentmemory is the primary memory layer. Current `.claude/rules/workflow.md` assumes Python .venv + PM2; agentmemory assumes Node.js + SQLite + localhost. Decision required from user.

### Surface 6 (Docs) — Defer
Create `docs/architecture/MEMORY_STRATEGY.md` only after skill (surface 3) is confirmed working. Doc should synthesize the two-tier approach and cross-reference both claude-mem and agentmemory benchmarks.

### Surface 7 (Dev tooling) — Defer
Add PM2 entry for agentmemory to `ecosystem.config.js` only after port conflict testing and hook ordering validation. Low priority until user runs agentmemory in parallel with jarvis-engine.

### Surface 9 (Ops / messaging) — Defer
Wire agentmemory memory-mutation events to OpenClaw notifications only after: (a) MCP hook-to-HTTP bridge is prototyped, (b) noise-gating strategy is decided, (c) OpenClaw plugin exits beta.

## License & attribution

Apache-2.0. When shipping agentmemory integration code, include header: `Adapted from rohitg00/agentmemory (Apache-2.0, https://github.com/rohitg00/agentmemory)`.

## Effort estimate

- **Surface 3 (skill)**: S (2hr) — copy template, document hooks, add bench links.
- **Surface 6 (docs)**: S (1–2hr) — synthesize memory strategy, cross-link.
- **Surface 7 (tooling)**: M (4–6hr) — PM2 wiring, port conflict test, hook ordering.
- **Surface 9 (ops)**: L (1–3 days) — MCP bridge prototype, noise-gating design, OpenClaw beta validation.

**Total (all surfaces)**: M–L (8–24hr if pursuing surfaces 3+6+7+9 together).

## Red flags

1. **Duplication with claude-mem**: jarvis-trader already uses thedotmack/claude-mem for cross-session memory (YAML handoff pattern). agentmemory is opt-in complementary, not a replacement. Adding both requires clear delineation: when to use which.

2. **Port conflicts**: agentmemory assumes 3111 (API) and 3113 (viewer). Current jarvis-trader uses 8010 (engine), 3010 (dashboard), 4002 (IB Gateway paper). Verify no DNS/port-forwarding rules block these.

3. **PM2 startup ordering**: If adding agentmemory to `ecosystem.config.js`, test whether agentmemory boots before or after jarvis-engine. claude-mem loads from disk (fast); agentmemory spins up a Node.js server (slower). Race condition possible if engine tries to call agentmemory MCP tools on startup.

4. **Node.js + Python split**: jarvis-trader's engine is Python (FastAPI); dashboard is Node.js (pnpm). agentmemory is TypeScript/Node.js. Three runtime stacks now (Python, Node, Rust iii-engine). Maintenance burden grows.

5. **Vendor lock-in risk**: agentmemory is 1 month old (2026-02-25 created). Popular (1.7K stars) but early. The benchmark claims (95.2% retrieval) are vendor-published, not third-party audited. API stability not yet proven across seasonal releases.

## Verdict

**Partial-integrate** across surfaces 3 (skills), 2 (rules, deferred), 6 (docs, deferred), 7 (tooling, deferred), 9 (ops, deferred). No value on surfaces 1 (engine), 4 (commands), 5 (subagents), 8 (dashboard). Recommend user start with surface 3 (skill file only) to unblock cross-session auto-capture while preserving existing claude-mem YAML handoff workflow. If agentmemory proves stable and valuable over 2–4 weeks of parallel use, escalate to surfaces 6+7+9.
