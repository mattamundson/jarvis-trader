# PASS51 - Sidebar Route Consolidation

Date: 2026-09-01
Backlog item: P10-008

## Scope

Aligned the dashboard sidebar with the Command Center consolidation policy:

- Added a primary `Command` nav group with `Command Center` as the canonical entry.
- Demoted `/today`, `/mission-control`, and `/trust-pane` into smaller Command drilldown links.
- Removed duplicate primary sidebar entries for Dashboard, Today at a Glance, Mission Control, Trust Pane, and the duplicate Command Center link.
- Added route consolidation E2E coverage for the sidebar contract.

## Evidence

Validation commands:

```powershell
pnpm run typecheck
pnpm run guards
pnpm run test:e2e:isolated -- tests/e2e/command-center-route-consolidation.spec.ts --project=golden-path --workers=1
```

Results:

- `pnpm run typecheck` passed.
- `pnpm run guards` passed.
- Isolated E2E passed: 5 tests passed on `golden-path`.

## Notes

The first isolated E2E attempt failed before assertions because C: had no writable build space. Package-manager cache pruning freed enough space, and the same focused test then passed.
