# Command Center Implementation Tickets

Date: 2026-09-01

Source specs:

- `JARVIS_MASTER_IMPLEMENTATION_PLAN_V1.md`
- `PASS5_PR749_AND_COMMAND_CENTER_MAPPING_2026-09-01.md`
- `RUNTIME_SURFACE_INVENTORY_2026-09-01.json`

## CC-001 Canonical Shell

Goal: make `/command-center` the first-screen operator shell.

Files:

- `dashboard/app/command-center/page.tsx`
- `dashboard/components/*`
- `dashboard/lib/api.ts`

Engine dependencies:

- `/health`
- `/ws/status`
- `/system/data-integrity`

Empty/degraded states:

- Engine unreachable.
- Dashboard proxy reachable but engine proxy failing.
- Data-integrity endpoint unavailable.

Unsafe-action gates:

- No trade action buttons on the shell until queue-specific backend contracts are loaded.
- Paper/live mode must be visible before any order-capable panel renders.

Acceptance:

- `/command-center` renders health, trade queue, eligibility, strategy ledger, data integrity, and research intake regions without requiring engine uptime.

## CC-002 Status Strip

Goal: expose engine, broker, paper/live mode, kill-switch, and data-freshness state as persistent operator context.

Files:

- `dashboard/app/command-center/page.tsx`
- `dashboard/app/health/page.tsx`
- `dashboard/app/data-integrity/page.tsx`

Engine dependencies:

- `/health`
- `/system/data-integrity`
- `/safety/status`

Empty/degraded states:

- `ECONNREFUSED 127.0.0.1:8010`.
- Missing broker state.
- Data freshness unknown.

Unsafe-action gates:

- Never collapse partial failures into a green aggregate state.
- Live port `4001` must not be treated as an expected healthy endpoint.

Acceptance:

- Status strip shows independent health chips for engine, broker, safety, and data; each chip has an explicit unknown/offline state.

## CC-003 Trade Queue Panel

Goal: unify pending approvals, open paper positions, stale stop risk, and recent order-path errors.

Files:

- `dashboard/app/command-center/page.tsx`
- `dashboard/app/trades/page.tsx`
- `dashboard/app/trades/pending-approvals/page.tsx`
- `dashboard/app/trades/journal/page.tsx`

Engine dependencies:

- `/portfolio/paper/*`
- `/trades/*`
- `/paper/*`
- `/approval/*`

Empty/degraded states:

- No pending approvals.
- No open paper positions.
- Trade journal schema unavailable.
- Approval backend unavailable.

Unsafe-action gates:

- Approve/reject/close operations require explicit user action and backend idempotency keys.
- No optimistic order-path success state without backend confirmation.

Acceptance:

- Queue panel can render zero-state, degraded-state, and populated-state data without duplicate order actions across routes.

## CC-004 Eligibility Panel

Goal: show approved paper gates, failed gates, stale verdicts, and validation freshness.

Files:

- `dashboard/app/command-center/page.tsx`
- `dashboard/app/trading-eligibility/page.tsx`
- `dashboard/app/validation/page.tsx`

Engine dependencies:

- `/paper/validation/approved-paper-gates`
- `/validation/*`
- `/readiness/*`
- `engine/data/gate_v2_verdicts/*.json` via backend surfaces only

Empty/degraded states:

- No approved gates.
- Stale verdict artifact.
- Validation endpoint unavailable.

Unsafe-action gates:

- Strategy promotion requires a current certification artifact.
- UI cannot offer manual override unless backend exposes audited override.

Acceptance:

- Eligibility panel distinguishes adopted, paused, failed, stale, and research-only strategies.

## CC-005 Strategy Ledger Panel

Goal: present strategy provenance and adoption state without conflating research spikes with deployable systems.

Files:

- `dashboard/app/command-center/page.tsx`
- `dashboard/app/strategy-ledger/page.tsx`
- `dashboard/app/research-log/page.tsx`

Engine dependencies:

- `/strategies/*`
- `/strategy-ledger/*`
- `/analytics/*`
- `/experiments/*`

Empty/degraded states:

- No adopted strategies.
- Research ledger unavailable.
- Strategy artifact missing.

Unsafe-action gates:

- Research-only PRs and branches must remain visually separate from approved paper/live readiness.

Acceptance:

- Ledger shows strategy family, rank, latest verdict, freshness, state, and next required gate.

## CC-006 Data Integrity Panel

Goal: make stale cache, provider, source parity, and bar-quality failures first-class.

Files:

- `dashboard/app/command-center/page.tsx`
- `dashboard/app/data-integrity/page.tsx`

Engine dependencies:

- `/system/data-integrity`
- `/cache/*`
- `/prices/*`

Empty/degraded states:

- Provider offline.
- Cache freshness unknown.
- No current price anchor.

Unsafe-action gates:

- Trade enablement is blocked when data is stale or provenance is unknown.

Acceptance:

- Data integrity panel exposes cache age, provider status, bar freshness, and source parity with explicit stale/unknown states.

## CC-007 Research Intake Panel

Goal: make open PRs, issues, experiments, and candidate backlog visible as intake, not readiness.

Files:

- `dashboard/app/command-center/page.tsx`
- `dashboard/app/research-log/page.tsx`

Engine dependencies:

- `/experiments/*`
- `/discovery/*`
- `/analytics/*`

Empty/degraded states:

- No open research items.
- Experiment ledger unavailable.
- GitHub/PR metadata unavailable.

Unsafe-action gates:

- Research spikes cannot change strategy readiness state directly.

Acceptance:

- Research intake groups PRs/issues/spikes by keep, split, replace, reference, or retire-to-archive.

## CC-008 Route Consolidation

Goal: remove competing first-screen command surfaces by merging or demoting overlap.

Files:

- `dashboard/app/mission-control/page.tsx`
- `dashboard/app/today/page.tsx`
- `dashboard/app/trust-pane/page.tsx`
- `dashboard/app/command-center/page.tsx`

Engine dependencies:

- Same dependencies as panels moved into `/command-center`.

Empty/degraded states:

- Legacy route viewed directly.
- Merged panel dependency unavailable.

Unsafe-action gates:

- Legacy surfaces must not expose stronger readiness or action affordances than `/command-center`.

Acceptance:

- `/mission-control`, `/today`, and `/trust-pane` either redirect, link, or clearly demote to reference panels once their canonical content exists in `/command-center`.

## CC-009 API Proxy Contract

Goal: ensure browser-side engine calls use `dashboard/lib/api.ts` and `/api/engine/*`.

Files:

- `dashboard/lib/api.ts`
- `dashboard/app/api/engine/[...path]/route.ts`
- Command Center panel components

Engine dependencies:

- All panel dependencies through the dashboard proxy.

Empty/degraded states:

- Proxy reachable, engine unreachable.
- Proxy error with structured backend detail.

Unsafe-action gates:

- No direct browser calls to `127.0.0.1:8010`.
- No bare fetch outside approved wrapper.

Acceptance:

- `pnpm run guards` passes after Command Center implementation.

## CC-010 Acceptance Harness

Goal: prove the Command Center can render offline/degraded states and does not regress static quality gates.

Files:

- `dashboard/tests/*`
- `dashboard/scripts/check-guards.mjs`
- Command Center panel tests

Engine dependencies:

- Mocked proxy responses for health, trade queue, eligibility, strategy ledger, data integrity, and research intake.

Empty/degraded states:

- Engine offline.
- Partial endpoint failure.
- Empty data.

Unsafe-action gates:

- Tests must assert unsafe actions are disabled until backend contracts and idempotency keys are present.

Acceptance:

- `pnpm run guards`, `pnpm run typecheck`, and the focused Command Center test slice pass.
