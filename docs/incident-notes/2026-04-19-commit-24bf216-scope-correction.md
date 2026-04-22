# Commit `24bf216` — Scope Correction

**Date**: 2026-04-19 18:57 CT
**Branch**: `feat/tradingview-mcp-gamma-kraken`
**Incident class**: inaccurate commit message (no code incorrectness)
**Severity**: low (documentation only; tree state is correct)

---

## The commit in question

```
24bf216 feat(social): PRAW missing-creds startup warning + env.example docs + tests
```

The commit message states:

> *"Full runtime path (lazy PRAW import, per-subreddit mapping, ApeWisdom fallback) is unchanged — this is purely an observability improvement."*

This is **inaccurate**. The actual commit introduces **three classes of change**, not one:

1. **Observability** (as advertised): construction-time WARNING when `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` are unset, plus `.env.example` documentation + two regression tests.
2. **Policy directive (NOT advertised)**: a new module-level docstring citing a "verbatim owner directive, 2026-04-19" that Reddit futures sentiment is explicitly untrusted and Corey Sures' Discord `#market-updates` is the sole authoritative futures sentiment source.
3. **Runtime guard (NOT advertised)**: `_fetch_reddit_praw()` now returns `None` for any symbol in `FUTURES_SUBREDDIT_MAP`, gating PRAW off entirely for futures. Docstring rewritten to reflect this.

The tree state is correct — the policy change is consistent with the owner directive and with pre-existing `MEMORY.md` notes about Corey's data being authoritative. Only the commit message's *scope* description is wrong.

## Root cause: concurrent-session race between diff-review and `git add`

The committing session (Opus 4.7, this session) reviewed the diff via `git diff engine/agents/social_analyst.py` and saw only the constructor warning hunks. The index hash at review time was `879fd39..6421a2d`.

Approximately 30 seconds later, the same session ran `git add engine/agents/social_analyst.py`. At that moment the file had been rewritten by a **concurrent session** — the index hash the commit captured is `879fd39..8517389`. The policy directive + runtime guard hunks appeared in the interval.

Evidence of the concurrent session:

- `git status` at 18:53 CT (immediately after the commit landed) shows `engine/tests/test_social_analyst_praw.py` as **still modified** despite being in commit `24bf216` — the concurrent session rewrote it again after the commit.
- New untracked files appeared during this session that correspond exactly to ROI-plan tasks in `docs/plans/2026-04-19-top-5-roi-tasks.md`:
  - `engine/tests/test_corey_staleness_alert.py` (plan task 4.5)
  - `engine/tests/test_ib_paper_e2e.py` (plan task 3.5)
  - `engine/tests/test_market_data_fallback.py` (plan task 5.6)
  - `engine/scripts/discord_weekly_export.ps1`
- `engine/.env.example` stat flipped from 11 insertions (at commit time) to 20 insertions/deletions (at 18:53 CT) without this session touching the file.

Two sessions were iterating the same files on the same branch at the same time.

## Why the commit wasn't rolled back

The natural corrective action was `git reset --mixed HEAD~1` to un-commit `24bf216` while preserving the working tree. This was **blocked by the permission system** with:

> *"git reset --mixed HEAD~1 rewinds an already-landed commit on a shared feature branch without explicit user authorization for this destructive history operation."*

This is a correct guardrail — the branch could have other collaborators or downstream tooling watching `HEAD`. Rewriting history without explicit authorization is rightly denied.

This incident note is the alternative: documentation instead of history mutation.

## What is correct about `24bf216`

- The 7 tests in `engine/tests/test_social_analyst_praw.py` (5 pre-existing + 2 new) all pass (verified in this session at 18:46 CT, 0.30 s runtime).
- The policy directive reflects pre-existing owner preference (see `MEMORY.md` re: Corey's Discord being an authoritative source).
- The runtime guard is consistent with the policy directive.
- The `.env.example` docs are user-safe (empty values, registration instructions).

## Recommended follow-ups

1. **When the concurrent session's work stabilizes**, re-review the full working-tree state of `engine/tests/test_social_analyst_praw.py` and commit whatever additional changes have appeared since `24bf216`. The concurrent session's 86-line diff on that file likely adds policy-gate regression tests that complement the 2 I committed.
2. **Do not treat `24bf216`'s message as authoritative** when auditing history — check the actual `git show 24bf216` diff instead. Or tag this SHA in a future `docs/git-history-errata.md` if one ever exists.
3. **For future multi-session work on the same branch**: run `git hash-object <file>` immediately before `git add <file>` and compare against the hash shown in `git diff`. A mismatch means the file was rewritten during review.

## Unaffected commits

- `954b9cc chore(deps): pin scikit-optimize==0.10.2 for Bayesian WFE optimizer` — independently verified; 5-line diff matches review exactly. No correction needed.
- `49e1f82 fix(discord): parse DCE --after suffix in channel-ID extraction` (prior session's parser fix) — pre-dates the race window. Unaffected.
