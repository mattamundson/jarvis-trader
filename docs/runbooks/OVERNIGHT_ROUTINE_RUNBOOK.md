# OVERNIGHT ROUTINE RUNBOOK

How to run Claude unattended overnight against jarvis-trader using a **cloud Routine** —
the only mechanism that keeps working while your laptop is off. The Routine runs on
Anthropic infra, clones the repo, and runs the `/overnight` command
(`.claude/commands/overnight.md`).

## What this is / is not

This Routine is the **Claude-agent reasoning layer**. It does NOT replace the engine-side
jobs or the on-machine loops — it reads their output and reasons over it.

| Layer | Mechanism | Role | Needs laptop on? |
|---|---|---|---|
| **Cloud Routine (this)** | `/overnight` on Anthropic infra | Synthesize briefs, draft PRs, run research sweeps | No |
| PM2 cron + HERMES | `engine/ecosystem.config.js` (Windows) | **Source of truth** for brief/health/EOD data | Yes |
| Local loops | `scripts/loops/*.ps1` via Task Scheduler | On-machine read-only triage / maker-checker | Yes |

The Routine **reads** PM2/HERMES output and reports "stale" if missing — it never starts
the engine or re-runs PM2 jobs. No duplication.

## Create the Routine (web UI)

1. Open `claude.ai/code/routines` (or run `/schedule` from the CLI) → **New routine**.
2. **Repository:** `mattamundson/jarvis-trader`.
3. **Cadence:** once nightly at **02:30 America/Chicago**. This lands after
   `jarvis-discord-export` (02:00 CT, so sentiment data is fresh) and before
   `jarvis-morning-brief` (06:30 CT, so the engine brief is undisturbed). Do **not** set
   hourly — this is a nightly cycle; hourly would burn budget and spam draft PRs. (Platform
   minimum is 1 hour either way.)
4. **Prompt to paste:** exactly `/overnight` (nothing else — all logic lives in the
   command file, version-controlled).
5. **Permission mode:** runs "autonomously" (cloud default). This is precisely why the
   harness `permissions.deny` rules in `.claude/settings.json` exist — they are the
   enforced backstop, independent of model behavior.
6. **Network policy:** **Trusted** (needs package registries for pytest deps and git push).
   Trusted does not relax the file-deny rules.
7. **Branch behavior:** the Routine clones and pushes to `claude/`-prefixed branches and
   opens **draft** PRs. Confirm it never targets `master`/`main` and never auto-merges.

## 7-day expiry caveat

Recurring Routines **auto-expire 7 days after creation** (they fire one final time, then
delete). Set a **weekly calendar reminder to re-create** this Routine, and note the
creation date at the top of that week's loop-report.

## Morning review workflow

Each morning:

1. Open the newest `docs/loop-reports/<YYYY-MM-DD>-overnight.md`.
2. Read the top-line **verdict** and the **Blocked / needs-human (`[safety-review]`)**
   section first.
3. Review the **`[overnight]` draft PR** — merge or close it. Anything in the
   `[safety-review]` bucket is applied by a human with the `[safety-review]` PR tag, never
   auto-applied.
4. Check `docs/loop-reports/.heartbeat` freshness (or trust the local `heartbeat-check.ps1`
   alert). A missing heartbeat means the Routine silently stopped firing — re-create it.

## Kill the Routine

Pause or delete it from `claude.ai/code/routines` if it misbehaves. PM2 jobs and the local
`.ps1` loops are unaffected — they run independently on your machine.

## First-run discipline

Before relying on it nightly, trigger the Routine **once manually** (or run `/overnight` in
an interactive cloud session) and confirm: a `claude/` branch was used; a **draft**
`[overnight]` PR (not merged) opened; the report wrote with all sections + verdict; the
heartbeat appended; the PR diff touches **no** deny-listed file; the transcript shows **no**
POST to execution/safety endpoints. Read the draft PR end-to-end as the human gate, then
enable the nightly schedule.

---

*Companion: `.claude/commands/overnight.md` (payload), `.claude/skills/loop-brakes/SKILL.md`
(guardrails), `docs/loop-engineering.md` (mental model). Last verified 2026-06-27.*
