---
repo: fainir/most-capable-agent-system-prompt
url: https://github.com/fainir/most-capable-agent-system-prompt
stars: unknown
language: markdown
license: unknown
archived: false
pushed_at: unknown
analyzed_at: 2026-04-17
recommendation: partial-integrate
surfaces_with_value: [rules, docs]
---

# fainir/most-capable-agent-system-prompt

## Core value proposition

A comprehensive system prompt for building maximally capable, self-improving agentic systems that can handle software engineering, research, operations, and multi-month projects. The prompt emphasizes reliability engineering, state machines, verification loops, idempotency, and structured harnesses over ad-hoc agent design. It targets Claude Code, Cursor, or similar tools and includes concrete guidance on task decomposition, checkpoint management, and failure recovery.

## Surface analysis

### 1. Engine code

`no-fit` — The repo is entirely prompt/narrative design guidance. It contains no signals, indicators, agents, backtesting harnesses, risk checks, or trading-specific code. Jarvis-trader's agent system (bull/bear/trader/risk_manager/advisor_client) is already architecture-complete per 2026-04-10 audit. This repo does not modify engine execution paths.

### 2. Project rules

`partial-integrate` — The prompt contains system-level engineering disciplines highly relevant to `.claude/rules/meta-discipline.md` evolution. Specific borrowable patterns: (a) **reliability math** (section "RELIABILITY MATH AND HARNESS ENGINEERING") — 18 hard conclusions about skills vs. codification, state machines, validation loops, and idempotency. Jarvis-trader has safety hardcoding but lacks explicit checkpoint/compensation policy for multi-step workflows like discovery_loop.py or SDK pipeline orchestration. (b) **verification-first discipline** — the prompt's "FIRST MILESTONE DEFINITION" and "INITIAL ACTIONS YOU MUST TAKE NOW" mirror jarvis-trader's "verifiable goals before loops" rule, but generalized to harness-building. Recommend excerpt into `.claude/rules/reliability-engineering.md` (new file, ~300 lines, MIT license attribution required). This does not override existing `safety.md` non-negotiables — it augments the infrastructure discipline layer.

### 3. Project skills

`no-fit` — No new skills are implied. The repo is methodology, not a portable SOP or workflow. The guidance could inform how `/jarvis-trader` skill documentation structures multi-agent choreography, but no file-level integration applies.

### 4. Slash commands

`no-fit` — No `/` command patterns are suggested. The prompt covers architectural governance (which agent to call when, how to gate decisions), not single-shot commands like `/pretrade-check` or `/jarvis-morning-brief`.

### 5. Subagents

`defer` — The prompt's section "Keep the orchestrator lean" and discussion of "isolated subagents for narrow work packages" is conceptually aligned with jarvis-trader's debate/advisor design, but requires safety review before integration. Any subagent changes touch the risk control plane (debate_score affects position sizing, advisor_client augments trader.py decisions). The prompt proposes "cheaper or faster models for narrow repeated tasks" — jarvis-trader uses haiku for some utilities but tier by task risk. Before shipping subagent-routing policy from this repo, require Tier 3 review to ensure it does not bypass risk gates in `engine/risk/` or `engine/execution/`.

### 6. Docs

`partial-integrate` — Strong conceptual fit for `docs/architecture/` and future runbooks. Specific sections worth excerpt: (a) **"RELIABILITY MATH"** (lines 209–320) — 18 hard conclusions on workflows, schemas, validation, checkpointing, and compensation. (b) **"UNIVERSAL COMPUTER WORK SURFACE"** (lines 182–206) — list of task surfaces (terminal, git, browser, database, CRM, schedulers) that could inform future feature roadmap docs. (c) **"SUCCESS METRICS"** (lines 124–139) — jarvis-trader tracks trade outcomes and backtest metrics but not "percentage of work completed proactively versus reactively" or "memory reuse rate" — adding these KPIs to `docs/analytics/metrics.md` would strengthen learning-system instrumentation. Recommend: create `docs/architecture/reliability-engineering-patterns.md` (new, ~200 lines) and link from `docs/strategy/ARCHITECTURE.md`. Attribution in file header.

### 7. Dev tooling

`no-fit` — The repo does not discuss CI, PM2, GitHub Actions, pre-commit hooks, or ecosystem.config.js patterns. Jarvis-trader's dev tooling is complete with `.github/workflows/`, `ecosystem.config.js`, and `engine/scripts/` harnesses. No integration value.

### 8. Dashboard

`no-fit` — The repo does not cover UI, Tailwind, React components, charts, or monitoring dashboards. Jarvis-trader dashboard is already wired. No integration value.

### 9. Ops / messaging

`defer` — The prompt's section on "durable waits", "idempotent side effects", and "compensating actions" (lines 304–320) is relevant to openclaw_notifier.py, scheduler cron jobs, and WhatsApp approval workflows. However, any integration must first verify that existing patterns in `engine/notifications/` and `engine/schedulers/` already implement these principles. Recommend: audit `engine/notifications/openclaw_notifier.py` (kill-switch guards, WhatsApp message idempotency) and `engine/schedulers/cron_triggers.py` against the prompt's "side effects need an idempotent effect layer" requirement. If gaps exist, file a task for Tier 3 safety review before borrowing compensation-action patterns.

## Integration plan

### `partial-integrate` surface 2: Project rules

**File**: `.claude/rules/reliability-engineering.md` (new)  
**Scope**: ~300 lines (excerpt + synthesis from fainir repo + jarvis-trader context)  
**Content**:
1. **State machines for workflows** — hardcode mandatory steps (e.g., debate round sequencing in `debate.py:85-150` already does this; generalize pattern)
2. **Validation loops, not final summaries** — add subsection with examples from discovery_loop.py, SDK pipeline orchestration
3. **Checkpointing and resumability** — proposal for learning_router.py and discovery_router.py to persist phase state (already in database layer; document the pattern)
4. **Idempotency for side effects** — link to existing `engine/notifications/` guards; clarify that OpenClaw alerts and WhatsApp messages must carry effect identities
5. **Structured schemas at phase boundaries** — reference existing Pydantic models (BullReport, BearReport, TradeDecision, DebateResult); validate input/output contracts

**Steps**:
- Extract lines 209–320 from fainir README (reliability math section)
- Synthesize with jarvis-trader code examples (debate.py, discovery_loop.py, SDK pipeline)
- Write new file with MIT attribution header
- Link from `.claude/rules/README.md` (if one exists) or from `meta-discipline.md` under "See also"
- No code changes required; documentation only

### `partial-integrate` surface 6: Docs

**File**: `docs/architecture/reliability-engineering-patterns.md` (new)  
**Scope**: ~200 lines  
**Content**:
1. **Why harnesses matter in trading systems** — contextualize for jarvis-trader's debate, advisor, and execution pipelines
2. **Multi-stage workflow failures** — chart showing how 95% step reliability cascades to <80% end-to-end (from fainir)
3. **Jarvis-trader harness architecture** — debate orchestrator (3-round state machine), fund manager (paper vs. live gates), risk manager (6-check safety layer)
4. **KPIs for learning systems** — add "memory reuse rate" and "proactive vs. reactive work ratio" to existing analytics framework

**Steps**:
- Create new file
- Add MIT attribution header
- Link from `docs/strategy/ARCHITECTURE.md`
- No code changes required

### `defer` surface 5: Subagents

**Requirement**: Tier 3 safety review (see red flags below)  
**Action**: File for next session — "Review subagent routing policy against fainir guidance, verify risk gates preserved"  
**Scope**: Deck assessment of whether current advisor_client integration and future subagent scaling can adopt "cheaper/faster models for narrow tasks" without bypassing RiskManagerAgent

## License & attribution

**License**: Not specified in the repository (assumed MIT or permissive based on "Paste this prompt into your agent" language). **CRITICAL**: Confirm license before integrating. If unknown, treat as reference-only (ideas, not verbatim copy).

**Attribution**: File headers in `.claude/rules/reliability-engineering.md` and `docs/architecture/reliability-engineering-patterns.md` will include:
```
Concepts adapted from fainir/most-capable-agent-system-prompt (assumed MIT).
See https://github.com/fainir/most-capable-agent-system-prompt
```

If license is GPL/AGPL, reject integration and flag for legal review.

## Effort estimate

**S** — Estimated 1.5–2 hours. Surface 2 (rules) and Surface 6 (docs) are documentation-only, no code changes. Extraction, synthesis, and link management are straightforward. No testing required (not executable). Risk review gate (`defer` on surface 5) is separate and Tier 3-scoped.

## Red flags

1. **License unknown** — Repository does not include a LICENSE file. Confirm fainir's intent (MIT, Apache 2.0, or proprietary) before committing. If proprietary or GPL, do not integrate code; reference ideas only in commentary.

2. **Safety-critical subagent routing** — Surface 5 (subagents) proposes "cheaper/faster models for narrow repeated tasks". Jarvis-trader's risk control plane (safety_layer.py, RiskManagerAgent, FundManagerAgent) must not be bypassed by cost optimization. Any adoption requires Tier 3 safety review and explicit approval.

3. **No trading-specific context** — The prompt is generic-agent focused. Borrowing "idempotent side effects" and "compensating actions" patterns directly from ops/messaging into a financial trading system carries risk if not carefully validated. E.g., a failed trade execution that gets compensated can create accounting/tax record confusion; the prompt does not cover that. Recommend: consult with domain expert (trading ops, risk) before implementing compensation patterns in `engine/notifications/` or `engine/schedulers/`.

4. **Architectural mismatch on "harness vs. agents"** — The prompt positions agents as components inside a harness. Jarvis-trader inverts this: agents (bull/bear/trader/advisor) are first-class, and the harness (debate orchestrator, pipeline) coordinates them. Borrowing harness-centric patterns wholesale without remapping to agent-centric model could introduce unnecessary abstraction layers.

