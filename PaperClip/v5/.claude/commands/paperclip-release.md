Work on build, release, packaging, or dev-environment in paperclipai/paperclip.

Read `.claude/paperclip/docs/dev-commands.md` and `.claude/paperclip/docs/review-checklists.md` (Release section).

Priorities:
1. Reproduce on the smallest reliable path
2. Preserve `pnpm install && pnpm dev` fresh-checkout flow
3. Distinguish local-dev from packaged/release assumptions
4. Test embedded PGlite vs. hosted Postgres if DB is involved
5. Run `pnpm typecheck` and `pnpm test` before declaring done

$ARGUMENTS
