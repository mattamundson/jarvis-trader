# JARVIS Delivery Backlog — Master Hierarchy

**Parent:** `JARVIS-MPP-1.0`  
**Status:** DRAFT / proposed execution hierarchy  
**Snapshot:** 2026-09-08

This backlog is the PlanLife-style execution view of the Master Product Plan. Status is conservative: a capability is not marked complete merely because code or a PR exists.

## Status key

`NS` Not Built · `P` Proposed · `D` Draft · `AU` Active-Unadopted · `A` Adopted · `I` Implemented · `V` Validated · `PQ` PAPER-Qualified · `B` Blocked

---

# Outcome O1 — Truthful Data

## Program B — Data & Instrument Authority

### Epic B1 — Instrument Master
- **B-01 [D] Canonical instrument contract** — draft in #788
  - disposition provider aliases `MES=F`, `NQ=F`, `CL=F`, `GC=F`
  - enumerate every active multiplier/spec consumer
  - reconcile root/provider/contract identity
  - add tick size, point value, currency, exchange, session/calendar reference
  - prove parity before active consumer migration
- **B-02 [P] Session/calendar authority**
- **B-03 [P] Provider symbol mapping and current-contract resolution**

### Epic B2 — Point-in-time data
- **B-10 [P] Observation contract with observed/available timestamps**
- **B-11 [P] PIT feature availability registry** — harvest candidate #749
- **B-12 [P] Replayable PIT feature store** — harvest candidate #749
- **B-13 [P] Freshness/read-time quality gate**
- **B-14 [P] Provenance stamp on every decision input**
- **B-15 [P] Source contradiction and fallback policy**

### Epic B3 — Source integrity
- **B-20 [AU] Existing source-integrity/mission-control work** — #787 contributes read-side evidence
- **B-21 [D] ThinkScript source integrity** — #749/#770 evidence sources
- **B-22 [P] External/source parity fixtures**

---

# Outcome O2 — Reproducible Edge

## Program C — Research & Validation

### Epic C1 — Research truth
- **C-01 [D] Immutable trial ledger** — harvest candidate #749
- **C-02 [D] Research fingerprints** — harvest candidate #749
- **C-03 [D] Purged/CPCV validation** — harvest candidate #749
- **C-04 [D] Judge V3 diagnostics/trial accounting** — harvest candidate #749
- **C-05 [P] Hypothesis registry and null/falsification statement**

### Epic C2 — Known leakage/defect quantification
- **C-10 [D] Initial Balance look-ahead defect evidence** — issue #751 / #749
- **C-11 [D] Session VWAP overnight/pre-market contamination evidence** — issue #752 / #749
- **C-12 [P] Quantify economic/statistical impact before active patch decision**
- **C-13 [P] Re-run affected research after approved patch**

### Epic C3 — Robustness
- **C-20 [P] Execution-cost stress**
- **C-21 [P] Parameter uncertainty**
- **C-22 [P] Regime-conditioned bootstrap**
- **C-23 [D] Dependence-preserving resampling** — #749
- **C-24 [D] Edge degradation scenarios** — #749
- **C-25 [P] Multiple-testing / trial-budget reporting**

### Epic C4 — Strategy promotion evidence
- **C-30 [P] Minimum sample/economic significance policy**
- **C-31 [P] IS/OOS degradation thresholds**
- **C-32 [P] PAPER candidacy evidence pack**

---

# Outcome O3 — Deterministic Safety

## Program H — Risk Authority

### Epic H1 — Canonical risk policy
- **H-01 [D] Versioned inert risk-policy contract** — #788
- **H-02 [P] Compare active SafetyLayer/legacy constants to H-01**
- **H-03 [P] Adopt one risk-policy authority**
- **H-04 [P] Risk-decision receipt with reason codes**

### Epic H2 — Exposure and sizing
- **H-10 [AU] RT-2 zero-allowed manual sizing behavior** — merged #756; not canonical
- **H-11 [P] Replace minimum-one legacy behavior in canonical path only after migration evidence**
- **H-12 [P] Portfolio/correlation exposure limits**
- **H-13 [P] Margin/capacity limits**

### Epic H3 — Safety drills
- **H-20 [P] Kill-switch adversarial test suite**
- **H-21 [P] Daily-loss/drawdown halt drills**
- **H-22 [P] stale/unknown/contradictory fail-close drills**
- **H-23 [P] emergency flatten/halt recovery receipt**

---

# Outcome O4 — Reliable Execution

## Program I — OMS & Execution

### Epic I1 — Canonical lifecycle
- **I-01 [D] OMS lifecycle contract** — #788
- **I-02 [P] Durable canonical aggregate/store**
- **I-03 [P] Partial fill / cancel / replace transitions**
- **I-04 [P] Restart/recovery state reconstruction**
- **I-05 [P] Ambiguous broker acknowledgement state**

### Epic I2 — Manual order authority migration
- **I-MIG-001 [D] `/orders/place` vs `/trade-intents/*` migration receipt** — #786
- **I-10 [AU] RT-2 TradeIntent preview/submit** — merged #756
- **I-11 [P] Shadow/parity harness across mutation paths**
- **I-12 [P] Non-futures legacy route disposition**
- **I-13 [P] Canonical cutover decision**
- **I-14 [P] Old authority read-only/deprecation/removal sequence**

### Epic I3 — Protected orders
- **I-20 [AU] Broker-native bracket path available through current SafetyLayer/gateway composition**
- **I-21 [P] Canonical protection relationship model**
- **I-22 [P] Orphaned child/parent failure drills**
- **I-23 [P] Cancel/replace protection semantics**

---

# Outcome O4 — Broker Truth

## Program J — Broker & Reconciliation

### Epic J1 — Broker capability model
- **J-01 [AU] Simulator gateway path exists**
- **J-02 [AU] Real IB PAPER manager path exists when configured for PAPER**
- **J-03 [P] Capability advertisement: SIMULATOR vs IB_PAPER vs future LIVE**

### Epic J2 — Reconciliation
- **J-10 [P] Order reconciliation authority**
- **J-11 [P] Fill reconciliation authority**
- **J-12 [P] Position reconciliation authority**
- **J-13 [P] unresolved-drift state and alerts**
- **J-14 [P] restart reconciliation campaign**

---

# Outcome O5 — One Operator Product

## Program K — Operator Product

### Epic K1 — Canonical information architecture
- **K-01 [D] Canonical route migration manifest** — #788
- **K-MIG-001 [D] V2→canonical migration receipt/census** — #786
- **K-02 [P] Canonical application shell**
- **K-03 [P] semantic status token system**
- **K-04 [P] responsive/accessibility baseline**

### Epic K2 — Command Center
- **K-10 [AU] `/command-center-v2` implementation source** — merged #754; not final product
- **K-11 [P] `/command-center` trust/vitals projection**
- **K-12 [P] market/regime + risk governor**
- **K-13 [P] candidate table with evidence-separated states**
- **K-14 [P] positions/orders/reconciliation panels**
- **K-15 [P] attention/event tape**
- **K-16 [P] degraded/unknown visual acceptance tests**

### Epic K3 — Trade Workstation
- **K-20 [AU] V2 trade-intent UI scaffolding** — #754
- **K-21 [P] canonical preview/confirmation flow**
- **K-22 [P] intent/order lifecycle viewer**
- **K-23 [P] ambiguity/reconciliation workflow**
- **K-24 [P] safety-reviewed risk-reducing controls**

### Epic K4 — Truth workspaces
- **K-30 [P] Portfolio**
- **K-31 [P] Risk Center**
- **K-32 [P] Broker**
- **K-33 [P] Operations**
- **K-34 [P] Audit**

### Epic K5 — Research workspaces
- **K-40 [P] Research Lab**
- **K-41 [P] Strategies**
- **K-42 [P] Intelligence**
- **K-43 [P] Capital Path**
- **K-44 [P] Learning**

---

# Outcome O6 — Evidence-driven Capital Progression

## Program N — Security & Authorization

### Epic N1 — Authorization evidence
- **N-01 [D] Environment/authorization contract** — #788
- **N-02 [P] human approval identity + scope + expiry**
- **N-03 [P] capital authorization record**
- **N-04 [P] authorization revocation**

### Epic N2 — Promotion workflow
- **N-10 [P] PAPER qualification receipt**
- **N-11 [P] LIVE-canary candidate checklist**
- **N-12 [P] explicit human LIVE-canary authorization**
- **N-13 [P] post-canary review**
- **N-14 [P] explicit production authorization**

---

# Outcome O7 — Continuous Learning

## Program L — Learning & Performance

### Epic L1 — Outcome truth
- **L-01 [P] decision→fill→outcome linkage**
- **L-02 [P] realized-vs-expected slippage**
- **L-03 [P] strategy calibration**
- **L-04 [P] regime attribution**

### Epic L2 — Drift
- **L-10 [P] data drift**
- **L-11 [P] execution drift**
- **L-12 [P] strategy degradation**
- **L-13 [P] proposal generation; no self-activation**

---

# Outcome O8 — Maintainable Platform

## Program A — Architecture
- **A-01 [D/B] runtime truth / adoption foundation** — host evidence affected by CI/runtime constraints
- **A-04 [D] core TradeIntent/domain contracts** — #788
- **A-MIG [D] authority migration receipt process** — #788

## Program M — Observability & Audit
- **M-01 [D] event/audit envelope** — #788
- **M-02 [P] correlation across decision/risk/order/fill**
- **M-03 [P] authoritative runtime snapshot**
- **M-04 [AU] mission-control/source-integrity improvements** — #787

## Program O — Delivery & Engineering
- **O-01 [AU] local PR gate tooling** — merged #748
- **O-02 [B] reliable cloud exact-head CI execution** — zero-step runner failures observed recently
- **O-03 [P] evidence classifier: CODE_FAIL vs CI_INFRA vs ENV_BLOCKED**
- **O-04 [P] PR template bound to product hierarchy**
- **O-05 [P] quarterly authority/route debt census**

---

# Immediate execution queue

The next work should proceed in this order unless a new S3/S4 defect changes priority:

1. Review/adopt or revise `JARVIS-MPP-1.0`.
2. Review #788 as the clean current-master inert Phase-1 contract stack.
3. Review #786 migration receipts against the current merged mutation/UI paths.
4. Restore trustworthy exact-head CI execution; do not misclassify zero-step runner failure as code failure.
5. Complete I-MIG-001 source/target semantic matrix and restart/reconciliation test plan.
6. Complete K-MIG-001 component/read/mutation census.
7. Adopt Instrument Master and explicit alias dispositions.
8. Adopt deterministic risk/OMS contracts before active integration.
9. Harvest research-integrity assets from #749 into bounded PRs.
10. Begin canonical Command Center shell/read-only projection before adding new mutation capabilities.

---

# Completion rule

A checkbox is closed only when its **parent acceptance condition** is satisfied. Child PR completion never automatically completes the epic, program, outcome, or promotion gate.
