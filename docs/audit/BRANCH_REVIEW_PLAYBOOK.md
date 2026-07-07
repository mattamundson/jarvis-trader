# Branch Review Playbook

Companion to `docs/audit/open-sessions-2026-06-29.md` and the evidence produced by
`scripts/audit/gather_branch_evidence.sh`. This is the rubric a review session applies
to each branch **before any deletion**. Run one batch per fresh Claude Code session.

## The governing principle

**An empty three-dot diff (`git diff master...branch` shows nothing) does NOT prove a
branch is safe to delete.** It only proves the branch's tree equals its fork point. That
happens in three very different situations, and only two are safe:

| Why the delta is empty | Safe to delete? | How to tell from the evidence |
|---|---|---|
| Branch tip is an **ancestor of master** (truly merged) | **Yes** | `tip is ancestor of master = YES` |
| Branch work was **squash-merged** (content is in master under a different commit) | **Yes**, after confirming the squashed PR exists | `merged = no`, but unique commit subjects match a merged PR title; the work is visibly in master |
| Branch work was **reverted out of master** (the MES-authorization pattern: #172/#174 → reverted by #175/#180) | **NO — RECOVER candidate** | `'Revert' commits among unique > 0`, or the unique subjects describe a capability that is NOT in current master |

The third row is exactly the case to distrust. A "zero-delta" branch can hold the only
copy of work that was undone in `master`. Never auto-delete on the diff alone.

## Verdicts (assign exactly one per branch)

- **SAFE-DELETE** — Fully merged (`tip is ancestor = YES`) **or** squash-merged with the
  content confirmed present in current `master`. No unique unmerged value, no reverts.
- **RECOVER** — The branch has unique content (or reverted-out content) with standalone
  value — a fix, feature, or tests not in `master`. Do **not** delete yet: extract the
  valuable slice into a fresh **<30-file** PR off current `master`, land it, *then* delete.
- **KEEP-OPEN** — Corresponds to an active open PR or work the user still wants in flight.
  Cross-check the open-PR list in the audit doc. Leave the branch; ensure it has a PR.
- **ESCALATE** — Bring to the user. Any of: touches `engine/config.py`, `engine/risk/`,
  kill-switch, or `engine/.env`; appears to revert a safety change; the unique content's
  value can't be determined from the evidence; or it's one of the 1.7M-line CSV-blob
  branches (`*corey-extract-viewer*`, `*beautiful-fermi*`, `*corey-cache-stale*`) which
  need a re-slice decision, not a plain delete.

## Procedure for each branch in the batch

1. Read the evidence block (classification, merged flag, delta, unique commits, reverts).
2. If `tip is ancestor of master = YES` → **SAFE-DELETE** (record it; move on).
3. Else inspect the **unique commit subjects** and **name-status** files:
   - Do they describe a capability/fix/test? Check whether it exists in current `master`
     (grep the engine for the key symbol/file). Present → SAFE-DELETE. Absent → **RECOVER**.
   - Any `Revert` in the unique commits, or subjects matching a known reverted feature →
     **RECOVER** or **ESCALATE** (if safety-adjacent).
4. Touches a safety path, or you're not sure → **ESCALATE**. Never guess on safety.
5. Write one line to the batch's verdict file:
   `` `branch-name` — VERDICT — one-sentence justification grounded in the evidence ``

## Hard rules for the review session

- **Produce verdicts only. Delete nothing. Open no PRs.** Deletion/recovery is a
  separate, human-approved step after verdicts are collected.
- **Never** mark SAFE-DELETE for a branch whose unique value you could not locate in
  `master`. Absence of proof of value is not proof of absence — that's ESCALATE.
- Giants (>30 files) and anything safety-adjacent default to **RECOVER** or **ESCALATE**,
  never SAFE-DELETE, unless they are provably merged.
- Keep justifications evidence-grounded (cite the commit/file), not vibes.

## Output

One verdict file per batch under `docs/audit/branch-review/verdicts/`, e.g.:

```
# Verdicts — zero-01
`feat/forward-test-loop` — SAFE-DELETE — tip is ancestor of master (#NNN), fully merged.
`feat/some-capability`   — RECOVER     — adds engine/x/y.py not present in master; 3 unique commits, no PR.
`fix/safety-thing`       — ESCALATE    — touches engine/risk/; confirm with user before any action.
```

When all batches are reviewed, the consolidated verdicts drive the cleanup: SAFE-DELETE
branches get deleted in one human-approved sweep; RECOVER branches each become a small PR.
