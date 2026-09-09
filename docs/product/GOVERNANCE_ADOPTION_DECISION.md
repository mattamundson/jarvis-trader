# GOV-01 — JARVIS-MPP-1.0 Adoption Decision Record

**Plan candidate:** `JARVIS-MPP-1.0`  
**PR:** #789  
**Status:** **READY FOR HUMAN DECISION — NOT ADOPTED**  
**Decision authority:** repository owner / human capital owner  
**Capital effect of plan adoption:** none

## Purpose

Create one explicit, auditable decision point for adopting or revising the proposed JARVIS Master Product Plan without conflating product governance with runtime truth, architecture-ADR adoption, PAPER qualification, or LIVE capital authority.

The existence or merge of #789 does not itself satisfy this record. The final decision must name the effective commit SHA.

## Review result

Repository/product review finds the proposed hierarchy internally coherent and suitable as the parent product-governance model **provided the boundaries below remain explicit**:

1. product-plan adoption is a governance decision, not a trading authorization;
2. A-01 Windows/TWS runtime truth remains an independent evidence gate;
3. A-02/A-03/B-01/H-01/I-01/M-01/N contracts require their own adoption/migration decisions;
4. #754/#756/#787 remain `ACTIVE-UNADOPTED` until their parent work packages are explicitly adopted and migrated;
5. historical plans and PRs are not silently deleted or declared superseded until their unique safety/evidence content is dispositioned in `LEGACY_PLAN_CROSSWALK.md`;
6. exact-head CI infrastructure failures remain `CI-INFRA / NO VALIDATION EXECUTED`, never code-failure or validation-success evidence;
7. PAPER qualification and LIVE authorization remain later independent promotion states.

## Decision checklist

Mark each item explicitly before `ADOPT`:

- [ ] Mission and non-goals accepted or revised.
- [ ] Programs A–O accepted or revised.
- [ ] Canonical authority map accepted or revised.
- [ ] Canonical operator IA accepted or revised.
- [ ] Status vocabulary accepted.
- [ ] Verification ladder V0–V5 accepted.
- [ ] Definition of Done accepted.
- [ ] Authority-migration receipt requirement accepted.
- [ ] Release trains / PRs / issues accepted as children of work packages rather than independent product plans.
- [ ] Current classification of #754/#756/#787 as `ACTIVE-UNADOPTED` accepted.
- [ ] Priority top-20 execution order accepted or revised.
- [ ] Legacy-plan crosswalk reviewed so unique safety/governance content is not lost.
- [ ] Effective adoption commit SHA recorded.

## Decision

Choose exactly one:

- [ ] **ADOPT** — `JARVIS-MPP-1.0` becomes the canonical parent product-governance hierarchy at the effective SHA below.
- [ ] **REVISE** — return #789 for named changes; no adoption occurs.
- [ ] **REJECT** — retain existing governance until a replacement is proposed.

**Effective SHA:** `PENDING`  
**Decision date:** `PENDING`  
**Decision actor:** `PENDING`  
**Decision notes:** `PENDING`

## What ADOPT would mean

If explicitly adopted, `JARVIS-MPP-1.0` becomes the parent hierarchy for product outcomes, programs, epics, work packages, verification states, and delivery status. Existing implementation plans such as `JARVIS-MIP-1.0` become subordinate implementation/evidence plans where they do not conflict with the adopted product hierarchy.

## What ADOPT would not mean

It would **not**:

- close A-01;
- establish loaded Windows/TWS/runtime facts;
- activate B-01/H-01/I-01/M-01/N contracts;
- migrate any active consumer to draft domain objects;
- make `/trade-intents/*` the canonical OMS;
- retire `/orders/place`;
- redirect or remove `/command-center-v2`;
- qualify real IB PAPER execution;
- change risk thresholds;
- enable LIVE trading;
- grant LIVE-canary or production capital authorization.

## After ADOPT

The next governed sequence is:

```text
GOV-01 explicit adoption
→ GOV-02 bind PR/status/DoD language to the hierarchy
→ reconcile/harvest legacy governance PRs
→ adopt/revise #788 contracts authority-by-authority
→ complete I-MIG-001 / K-MIG-001 migrations
→ implement read-only canonical K-01/K-02 surfaces
→ V3/V4 evidence only after dependencies are satisfied
```

No step in this record self-executes a trading or capital mutation.
