# Commit Rules — jarvis-trader

## Conventional commits

Use one of: `feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `perf:`, `chore:`.

One change per commit. Not a batch. A diff that fixes a bug AND adds a feature gets split.

## Messages

- Subject ≤ 70 chars, imperative mood ("add brier calibration", not "added" / "adds").
- Body (optional) explains WHY, not what — the diff shows what.
- Reference an issue or doc when the reason isn't obvious.

Example:

```
feat(analytics): add Brier calibration tracker to ic_ensemble

Complements IC (which scores direction) with a calibration metric
that penalizes confident-and-wrong signals. Source: runesleo/polymarket-toolkit.
Additive only — does not alter existing IC weight computation.
```

## Never

- **Never `git add -A`** blindly. There are ~1,450 uncommitted GMS changes
  in `personal_agent/` that must not enter trading commits. Stage specific files.
- **Never commit**: `.env`, API keys, bearer tokens, IB credentials, broker cookies.
- **Never amend** a pushed commit without Matt's explicit instruction.
- **Never force-push** to `main` or `master`. Branch + PR.
- **Never skip hooks** (`--no-verify`, `--no-gpg-sign`) unless Matt explicitly asks.

## Safety files require `[safety-review]` tag

Any commit touching `engine/config.py`, `engine/risk/`, `engine/execution/kill_switch.py`,
position sizing bounds in `engine/agents/trader.py`, or `engine/.env` must have
`[safety-review]` in the subject line. Example:

```
[safety-review] fix(risk): correct stop-loss direction for SHORT trades

Addresses T1.4 in roadmap-2026-04-15.md. Regression test
test_stop_direction_invariant added. Verified PATCH on MCL inverted stop.
```

## Merging PRs — never self-merge without real review

**Never merge your own PR** on your own initiative. Merging requires one of:
- Matt gives an explicit merge instruction *for that PR, at that time* ("merge
  #227", "go ahead and merge it"). A past merge instruction on a different PR
  is not standing authorization — ask again each time.
- A genuine human/reviewer approval is on the PR.

A CI check passing, or a bot comment, is **not** review. Explicitly: a
`chatgpt-codex-connector[bot]` comment that only reports hitting its usage
limit is not an approval — treat it exactly like no review happened, because
none did.

Incident (2026-07-01, PR #242): an agent session self-merged its own PR after
Matt had given a one-time "proceed" answer to a specific merge question on a
*different* PR (#227). The agent treated that precedent — "same pattern, small,
safe, verified" — as license to repeat the action unprompted on the next PR,
with no fresh instruction and no real review (only a Codex usage-limit
comment). Confidence in your own diff is not review. If nothing has actually
reviewed the PR, say it's ready and wait — don't merge it yourself because it
resembles a PR that was merged before.

## Conflict resolution

- Resolve merge conflicts in the file — do not `--ours` / `--theirs` blindly.
- When in doubt, pause and ask. Do not discard uncommitted changes as a shortcut.

## Pre-push checklist

- [ ] Fast test suite passes
- [ ] `pnpm run build` passes if dashboard touched
- [ ] No `.env`, keys, or credentials staged
- [ ] Commit message starts with a conventional prefix
- [ ] `[safety-review]` present if safety files touched
