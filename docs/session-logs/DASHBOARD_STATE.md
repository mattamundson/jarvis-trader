# JARVIS Dashboard State

_Last updated: 2026-09-03 04:38 CDT_

**Incident severity:** `AMBER` — runtime is currently healthy and authenticated on `:3010`, but canonical dashboard Git authority remains drifted. A clean master-based authority candidate now exists and is verified; serving cutover is not yet executed.

## Runtime truth
- `jarvis-dashboard`: PM2 online on local port `3010` behind Basic Auth.
- `jarvis-engine`: PM2 online on local port `8010`.
- Authenticated `/mission-control`: `200`.
- Authenticated `/api/runtime-snapshot`: `200`, `contract=true`.
- Deployed runtime remains paper-safe: no live engine/risk/kill-switch config changes were made in this tranche.

## Authority state
- Canonical serving tree: `C:/Users/mattm/ThinkorSwim/jarvis-trader`
  - status rows: `1939`
  - deleted: `1885`
  - modified: `26`
  - untracked: `28`
  - branch: `master`
  - head: `99d75f31`
  - build failure observed: `ENOTEMPTY ... dashboard\\.next\\export`
- Clean authority candidate: `C:/Users/mattm/ThinkorSwim/jarvis-authority-master-20260903`
  - branch: `feat/canonical-authority-cutover-20260903`
  - base: merged master `99d75f31`
  - replayed runtime-snapshot tranche commits: `3b2e0b3c`, `636ce656`, `2a52111c`, `a644512e`, `31140488`

## Verification completed this tranche
1. `pnpm install --frozen-lockfile` in authority candidate dashboard → PASS.
2. `./node_modules/.bin/tsc --noEmit && pnpm run build` in authority candidate dashboard → PASS.
3. `pnpm exec playwright test --config=playwright.fresh.config.ts tests/e2e/mission-control-runtime-snapshot.spec.ts` in authority candidate dashboard → PASS (`2 passed`).
4. `pm2 status jarvis-dashboard` + authenticated live `/mission-control` and `/api/runtime-snapshot` on canonical `:3010` → PASS.

## Current degradations
- Canonical serving tree remains serving-but-non-authoritative.
- In-place canonical builds are not trustworthy due to `.next` lifecycle corruption.
- MES enabled/non-tradeable disagreement remains visible in runtime truth and is not resolved here.

## Recommended next tranche
Preserve canonical deploy-only artifacts and audit PM2 binding so the next step can be a low-risk serving cutover from the drifted canonical tree to the verified authority candidate.
