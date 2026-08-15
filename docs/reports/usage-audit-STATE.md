---
source: "claude-usage-audit"
kind: "state-file"
tags:
  - claude-code-usage
  - the-coach
  - self-improving-loop
---

# Claude Code Usage Audit — STATE

Persistent memory for `/usage-audit` ("The Coach"). Each run **reads this first**
and **writes it before finishing**, so month N+1 resumes instead of restarting.
Five sections mirror the memory progression (Fail → Investigate → Verify →
Distill → Consult). Curate, don't accrete: verify entries against fresh data
each run; archive stale ones — never blindly append.

This file is a template until the first real `/usage-audit` run populates it.

## Verified facts
<!-- stage 3 — things confirmed about how Matt works; stop re-deriving these.
     e.g. "Correction rate is low when acceptance criteria are in the first
     message (verified 2026-07: 4% vs 22% when absent)." -->
_(none yet — first run will populate)_

## General rules
<!-- stage 4 — distilled habits that generalize across sessions.
     e.g. "State the acceptance test in message 1 for any engine/ task." -->
_(none yet)_

## Open failures
<!-- stages 1-2 — patterns flagged but not yet diagnosed/verified.
     e.g. "unverified-done-claim rate spikes in Firefighter sessions — why?" -->
_(none yet)_

## Lessons learned
<!-- stage 4 distillations from the audit's own mistakes (heuristic false
     positives the verifier caught), so next run's extractor/prompts improve. -->
_(none yet)_

## Last run
<!-- stage 5 — resume pointer: date, window, headline metrics, the Top-3
     changes recommended, and which prior recommendations moved their metric. -->
_(no runs yet)_
