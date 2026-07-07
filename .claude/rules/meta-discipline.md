# Meta-Discipline — JARVIS TRADER

_Adapted from Karpathy's LLM-coding observations via [forrestchang/andrej-karpathy-skills](https://github.com/forrestchang/andrej-karpathy-skills) (MIT). These rules cover **how to approach work**; see `coding-style.md` for **what to write**._

## 1. State assumptions, don't guess

When the request is ambiguous — which symbol, which window, which side of a trade, which of two possible interpretations — surface the ambiguity before acting.

- If 80%+ confident: state the assumption, act, note it in the response.
- Less confident: ask one sharp question, wait.
- **Never act on a silent assumption** for anything touching `engine/risk/`, `engine/config.py`, order execution, stop-loss direction, or kill-switch logic. Prior incident: 2026-04-09 MCL inverted stop — silent assumption that stop > entry defines "long" cost real dollars in regression risk.

## 2. Push back when a simpler path exists

Disagreement is information, not rudeness. Before implementing, flag in one sentence when the request:

- Creates a new abstraction where existing code already fits (grep `engine/` first).
- Re-implements something already shipped (see `docs/digest/` for existing novel audits).
- Violates `safety.md` non-negotiables (no soft overrides).
- Would add a fallback or retry for a scenario that cannot actually occur.

Performative agreement erodes trust faster than accurate disagreement.

## 3. Surgical changes only

Every staged file must trace directly to the current request. No drive-by cleanups, no adjacent-file refactors, no "while I'm here" edits.

- **Never `git add -A`**. Stage files explicitly by path. Repo has 80+ legitimately untracked files across parallel workstreams; blanket staging sweeps in unrelated work.
- Don't delete pre-existing dead code you didn't author — surface it, let the user decide.
- Match existing style even if you'd do it differently. Style migrations are separate PRs.
- Session-log and handoff files are NOT implicit outputs. Edit them only on explicit request. Prior feedback 2026-04-17 00:31: "proceed" authorizes substantive work, not doc sprawl.

## 4. Verifiable goals before loops

For any multi-step task, translate the ask into a verification checklist **before coding**:

| Imperative instruction | Verifiable goal |
|---|---|
| "fix the debate scoring bug" | "write failing test reproducing score=0.000, implement until it passes, no other change" |
| "add confluence weight" | "define formula, add unit test with known inputs→outputs, implement to pass" |
| "refactor trader.py" | "full suite green before, refactor, full suite green after — no behavior delta" |
| "make backtest faster" | "baseline wall-clock, change, re-measure, report speedup — revert if <10%" |

Weak success criteria ("make it work", "clean it up") invite over-engineering. Strong criteria let the agent loop independently without mid-task clarification.

## Applies to

All jarvis-trader work. Not a style guide — a discipline guide. If a specific rule here conflicts with `safety.md`, safety wins.
