# O-02 — Verification Matrix and Evidence Ladder

**Plan:** JARVIS-MIP-1.0  
**Program:** O — Delivery, Verification & Governance  
**Phase:** MIP-0  
**Safety class:** S0 document with S1–S4 enforcement implications  
**State:** **DRAFT COMPLETE — ADOPTION BLOCKED BY PR #768 / ISG-0**  
**Depends on:** O-01 CI baseline, A-02/A-03 architecture  
**Required for:** all implementation work packages after MIP-0

## 1. Decision

JARVIS will use a five-rung verification ladder. A work package is not `DONE`, `FINAL`, `PRODUCTION READY`, or eligible for a higher-capital environment unless every required rung has a durable verification receipt or the work package is explicitly marked `BLOCKED`.

A missing verification result is not a pass. A blocked rung is not silently skipped.

## 2. Verification ladder

| Rung | Name | Purpose | Typical evidence |
|---|---|---|---|
| **V0** | Static / Contract | Prove structure, schemas, invariants and forbidden-path rules before execution | parse/schema checks, migration review, safety invariant guard, contract tests, secret scans, dependency-direction checks |
| **V1** | Deterministic Unit / Type / Lint | Prove local deterministic behavior and compilation/type correctness | Ruff, pytest unit slices, TypeScript typecheck, Vitest, deterministic property tests |
| **V2** | Integration / State Machine | Prove cross-module lifecycle, durability and recovery semantics | API integration, DB migration, idempotency, restart/recovery, reconciliation, partial-fill/ambiguous-state tests |
| **V3** | Build / Operator Journey | Prove deployable product behavior and operator-visible contracts | production Next build, route manifest, Playwright, packaged startup, read-model/fail-closed UI journeys |
| **V4** | PAPER Runtime | Prove behavior against an observed runtime and non-capital or broker-paper environment | runtime truth receipt, simulator then real broker PAPER where applicable, broker reconciliation, restart drills, paper metrics |
| **V5** | LIVE Canary | Prove tightly bounded capital behavior after explicit human authorization | tiny-capital canary, policy/version receipt, explicit activation, kill/flatten rehearsal, broker reconciliation, rollback evidence |

V5 is never entered automatically.

## 3. Minimum rung by safety class

| Safety class | Minimum verification | Additional requirements |
|---|---|---|
| **S0** docs/research-only | V0; V1 when executable examples/tools change | evidence links and review |
| **S1** non-trading implementation | V0–V1 | regression tests for changed behavior |
| **S2** state/data/operator behavior | V0–V3 | integration + production-build/operator journey |
| **S3** paper-trading/execution/risk-adjacent | V0–V4 | deterministic safety review, PAPER runtime evidence, rollback/recovery evidence, human safety review |
| **S4** live-capital authorization/execution | V0–V5 | explicit human capital authorization, real broker canary, kill/flatten rehearsal, no autonomous promotion |

A higher class inherits every lower rung.

## 4. Decision-class coupling

- **D0:** design/planning may be accepted with V0 evidence, but does not authorize runtime behavior.
- **D1:** reversible implementation requires the class-specific verification rung.
- **D2:** data/schema migration requires migration + rollback evidence at V2 or higher.
- **D3:** safety/execution policy requires deterministic tests and V4 before PAPER adoption where applicable.
- **D4:** live capital/environment authorization requires V5 and explicit human approval.

## 5. Verification receipt contract

Every receipt must record:

```text
work_package
plan_version
commit_sha
verification_rung
started_at / completed_at
environment_identity
runtime_or_dataset_identity
broker_identity_or_mode (when applicable)
policy/evidence/version hashes (when applicable)
commands/checks executed
result: PASS | FAIL | BLOCKED
artifacts/logs
known limitations
reviewer/approver when required
```

A CI check name alone is not a receipt when environment, commit or relevant test scope is ambiguous.

## 6. Required matrix by domain

| Domain | Required emphasis |
|---|---|
| Architecture/contracts | V0 dependency and schema invariants |
| Instrument Master/data | V0 schema + V1 deterministic calendars/contracts + V2 provider/session integration |
| PIT feature system | V0 availability contract + V1 causal properties + V2 replay/no-lookahead integration |
| Research/Judge | V0 preregistration/evidence schema + V1 statistics + V2 replay/trial-accounting consistency |
| Portfolio/risk | V1 deterministic arithmetic/properties + V2 state integration + V4 PAPER observed limits |
| OMS/execution | V1 state-transition properties + V2 idempotency/restart/ambiguous outcomes + V4 broker PAPER |
| Broker adapter | V2 mocked transport/reconciliation + V4 real broker PAPER where applicable |
| Dashboard/control plane | V1 type/unit + V3 production build/E2E + V4 observed read/command state for execution surfaces |
| Capital Path | V1 deterministic calculations + V2 simulation/replay identities; never substitutes for risk-policy verification |
| LLM/intelligence | V1 contract tests + V2 failure/degradation tests; no safety authority |
| Live promotion | all lower rungs + V5 explicit canary |

## 7. Mandatory safety scenarios

S3/S4 execution work must test, as applicable:

1. kill switch engaged;
2. stale/unknown/ambiguous quote;
3. broker disconnected;
4. account state unavailable;
5. reconciliation mismatch;
6. duplicate command/idempotency collision;
7. process restart during lifecycle;
8. ambiguous broker acknowledgement;
9. partial fill;
10. protective-order failure;
11. risk budget supports zero units;
12. changed policy/evidence version between preview and submit;
13. environment authorization mismatch;
14. cancel/reduce/flatten availability under degraded conditions.

## 8. CI versus runtime evidence

CI is necessary but not sufficient for S3/S4. Hosted CI cannot prove the operator's loaded `.env`, running IB account/session, local DB identity, TWS state or actual broker-paper connectivity. Those facts belong to A-01/V4 runtime receipts.

Conversely, a successful local PAPER run does not waive static/unit/build failures.

## 9. Evidence retention

- GitHub Actions logs are linked by run/job ID.
- Durable reports belong under `docs/evidence/` or an explicitly referenced immutable artifact location.
- Runtime snapshots must exclude secrets.
- Research receipts include dataset/feature/trial/evidence hashes.
- Broker receipts redact account identifiers while preserving a stable alias/fingerprint sufficient to distinguish environments.

## 10. Failure semantics

- `FAIL` means the work package is not done.
- `BLOCKED` means a required external fact/environment is unavailable and the work package remains open.
- flaky/red-on-rerun is not converted to pass without root-cause evidence.
- pre-existing failures must be demonstrated on a baseline commit and tracked; they do not permit new failures.
- verification scope may be ratcheted upward but not silently weakened.

## 11. O-01 baseline ratchet

Once O-01 records a clean required CI baseline on current master, that result becomes the minimum ratchet:

- new work may not introduce new required-check failures;
- known quarantines/skips must remain explicit;
- test-count changes are reviewed for accidental deselection;
- safety invariant and secret-scanning checks remain independent of ordinary unit suites;
- workflow changes require O-05 metadata/governance review and must not execute untrusted PR code through privileged events.

## 12. Acceptance criteria

- [x] Verification rungs V0–V5 are defined.
- [x] Safety classes map to minimum rungs.
- [x] Runtime evidence is distinguished from CI evidence.
- [x] S3/S4 mandatory adverse scenarios are enumerated.
- [x] Durable receipt fields are defined.
- [x] `BLOCKED` cannot masquerade as `PASS`.
- [x] No autonomous V5/live promotion is permitted.
- [ ] O-01 exact current-master receipt finalized.
- [ ] PR #768 adopted.
- [ ] Human review marks this matrix adopted.

## 13. Decision status

**Draft decision:** ACCEPTED FOR REVIEW.  
**Enforcement authority:** not effective until adopted.  
**Live authorization:** none.
