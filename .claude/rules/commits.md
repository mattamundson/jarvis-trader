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

## Conflict resolution

- Resolve merge conflicts in the file — do not `--ours` / `--theirs` blindly.
- When in doubt, pause and ask. Do not discard uncommitted changes as a shortcut.

## Pre-push checklist

- [ ] Fast test suite passes
- [ ] `pnpm run build` passes if dashboard touched
- [ ] No `.env`, keys, or credentials staged
- [ ] Commit message starts with a conventional prefix
- [ ] `[safety-review]` present if safety files touched
