# PASS78 - Trust Audit Compact Summary

## Scope

Completed P15-003 through P15-007 by strengthening the Command Center Trust Audit summary and its regression coverage.

## Changes

- Added explicit `Provenance` row: `live`, `partial`, or `unknown` based on health, bar-quality, and edge-ledger availability.
- Strengthened `Bar Rejects` detail to include gate status and window hours.
- Strengthened `Edge Ledger` detail to include PASS and FAIL counts.
- Added `Post-Trade` handoff row pointing to `/trust-pane` execution and quality diagnostics.
- Expanded Trust Audit summary layout from four to six compact rows.
- Updated node tests for populated and unavailable Trust Audit evidence.

## Evidence

```powershell
pnpm run typecheck
pnpm run typecheck:tests
pnpm run guards
node --test --experimental-strip-types --import ./tests/_register-alias.mjs tests/commandCenterState.node.test.ts
```

Results:

- Dashboard typecheck passed.
- Test typecheck passed.
- Dashboard guards passed.
- Command Center state node tests passed with 12 tests.
