---
description: Audit your own Claude Code usage over the last N days — prompting habits, skill level, cutting-edge features you're missing, and skills you built but don't use when you should. Runs the deterministic extractor, fans out reader + gap-analyst subagents per sampled session, verifies findings with an independent grader, and writes a house-style report + STATE memory. Read-only against ~/.claude.
allowed-tools: Bash(python3:*), Read, Grep, Glob, Agent, Write
argument-hint: "[optional: --days 90] [--project <dir-name>]"
---

# Claude Code Usage Self-Audit ("The Coach")

You are orchestrating a usage self-audit. Coordinate — do not do the
per-session reading yourself. Args: $ARGUMENTS (default `--days 90`).

Design: a cheap deterministic backbone reduces months of transcript to signals;
the LLM tiers only read a stratified sample. Every claim in the final report
carries a receipt (a session date + quote, or a stat from `summary.json`). This
audit is **read-only against `~/.claude`** — never modify a transcript.

## Phase 0 — loop-brakes preflight
State the blast radius before running: reads `~/.claude/projects/**` (read-only)
and the repo's `.claude/` inventory; writes ONLY to `./claude-usage-analysis/`
and `docs/reports/`. Set a subagent cap: **max 20 reader/analyst agents per
run** (sample is bounded). If the corpus is huge, keep the default `--days`
window rather than widening it.

## Phase 1 — deterministic extraction (Tier 0-2)
```bash
python3 scripts/analyze_claude_usage.py $ARGUMENTS --out ./claude-usage-analysis
```
Then read `./claude-usage-analysis/summary.md`, `summary.json`, and
`sample_sessions.json`. If `sessions` is 0, STOP and report "no history in
window" (note: this may mean you're on a different machine than your CLI
history — say so). Sanity-check `summary.json` before trusting it: if any rate
is impossible (e.g. >100%) or the date range looks wrong, halt and report.

## Phase 2 — qualitative fan-out (Tier 3-4), parallel
For each session in `sample_sessions.json` (cap 20), dispatch **in parallel**
(single message, multiple Agent calls), passing the session `file` + its row
from `sessions_raw.json`:
- `usage-session-reader` — rubric scores + evidence for that session.
- `usage-gap-analyst` — should-have-fired + feature gaps for that session.
Collect the structured JSON returns. Do not read the transcripts yourself.

## Phase 3 — independent verification (maker ≠ grader)
A finding is not trusted because the reader asserted it. Dispatch a fresh
grader Agent (a DIFFERENT context, no exposure to the reader's reasoning) to
spot-check the highest-severity findings: confirm each cited quote actually
exists verbatim in the named transcript and that the should-have-fired trigger
really matched. Drop any finding whose evidence doesn't check out. Report how
many findings survived vs. were dropped.

## Phase 4 — synthesize the report (Tier 6, house six-section format)
Write `docs/reports/claude-usage-audit-<YYYY-MM-DD>.md` using the
`backtest-report` skeleton, plus a top `**Verdict:**` line:

```
# Claude Code Usage Audit — <YYYY-MM-DD>
**Verdict:** <skill-level one-liner, e.g. "Advanced orchestrator, weak on verification-before-done">
## Headline            (one paragraph, evidence-cited)
## Skill-Level Profile (radar: score per facet, Novice→Power-user)
## Scorecard           (table: metric | value | trend vs last run | flag)
## What's Working       (evidence-backed)
## Gaps & Should-Have-Fired  (skill×session, feature-adoption, dead skills, config gaps)
## Risk Flags           (ALWAYS present — e.g. unverified-done-claim rate; "None" if clean)
## Top 3 Next-Week Changes  (concrete + checkable, not "be more specific")
```
Rules: no claim without a receipt; never invent a metric the extractor didn't
return (write "not measured"); state the verification level of each conclusion.
Also write the `summary.json` alongside as the machine-readable snapshot.

## Phase 5 — update memory (Tier 7 lightweight)
Update `docs/reports/usage-audit-STATE.md` (create from the template if absent)
using its five sections (Verified facts / General rules / Open failures /
Lessons learned / Last run). If a prior `claude-usage-audit-*.md` exists, DIFF
the key metrics and fill the Scorecard "trend" column — this is the monthly
re-run that measures whether last month's Top-3 changes actually stuck. Curate,
don't accrete: update/verify entries, archive stale ones (memory-curator
pattern). Refresh `docs/reports/operator-profile.json` with the stable facts.

## Phase 6 — visual dashboard (optional, Tier 8)
If asked for the dashboard, invoke the `dataviz` + `artifact-design` skills to
render a self-contained Artifact (skill radar, weekly trend lines,
feature-adoption scorecard, archetype mix) from `summary.json` — aggregated
numbers only, never raw prompt text. Vision-verify it with a gstack screenshot
read before declaring it done.

## Guardrails
- Nothing auto-installed. Proposed new skills/hooks are drafted as suggestions
  for the human to approve — never written into `.claude/settings*.json`.
- Privacy: raw transcripts never leave the machine; the report and dashboard
  carry aggregates + short quotes, not bulk prompt text.
- Report the verification level of the whole audit honestly (which findings are
  grader-confirmed vs. single-pass).
