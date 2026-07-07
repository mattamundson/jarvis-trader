# Change playbooks

Use the playbook that matches the task.

## 1. Repo orientation / explain the codebase

1. Read `.claude/paperclip/docs/repo-map.md`.
2. Classify the target area.
3. Explain the smallest useful subset first.
4. Show likely file/package touchpoints.
5. Call out invariants if the question implies a change.

## 2. Bug investigation

1. Identify the failing layer: DB / server / shared / UI / adapter / plugin
2. Trace the request/data path across adjacent layers.
3. Look for:
   - company-scope leaks
   - stale shared validators/types
   - UI assumptions drifting from API output
   - silent error handling
   - budget/approval side effects on mutated actions
4. Propose the narrowest fix that restores invariants.
5. Validate with `review-checklists.md`.

## 3. Add or change a DB field

1. Edit `packages/db/src/schema/*.ts`
2. Export from `packages/db/src/schema/index.ts`
3. `pnpm db:generate`
4. Update `packages/shared` types/validators/constants
5. Update `server` read/write logic
6. Update `ui` consumers/forms/displays
7. Update docs if the field changes behavior, workflow, or setup
8. Run `pnpm typecheck` and `pnpm test`

## 4. Add or change an API route

1. Confirm the route is company-scoped where appropriate.
2. Define/update request/response contracts in `packages/shared`.
3. Update server route + service implementation.
4. Check for activity logging, approvals, auth, and budget implications on mutating actions.
5. Update UI callers and error handling.
6. Update docs if public or operator-facing behavior changed.

## 5. UI feature or fix

1. Confirm the backing API and shared contract already support it.
2. Keep navigation/routes aligned with actual API surface.
3. Preserve company selection context for company-scoped pages.
4. Surface failures clearly.
5. If UI change reveals a contract mismatch, fix the contract deliberately — don't patch around it.

## 6. Adapter change

1. Identify the adapter package(s) involved.
2. Map the change across: execution model, config shape, heartbeat integration, server integration, UI status/config surfaces, CLI integration.
3. Preserve runtime agnosticism — Paperclip orchestrates; it does not become the runtime.
4. Check `packages/adapter-utils/` for shared helpers.
5. Update server orchestration assumptions if the adapter's execution contract changed.
6. Verify adapter-facing docs/examples are accurate.

## 7. Plugin change

1. Distinguish core vs. plugin placement:
   - Core: needed by everyone, always-on, fundamental to control-plane guarantee
   - Plugin: optional, environment-specific, tenant/project-specific
2. Check `packages/plugins/` for the SDK and example usage.
3. Preserve host/plugin contract boundaries.
4. Confirm workspace/path behavior is correct.
5. Update public-facing docs/examples if the plugin API changed.

## 8. Release / packaging / dev-env

1. Start with the smallest reproducible path.
2. Distinguish local-dev assumptions from packaged/release assumptions.
3. Check `scripts/` for relevant automation.
4. Preserve onboarding experience — fresh `pnpm install && pnpm dev` should still work.
5. Test against both embedded PGlite and Docker Postgres if DB-layer is involved.

## 9. Documentation update

1. Read the existing doc before editing.
2. Prefer additive updates over rewrites.
3. Keep `doc/SPEC.md` and `doc/SPEC-implementation.md` aligned.
4. New plans → `doc/plans/YYYY-MM-DD-slug.md`.
5. Verify any commands or workflows mentioned are accurate.
