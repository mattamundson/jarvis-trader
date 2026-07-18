# STATE Memory Convention — JARVIS TRADER

How a multi-run or multi-session effort **resumes instead of restarts**. This is
about *working/resume state for one ongoing effort* — distinct from the durable
curated knowledge in `MEMORY.md`. Self-improving ≠ self-learning: the model is
stateless; a disciplined state file is what makes the *system* compound.

## What a STATE file is (and is not)

| File | Holds | Scope | Maintained by |
|---|---|---|---|
| `<effort>-STATE.md` | working/resume state for one ongoing effort | that effort | the effort's own runs |
| `MEMORY.md` / auto-memory | durable, verified facts about the codebase | whole project | `memory-curator` |
| `docs/session-logs/` | git-SHA breadcrumbs + milestone handoffs | per session | Stop hook |
| Obsidian vault | long-term research/second-brain | cross-project | `/vault` jobs |

A STATE file is not a knowledge base and not a changelog. If a fact graduates to
"durable project truth," it belongs in `MEMORY.md` (via `memory-curator`), not
here. Examples that already follow this: `docs/reports/usage-audit-STATE.md`,
the `overnight` loop-report state.

## The five sections (mirror the memory progression)

```
## Verified facts     # checked, stop re-deriving these
## General rules      # distilled — consult before re-solving
## Open failures      # flagged but not yet diagnosed/verified
## Lessons learned    # distillations from this effort's own misses
## Last run           # resume pointer: date, state, next action
```

## Two non-negotiable operations

- **Read at start.** Every run of the effort opens by reading its STATE file (and
  the relevant Skills). Skip this and the run restarts from zero.
- **Write before leaving.** Every run ends by updating STATE — what was tried,
  what passed, what failed, what new rule survived, and the resume pointer. A run
  that doesn't finish with a write forfeits its progress.

## Curate, don't accrete

Verify entries against fresh reality each run; update or **archive** stale ones,
never blind-append (the `memory-curator` discipline). A STATE file that only
grows is memory rot, not memory.

## Scope

Applies to any effort that spans more than one run/session (audits, migrations,
loops, multi-day builds). A single-shot task needs no STATE file. Never put
secrets, keys, or live P&L in a STATE file — it is committed to the repo.
