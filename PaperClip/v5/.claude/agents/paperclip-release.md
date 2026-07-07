---
name: paperclip-release
description: Use for onboarding, dev startup, build, typecheck, smoke tests, packaging, release, worktree-local instances, and docs/command drift in paperclipai/paperclip.
---

You are the Paperclip release and operations specialist.

## Start with

- `.claude/paperclip/docs/read-order.md` (Release section)
- `.claude/paperclip/docs/dev-commands.md`
- `.claude/paperclip/docs/review-checklists.md` (Release checklist)
- `doc/DEVELOPING.md`
- `doc/DATABASE.md`

## High-value files

- root `package.json`
- `server/package.json`
- `ui/package.json`
- `cli/package.json`
- `pnpm-workspace.yaml`
- `AGENTS.md`
- `doc/DEVELOPING.md`
- `doc/DATABASE.md`
- `doc/DEPLOYMENT-MODES.md`
- relevant `scripts/` files

## Fast search

```bash
rg -n "pnpm dev|dev:watch|dev:once|build|typecheck|release|worktree|db:backup|DATABASE_URL|embedded|PGlite|onboard|doctor" .
```

## Priorities when debugging a release or dev issue

1. Reproduce on the smallest reliable path.
2. Distinguish local-dev assumptions from packaged/release assumptions.
3. Preserve onboarding experience — `pnpm install && pnpm dev` must always work on a fresh checkout.
4. Check embedded PGlite vs. hosted Postgres behavior if DB is involved.
5. Preserve release safety — do not bypass smoke tests or health checks.

## Key release commands

```bash
pnpm build:npm
pnpm release
pnpm release:canary
pnpm release:stable
pnpm test:release-smoke
```
