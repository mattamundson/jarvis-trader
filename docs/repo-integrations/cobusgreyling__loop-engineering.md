---
repo: cobusgreyling/loop-engineering
url: https://github.com/cobusgreyling/loop-engineering
stars: 2600
language: JavaScript/TypeScript
license: MIT
archived: false
pushed_at: 2026-06 (actively maintained)
analyzed_at: 2026-06-27
recommendation: dedup
surfaces_with_value: [dev-tooling]
---

# cobusgreyling/loop-engineering

## Core value proposition

An essay + toolkit for "loop engineering" — designing autonomous agent loops
that find work, hand it to an agent, check the result, and decide the next move,
plus the brakes (step cap, budget ceiling, blast radius, circuit breaker,
dead-man heartbeat) that stop a loop from running up a $47k bill. Ships seven
production patterns (Daily Triage, PR Babysitter, CI Sweeper, Dependency Sweeper,
Changelog Drafter, Post-Merge Cleanup, Issue Triage), Claude Code / Codex / Grok
starters, an MCP cookbook, and three npm CLIs (`loop-audit`, `loop-init`,
`loop-cost`).

**Critical context:** this repo is the *source* jarvis-trader's existing loop
material was derived from. `docs/loop-engineering.md` is a near-verbatim adaptation
of the essay (same Boris Cherny 259-PRs, Steinberger, $47k-in-11-days, ~$1.3M/mo
fleet anchors), and `loop-brakes` SKILL.md encodes its section-9 brake checklist.
So most of the conceptual value is already integrated — this analysis is
confirming dedup, not discovering novelty.

## Surface analysis

### 1. Engine code
no-fit — agent-orchestration tooling, no trading/signal/risk code.

### 2. Project rules
dedup-rules — the brakes + discipline are already in `loop-brakes` SKILL.md,
`.claude/rules/meta-discipline.md`, and `.claude/rules/safety.md` (brakes-first,
blast radius, "Never" list).

### 3. Project skills
dedup-skills — `loop-brakes` (section 9) and `jarvis-cost-routing` (the `loop-cost`
token-spend concept) already exist. The seven patterns map to existing assets, not
new skills (see surface 7).

### 4. Slash commands
dedup-commands — Daily Triage ≈ the new `/overnight` command + `jarvis-morning-brief`;
no new command worth adding for a trading repo.

### 5. Subagents
dedup-subagents — the maker/checker split is `.claude/agents/safety-reviewer.md`
(checker) and the `scripts/loops/maker-checker-loop.ps1` harness.

### 6. Docs
dedup-docs — `docs/loop-engineering.md` IS this repo's essay (primitives matrix,
four deaths, brakes, cost spread), with a jarvis-trader appendix already mapping
each piece to local equivalents.

### 7. Dev tooling
partial-integrate (thin) — the only surface with residual novelty. The three npm
CLIs are generic and mostly overlap the existing `scripts/loops/*.ps1` harness:
- `loop-audit` (readiness scoring) ≈ `scripts/loops/preflight.ps1`
- `loop-cost` (token estimation) ≈ `jarvis-cost-routing` skill
- `loop-init` (scaffolding) — not needed; loops already scaffolded
The `STATE.md` / `loop-budget.md` / `loop-run-log.md` file conventions are already
realized as `docs/CURRENT_STATE.md` + `docs/loop-reports/`. Net: reference, don't
vendor.

### 8. Dashboard
no-fit.

### 9. Ops / messaging
dedup-ops — PR Babysitter ≈ the `subscribe_pr_activity` flow already in use; the
triage-inbox handoff ≈ `docs/loop-reports/` + `scripts/loops/triage-loop.ps1`.

## Integration plan

No integrations recommended — the repo is already integrated at the level that
matters (essay → `docs/loop-engineering.md`, brakes → `loop-brakes`, patterns →
`scripts/loops/`). Optional, only if a specific gap is felt later:
- When tuning unattended-run cost, skim `loop-audit` / `loop-cost` output via
  `npx @cobusgreyling/loop-audit` rather than vendoring — compare its readiness
  rubric against `scripts/loops/preflight.ps1` and backport any missing check.

## License & attribution

MIT — free to reference/adapt with attribution. Attribution already present in
`docs/loop-engineering.md` (cites the essay) and `loop-brakes` (cites the $47k
incident). No further attribution action needed.

## Effort estimate

S (zero for the recommendation; ~1hr if backporting one `loop-audit` check into
`preflight.ps1` is desired later).

## Red flags

None for the repo itself (MIT, active, 2.6k stars). The only "flag" is the
temptation to re-integrate already-shipped material — duplication is worse than
omission (skill anti-pattern). Do NOT fork/clone the whole repo: it's a generic
JS/TS toolkit, the conceptual content is already local, and a vendored fork just
becomes stale maintenance.
