# PASS76 - Next Top ROI Tranche

## Scope

Completed P14-010 by seeding the next route-consolidation tranche after Daily Brief parity.

## Decision

The next tranche is Trust Audit parity for `/trust-pane`.

Rationale:

- `/mission-control` is redirected and owned by Command Center operations.
- `/today` is demoted with compact Daily Brief facts in Command Center and detailed chart/context retained as a drilldown.
- `/trust-pane` is the remaining broad operator route named in the route-consolidation plan.
- Trust Audit parity should focus on compact provenance, edge-ledger, bar-quality, and post-trade audit facts without folding dense diagnostic detail into Command Center.

## Seeded Tasks

| Task | Status | ROI |
|---|---|---|
| P15-001 | ready | Rank Trust Audit parity tranche. |
| P15-002 | blocked | Audit `/trust-pane` first-screen facts. |
| P15-003 | blocked | Add explicit live/static provenance summary. |
| P15-004 | blocked | Strengthen bar-quality summary. |
| P15-005 | blocked | Strengthen edge-ledger summary. |
| P15-006 | blocked | Add post-trade audit handoff. |
| P15-007 | blocked | Add Trust Audit summary regression tests. |
| P15-008 | blocked | Update route-consolidation docs for Trust Audit parity. |
| P15-009 | blocked | Run static evidence. |
| P15-010 | blocked | Record browser evidence gate or run after disk recovery. |
