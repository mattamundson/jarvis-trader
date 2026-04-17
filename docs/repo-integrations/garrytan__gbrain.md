---
repo: garrytan/gbrain
url: https://github.com/garrytan/gbrain
stars: 8684
language: TypeScript
license: MIT
archived: false
pushed_at: 2026-04-16T19:35:02Z
analyzed_at: 2026-04-17
recommendation: partial-integrate
surfaces_with_value: [skills, ops, dev-tooling]
shipped:
  - file: engine/utils/scheduler_safety.py
    surface: dev-tooling
    date: 2026-04-17
    what: "StaggeredCronRunner — deterministic per-job-id minute stagger, quiet-hours gate with wrap-around midnight support, dedupe window. Wraps async callables before APScheduler registration; no scheduler replacement. 18 passing tests."
  - file: engine/notifications/supervisor_fallback.py
    surface: ops-messaging
    date: 2026-04-17
    what: "Cross-modal refusal fallback — detect_refusal() regex-based classifier and try_with_fallback() async helper that routes to a secondary model on primary refusal OR exception. Designed to compose with SupervisorAgent (which already fail-opens on HTTP errors) for the distinct case of a successful-but-refusal primary response. 25 passing tests."
deferred:
  - what: "signal-detector skill + brain-ops skill"
    reason: "blocked on persistent agent memory decision — would require embeddings table + vector search in jarvis_trader.db"
  - what: "tiered entity enrichment (Tier 1/2/3 for counterparties and symbols)"
    reason: "M-effort (8hr) with schema migration; not blocking paper-trading validation"
  - what: "hybrid query search in dashboard"
    reason: "blocked on persistent-memory decision; extends tiered enrichment"
---

# garrytan/gbrain

## Core value proposition

GBrain is a production agent memory system built by Y Combinator's president for managing knowledge across meetings, emails, tweets, and voice calls. It organizes 17,888 pages of interconnected knowledge via 25 pre-built skills, enforces compiled-truth + timeline patterns, and runs 21 autonomous cron jobs using deterministic classifiers that improve over time. The repo ships as an OpenClaw/Hermes agent mod with MCP server exposure, CLI, and local-first PGLite or cloud-backed Postgres storage.

## Surface analysis

### 1. Engine code
**no-fit** — GBrain is a knowledge management and agent orchestration system written in TypeScript/Bun. Jarvis-trader's engine code is Python-based trading execution (agents, backtest, risk, pipelines). No signal detection, indicators, portfolio logic, or market data patterns map across. GBrain's vector search, entity enrichment, and timeline compaction are domain-agnostic retrieval patterns, not trading-specific.

### 2. Project rules
**no-fit** — GBrain's conventions (quality.md, brain-first.md, model-routing.md, cross-modal.yaml) govern knowledge ingestion, source attribution, and multi-model refusal handling. Jarvis-trader already has competing rules (meta-discipline.md, safety.md, engine-python.md, testing.md) tailored to trading execution safety. No conceptual conflict, but no additive value at the rules layer.

### 3. Project skills
**partial-integrate** — GBrain's 25 skills are highly reusable patterns. High-value candidates for port:
- **signal-detector** (parallel entity + original-thought capture) → Ports to `.claude/skills/agent-signal-detector/` as a companion to existing pipeline signal processing. Could feed market data mentions, regime changes, or trade ideas into a persistent agent memory layer.
- **brain-ops** (brain-first lookup before external API) → Complements existing `.claude/skills/jarvis-cost-routing/` cost optimization. Would cache market data queries, price lookups, and position data in local vector store before hitting live APIs.
- **enrich** (tiered enrichment: Tier 1/2/3 based on mention frequency) → Useful for enriching counterparties, venues, and symbols across the trade database. Tier 3 stub (first mention) → Tier 2 (web + risk profile at 3+ mentions) → Tier 1 (full compliance check at 8+ mentions or after live trade).
- **daily-task-manager** + **daily-task-prep** (priority P0-P3, calendar lookahead with context) → Direct analog to morning briefing + approval queue system. Could replace manual briefing Markdown with searchable brain pages.
- **query** (3-layer hybrid search with citations) → Could retrofit the dashboard's position lookup and trade history search from keyword-only to vector+keyword fusion, improving recall on semantic queries like "what large losses did we take in rates?" or "which trades happened during FOMC?"

**Effort to port:** M-L (2-8 hours each for signal-detector + brain-ops alone; enrich + task skills are 1-3 day tasks each due to Postgres schema alignment with jarvis_trader.db and trade_outcomes table redesign).

**Existing dedup risk:** Jarvis-trader already has:
- Signal detection in `engine/agents/pipeline.py:pre_filter_signal()` + `pipeline.py:run_on_signal()` 
- Cost routing in `.claude/skills/jarvis-cost-routing/`
- Task management via manual briefing at `engine/notifications/morning_brief.py`

Port strategy: Consume GBrain skill patterns (not code) as templates; wire to existing infrastructure (trade DB, OpenClaw notifier, PM2 crons).

### 4. Slash commands
**no-fit** — GBrain exposes agent-level commands (setup, migrate, soul-audit, briefing). Jarvis-trader already has competing command suite (`.claude/commands/jarvis-*`) scoped to trading workflows. GBrain's soul-audit (identity interview) and migrate (Obsidian/Notion→gbrain) are outside trading scope.

### 5. Subagents
**no-fit** — GBrain's agent roles (signal-detector, brain-ops orchestrator) are embedded in the skill system, not separate analyzer agents. Jarvis-trader's subagents (backtest-runner, safety-reviewer, memory-curator, pipeline-debugger) are trading-specific. No architectural transfer.

### 6. Docs
**partial-integrate** — GBrain's documentation of tiered enrichment (Tier 1/2/3), compiled-truth + timeline pattern, deterministic-classifier improvement feedback loop, and RRF hybrid search are valuable reference patterns.
- Document `docs/repo-integrations/gbrain-patterns-reference.md`: Compiled-truth pattern (snapshot + append-only evidence trail) could apply to trade outcomes (current position state + trade event log).
- Deterministic classifier / fail-improve loop (regex → LLM → regex refinement) applicable to regime classification and trade event classification in `engine/agents/pipeline.py`.

**File:** `docs/strategy/memory-systems-reference.md` (defer creation until surface 3 skills are scoped).

### 7. Dev tooling
**integrate-now** — GBrain's scheduler patterns are directly applicable:
- **cron-scheduler skill** (schedule staggering with 5-min offsets, quiet hours, timezone-aware wake-up override, idempotency) → Port to `engine/schedulers/base_scheduler.py` safety layer. Jarvis-trader currently runs 4 crons (eod_scheduler, validation_checker, tv_archive_scheduler, market_scanner) without stagger or quiet-hour protection.
  - **Action:** Extract GBrain's `cron-scheduler.md` logic into `engine/utils/scheduler_safety.py:StaggeredCronRunner` (idempotent, 5-min stagger, market-hours-aware). Add `quiet_hours` config to `engine/config.py`.
  - **Files to modify:** `engine/schedulers/__init__.py`, `engine/config.py`, new `engine/utils/scheduler_safety.py`, add tests in `engine/tests/test_scheduler_safety.py`.
  - **Effort:** S (2 hours — copy pattern, refactor existing crons to inherit safety layer).

- **webhook-transforms skill** (SMS/meeting/social→brain-page conversion with entity extraction) → Port webhook pattern to `engine/routers/webhook_router.py` (already exists for Discord, could extend to generic event-to-trade-context pipeline).
  - **Current state:** `engine/routers/webhook_router.py` exists but is minimal. GBrain's entity-extraction + contextualized page creation pattern could enhance it.
  - **Defer:** Depends on whether Telegram/WhatsApp webhooks are desired (currently only polling).

### 8. Dashboard
**no-fit** — GBrain's dashboard is a knowledge browser (search, timeline view, people/company cards). Jarvis-trader's dashboard is trading-specific (positions, P&L, alerts, approval queue). The viz patterns (timeline, entity cards, search results) could inspire components, but no direct code reuse.

### 9. Ops / messaging
**integrate-now** — GBrain's operational skill patterns align with jarvis-trader's OpenClaw integration:
- **cron-scheduler** (stagger, quiet hours, wake-up override, idempotency) — See Surface 7.
- **webhook-transforms** (route SMS/meeting/social to brain ingestion) — Extensible to trade approvals + market alerts via WhatsApp (already live at `engine/notifications/openclaw_notifier.py`).
- **cross-modal-review** (quality gate: second model, refusal routing) → Applicable to trade approval flow. GBrain's pattern: if Model A refuses a task, silently route to Model B. Jarvis-trader parallel: if Advisor (Claude Opus) refuses a trade, log and escalate to supervisor.

**Action:** Document GBrain's cross-modal pattern in `engine/notifications/supervisor.py` as a fallback template if OpenClaw approval fails (currently no fallback).

**Cron job sync:** GBrain's 21 crons (email sync, X timeline, calendar, meeting transcripts, voice ingestion) are not directly needed. But the **scheduling discipline** (5-min stagger, quiet-hours respect, idempotency heartbeat) should port to `engine/schedulers/`.

## Integration plan

### High-priority (integrate-now):
1. **Scheduler safety layer** (Surface 7, effort S)
   - Extract `cron-scheduler.md` patterns from GBrain
   - Create `engine/utils/scheduler_safety.py:StaggeredCronRunner` class
   - Refactor 4 existing crons to inherit from safety base
   - Add `quiet_hours` config to `engine/config.py` (market-hours gating for crons like EOD)
   - Files: `engine/schedulers/__init__.py`, `engine/config.py`, new `engine/utils/scheduler_safety.py`, test file
   - Commit message: `feat: scheduler safety layer with stagger+quiet-hours per gbrain cron-scheduler pattern`

2. **Cross-modal review fallback** (Surface 9, effort S)
   - Add secondary-model fallback template to `engine/notifications/supervisor.py`
   - Document pattern: if OpenClaw approval times out or returns 429, route to local Ollama fallback
   - Files: `engine/notifications/supervisor.py`, comment block at line ~60
   - Commit message: `feat: cross-modal approval fallback per gbrain pattern`

### Medium-priority (partial-integrate, requires scoping):
3. **Signal-detector + brain-ops skills** (Surface 3, effort M each)
   - Scope: Port GBrain's `signal-detector` (parallel entity capture) and `brain-ops` (brain-first lookup) as `.claude/skills/` templates
   - Dependencies: Requires decision on whether to wire semantic memory (vector store) into engine or keep it CLI-only
   - Blockers: `engine/data/jarvis_trader.db` schema would need `embeddings` table + vector extension (Postgres) if self-hosted; otherwise PGLite via GBrain's approach
   - Decision gate: Does user want agent memories (past trade decisions, regime observations, failure patterns) persisted in vector search?
   - If yes: **.3-day task:** wire `gpt-4o-mini` embeddings into trade logger + decision log, backfill trade history, create skill.
   - If no: Defer indefinitely.

4. **Tiered enrichment for entities** (Surface 3, effort M)
   - Scope: Apply GBrain's Tier 1/2/3 enrichment to counterparties (execution venues, brokers) and symbols (watch-list metadata, historical drawdowns)
   - Files: new `engine/agents/entity_enricher.py`, modify `engine/database/_mixins_trades.py` to track mention counts per counterparty
   - Effort: 8 hours (includes schema migration)
   - Blocker: None; can proceed in parallel.

### Low-priority (defer, requires upstream decision):
5. **Query skill with hybrid search** (Surface 3, effort L)
   - Scope: Retrofit dashboard position/history search with vector+keyword fusion (currently keyword-only)
   - Requires: Embeddings table + HNSW index on queries
   - Blocker: Decision on persistent agent memory (item 3 above)
   - If yes: Extends item 3 (8 hours → 16 hours total)
   - If no: Implement hybrid search on trade metadata only (dates, symbols, amounts), no semantic layer

## License & attribution

**License:** MIT (allows free use with attribution)

**Attribution:** GBrain patterns ported under MIT license. Add header to each modified file:
```python
# Adapted from garrytan/gbrain (github.com/garrytan/gbrain)
# Patterns: cron-scheduler (stagger, quiet hours, idempotency),
#          cross-modal-review (fallback routing), signal-detector (entity extraction)
# Original license: MIT
```

Include in `docs/repo-integrations/gbrain-attribution.md` if patterns are shipped.

## Effort estimate

| Task | Surface | Effort | Blocker |
|------|---------|--------|---------|
| Scheduler safety layer | 7 | S (2h) | None |
| Cross-modal fallback | 9 | S (2h) | None |
| Signal-detector skill | 3 | M (6h) | Persistent memory decision |
| Brain-ops skill | 3 | M (6h) | Persistent memory decision |
| Tiered entity enrichment | 3 | M (8h) | None |
| Hybrid query search | 3 | L (16h) | Persistent memory decision |
| **Total (integrate-now only)** | - | **S (4h)** | - |
| **Total (+ medium-priority)** | - | **L (26h)** | 1 decision gate |
| **Total (full integration)** | - | **XL (38h)** | 1 decision gate |

## Red flags

1. **Persistent memory decision required:** GBrain's core value is long-term semantic memory (21 crons ingesting data, vector embeddings, timeline compaction). Jarvis-trader is currently **stateless between sessions** (relies on live APIs + CSV cache). Porting skills without adding embeddings table + cron ingestion layer = surface-level integration (low ROI).
   
2. **Timezone/market-hours complexity:** GBrain assumes always-on agent (office hours override configurable). Jarvis-trader operates within CME Globex hours (Sun 5pm–Fri 4pm CT). Scheduler safety layer must respect this fence — already flagged in integration plan (Surface 7).

3. **Database schema coupling:** GBrain uses `pgvector` extension (Postgres 15+) or PGLite with custom vector ops. Jarvis-trader currently uses SQLite on engine-side (`jarvis_trader.db` via Python ORM). Any persistent-memory integration requires:
   - Schema migration (SQLite → Postgres if scaling, or add embeddings table to existing SQLite)
   - Backwards-compatibility test (existing 30 tables in jarvis_trader.db must remain queryable)

4. **Agent model routing:** GBrain uses model-routing.md (haiku for cheap classification, Sonnet for synthesis, Opus for complex decisions). Jarvis-trader already has cost-routing skill. No conflict, but ensure new skills inherit existing model budgets.

5. **OpenClaw integration depth:** GBrain is **designed to run inside OpenClaw** as a 25-skill mod (INSTALL_FOR_AGENTS.md auto-install). Jarvis-trader has **OpenClaw notifier only** (send-side). Porting GBrain skills as `.claude/skills/` means they run in Claude Code harness, not OpenClaw agent. This is acceptable for dev workflows (morning brief generation, memory curation) but won't participate in GBrain's autonomous ingestion loop unless OpenClaw gateway is extended.

## Summary

GBrain's **high-value exports for jarvis-trader are operational patterns (cron safety, cross-modal fallback) and skill templates (signal-detector, brain-ops, enrichment), not code**. The scheduler stagger + quiet-hours pattern solves a real problem (current crons can collide during market overlap periods). Hybrid search and tiered enrichment unlock knowledge reuse across past trades and regime observations — but only if persistent memory is wired into the engine.

Recommend: **Integrate Surface 7 (scheduler) + Surface 9 (cross-modal fallback) this session (S effort, 4 hours). Defer Surfaces 3–5 (skills) pending user decision on whether to add persistent agent memory layer.** If yes, plan 3-day follow-up to scope memory schema + skill porting. If no, close this repo as `dedup-architecture` (operational patterns already exist, just need hardening).
