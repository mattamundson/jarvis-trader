---
name: loop-brakes
description: Safety checklist for setting up an unattended, scheduled, or recurring Claude Code agent loop — caps the blast radius before it runs. Use when the user wants to "run a loop", "set up an automation", "kick off an autonomous agent", "let it run overnight", "schedule a routine", "babysit/autofix a PR on a loop", "run /loop or /goal or /schedule", or any agent run that proceeds without a human watching each step. Installs step cap, budget ceiling, tool allowlist, blast radius, circuit breaker, and a dead-man check. Read BEFORE walking away.
---

# loop-brakes

_Companion to `docs/loop-engineering.md` (the mental model). This skill is the
one actionable slice: scope the blast radius **before** the loop runs. Brakes
before horsepower — do not ship the engine until the brake pedal is in._

A runaway loop once burned $47,000 in eleven days because it had no step cap, no
budget ceiling, and no stop condition. One brake would have killed it on day one.

## When to use

Trigger whenever a run will proceed without a human reviewing each step:

- `/loop`, `/goal`, or `/schedule` (Routines) is about to run
- A headless run (`claude -p`) that loops or self-continues
- A subscribed PR auto-fix loop ("babysit", "make it green")
- Any "let it run overnight / while I sleep" request

Skip for a single interactive turn the user is watching.

## The checklist (all must be answered before the loop starts)

| Brake | Question to answer | How |
|---|---|---|
| Step cap | What is the hard turn limit? | `claude -p --max-turns 50` (no default limit; print mode only) |
| Budget ceiling | What dollar amount halts it? | `claude -p --max-budget-usd 10` per phase (or `costLimitUsd` in settings.json) |
| Tool allowlist | What is it allowed to touch? | `--tools "Read,Bash,Grep"` + `--disallowedTools "Write,Edit"` for read-only loops |
| Permission mode | Who approves actions? | `--permission-mode auto` (classifier reviews, no prompts); never `bypassPermissions` unattended |
| Blast radius | What can it destroy? | one worktree, one branch, read-only outside `src/`/`engine/` |
| Stop condition | When is it *truly* done? | a verifiable fixpoint (tests pass, lint clean) — never "looks done" / "make it better" |
| Circuit breaker | When does it self-halt? | same tool + same args 3x in a row = stop |
| Dead-man check | How do you know it died? | heartbeat to `docs/CURRENT_STATE.md`/`MEMORY.md` each run; silence pages you |

If any cell is blank, the loop is not ready. Set it or do not walk away.

## Verified flags (current Claude Code, confirmed 2026-06-22)

```bash
# Safe unattended run: capped, read-only, classifier-gated
claude -p --max-turns 20 --max-budget-usd 2.50 \
  --permission-mode auto \
  --tools "Read,Bash,Grep" --disallowedTools "Write,Edit" \
  --output-format json \
  "investigate the failing test in tests/test_safety_layer.py"
```

- `--max-turns` and `--max-budget-usd` are **print-mode only** (`-p`). They do
  nothing in an interactive session.
- `/loop` is **session-bound** — it dies when the CLI exits. For laptop-closed
  scheduling use `/schedule` Routines (1-hour minimum) or GitHub Actions.
- `/goal`'s verifier is your configured small/fast model and only judges the
  transcript — it does not run commands or read files itself. Give it a stop
  condition it can actually see (e.g. test output printed in the run).

## The four ways loops die (what each brake prevents)

1. **Runaway recursion** — two agents feed each other forever → step cap + budget.
2. **Silent death** — context fills, run looks alive but is stuck → dead-man heartbeat + fresh context per phase.
3. **Random walk** — drifts off-goal with no fixpoint → verifiable stop condition.
4. **Comprehension debt** — ships code nobody read → human-read gate the loop can never skip.

## jarvis-trader hard rules (override everything above)

- **Never let an unattended loop place an order.** `REQUIRE_HUMAN_APPROVAL =
  True` is invariant. The human-approval gate IS the non-negotiable dead-man
  check for any trading loop.
- **Never point a loop at `engine/risk/`, `engine/config.py`, or kill-switch
  code** without a human and the `[safety-review]` PR tag. No autonomous edits to
  safety files — ever.
- **Read curated state, write your own.** A loop *reads* `docs/CURRENT_STATE.md`
  / `MEMORY.md` but must never edit them (`meta-discipline.md` rule 3). Write loop
  output to a dedicated `docs/loop-reports/` file instead.
- **Budget every LLM-in-the-loop** against `jarvis-cost-routing` before scheduling
  an agent that burns tokens on a cadence.
- A trading loop's blast radius is dollars in the paper account (DUP662235), not
  just CI minutes. Cap accordingly; live port 4001 stays permanently blocked.
