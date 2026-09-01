# Pass 13 - Command Center Tickets

Date: 2026-09-01

## Scope

This pass converted the Command Center information architecture into concrete implementation tickets.

## Created

- `COMMAND_CENTER_IMPLEMENTATION_TICKETS_2026-09-01.md`

## Ticket Set

| Ticket | Surface | Primary Acceptance |
|---|---|---|
| CC-001 | Canonical shell | `/command-center` renders all core regions without requiring engine uptime. |
| CC-002 | Status strip | Engine, broker, safety, and data health render as independent states. |
| CC-003 | Trade queue | Approval, position, stale-stop, and journal states are unified without duplicate unsafe actions. |
| CC-004 | Eligibility | Adopted, paused, failed, stale, and research-only states are distinct. |
| CC-005 | Strategy ledger | Family, rank, latest verdict, freshness, state, and next gate are visible. |
| CC-006 | Data integrity | Cache age, provider status, bar freshness, and source parity are visible. |
| CC-007 | Research intake | PRs, issues, experiments, and spikes remain intake, not readiness. |
| CC-008 | Route consolidation | `/mission-control`, `/today`, and `/trust-pane` are merged or demoted after canonical panels exist. |
| CC-009 | API proxy contract | Browser calls route through `dashboard/lib/api.ts` and `/api/engine/*`; guards pass. |
| CC-010 | Acceptance harness | Offline/degraded states and unsafe-action disablement are covered by tests. |

## Backlog Impact

- P6-010 can be marked done.
- P7 should start with CC-001/CC-002 because they create the canonical shell and status strip that every downstream panel depends on.
