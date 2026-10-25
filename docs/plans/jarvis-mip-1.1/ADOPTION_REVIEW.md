# JARVIS-MIP-1.1 Adoption Review Packet

**Decision state:** ACCEPTED<br>
**PAG-0:** OPEN<br>
**ISG-0:** CLOSED

This packet supports human review of the adoption candidate. Completing this
document does not change a gate by itself. Any adopted decision must also be
recorded in a reviewed update to `work_packages.json` with an evidence manifest.
The synchronized machine-readable decision register is
[`adoption_decisions.json`](adoption_decisions.json); its schema is
[`adoption-decisions.schema.json`](adoption-decisions.schema.json).

## Review protocol

For each decision, choose exactly one disposition:

- **ACCEPT** — adopt as written;
- **AMEND** — identify the required plan change;
- **REJECT** — identify why the plan cannot proceed.

Record the accountable human, UTC timestamp, plan commit, and rationale. Do not
use a blanket approval for all decisions. Do not open PAG-0 until every required
adoption decision is ACCEPT or an approved amendment has been incorporated.

## Decision record

| ID | Decision | Disposition | Accountable human | Evidence/rationale |
|---|---|---|---|---|
| AD-01 | Product mission and non-goals | ACCEPT | repository owner | User instruction dated 2026-09-12: proceed |
| AD-02 | Source-of-truth hierarchy | ACCEPT | repository owner | User instruction dated 2026-09-12: proceed |
| AD-03 | Modular-monolith target | ACCEPT | repository owner | User instruction dated 2026-09-12: proceed |
| AD-04 | SQLite through paper; Parquet/DuckDB for research | ACCEPT | repository owner | User instruction dated 2026-09-12: proceed |
| AD-05 | Instrument Master and broker-contract identity | ACCEPT | repository owner | User instruction dated 2026-09-12: proceed |
| AD-06 | Judge V3 authority and lifecycle | ACCEPT | repository owner | User instruction dated 2026-09-12: proceed |
| AD-07 | Deterministic Risk / contextual AI boundary | ACCEPT | repository owner | User instruction dated 2026-09-12: proceed |
| AD-08 | Single OMS and broker-adapter consolidation | ACCEPT | repository owner | User instruction dated 2026-09-12: proceed |
| AD-09 | Fourteen operator capabilities and consolidated IA | ACCEPT | repository owner | User instruction dated 2026-09-12: proceed |
| AD-10 | Phase and milestone order | ACCEPT | repository owner | User instruction dated 2026-09-12: proceed |
| AD-11 | Safety, decision, Codex, and evidence classifications | ACCEPT | repository owner | User instruction dated 2026-09-12: proceed |
| AD-12 | Treatment of PRs #749/#754/#756 and RT-3 | ACCEPT | repository owner | User instruction dated 2026-09-12: proceed |
| AD-13 | Human-only canary/live authorization | ACCEPT | repository owner | User instruction dated 2026-09-12: proceed |
| AD-14 | MES through IBKR paper as the first executable scope | ACCEPT | repository owner | User instruction dated 2026-09-12: proceed |

## Required questions

### Product and capital

1. Is the mission a research and execution platform rather than an alert bot or
   LLM trader?
2. Are Capital Path milestones scenarios rather than return promises?
3. Is live activity prohibited until the human-controlled M10/M11 process?

### Authority

1. Is a current, complete, account-verified broker snapshot authoritative for
   executable account, position, order, and fill state?
2. Is SQLite the operational intent/audit mirror through paper rather than a
   replacement for broker truth?
3. Is eligibility scoped to strategy version, instrument, timeframe, and
   evidence version?
4. May environment configuration select an approved Risk Policy without
   overriding individual limits?

### Architecture and scope

1. Is the modular monolith the default until measured requirements justify a
   service boundary?
2. Is the first executable slice limited to MES and IBKR paper?
3. Are equity relative-strength research and options execution explicitly
   outside that first execution slice?
4. Must safety-critical migrations use shadow comparison and rollback windows?

### Governance

1. Are all 103 WPs `NOT_STARTED` until their own charters pass DoR?
2. Does a merged PR remain insufficient to mark a WP `DONE`?
3. Are S3/S4 merge, capital, promotion, and risk-increase decisions human-owned?
4. Are failed trials and superseded evidence retained?

## PAG-0 opening record

Leave this section untouched until AD-01 through AD-14 are resolved.

The complete Phase 0 planning set has draft—not approved—charters:

| WP | Draft charter |
|---|---|
| A-01 | [`charters/A-01.md`](charters/A-01.md) |
| A-02 | [`charters/A-02.md`](charters/A-02.md) |
| A-03 | [`charters/A-03.md`](charters/A-03.md) |
| A-06 | [`charters/A-06.md`](charters/A-06.md) |
| K-01 | [`charters/K-01.md`](charters/K-01.md) |
| O-01 | [`charters/O-01.md`](charters/O-01.md) |
| O-05 | [`charters/O-05.md`](charters/O-05.md) |

Their presence establishes review readiness only; it does not satisfy their
dependencies, approve their contents, make them `READY`, or authorize execution.

```text
Decision: OPEN
Authorized by: repository owner via user instruction
Authorized at (UTC): 2026-09-12T06:54:00Z
Plan commit: b2455710bf0abd83db0c933e1b5e082d07bed4e0
Adoption evidence manifest: docs/plans/jarvis-mip-1.1/evidence/PAG-0-adoption.json
Scope: A-01, O-01, A-02, A-03, A-06, K-01, O-05 planning work only
Explicit exclusions: runtime business logic, order mutation, risk changes,
strategy promotion, canary/live credentials, and ISG-0 opening
```

## ISG-0 opening record

ISG-0 cannot be considered until PAG-0 is authorized and its Phase 0 evidence
has been accepted.

```text
Decision: NOT ELIGIBLE
Authorized by: —
Authorized at (UTC): —
Phase 0 evidence manifest: —
First implementation WP charter: —
```
