# PASS31 - Route Consolidation Plan

## Scope

- Completed backlog task `P8-010`.
- Defined concrete keep/merge/demote/redirect actions for `/mission-control`, `/today`, and `/trust-pane`.
- Kept the work docs-only because immediate redirects would hide still-unique safety and diagnostic surfaces.

## Files

- `docs/plans/master-implementation/COMMAND_CENTER_ROUTE_CONSOLIDATION_PLAN_2026-09-01.md`
  - Establishes `/command-center` as the canonical first-screen operator shell.
  - Assigns final route state and risk notes for `/mission-control`, `/today`, and `/trust-pane`.
  - Lists the panel/fact migration checklist needed before redirects.
  - States nav policy and archive policy.
- `docs/plans/master-implementation/IMPLEMENTATION_BACKLOG.json`
  - Marks `P8-010` done.

## Validation

- Reviewed `dashboard/app/mission-control/page.tsx`.
- Reviewed `dashboard/app/today/page.tsx`.
- Reviewed `dashboard/app/trust-pane/page.tsx`.
- Reviewed prior Command Center route disposition in `PASS5_PR749_AND_COMMAND_CENTER_MAPPING_2026-09-01.md`.
- Verified the backlog JSON parses.
- Verified the touched documentation has no whitespace errors with `git diff --check`.

## Next Task

- Seed the next high-ROI tranche from this plan:
  - route drilldown links,
  - mission-control panel migration,
  - daily-brief summary extraction,
  - trust summary extraction,
  - redirect/parity tests.
