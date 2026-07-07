---
repo: Corbell-AI/Corbell
url: https://github.com/Corbell-AI/Corbell
stars: 192
language: Python
license: Apache-2.0
archived: false
pushed_at: 2026-04-11T17:39:49Z
analyzed_at: 2026-04-17
recommendation: partial-integrate
surfaces_with_value: [engine code, dev tooling, ops/messaging]
---

# Corbell-AI/Corbell

## Core value proposition
Corbell builds a knowledge graph from multi-repo codebases using tree-sitter AST parsing and semantic embeddings, then uses LLM-powered spec generation to produce architecture-aware design documents with method signatures, call paths, and cross-service impacts. It exposes these capabilities via MCP server and CLI, supporting local-only execution without cloud infrastructure.

## Surface analysis

### 1. Engine code
**partial-integrate** — Corbell's embedding-based code analysis and call-graph extraction align with engine's existing SDK pipeline MCP server infrastructure (engine/agents/sdk_pipeline.py). Tree-sitter AST parsing for method signatures + typed call graphs maps to engine's backtest/agents analysis patterns. Integration path: (a) analyze whether Corbell's `graph build --methods` can augment engine's existing service boundary detection in portfolio/debate agents; (b) embed Corbell's sentence-transformers model for semantic code search alongside existing token_optimizer; (c) no direct signal/strategy code — architecture analysis tool, not a trading signal.

### 2. Project rules
**no-fit** — Corbell documents code architecture discipline, testing structure, and CI/CD patterns. Jarvis-trader already has mature `.claude/rules/` (coding-style.md, engine-python.md, safety.md, testing.md). Corbell itself enforces no new behavioral rules; it generates docs from existing code. No rule integration needed.

### 3. Project skills
**no-fit** — Corbell's design-doc generation, spec review, and decompose workflows are domain-specific to multi-team backend projects. Jarvis-trader has no use for spec generation (trading system, single-author codebase). Corbell skill patterns (interactive graph browser, linear/jira export) are not applicable to trading ops.

### 4. Slash commands
**no-fit** — Corbell exposes `corbell spec new`, `corbell spec review`, `corbell ui serve`, and `corbell mcp serve` as CLI commands. None translate to jarvis-trader quick-action workflow (`/pretrade-check`, `/engine-health`, etc.). Corbell's domain is backend multi-repo coordination; jarvis-trader operates on single trading engine + strategy agents.

### 5. Subagents
**no-fit** — Corbell agents are spec-review and auto-service-discovery agents (agentic roadmap section). Jarvis-trader's agent layer (bull_researcher, bear_researcher, debate, trader) solves different problem (signal generation, not architecture review). No integration point.

### 6. Docs
**defer** — Corbell's architecture graph browser (UI + force-directed graph, service dependency visualization) could inform future jarvis-trader dashboarding for multi-component system instrumentation (e.g., visualizing agent flow topology, service interconnect). Current dashboard is trading-centric (positions, risk metrics). Architectural visualization is a feature-branch item, not immediate need. Blocker: would require wrapping Corbell's D3.js graph layer and SQLite schema to index jarvis-trader's internal agent calls.

### 7. Dev tooling
**partial-integrate** — Corbell's CI integration via `corbell spec lint specs/my-feature.md --ci` offers a lint hook pattern. Jarvis-trader's existing `.claude/hooks/` (pre-tool-use, post-tool-use, session-start, stop, user-prompt-submit) do not include architecture linting. Integration path: (a) add pre-commit hook to run `corbell spec lint` on any docs/specs changes (low-effort, non-blocking); (b) ecosystem.config.js could spawn Corbell UI server as optional PM2 service for architecture visualization (currently disabled). Low priority — lint hook is defensive, not critical.

### 8. Dashboard
**no-fit** — Corbell UI is a force-directed graph + constraint-visualization browser for multi-service backends. Jarvis-trader dashboard (dashboard/components/, dashboard/lib/) is trading-focused (positions, P&L, regime, alerts). No component reuse; architectural graphs are not a trading-operations need.

### 9. Ops / messaging
**no-fit** — Corbell's operations are CLI workflows (spec generation, graph export) and optional UI server. No alert patterns, cron jobs, or messaging integrations. Engine notifications (engine/notifications/openclaw_notifier.py) and schedulers (engine/schedulers/) solve trading-alert and broker-sync problems, not architecture-design workflows.

## Integration plan

### Recommended: Dev tooling lint hook (Surface 7, low effort)
1. Add `corbell[anthropic]` to `engine/requirements.txt` (Corbell supports Claude Sonnet out of box; uses existing ANTHROPIC_API_KEY).
2. Create `.claude/hooks/pre-spec-lint` hook that runs `corbell spec lint docs/specs/**/*.md --ci` on any spec file changes.
3. Document in `.claude/rules/commits.md` that all architecture specs must pass Corbell lint before commit.
4. Effort: 30–60 min (stub hook, test against one existing spec).

### Optional: Future architecture visualization (Surface 6, deferred)
Create a separate task for post-paper-trading phase:
- Wrap Corbell's graph-builder to index internal agent call paths (debate → trader → portfolio).
- Add optional dashboard tab for "Agent Topology" showing signal flow and decision trees.
- Requires: Corbell SQLite schema integration + D3.js reuse. Effort: 1–2 days. Blocker: needs explicit decision on whether architecture viz is a monitoring priority vs. existing OpenClaw/WhatsApp alerts.

## License & attribution
Apache-2.0. If lint hook or any code is integrated: add attribution in file header as `# Inspired by Corbell-AI/Corbell (Apache-2.0)` and link in commit message.

## Effort estimate
S (for lint hook only) = 30–60 min. M (if adding optional UI integration) = 4–6 hours. L+ (if full graph indexing + dashboard refactor) = 1–3 days.

## Red flags
- **Not a trading tool** — Corbell solves backend team coordination, not market signals. All value is meta-operational (documentation/architecture), not alpha-generating.
- **Requires Anthropic API key** — Already satisfied (engine/.env has ANTHROPIC_API_KEY). No new secret needed.
- **Python 3.11+ requirement** — Engine uses `.venv/Scripts/python`, check version: if < 3.11, skip or isolate in separate venv. (Likely not a blocker; most managed repos are 3.12+.)
- **Optional UI server** — If enabled, adds port 7433 to ecosystem.config.js. Risk: port collision with other PM2 services or local dev servers. Mitigation: make UI optional flag, disabled by default.
- **No trading-adjacent value** — Corbell's roadmap (agentic spec review, dynamic task generation) is for backend-team workflows. Unlikely to generate future value for trading engine; this is a one-time lint-hygiene add.
