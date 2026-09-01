# Pass 21 - Next Top ROI Tranche

Date: 2026-09-01

## Scope

The P7 Command Center backlog is fully drained. This pass seeded the next ten recommended tasks for the loop.

## Ranking Logic

The next tranche prioritizes work that reduces fragility from the new Command Center surface:

- keep the page maintainable after the P7 additions
- move state derivation into testable units
- repair the broader dashboard test typecheck blocker
- make isolated E2E verification repeatable without generated-file churn
- replace placeholder panel claims with backend contracts before the UI presents stronger readiness language

## New Tasks

| Task | Status | Why It Is High ROI |
|---|---|---|
| P8-001 | ready | Reduces risk from the large `/command-center` page before more panels are added. |
| P8-002 | blocked | Locks state derivation behavior after component extraction. |
| P8-003 | ready | Restores the broader dashboard test typecheck gate. |
| P8-004 | ready | Prevents fixture drift across duplicated Command Center/root-route tests. |
| P8-005 | ready | Makes isolated E2E verification repeatable without touching production `.next`. |
| P8-006 | blocked | Adds visual/responsive proof once the isolated runner exists. |
| P8-007 | ready | Defines data-integrity backend contracts before UI claims become stronger. |
| P8-008 | blocked | Removes front-end inference from strategy-ledger next-gate/freshness display. |
| P8-009 | ready | Turns research intake from static placeholders into a real source contract. |
| P8-010 | blocked | Consolidates duplicate routes only after the canonical panels have stronger data and visual proof. |

## Next Ready Item

P8-001 is the highest-ROI ready task.
