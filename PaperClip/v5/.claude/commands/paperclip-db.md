Work on a database or schema change in paperclipai/paperclip.

Read `.claude/paperclip/docs/read-order.md` (DB section), `doc/DATABASE.md`, and `.claude/paperclip/docs/review-checklists.md`.

Steps:
1. Identify the persisted shape change
2. Check company scope and tenant isolation
3. Update schema, migrations, shared types, server logic, and UI consumers
4. Run `pnpm db:generate` → `pnpm typecheck` → tests

$ARGUMENTS
