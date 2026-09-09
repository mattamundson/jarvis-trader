# O-02 — Verification Matrix and Evidence Ladder

**Parent product candidate:** `JARVIS-MPP-1.0` (#789 / GOV-01 #791)  
**Program:** O — Delivery & Engineering System  
**Phase:** Phase 0 / ISG-0 design  
**Safety class:** S0 document with S1–S4 enforcement implications  
**State:** **DRAFT CURRENT-MASTER REFRESH — NOT ADOPTED**  
**Observed repository baseline:** `master@6afe8970b8a588a3b67131d960fe47bee6fa40cf`  
**Current CI infrastructure blocker:** O-CI-001 / #790  
**Required for:** implementation, migration, PAPER qualification, and capital-promotion evidence

## 1. Decision

JARVIS will use verification rungs **V0–V5**. A capability may claim only the highest rung for which the required evidence actually executed successfully on the relevant source/runtime identity.

A missing result is not a pass. A blocked rung is not silently skipped. A workflow job created by GitHub but never assigned a runner and never executing a step is **CI-INFRA / NO VALIDATION EXECUTED**.

`MERGED`, `DEPLOYED`, `ADOPTED`, `VALIDATED`, `PAPER-QUALIFIED`, and `LIVE-AUTHORIZED` remain distinct states.

## 2. Verification ladder

| Rung | Name | Purpose | Representative evidence |
|---|---|---|---|
| **V0** | Static integrity | Prove schemas, dependency boundaries, forbidden paths, source/config invariants | parsing/schema checks, secret scan, safety/config guards, manifest and migration review |
| **V1** | Component | Prove deterministic unit/component behavior on an exact candidate head | Ruff, compile/typecheck, focused pytest, Node/Vitest/unit tests, deterministic properties |
| **V2** | Integration / replay | Prove composed modules, persistence, state machines, migrations, replay, restart/recovery | API/DB integration, idempotency, restart, parity, reconciliation, ambiguous-state drills |
| **V3** | Operator E2E | Prove deployable operator workflows and visible degraded/failure semantics | production Next build, route census, Playwright/E2E, source→API→render assertions |
| **V4** | PAPER runtime | Prove behavior against observed PAPER runtime/broker/data conditions | Windows/TWS runtime receipt, real IB PAPER where applicable, reconciliation and failure drills |
| **V5** | LIVE canary | Prove explicitly authorized bounded real-capital behavior | scoped canary authorization, independent broker truth, kill/flatten rehearsal, reconciliation |

V5 is evidence under explicit capital authorization; it is never an automatic promotion mechanism.

## 3. Minimum evidence by safety class

| Safety class | Minimum evidence before adoption/use | Additional boundary |
|---|---|---|
| **S0** docs/research design | V0 | human review where the artifact becomes governance |
| **S1** inert contracts/tests/read models | V0–V1 | exact-head deterministic evidence |
| **S2** stateful non-capital behavior / migrations | V0–V3 | integration, rollback, operator/error-state evidence |
| **S3** risk/safety/broker/PAPER mutation | V0–V4 | independent safety review + restart/reconciliation/broker PAPER evidence as applicable |
| **S4** LIVE-capital authority/exposure expansion | V0–V5 | explicit human capital authorization and bounded canary scope |

Higher classes inherit lower-rung requirements.

## 4. Exact-head evidence rule

Every repository validation receipt must bind to the exact candidate SHA.

A receipt records at minimum:

```text
work_package
plan/product version
commit_sha
verification_rung
environment / runner identity
started_at / completed_at
commands or checks executed
result: PASS | FAIL | BLOCKED | CI-INFRA
artifacts/logs/run IDs
known limitations
reviewer/approver where required
```

For runtime/broker evidence also record, in redacted form:

```text
runtime commit/worktree identity
runtime mode/environment
broker mode/connector identity
policy/evidence versions
dataset/account aliases or fingerprints
reconciliation result
```

A check name or red/green icon without execution details is insufficient when runner/runtime identity is uncertain.

## 5. CI infrastructure classification

GitHub-hosted validation is currently affected by O-CI-001 (#790). Recent exact-head jobs have been created with `steps=[]`/`runner_id=0` and downstream jobs skipped.

Such a result is classified:

> **CI-INFRA / NO VALIDATION EXECUTED**

It is:

- not a code regression;
- not a test pass;
- not V1 credit;
- not a reason to weaken tests or safety gates.

Local verification may supplement the record but does not replace a required hosted rung or V4/V5 runtime evidence.

## 6. Required emphasis by domain

| Domain | Evidence emphasis |
|---|---|
| Architecture/contracts | V0 schema/dependency/authority review; V1 executable contract tests when code exists |
| Instrument Master/data | V0 schema/alias rules; V1 deterministic calculations; V2 provider/session/contract parity |
| PIT feature system | V0 availability contract; V1 causal properties; V2 no-lookahead replay |
| Research/Judge | preregistration/trial identity, deterministic stats, replay/trial accounting, OOS/cost robustness |
| Portfolio/risk | V1 arithmetic/properties; V2 state/restart; V4 observed PAPER limits where used for execution |
| OMS/execution | V1 transition properties; V2 idempotency/restart/partial/ambiguity/reconciliation; V4 real PAPER |
| Broker adapter | V2 transport/reconciliation simulations; V4 real broker PAPER for broker claims |
| Operator product | V1 component/type; V3 production build/E2E/degraded states; V4 for integrated broker mutations |
| Capital Path | deterministic/replayable simulation identities; remains advisory unless separately authorized |
| LLM/intelligence | contract/degradation/calibration tests; no deterministic safety or capital authority |
| LIVE promotion | all required lower evidence + V5 + explicit authorization |

## 7. Mandatory S3/S4 adverse scenarios

As applicable, execution/safety work must exercise:

1. kill switch active;
2. stale/unknown/contradictory quote;
3. broker disconnected or identity mismatch;
4. account/equity unavailable;
5. broker/local reconciliation mismatch;
6. duplicate command/idempotency collision;
7. restart before and during submission lifecycle;
8. lost/ambiguous broker acknowledgement;
9. partial fill;
10. incomplete/rejected protective child;
11. risk result of zero / `NO_TRADE`;
12. changed policy/evidence or reduced risk budget between preview and submit;
13. environment/authorization mismatch;
14. persistence failure after possible broker side effect;
15. cancel/reduce/flatten behavior under degraded conditions.

A simulator-only pass does not establish real broker behavior for scenarios whose purpose is broker fidelity.

## 8. CI versus runtime evidence

CI can prove code/static/component/integration behavior in its environment. It cannot prove the operator machine's loaded configuration, running TWS/Gateway, current broker account/mode, local process/port/database, or live freshness.

Those facts belong to A-01 and V4 runtime receipts.

Likewise, an observed local PAPER session cannot waive deterministic source/type/test failures.

## 9. Failure semantics

- `PASS` — required checks executed successfully for the stated rung/scope.
- `FAIL` — checks executed and violated acceptance criteria.
- `BLOCKED` — required external dependency/evidence is unavailable; work remains open.
- `CI-INFRA` — required hosted validation did not execute due to infrastructure/allocation failure.

Flaky failure is not silently converted to pass. Any retry policy must remain visible and the root-cause debt tracked.

Pre-existing failures require baseline evidence; they never authorize new regressions.

## 10. Evidence retention

- GitHub Actions evidence references exact run/job IDs.
- Durable reports belong under `docs/evidence/` or another explicitly referenced immutable location.
- Runtime artifacts exclude secrets.
- Research evidence carries dataset/feature/trial/code identities.
- Broker evidence masks account identifiers while preserving a stable environment/account alias or fingerprint.
- Migration receipts retain old/new authority identities, parity evidence, rollback, and reconciliation state.

## 11. Relationship to O-01 / O-CI-001

O-01 establishes the repository's technical test baseline; O-CI-001 separately tracks whether hosted runners can actually execute it.

Once hosted execution is restored, the current-master required-check result becomes a ratchet:

- no new required-check regressions;
- quarantines/skips remain explicit;
- test-count/deselection changes are reviewed;
- safety/config/secret checks remain independent;
- workflow changes preserve privileged-event threat boundaries.

## 12. Acceptance criteria

- [x] V0–V5 are defined consistently with the proposed MPP.
- [x] Safety classes map to evidence requirements.
- [x] Exact-head receipt fields are explicit.
- [x] Runtime evidence is distinguished from CI evidence.
- [x] Zero-step GitHub failures are classified `CI-INFRA`, not PASS/FAIL.
- [x] S3/S4 adverse scenarios include ambiguity, restart, partial fill, reconciliation, and zero sizing.
- [x] Missing evidence cannot masquerade as success.
- [x] No autonomous V5/LIVE promotion is permitted.
- [ ] GOV-01 parent hierarchy explicitly adopted/revised.
- [ ] O-CI-001 restored sufficiently for required hosted jobs to execute.
- [ ] Human governance review marks O-02 `ADOPTED` with effective SHA.

## 13. Decision status

**Draft decision:** READY FOR REVIEW.  
**Enforcement authority:** NOT EFFECTIVE.  
**PAPER/LIVE/capital authorization:** NONE.
