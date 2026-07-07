---
repo: always-further/AgentUp
url: https://github.com/always-further/AgentUp
stars: 112
language: Python
license: Apache-2.0
archived: false
pushed_at: 2026-04-07T18:01:38Z
analyzed_at: 2026-04-17
recommendation: defer
surfaces_with_value: [engine-code, dev-tooling, ops-messaging]
---

# always-further/AgentUp

## Core value proposition

AgentUp is a Docker-for-agents framework that bundles agent configuration, middleware, security (OAuth2/JWT), MCP support, and task management into a portable Python/FastAPI runtime. Agents declare capabilities via config file, inherit production-grade infrastructure (async tasks, inter-agent discovery, deterministic routing), and scale from single-shot reactive agents to iterative research agents with persistent state across backends (Redis, etc.).

## Surface analysis

### 1. Engine code
`defer` — AgentUp's agent framework is architecturally similar to jarvis-trader (FastAPI, async tasks, MCP), but represents a complete architectural rewrite. Current jarvis engine has 10+ agents hard-coded as Python classes in `engine/agents/` with LLM-based decision flow. AgentUp requires declarative config-driven architecture, separate plugin versioning, A2A discovery cards, and deterministic routing — a 2-3 week refactor. Value is real but blocked on decision: keep current monolithic agent loop or adopt AgentUp's plugin-first model. Cross-reference: `engine/agents/` (10 agents), `engine/main.py:FastAPI lifespan`, `engine/agents/managed_agent_bridge.py` (already does some orchestration).

### 2. Project rules
`no-fit` — AgentUp's security model (OAuth2, fine-grained scope-based access, tool/MCP blocks) is enterprise-grade but not directly applicable to a single-user trading system. Jarvis already has X-API-Key auth + kill-switch safety layer. New trading rules could borrow from AgentUp's security-first design philosophy (e.g., audit logging for all agent tool calls, scope definitions for paper/live trading), but not as a direct port.

### 3. Project skills
`no-fit` — AgentUp is a framework, not a workflow skill. Skills like `repo-integrator`, `jarvis-trader`, `hidden-pivots` are Claude Code patterns. AgentUp agents are configured containers that run independently. Not a semantic fit.

### 4. Slash commands
`no-fit` — AgentUp doesn't contribute new slash commands. Its command-line interface (`agentup init`, `agentup run`) is a deployment/ops tool, not a Claude Code command.

### 5. Subagents
`defer` — AgentUp's inter-agent discovery (A2A Agent Card spec) is relevant if jarvis scales to orchestrate multiple specialized agents (e.g., a "STC signal agent" and a "VIX regime agent" as separate containerized services). Current monolithic agent design doesn't need this. Blocked on architecture decision.

### 6. Docs
`defer` — AgentUp's docs (deterministic routing, MCP integration patterns, Redis state persistence) would enrich `docs/architecture/` and `docs/strategy/`. Specific patterns: keyword-based routing (non-LLM for efficiency, matches jarvis's composite_signals dedup logic), async task callbacks for long-running ops (research agents taking 5+ minutes), and state persistence. Create a reference doc `docs/reference/agentup-patterns.md` if/when jarvis adopts plugin architecture. Current value is organizational, not immediately actionable.

### 7. Dev tooling
`partial-integrate` — AgentUp's CI/CD patterns (plugin versioning independent from core platform updates, testing matrix for agent + plugin combos) and PM2 equivalents (agentup manages container lifecycle) align with jarvis's ecosystem.config.js / PM2 setup. AgentUp's deterministic routing (caching, efficiency) is a code pattern worth documenting. No code to copy, but operational lesson learned: `engine/scripts/` could adopt AgentUp's "fail fast on config mismatch" pattern. Requires ~2-4 hours to document + prototype a config validator. Cross-reference: `ecosystem.config.js`, `.github/workflows/ci.yml`, `engine/scripts/`.

### 8. Dashboard
`no-fit` — AgentUp CLI focuses on server-side agent orchestration. Dashboard components (agent status, A2A discovery registry, plugin dependency graph) are not applicable to jarvis's trading dashboard. Jarvis already has agent activity feed and signal heatmap; AgentUp adds admin/ops visualization not needed for paper trading.

### 9. Ops / messaging
`partial-integrate` — AgentUp's async task callbacks (long-running operations notify listeners on completion) and state persistence patterns apply to jarvis's news-monitor, pre-market research, and multi-agent debate flows that already use async/await. Current implementation: `engine/notifications/discord_notifier.py` (async), `engine/schedulers/` (cron). AgentUp's patterns are already present; value is in formalizing the callback contract (e.g., define a `TaskCallback` Pydantic model, ensure all agent operations support callbacks). Effort: ~1-2 hours documentation + optional refactor to unified callback system. Cross-reference: `engine/notifications/`, `engine/schedulers/`, `engine/agents/managed_agent_bridge.py`.

## Integration plan

**No immediate integrations.** AgentUp's core value (config-driven agent runtime with plugin ecosystem) requires an architectural decision: keep jarvis's monolithic agent loop or adopt AgentUp's plugin-first containerized model. Without that decision, integrations are speculative.

**Deferred pending decision:**
- If jarvis scales to multi-region or multi-strategy containerized agents, evaluate full AgentUp adoption (4-6 week project).
- If jarvis stays monolithic, document operational patterns from AgentUp only:
  1. Create `docs/reference/agentup-patterns.md` summarizing: deterministic routing (keyword caching), async task callbacks (long-running op notifications), state persistence (Redis for agent consensus).
  2. Prototype config validator for `engine/config.py` (2-4 hours) — catch agent/route mismatches at startup, matching AgentUp's "fail fast" philosophy.
  3. Formalize callback contract in `engine/notifications/` (1-2 hours) — ensure all async agents (debate, news-monitor, etc.) support callbacks for UX.

**Partial integrations (no code changes):**
- Document plugin versioning pattern in `docs/dev/plugin-lifecycle.md` — reference AgentUp's independent plugin versioning approach.
- Add CI/CD test matrix for agent + plugin combinations if jarvis adopts plugin architecture (future).

## License & attribution

Apache 2.0 — can reference and adapt ideas freely. If code (e.g., task callback infrastructure) is borrowed, attribute in file header: `# Adapted from always-further/AgentUp (Apache 2.0)`.

## Effort estimate

- **Defer (full adoption)**: XL (4-6 weeks, architectural refactor)
- **Partial (patterns + docs only)**: S-M (2-6 hours, documentation + optional config validator)

## Red flags

1. **Architectural lock-in**: Full adoption requires containerization + plugin registry, eliminating jarvis's current flexibility for rapid agent tweaking (change a score threshold, restart engine in 3 seconds). AgentUp trades rapid iteration for stability and multi-tenant isolation.
2. **Plugin ecosystem immaturity**: AgentUp's plugin registry (agentup.dev/packages) has ~10 plugins; jarvis's custom agents (debate, researcher, trader) would need to be refactored as plugins. Testing burden increases.
3. **State management complexity**: AgentUp's Redis state persistence is powerful but adds operational overhead (Redis deployment, state schema evolution, debugging). Jarvis's in-memory agent state (current context, confidence scores) is simpler and sufficient for paper trading.
4. **Deployment overhead**: AgentUp agents run as separate containers (agentup run). Jarvis is a single uvicorn process on port 8010. Multi-agent scaling would require Docker/orchestration infrastructure not currently in place.
5. **MCP integration is young**: AgentUp touts "full MCP support (STDIO, SSE, HTTP)" but real-world testing against jarvis's MCP use cases (Figma, GitHub, Alpaca) would be needed.

**Verdict**: AgentUp is a best-in-class agent framework for production multi-tenant systems, but jarvis is a single-user trading bot with rapid iteration cycles. Adoption would reduce iteration speed for marginal gains in isolation and plugin reusability. Recommended: monitor AgentUp's growth (plugin registry, adoption), document patterns for future scaling, but maintain current monolithic design for 2026 H1.
