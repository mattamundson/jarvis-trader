---
repo: gabogabucho/vertical-agent-kit
url: https://github.com/gabogabucho/vertical-agent-kit
stars: 19
language: Shell
license: MIT
archived: false
pushed_at: 2026-04-11T20:15:52Z
analyzed_at: 2026-04-17
recommendation: partial-integrate
surfaces_with_value: [rules, skills, commands]
---

# gabogabucho/vertical-agent-kit

## Core value proposition

Vertical Agent Kit is a Hermes-first scaffolding framework for rapidly converting a generic agent into a domain-bound operator. It provides blueprints, molding cards (lightweight role starters), verification checklists, and a thin CLI wizard (`vak.sh`) that guides configuration of agent identity (SOUL.md), user context, skill bindings, and domain boundaries without adding wrapper architecture. The repo assumes Hermes primitives (profiles, skills, MCPs) already exist and focuses on *composition and configuration* rather than foundation.

## Surface analysis

### 1. Engine code
`no-fit` — Vertical Agent Kit is agent infrastructure, not trading logic. JARVIS-TRADER has its own engine (Python backtest, signal pipeline, execution layer). No direct code migration path.

### 2. Project rules
`partial-integrate` — The repo's core philosophy maps cleanly to JARVIS-TRADER's discipline. Specifically:
- **Identity/voice/tone in SOUL.md only** (`vertical-agent-kit/docs/what-you-can-build.md:50-52`) parallels JARVIS-TRADER's agent profile isolation (see `.claude/skills/jarvis-trader/SKILL.md` for current agent identity).
- **Prune tools and skills aggressively** (`vertical-agent-kit/docs/what-you-can-build.md:55`) aligns with existing `.claude/rules/less-permission-prompts.md` (scope-first discipline).
- **Clear boundary and refusal behavior** (`vertical-agent-kit/docs/what-you-can-build.md:57`) mirrors `safety-reviewer.md` agent mandate and pre-trade verification flow.

Proposal: Create `.claude/rules/agent-config-discipline.md` distilling VAK's boundary-first philosophy into JARVIS-specific checklist (when adding new agent, verify: SOUL.md isolation, tool scope, refusal edge, verification gate).

### 3. Project skills
`integrate-now` — VAK's blueprint concept directly enables faster agent creation in `.claude/skills/`. Two immediate opportunities:
1. **Verification/checklist pattern**: VAK bundles `vak.sh verify` + `vak.sh smoke` logic. JARVIS has scattered checklist commands (`jarvis-pretrade-check.md`, `jarvis-kill-switch-check.md`, `jarvis-wfe-check.md`). Proposal: Create `.claude/skills/agent-scaffold/` with VAK-style verification template, pre-trade gate pattern, and molding-card starter for new trading agents (e.g., a new ArbitrageBot would inherit checklist discipline, SOUL isolation, and refusal edges without copy-paste).
2. **Molding-card lightweight starters**: VAK's `docs/areas/` + `templates/molding/` enable fast iteration. Proposal: Create `.claude/skills/trading-agent-molding-cards/` with variants: (a) signal-discovery agent (evidence sources: indicators, macro regime, CoT feeds), (b) risk-constraint agent (refusal boundaries: max leverage, position size), (c) execution-approval agent (WhatsApp gate, kill-switch check).

### 4. Slash commands
`partial-integrate` — VAK's CLI workflow (`vak.sh init`, `vak.sh verify`, `vak.sh list-blueprints`) can inform command design. JARVIS has no equivalent bootstrap/verification command for *new agents*. Proposal: Create `.claude/commands/jarvis-new-agent-scaffold` that:
- Runs VAK-style wizard locally asking: role (e.g. "momentum trader"), outcome, domain boundary, refusal edge, evidence sources.
- Generates SOUL.md + agent profile stub + verification checklist automatically.
- Hands off to agent with self-review prompt (VAK's two-step pattern).
- Returns a pre-trade gate command specific to that agent (e.g. `/pretrade-check-momentum`).

### 5. Subagents
`no-fit` — JARVIS-TRADER's agents (safety-reviewer, pipeline-debugger, backtest-runner, memory-curator) are trading-specific. VAK's cross-domain agent examples (support-triage, security-alert-triage, executive-reporting) don't map to futures trading. However, the *verification agent pattern* (VAK bundles role verification as an implicit step) could inspire a `config-reviewer` subagent: pre-ship check for new trading agent configs. Defer to rules/skills integration first.

### 6. Docs
`integrate-now` — VAK's `docs/` is a reference library for agent design discipline. Specific files to adapt:
- **`docs/what-you-can-build.md`** (positioning guide): Adapt to JARVIS domain — "what kinds of trading agents fit JARVIS-TRADER architecture" (e.g. signal agents fit, macro-regime agents fit, execution-override agents don't without safety review).
- **`docs/top-10-blueprint-ready-jobs.md`** (commercial operator roles): Create JARVIS equivalent listing top-10 trading agent archetypes (momentum, mean-revert, spread, volatility, macro-regime, news-sentiment, CoT-research, execution-gating, portfolio-rebalance, arb-discovery). Map each to: evidence sources, refusal boundaries, approval gates, backtest infrastructure.
- **`docs/how-to-choose-what-to-productize-first.md`** (prioritization filter): Adapt to JARVIS roadmap — filter trading agents by: backtest availability (exists vs. missing), live capital allocation (MCL/MNQ approved vs. pending), safety review (kill-switch integration done vs. pending).

Proposal: Create `docs/agent-architecture/trading-agent-blueprint-catalog.md` and `docs/agent-architecture/agent-config-playbook.md` drawing from VAK's structure but scoped to futures trading.

### 7. Dev tooling
`defer` — VAK includes `scripts/vak.sh` (Hermes CLI scaffolding). JARVIS has PM2 orchestration + Claude Code hooks. No direct integration path unless building a local agent bootstrap tool (would require WSL Hermes install — currently not in scope). Revisit if Hermes becomes JARVIS's agent framework.

### 8. Dashboard
`no-fit` — VAK has no dashboard examples. JARVIS-TRADER's dashboard is instrument-specific (portfolio, P&L, signal feeds). No UI components to port.

### 9. Ops / messaging
`no-fit` — VAK's ops patterns (cron jobs, alerts, handoff prompts) are generic agent-lifecycle events. JARVIS has trading-specific ops (OpenClaw notifications, WhatsApp approvals, morning brief crons). No direct fit, though VAK's two-step handoff pattern (self-review → skill-review) could inform approval flow design (defer to future review).

## Integration plan

**Recommended order (effort ascending):**

1. **Docs** (S = <2 hours) — Create `docs/agent-architecture/trading-agent-blueprint-catalog.md` mapping VAK's blueprint idea to JARVIS trading archetypes (momentum, mean-revert, spread, volatility, macro, news, CoT, execution-gate, rebalance, arb). No code changes; pure documentation work.

2. **Rules** (S = <2 hours) — New file `.claude/rules/agent-config-discipline.md`. Distill VAK's core philosophy (identity in SOUL only, aggressive tool pruning, explicit refusal boundaries) into a JARVIS-specific verification checklist. When creating a new trading agent: (a) Define SOUL.md with voice/tone/domain-specific greetings, (b) Define skill scope (e.g., signal agents use indicators + CoT, not order execution), (c) Define refusal edge (e.g., momentum agents refuse over-leverage), (d) Wire into pre-trade gate, (e) Run safety-reviewer against config.

3. **Skills** (M = 2–8 hours) — Create `.claude/skills/agent-scaffold/` with two sub-skills:
   - `trading-agent-blueprint` — VAK's `vak init`-style wizard adapted to futures. Asks: agent role (from catalog), evidence sources, position-size cap, approval gate (manual/auto/WhatsApp), backtest timeframe. Generates SOUL.md + agent profile + verification checklist.
   - `trading-agent-molding-cards` — Lightweight starters (signal-discovery, risk-constraint, execution-approval archetypes) copyable as agent templates.

4. **Commands** (M = 2–8 hours) — New command `.claude/commands/jarvis-new-agent-scaffold`. Wraps the agent-scaffold skill. User runs `/jarvis-new-agent-scaffold`, answers wizard, gets agent stub + pre-trade gate command auto-generated. Hands off with self-review prompt (VAK's two-step pattern).

**Note**: All integrations are *compositional* (no modification of existing agent code). They add new choice/discipline to the agent-creation workflow, not change the engine or trading logic.

## License & attribution

MIT. Attribution: Vertical Agent Kit by gabogabucho (https://github.com/gabogabucho/vertical-agent-kit). File headers in new `.claude/rules/`, `.claude/skills/`, `.claude/commands/` files should note VAK-inspired patterns.

## Effort estimate

- Docs: S (1.5 hours)
- Rules: S (1.5 hours)
- Skills: M (4 hours)
- Commands: M (3 hours)
- **Total: ~10 hours** (M + doable in one focused session)

## Red flags

- **Hermes vs. OpenClaw mismatch**: VAK is built for Hermes' primitives (SOUL.md, profiles, skills namespace). JARVIS uses Claude Code skills + OpenClaw. The *pattern* (agent config discipline, verification checklist, molding cards) is portable; the *syntax* (HERMES_HOME paths, Hermes CLI) is not. Integration must translate philosophy, not port tooling.
- **Agent framework lock-in**: VAK assumes Hermes is the runtime. If JARVIS later switches agent frameworks, this integration's command/skill syntax may drift. Mitigate by keeping rules/docs framework-agnostic.
- **Limited trading domain coverage in VAK**: VAK's blueprints are cross-domain (support, marketing, security). The JARVIS blueprint catalog must be built from scratch (trading-specific archetypes, backtest infra requirements, capital allocation rules). VAK provides the *shape*, not the content.
