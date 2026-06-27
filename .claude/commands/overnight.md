---
description: Unattended overnight orchestrator for the cloud Routine. Runs three buckets read-only on trading — monitoring + morning brief, dev triage (draft PR), research/backtest sweeps. Encodes loop-brakes guardrails, never places an order, never edits safety files or curated state. Writes docs/loop-reports/YYYY-MM-DD-overnight.md.
allowed-tools: Bash, Read, Grep, Glob, Agent, Edit, Write
argument-hint: "(no arguments — runs the full overnight cycle)"
---

# Overnight Orchestrator

You are running **unattended on Anthropic cloud infra while Matt sleeps**. You read the
engine's existing outputs and reason over the codebase; you NEVER command the engine to
trade and you NEVER touch safety files or curated state. The full non-negotiable list is
in `## Hard constraints` at the bottom — read it first.

Work the phases in order. Phase 1 and Phase 4 ALWAYS run, even if a later phase aborts.
If a phase can't run (engine unreachable, missing data), record "skipped/stale" in the
report and move on — never fabricate, never try to start the engine.

## Phase 0 — Brakes preflight (must pass or abort)

Restate the `loop-brakes` contract for yourself; do not assume the skill is loaded:

- **Circuit breaker**: the same tool with the same args 3 times in a row = stop that
  phase and write what happened to the report. No retry loops.
- **Budget** (`jarvis-cost-routing`): Haiku for triage/summarization, Sonnet only where
  genuine reasoning is needed, never Opus on this cadence. Subagent fan-out is fine; tight
  retry loops are not.
- **Branch check**: confirm you are on a `claude/`-prefixed branch (`git branch
  --show-current`). If not, abort and report — do not work on `master`/`main`.
- **Engine read-only probe**:
  ```bash
  curl -s http://localhost:8010/health | head -c 500
  ```
  If unreachable, Phases 1 and 3 degrade to "engine down — brief/sweeps skipped". Do NOT
  attempt to start the engine or run PM2.

## Phase 1 — Monitoring + morning brief (first, always)

Highest value, lowest risk — so it runs first and its output is guaranteed. Reuse the
existing orchestration rather than reinventing it. Dispatch subagents in parallel (single
message, multiple `Agent` calls), the way `/jarvis-morning-brief` does:

- `safety-reviewer` — "verify hardcoded safety limits in engine/config.py are intact,
  confirm LIVE_TRADING_ENABLED=false, report kill-switch + loss-tracker state and any drift"
- `pipeline-debugger` — "report last 3 pipeline runs for MCL + MNQ, note stage failures,
  last debate score, final verdict"
- `backtest-runner` — "check last WFE snapshot for MCL + MNQ against paper thresholds
  (MCL≥0.82, MNQ≥0.57)"

Then read the engine-side outputs that PM2/HERMES already produce (latest
`data/morning_briefs/`, `data/daily_journals/`, health logs) for: engine health, kill
switch + loss tracker, equity (current/peak), open positions, overnight activity, and a
per-symbol go/no-go. **PM2/HERMES output is the source of truth** — if it is missing or
older than expected, report "stale", never recompute or invent it.

## Phase 2 — Dev triage → draft PR

Run the repo's standard fast checks (see `.claude/rules/git-workflow.md` Pre-Push
Checklist / `docs/runbooks/` for exact commands):

```bash
cd engine && .venv/Scripts/python -m pytest tests/ -m "not slow" -q ; ruff check .
cd dashboard && pnpm run build
```

Allowed autonomous fixes: **lint/format, obviously-safe test or doc fixes only**, and
only on paths NOT in the deny list. Then:

1. Create a branch `claude/overnight-<YYYY-MM-DD>` off the current branch.
2. Commit fixes with conventional-commit messages (`fix:`, `chore:`, `test:`, `docs:`).
3. Open a **draft** PR titled `[overnight] <date> — dev triage`, body linking the
   loop-report. **Never merge, never force-push.**

If a needed fix would touch `engine/risk/**`, `engine/config.py`, kill-switch code, or
`engine/.env`: **STOP that item, do not edit it**, and write a `[safety-review]`-tagged
note in the report describing the proposed change for a human. The harness deny rules will
block the edit anyway — do not try to work around them.

## Phase 3 — Research / backtest sweeps

Use the existing skills/CLIs only — do not re-implement any math:

- `jarvis-wfe-check` — WFE snapshot vs paper-approval thresholds.
- `backtest-report` skill — summarize any fresh `/backtest/*` output.
- `mcpt-validation` skill — one run per **locked** spec (no target-fiddling; MCPT is
  DIAGNOSTIC, not a promotion gate — see `docs/runbooks/MCPT_VALIDATION.md`).
- `last30days` skill — sentiment sweep for MCL/MNQ and any flagged topic.

All findings are diagnostic and go into the report only. Promotion of any strategy is a
separate Tier-3 human `[safety-review]` decision — never made here.

## Phase 4 — Report + heartbeat (always, even on partial failure)

Write one consolidated report to **`docs/loop-reports/<YYYY-MM-DD>-overnight.md`** with:

```
# Overnight Report — <YYYY-MM-DD>

**Verdict:** <GO | NO-GO | DEGRADED>

## Run metadata
- UTC / CT timestamps, branch, model + cost rollup, phases run/skipped

## Monitoring & Morning Brief
## Dev Triage  (link to the [overnight] draft PR, or "no changes")
## Research / Backtest
## Blocked / needs-human  ([safety-review] items)
```

Then append a dead-man heartbeat line to **`docs/loop-reports/.heartbeat`** (the file the
existing `heartbeat-check.ps1` watches — reuse it, do not invent a new mechanism):

```bash
echo "$(date -u +%FT%TZ) overnight <ok|partial>" >> docs/loop-reports/.heartbeat
```

## Hard constraints (override everything above)

1. **NEVER place, modify, or cancel an order.** NEVER POST to `/safety/*`, `/pipeline/*`
   execution paths, or any IB Gateway port. `REQUIRE_HUMAN_APPROVAL = True` is invariant.
2. **NEVER edit** `engine/risk/**`, `engine/config.py`, kill-switch code, or `engine/.env`.
   Surface needed changes as `[safety-review]` notes only.
3. **NEVER edit** `docs/CURRENT_STATE.md` or `MEMORY.md` — read-only; write your own report.
4. **NEVER merge or force-push.** Draft PRs only, `claude/`-prefixed branches only.
5. **Budget every LLM call** per `jarvis-cost-routing`; circuit-break on repeats.
6. Live port 4001 stays permanently blocked; paper account DUP662235 only.

## Why this command exists

This is the cloud-Routine payload for unattended overnight runs (see
`docs/runbooks/OVERNIGHT_ROUTINE_RUNBOOK.md`). It is the **Claude-agent reasoning layer**
that complements the engine-side PM2/HERMES jobs (`engine/ecosystem.config.js`, the source
of truth for brief data) and the on-machine `scripts/loops/*.ps1` harness — it survives a
closed laptop where those cannot. Guardrails are the `loop-brakes` skill
(`.claude/skills/loop-brakes/SKILL.md`) and `docs/loop-engineering.md` turned into an
enforced, version-controlled checklist.
