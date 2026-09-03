# Canonical Dashboard Authority Cutover — 2026-09-03

## Objective
Move from a **serving-but-non-authoritative** canonical dashboard tree to a **serving + git-authoritative** dashboard path without touching live engine/risk/kill-switch behavior.

## Current truth
- Canonical serving tree: `C:/Users/mattm/ThinkorSwim/jarvis-trader`
- Canonical runtime state: PM2 `jarvis-dashboard` online on `:3010`
- Canonical auth surface: authenticated `/mission-control` and `/api/runtime-snapshot` return `200`
- Canonical git status: `1939` rows (`1885 D / 26 M / 28 ??`)
- Canonical build failure observed: `ENOTEMPTY ... dashboard\\.next\\export`
- Clean authority candidate: `C:/Users/mattm/ThinkorSwim/jarvis-authority-master-20260903`
- Authority candidate branch: `feat/canonical-authority-cutover-20260903`
- Authority candidate base: merged master `99d75f31`
- Replayed commits on authority candidate:
  1. `3b2e0b3c` source-integrity evidence
  2. `636ce656` runtime contract drift checks
  3. `2a52111c` deployed-auth smoke
  4. `a644512e` stale snapshot warnings
  5. `31140488` canonical-tree classification

## Authority-candidate verification
- `pnpm install --frozen-lockfile` → PASS
- `./node_modules/.bin/tsc --noEmit && pnpm run build` → PASS
- `pnpm exec playwright test --config=playwright.fresh.config.ts tests/e2e/mission-control-runtime-snapshot.spec.ts` → PASS (`2 passed`)

## Cutover principles
1. Do **not** repair `.git` in place in the serving tree while PM2 depends on it.
2. Preserve deploy-only and secret-bearing artifacts; never delete.
3. Cut runtime from a verified authority lane, not from a drifted serving lane.
4. Do not mix dashboard cutover with engine/risk/killswitch mutation.

## Required preservation inventory before cutover [RISK]
- `dashboard/.env.local` (secret-bearing; single-writer)
- any PM2 cwd/script assumptions for `jarvis-dashboard`
- current canonical `.next` serving artifact
- canonical `.git` directory
- runtime logs and local operational notes under the canonical tree

## Lowest-risk cutover sequence
1. Verify PM2 + authenticated `:3010` are green immediately before action.
2. Archive canonical artifacts:
   - archive canonical `.git`
   - archive canonical `dashboard/.next`
   - archive any deploy-only dashboard files that do not belong to Git authority
3. In the authority candidate path, ensure `dashboard/.env.local` is present by secure local copy from canonical path if required. Do not commit it.
4. Re-run authority-candidate verification:
   - `tsc --noEmit`
   - `pnpm run build`
   - fresh Playwright runtime snapshot spec
5. Rebind PM2 dashboard serving to the authority-candidate path, not by rewriting canonical `.git` in place.
6. Verify after cutover:
   - `pm2 status jarvis-dashboard`
   - authenticated `GET /mission-control`
   - authenticated `GET /api/runtime-snapshot`
   - deployed-auth Playwright smoke on `:3010`
7. Only after successful cutover, decide whether the old canonical tree becomes a permanent archived serving snapshot or a later cleanup target.

## Explicit non-goals
- no `git reset --hard` in canonical serving tree
- no blind `.git` recreation in canonical serving tree
- no engine restart unless independently required
- no safety/risk config change

## Rollback
If the PM2 rebind fails, restore the last known-good canonical `.next` and PM2 target from the archived artifacts, then re-verify authenticated `:3010` endpoints.

## Recommended next action
Perform the preservation-inventory capture and PM2 binding audit, then prepare the exact cutover command set without executing it yet.
