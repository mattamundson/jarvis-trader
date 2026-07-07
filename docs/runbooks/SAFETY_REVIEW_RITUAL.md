# Safety-Review Clearing Ritual

**Purpose.** The `[safety-review]` gate (`.claude/rules/commits.md`, `.claude/rules/safety.md`)
correctly requires human Tier-3 sign-off for any change near live-trading risk. The gate has been
*correct* but *unclearable* — tagged PRs sat open forever because there was no defined step to
**decide** them. This adds the missing decision step.

> This document changes **no safety parameter and grants no new authority.** It only ensures a
> gated PR reaches a terminal state (APPROVE / REJECT / CHANGES) instead of accumulating in limbo.
> Per `safety.md`, **safety wins on any conflict** — nothing here overrides an invariant.

## What triggers a safety review

A PR is **safety-gated** if its diff touches any of (same set as `commits.md`):

- `engine/config.py`
- `engine/risk/**` (incl. `safety_layer.py`)
- `engine/execution/kill_switch.py`
- position-sizing bounds in `engine/agents/trader.py`
- `engine/.env`

Such a PR MUST carry `[safety-review]` in the subject **and** the `safety-review` label, and MUST
stay a **draft** until a decision (so it is never mistaken for merge-ready).

## The ritual (per gated PR)

1. **Tag + draft.** Author labels it `safety-review` and converts to draft.
2. **Safety-impact section** in the PR body, stating explicitly:
   - which invariant(s) the diff touches,
   - why it does not weaken any,
   - the test that proves it,
   - whether it changes **runtime behavior** or only **code defaults** (these are very different).
3. **Run `safety-reviewer`** (the subagent) on the diff. It checks the hardcoded caps + invariants
   below are intact and that no LLM-driven safety decision was introduced.
4. **Decide within the standing window** (next working session, target ≤ 48h). Exactly one of:
   - **APPROVE** → mark ready, merge.
   - **REJECT** → close with a one-line reason.
   - **CHANGES** → leave draft, comment what must change.
   There is no "leave it open and unreviewed" state.
5. **If undecided in the window**, it stays draft and is listed in the in-flight tracker under
   **"Awaiting safety decision"** — visible, not forgotten.

## Reviewer checklist — the invariants, none may regress

- `LIVE_TRADING_ENABLED` stays **False**; `REQUIRE_HUMAN_APPROVAL` stays **True**.
- Kill-switch triggers unchanged (**-2% daily P&L / -20% drawdown** runtime; `config.py` default -10%)
  and remain **hardcoded Python with no LLM route**.
- Risk caps intact: 5% max position, 2 micro contracts, 1 overnight, $5,000 single-order code default,
  40% margin, 10 orders/min.
- Port **4001 permanently blocked**; paper-only on **4002**.
- No exception silently swallowed in `safety_layer.py`; no safety decision routed through an LLM.
- The change can only **tighten or leave-equal** a verdict — never loosen — *unless* it carries
  explicit written Tier-3 authorization for the specific loosening.

## What this does NOT do

It does not change a single risk parameter, does not enable live trading, and does not let any PR
bypass the gate. It is purely the missing **decision cadence**. If you are ever tempted to change a
real safety parameter, that is a separate, deliberate, isolated, tested PR with a written reason —
never a side effect of clearing a queue and never a frustration-driven edit.

## Current queue (as of this document)

| PR | Touches | Recommendation |
|---|---|---|
| **#177** systematic-exec-bridge | order path (`SafetyLayer.submit_paper_order`); `SYSTEMATIC_AUTO_EXECUTE` default-off | **Decide** — APPROVE only after `safety-reviewer`; activation stays a separate Tier-3 step |
| **#183** queue-shared-dedup | order-path submission dedup; stacked on #177 | **Decide after #177** — it's the prerequisite double-fill guard |
| **#160** corey-cache-stale | `engine/config.py` defaults (already match live `.env`) + 1.7M-line CSV blob | **REJECT/close + re-slice** — unreviewable as-is; extract the real source into a <30-file PR |

Once a PR here is decided, remove it from this table in the same PR that resolves it.
