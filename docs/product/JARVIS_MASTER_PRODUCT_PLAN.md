# JARVIS Master Product Plan v1.0

**Plan ID:** `JARVIS-MPP-1.0`  
**Status:** **DRAFT — PROPOSED GOVERNING PLAN; NOT YET ADOPTED**  
**Snapshot date:** 2026-09-08  
**Repository baseline at creation:** `master@6afe8970b8a588a3b67131d960fe47bee6fa40cf`  
**Owner:** Human capital owner / repository owner  
**Applies to:** product, architecture, research, risk, execution, operator experience, validation, capital promotion, and release planning

> This document is intended to become the long-term product hierarchy for JARVIS. It does **not** become authoritative merely by existing in Git or by being merged. Adoption requires an explicit human decision. Until then, it is the proposed parent plan under which existing implementation plans, release trains, PRs, issues, research artifacts, and migration receipts are classified.

---

## 1. Why this plan exists

JARVIS has accumulated substantial engineering, research, safety, dashboard, and execution work across multiple generations of plans and branches. Several of those plans were excellent tactical roadmaps for the system state that existed when they were written, but none currently provides one durable hierarchy that answers all of these questions at once:

1. **What is the product supposed to become?**
2. **What are the canonical architecture domains and sources of truth?**
3. **Which operator surfaces are canonical?**
4. **Which capabilities are actually delivered versus merely coded, merged, tested, or proposed?**
5. **What evidence is required before PAPER or LIVE capital authority changes?**
6. **How do release trains and individual PRs map to long-term outcomes?**
7. **What should be built next, and why?**

This plan establishes that hierarchy.

### Governing rule

**Release trains, branches, PRs, and tickets are children of the product plan. They are not the product plan.**

A merged PR may supply evidence toward a work package. It does not, by itself, make that work package complete, canonical, production-ready, or capital-authorized.

---

## 2. Status vocabulary — mandatory everywhere

JARVIS will use the following states consistently in roadmap documents, PR descriptions, dashboards, and migration receipts.

| State | Meaning |
|---|---|
| **NOT BUILT** | Target capability does not yet exist in usable form. |
| **PROPOSED** | Design/plan exists; implementation has not been accepted. |
| **DRAFT** | Code or artifact exists on a branch/PR but is not merged/adopted. |
| **ACTIVE-UNADOPTED** | Code is on `master` or deployed, but is not yet the canonical implementation under this plan. |
| **ADOPTED** | Human-approved canonical design/contract/source of truth. |
| **IMPLEMENTED** | Adopted behavior is implemented in the intended authority. |
| **VALIDATED** | Required automated and runtime evidence has executed successfully at the required verification rung. |
| **PAPER-QUALIFIED** | Required real PAPER environment campaign and reconciliation evidence are complete. |
| **LIVE-CANARY-AUTHORIZED** | Explicit human capital authorization exists for a bounded canary. |
| **PRODUCTION-AUTHORIZED** | Explicit human capital authorization exists for defined production scope. |
| **DEPRECATED** | Replacement is canonical and migration evidence is complete; old path retained temporarily. |
| **REMOVED** | Old path retired after rollback/reconciliation requirements are satisfied. |
| **BLOCKED** | An explicit dependency or evidence gate prevents advancement. |

### Prohibited shortcuts

- `MERGED` does not mean `ADOPTED`.
- `TESTS PASS` does not mean `PAPER-QUALIFIED`.
- `PAPER-QUALIFIED` does not mean `LIVE-CANARY-AUTHORIZED`.
- A dashboard route existing does not mean the product UI is delivered.
- A backtest with attractive metrics does not mean an edge is causal, reproducible, executable, or promotable.
- An LLM recommendation never grants execution or capital authority.

---

# PART I — PRODUCT CHARTER

## 3. Mission

Build JARVIS into a **research-to-execution trading operating system** that can:

1. ingest trustworthy, point-in-time market and contextual data;
2. discover and falsify trading hypotheses rigorously;
3. convert only validated hypotheses into versioned strategies;
4. make deterministic, risk-constrained decisions;
5. route and reconcile PAPER orders safely;
6. explain its state, evidence, risk, and next action to an operator in seconds;
7. learn from realized outcomes without silently changing capital authority; and
8. progress toward bounded LIVE deployment only through explicit evidence and human promotion gates.

The system is optimized for **survival, truth, auditability, and repeatable edge** before autonomy or visual sophistication.

## 4. Long-term outcomes

### O1 — Truthful data
Every decision is traceable to fresh, point-in-time, provenance-stamped data. Unknown, stale, contradictory, or wrong-era inputs fail closed.

### O2 — Reproducible edge
Every promoted strategy has reproducible research lineage, point-in-time features, leakage controls, out-of-sample evidence, execution-cost stress, and enough sample size to support its claim.

### O3 — Deterministic safety
Risk decisions and execution eligibility are deterministic, testable, explainable, and independent of LLM discretion.

### O4 — Reliable execution
The OMS knows what was intended, submitted, acknowledged, filled, cancelled, rejected, or ambiguous, survives restart, reconciles with broker truth, and never retries an ambiguous exposure-increasing mutation blindly.

### O5 — One operator product
A canonical Command Center and a small set of purpose-built workspaces replace route sprawl. The operator can answer “Is JARVIS safe? What does it believe? What is exposed? What is it about to do? Can I trust the data?” without hunting across pages.

### O6 — Evidence-driven capital progression
PAPER, canary, and production promotion are explicit state changes supported by machine-readable evidence and human authorization.

### O7 — Continuous learning without uncontrolled self-modification
JARVIS measures calibration, slippage, strategy drift, regime behavior, and realized-vs-expected results. Learning may propose changes; it cannot silently activate strategies, alter risk policy, or grant itself capital.

### O8 — Maintainable platform
One set of domain contracts, one source of instrument truth, one event/audit model, one risk authority, one OMS, one broker reconciliation model, one canonical product IA, and explicit migration receipts for retiring parallel authorities.

---

## 5. Non-goals

JARVIS is **not** intended to:

- guarantee returns or a fixed capital-growth timetable;
- let an LLM decide whether safety rules apply;
- autonomously enable LIVE trading;
- promote a strategy from one attractive backtest;
- hide stale data behind fallback values;
- maintain multiple permanent order authorities or permanent parallel Command Centers;
- optimize vanity metrics at the expense of drawdown, capacity, robustness, or execution quality;
- treat simulated fills as proof of broker execution quality;
- use a dashboard as a substitute for broker truth;
- change risk limits merely to make tests pass.

Capital Path scenarios, including aggressive compounding targets, are planning and stress-analysis tools—not promises or authorization criteria.

---

## 6. Immutable safety principles

1. **Fail closed on uncertainty.** Unknown exposure, stale market data, stale account state, contradictory broker state, ambiguous order acknowledgement, missing protective geometry, or unresolved reconciliation blocks exposure-increasing actions.
2. **Broker is execution truth.** Internal state is reconciled to the broker for orders, fills, positions, and exposure.
3. **LLMs are advisory.** No model may bypass deterministic risk, broker, authorization, or reconciliation controls.
4. **Human promotion is explicit.** LIVE canary and production authority require explicit human approval independent of research verdicts.
5. **Mutations are idempotent.** Exposure-changing requests carry stable identity and cannot be accidentally duplicated by retries.
6. **Ambiguity is a state.** If a broker call may have occurred but acknowledgement is unknown, the OMS preserves ambiguity and reconciles before resubmission.
7. **Requested quantity is a ceiling, not a command.** Risk can reduce quantity to zero / `NO_TRADE`.
8. **Protect first.** Exposure-increasing futures orders require defined protective risk geometry and protected-order semantics.
9. **Evidence precedes authority migration.** New canonical sources replace old ones only through parity, restart, failure, reconciliation, and rollback evidence.
10. **IBKR/TWS remains independent truth during PAPER and early LIVE canary.** The operator application never removes the need for an independent broker escape hatch.

---

# PART II — MASTER HIERARCHY

## 7. PlanLife-style hierarchy

All work should map through this hierarchy:

```text
JARVIS TRADING PLATFORM
│
├── Outcome
│   └── Program / Workstream
│       └── Epic
│           └── Feature / Capability
│               └── Work Package
│                   └── Task
│                       └── Evidence / Test / Receipt
│
├── Release Train
│   └── bundles work packages for delivery; does not redefine outcomes
│
└── Promotion Gate
    └── controls transition from code → validated → PAPER → LIVE canary → production
```

Every implementation PR should eventually name:

- Outcome
- Program
- Epic
- Work Package
- Safety class
- Verification rung
- Dependencies
- Acceptance criteria
- Migration/rollback impact
- Capital impact

---

## 8. Master programs

### A — Platform & Architecture
Canonical contracts, process boundaries, configuration ownership, runtime composition, migrations, and dependency rules.

### B — Data & Instrument Authority
Instrument Master, sessions/calendars, market data, point-in-time storage, feature availability, corporate/event context, provenance, freshness, and replay.

### C — Research & Validation
Hypothesis registry, research ledger, leakage controls, causal feature engineering, purged validation, CPCV/walk-forward, robustness, cost stress, source parity, and falsification.

### D — Strategy Lifecycle
Strategy specifications, eligibility, versioning, parameter governance, regime applicability, promotion/demotion, and portfolio interaction.

### E — Intelligence & Context
Market regime, catalyst/news/macro/social context, model-assisted analysis, calibration, and advisory synthesis. No capital authority.

### F — Portfolio & Capital Path
Portfolio state, exposure aggregation, correlation, capital allocation, scenario analysis, drawdown bands, Monte Carlo, capacity, and long-horizon capital planning.

### G — Decision Engine
Deterministic synthesis of eligible strategy signals, market state, risk constraints, account state, freshness, and authorization into actionable or blocked decisions.

### H — Risk Authority
One deterministic versioned risk policy, sizing, exposure limits, drawdown and daily-loss constraints, price sanity, kill switch, protective requirements, and risk-decision receipts.

### I — OMS & Execution
TradeIntent, order lifecycle, idempotency, atomic claims, bracket/OCO semantics, broker routing, partial fills, cancel/replace, restart recovery, ambiguity, and reconciliation.

### J — Broker & Reconciliation
IBKR adapter, simulated/PAPER/real-PAPER distinction, connection health, account/position/order/fill truth, broker event normalization, drift detection, and emergency fallback.

### K — Operator Product
Command Center, Trade Workstation, Portfolio, Risk, Research Lab, Strategies, Capital Path, Intelligence, Data, Operations, Broker, Learning, Settings, and Audit.

### L — Learning & Performance
Performance attribution, calibration, slippage, drift, trade review, journal, model/strategy diagnostics, experiments, and recommendations.

### M — Observability & Audit
Immutable event envelope, correlation/causation, metrics, traces, runtime health, source integrity, decision lineage, audit evidence, and incident reconstruction.

### N — Security & Authorization
Identity, environment, permissions, capital authorization, API protection, secret hygiene, environment isolation, and promotion evidence.

### O — Delivery & Engineering System
CI/CD, local verification fallback, branch/worktree hygiene, test taxonomy, deployment, release receipts, documentation integrity, and dependency/security maintenance.

---

# PART III — TARGET ARCHITECTURE

## 9. Canonical authority map

| Domain fact | Target authority | Migration principle |
|---|---|---|
| Instrument identity/specification | Instrument Master | No provider alias silently becomes canonical. |
| Market/session calendar | Data platform calendar authority | Timezone/session semantics explicit and replayable. |
| Point-in-time observations | PIT data/feature store | No future knowledge; availability timestamp retained. |
| Strategy definition/version | Strategy Registry | Immutable version identity for each evaluated/promoted strategy. |
| Strategy eligibility | Strategy Lifecycle | Evidence-backed state, not an ad-hoc boolean. |
| Risk policy | Risk Authority | Versioned, deterministic, inactive until adopted/activated explicitly. |
| Risk decision | Risk Authority | Immutable receipt with inputs, policy version, and reason codes. |
| Trade intent | OMS | Stable idempotency identity; requested size remains a ceiling. |
| Order/fill/position truth | Broker + Reconciliation | Broker observed truth reconciled into internal projection. |
| Execution lifecycle | OMS | Durable state machine including ambiguity and restart recovery. |
| Capital authorization | Authorization domain | Human-granted, scoped, expiring/revocable. |
| Operator projection | Command Center/read models | Never a hidden execution authority. |
| Research trial | Research ledger | Immutable hypothesis/trial/fingerprint identity. |
| Audit/event history | Event/Audit authority | Append-oriented, correlated, provenance-stamped. |

### Command/query separation

- **HTTP**: commands, explicit queries, mutations, receipts.
- **WebSocket/SSE**: observations, state projections, broker events, health, tape, streaming updates.
- A dropped streaming connection never causes a command retry.
- UI state is a projection, not the source of execution truth.

---

## 10. Core domain objects

The long-term model should converge on these concepts:

```text
Instrument
MarketObservation
FeatureObservation
ResearchHypothesis
ResearchTrial
StrategyVersion
Signal
DecisionContext
RiskDecision
TradeIntent
OrderAggregate
ExecutionReport
BrokerPosition
ReconciliationResult
PortfolioSnapshot
AuthorizationEvidence
AuditEvent
RuntimeHealthSnapshot
PromotionEvidence
```

Each mutation-domain object requires:

- stable ID;
- created/observed timestamp;
- source/provenance;
- environment;
- correlation ID;
- version/fingerprint where applicable;
- explicit unknown/stale/ambiguous representation;
- deterministic serialization suitable for audit/replay.

---

# PART IV — PRODUCT / OPERATOR EXPERIENCE

## 11. Canonical operator information architecture

The target IA is intentionally small. Existing routes are migration sources, not permanent product topology.

| Surface | Canonical route | Purpose |
|---|---|---|
| **Command Center** | `/command-center` | One-glance operating state and next actions. |
| **Trade Workstation** | `/trades` | Candidates, previews, approvals, manual PAPER trade intents, order lifecycle. |
| **Portfolio** | `/portfolio` | Positions, P&L, exposure, capital utilization, attribution. |
| **Risk Center** | `/risk` | Risk policy, limits, current usage, blocks, kill switch, drawdown. |
| **Research Lab** | `/research-lab` | Hypotheses, experiments, validation, evidence, backtests. |
| **Strategies** | `/strategies` | Strategy registry, versions, eligibility, evidence state. |
| **Capital Path** | `/capital-path` | Monte Carlo, scenarios, frontier, capacity, drawdown bands. |
| **Intelligence** | `/intelligence` | Regime, catalysts, contextual/advisory analysis. |
| **Data** | `/data` | Feeds, freshness, provenance, PIT coverage, quality, source parity. |
| **Operations** | `/operations` | Runtime health, processes, queues, incidents, reconciliation health. |
| **Broker** | `/broker` | IBKR connectivity, broker-observed orders/fills/positions; PAPER/LIVE mode truth. |
| **Learning** | `/learning` | Calibration, realized outcomes, drift, improvement proposals. |
| **Settings** | `/settings` | Non-capital settings and explicit controlled configuration surfaces. |
| **Audit** | `/audit` | Decision/order/risk/research lineage and immutable receipts. |

`/performance` may exist during migration but should be folded into Portfolio/Learning/Audit according to final design.

### Product rule

No new top-level route is created unless it represents a durable operator job that cannot be served by an existing canonical surface.

---

# PART V — DELIVERY ROADMAP

## 12. Delivery phases

The phases are dependency-oriented. Work may be parallelized only when it does not create competing authorities.

### Phase 0 — Governance & Runtime Truth

**Objective:** know what exists, what is running, who owns each fact, and what may change safely.

Key outcomes:
- canonical product plan proposed and adopted;
- runtime/repository truth snapshot;
- spike harvest map;
- authority migration receipt process;
- safety classes and verification rungs;
- CI/runner reliability or documented local fallback;
- current routes and mutation paths inventoried.

**Exit gate:** ISG-0 — human adoption of architecture/product hierarchy and acceptance of current-state inventory.

### Phase 1 — Contracts, Data Truth & Instrument Authority

**Objective:** establish shared domain contracts and remove hidden instrument/data ambiguity.

Key work:
- A-04 TradeIntent/domain vocabulary;
- B-01 Instrument Master;
- session/calendar authority;
- point-in-time observation/availability schema;
- feature registry/store;
- M-01 event/audit envelope;
- N authorization evidence model;
- H-01 risk-policy contract;
- OMS lifecycle contract;
- active-path integration ratchets until migrations are approved.

**Exit gate:** canonical contracts adopted; contradiction audits dispositioned; no active path has silently bypassed migration receipts.

### Phase 2 — Research Integrity & Edge Discovery

**Objective:** create trustworthy evidence before strategy promotion.

Key work:
- hypothesis registry;
- immutable trial ledger;
- research fingerprints;
- source-integrity baseline;
- point-in-time features;
- purged CV / CPCV / walk-forward;
- execution-cost and slippage stress;
- parameter uncertainty;
- regime-conditioned resampling;
- Judge V3 adversarial/red-team review;
- quantify known IB/VWAP leakage defects before active patch/promotion decisions.

**Exit gate:** at least one strategy family has reproducible, leakage-controlled, OOS-positive evidence with robustness and cost stress sufficient for PAPER candidacy. No result is promoted from a single metric.

### Phase 3 — Canonical Risk + PAPER OMS

**Objective:** make every exposure-increasing action pass through one deterministic risk/OMS/broker path.

Key work:
- adopt H-01 risk authority;
- migrate TradeIntent sizing and validation;
- unify `/orders/place` and `/trade-intents/*` into one canonical mutation spine;
- broker-native protected order handling;
- partial fills;
- cancel/replace;
- restart persistence;
- ambiguous acknowledgement recovery;
- broker reconciliation;
- emergency flatten/halt drills;
- simulator vs real IB PAPER capability distinction.

**Exit gate:** one manual/automated PAPER order authority, verified restart/reconciliation behavior, no blind auto-retry after possible broker invocation, deterministic fail-closed safety tests.

### Phase 4 — Canonical Operator Product

**Objective:** deliver the actual operating product, not merely route scaffolding.

Key work:
- implement canonical shell and navigation;
- harvest useful #754 V2 components into target surfaces;
- remove duplicate product generations through staged migration;
- Command Center real-time state projection;
- Trade Workstation;
- Portfolio/Risk/Operations/Broker/Audit surfaces;
- stale/unknown/degraded states;
- responsive and accessibility pass;
- visual regression tests;
- operator E2E workflows;
- PAPER/LIVE visual and interaction separation.

**Exit gate:** canonical UI is rendered, navigable, visually reviewed, E2E-tested, and proves degraded/unknown behavior; V2 can be redirected only after parity evidence.

### Phase 5 — PAPER Campaign & Learning

**Objective:** prove the integrated product and execution system over real operating time.

Key work:
- real IB PAPER campaign;
- execution-fidelity data;
- strategy realized-vs-expected analysis;
- slippage and cost calibration;
- broker/internal reconciliation drift metrics;
- restart drills during safe windows;
- data outage drills;
- kill-switch drills;
- candidate→intent→order→fill→journal lineage;
- daily/weekly PAPER evidence pack.

**Exit gate:** predefined minimum observation count, zero unresolved safety defects, bounded reconciliation discrepancies, acceptable execution fidelity, stable runtime, and explicit human review.

### Phase 6 — Capital Path & Portfolio Intelligence

**Objective:** optimize survival-aware portfolio/capital allocation using validated inputs.

Key work:
- Monte Carlo and dependence-preserving resampling;
- strategy ensemble/correlation;
- drawdown-state policy simulations;
- capacity/slippage sensitivity;
- edge-degradation scenarios;
- risk-policy Pareto frontier;
- contribution/withdrawal/scenario models;
- strategy concentration and regime risk.

**Exit gate:** capital models are reproducible and stress-tested; outputs remain advisory until explicit capital policy approval.

### Phase 7 — LIVE Canary

**Objective:** verify the complete system with deliberately tiny bounded real exposure.

Prerequisites:
- all required V0–V4 evidence complete;
- no unresolved S3/S4 findings;
- explicit capital authorization record;
- canary instrument/strategy/size/session scope;
- independent IBKR/TWS monitoring;
- immediate flatten/halt procedure;
- maximum loss and duration defined;
- operator present.

**Exit gate:** explicit human decision only. No automated graduation.

### Phase 8 — Production & Continuous Governance

**Objective:** expand only through repeated evidence.

Key work:
- scoped production authorizations;
- strategy/instrument expansion gates;
- continuous drift/freshness/reconciliation monitoring;
- scheduled red-team testing;
- post-incident evidence;
- dependency/security maintenance;
- route/authority debt prevention;
- quarterly product-plan reconciliation.

---

## 13. Verification ladder

| Rung | Name | Required evidence |
|---|---|---|
| **V0** | Static integrity | schema, lint, type, import-boundary, config/safety invariants, deterministic unit checks. |
| **V1** | Component | focused unit/component tests on exact head. |
| **V2** | Integration / replay | real module composition, persistence, restart/replay, deterministic fixtures, migration parity. |
| **V3** | Operator E2E | browser/API workflow, error states, confirmation flows, visual/state semantics. |
| **V4** | PAPER runtime | real PAPER broker/data/runtime observations over meaningful samples and failure drills. |
| **V5** | LIVE canary | explicitly authorized tiny real-capital evidence with independent operator/broker truth. |

`V5` is evidence, not automatic authorization for wider production.

---

## 14. Definition of Done

A capability is **done** only when all applicable statements are true:

1. target product/architecture owner is named;
2. dependencies are satisfied;
3. old and new authorities are explicitly dispositioned;
4. code exists in the target authority—not only a spike;
5. tests executed successfully on the exact candidate head;
6. failure behavior is tested, not only happy path;
7. restart/recovery is tested for stateful components;
8. migration/reconciliation evidence exists where facts or capital state move;
9. operator-visible behavior is rendered and E2E-tested when applicable;
10. documentation matches actual behavior;
11. rollback is defined and tested at the appropriate rung;
12. required human review/adoption is recorded;
13. PAPER or LIVE runtime evidence exists when claimed;
14. no parallel authority was silently left behind.

This definition prevents “file created,” “route exists,” “PR merged,” and “feature delivered” from being used interchangeably.

---

# PART VI — CURRENT-STATE RECONCILIATION

## 15. Current implementation inventory at plan creation

| Artifact | State under this plan | What it contributes | What it does **not** prove |
|---|---|---|---|
| **PR #754, merged** | **ACTIVE-UNADOPTED** | Command Center V2 control-plane ideas, fail-closed aggregation, candidate/approval/trade UI scaffolding. | Canonical product delivered; visual acceptance; V3/V4 operator evidence. |
| **PR #756, merged** | **ACTIVE-UNADOPTED** | manual futures TradeIntent preview/submit lifecycle, zero sizing, idempotency, durable claim, ambiguity handling, brackets. | Canonical OMS; restart/reconciliation completeness; sole mutation authority; LIVE readiness. |
| **Legacy `/orders/place`** | **TRANSITIONAL ACTIVE** | existing manual order route. | Long-term authority. Must be dispositioned against TradeIntent path. |
| **PR #787, merged** | **ACTIVE-UNADOPTED feature addition** | analysis-only SPX intraday panel and mission-control/runtime-contract improvements. | Strategy promotion or execution authority; canonical IA adoption. |
| **PR #749, draft** | **DRAFT RESEARCH HARVEST SOURCE** | PIT/research integrity/Judge/Capital Path modules and defect evidence. | Edge promotion; active strategy patch authority; LIVE authorization. |
| **PR #786, draft** | **DRAFT GOVERNANCE** | current-master capability inventory, manual-order and V2 migration receipts, containment proposal/ratchets. | Runtime containment; adoption decision. |
| **PR #788, draft** | **DRAFT CONTRACT REBASE** | current-master inert A/B/H/I/K/M/N contracts and migration controls. | Runtime authority or adoption. |
| Older April/July master roadmaps | **HISTORICAL EVIDENCE** | valuable diagnoses, design principles, shipped history, prior priorities. | Current canonical long-term product hierarchy. |

### Immediate architectural debt

1. two manual-order mutation spines exist;
2. Command Center V2 exists alongside canonical-route intent;
3. active code predates proposed canonical domain contracts;
4. CI runner allocation has recently produced zero-step failures, weakening exact-head evidence;
5. research assets are substantial but not yet harvested into a governed strategy lifecycle;
6. product route inventory is still broader than the target IA;
7. “merged,” “deployed,” and “adopted” status has historically been inconsistently communicated.

---

# PART VII — PRIORITY EXECUTION ORDER

## 16. Next 20 highest-ROI work packages

Priority is risk-adjusted: authority ambiguity and evidence quality outrank new features.

| Rank | WP | Work | Dependency | Exit evidence |
|---:|---|---|---|---|
| 1 | **GOV-01** | Adopt/revise this Master Product Plan | human review | explicit adoption decision |
| 2 | **GOV-02** | Adopt authority/status vocabulary and DoD | GOV-01 | templates/status docs updated |
| 3 | **I-MIG-001** | Reconcile `/orders/place` vs `/trade-intents/*` | #786/#788 review | approved migration receipt |
| 4 | **K-MIG-001** | Map V2 routes/components to canonical IA | product spec | route/component parity matrix |
| 5 | **O-CI-001** | Restore trustworthy exact-head CI execution | none | required jobs execute, not zero-step |
| 6 | **B-01** | Adopt Instrument Master contract and disposition aliases | #788 | contradiction/consumer migration plan |
| 7 | **H-01** | Adopt canonical deterministic risk contract | #788 + safety review | policy semantics + parity evidence |
| 8 | **I-01** | Adopt canonical OMS lifecycle | H-01 | lifecycle/retry/reconcile tests |
| 9 | **I-02** | TradeIntent migration into canonical OMS | I-01 | dual-path shadow parity |
| 10 | **I-03** | Restart/ambiguity/partial-fill/reconciliation harness | I-01 | V2 failure/restart evidence |
| 11 | **B-02** | PIT data/availability foundation | B-01 | deterministic replay dataset |
| 12 | **C-01** | Research ledger/fingerprint harvest from #749 | B-02 | immutable reproducible trial |
| 13 | **C-02** | Quantify known IB/VWAP leakage defects | C-01 | impact report; patch decision |
| 14 | **C-03** | Execution-cost/parameter/regime stress harness | C-01 | robustness report |
| 15 | **K-01** | Implement canonical app shell/navigation | K-MIG-001 | rendered V3 shell |
| 16 | **K-02** | Command Center real-time projection | K-01 | degraded/unknown E2E |
| 17 | **K-03** | Trade Workstation on canonical OMS | I-02 + K-01 | candidate→fill E2E PAPER |
| 18 | **M-01** | Adopt audit/event envelope in active pathways | #788 | correlated lifecycle evidence |
| 19 | **V4-01** | Integrated real IB PAPER campaign | B/H/I/K/M complete | PAPER evidence pack |
| 20 | **F-01** | Capital Path production-grade advisory integration | validated strategies + V4 | stress-tested portfolio scenarios |

### Deliberately deferred

- additional autonomous trade actions;
- atomic stop-replacement operator features;
- single-position reduction UI unless OMS semantics are adopted first;
- LIVE feature activation;
- broader instrument expansion before Instrument Master and evidence gates;
- permanent new top-level dashboard routes;
- AI “agent swarms” that create additional authorities rather than improve evidence throughput.

---

# PART VIII — RELEASE TRAINS

## 17. Role of RT-0, RT-1, RT-2, RT-3…

Release trains are delivery slices. They must map upward to work packages.

Example:

```text
Outcome O4 Reliable Execution
└── Program I — OMS & Execution
    ├── I-01 Canonical OMS lifecycle
    ├── I-02 TradeIntent migration
    └── I-03 Recovery/reconciliation
        ├── RT-2 preview/submit foundation   [existing evidence source]
        ├── RT-3 operator PAPER controls     [future bounded slice]
        └── RT-4 failure/restart campaign    [future bounded slice]
```

A release train may be complete while the parent capability is not.

---

# PART IX — PRODUCT METRICS

## 18. System scorecard

### Safety
- unresolved S3/S4 defects;
- kill-switch drill success;
- stale/unknown fail-close success rate;
- unauthorized mutation count (target 0);
- ambiguous-order duplicate-resubmit count (target 0).

### Data truth
- source freshness by instrument;
- provenance completeness;
- PIT coverage;
- replay determinism;
- contradictory-source rate.

### Research quality
- hypotheses registered;
- trials reproducible by fingerprint;
- leakage failures caught;
- OOS vs IS degradation;
- execution-cost sensitivity;
- sample sufficiency.

### Execution
- broker acknowledgement latency;
- fill slippage;
- reject rate;
- reconciliation drift;
- unresolved ambiguity duration;
- restart recovery correctness.

### Operator product
- time-to-understand overall system state;
- route count and route debt;
- stale/unknown state visibility;
- E2E workflow pass rate;
- operator intervention error rate.

### Platform
- required CI execution rate;
- exact-head green rate;
- deployment reproducibility;
- open authority-migration debt;
- stale PR/worktree count.

---

# PART X — GOVERNANCE

## 19. Safety classes

| Class | Definition | Minimum governance |
|---|---|---|
| **S0** | docs/read-only presentation | standard review |
| **S1** | inert contracts/tests/read models | V0/V1 |
| **S2** | stateful non-capital behavior / migration | V1/V2 + rollback |
| **S3** | safety, risk, broker, PAPER mutation, execution path | independent safety review + V2/V3/V4 as applicable |
| **S4** | LIVE-capital authority or exposure expansion | explicit human capital approval + V5 canary |

## 20. Promotion state machine

```text
IDEA
→ PROPOSED
→ DRAFT_IMPLEMENTATION
→ ADOPTED_DESIGN
→ IMPLEMENTED
→ VALIDATED
→ PAPER_CANDIDATE
→ PAPER_QUALIFIED
→ LIVE_CANARY_CANDIDATE
→ [EXPLICIT HUMAN CAPITAL APPROVAL]
→ LIVE_CANARY_AUTHORIZED
→ REVIEW
→ [EXPLICIT HUMAN CAPITAL APPROVAL]
→ PRODUCTION_AUTHORIZED
```

Any material code/config/data/strategy change can demote the evidence state and require revalidation.

## 21. Change-control rules

1. Every new authority requires a migration receipt.
2. Every S3/S4 change requires an explicit safety review boundary.
3. No PR is marked ready or merged automatically by this plan.
4. No environment variable enabling LIVE trading is changed automatically.
5. Risk thresholds are not modified to satisfy tests.
6. Exact-head CI infrastructure failures are classified separately from code failures.
7. A route or API may be ACTIVE-UNADOPTED; its existence must be reconciled, not rewritten from history.
8. Historical plans remain evidence and should be archived/linked, not silently deleted.
9. Product plan reconciliation occurs after every material architecture merge and at least once per major release phase.

---

# PART XI — ADOPTION CHECKLIST

## 22. Human decisions required to make this canonical

- [ ] Accept/revise mission and non-goals.
- [ ] Accept/revise programs A–O.
- [ ] Accept/revise canonical operator IA.
- [ ] Accept status vocabulary.
- [ ] Accept verification ladder V0–V5.
- [ ] Accept Definition of Done.
- [ ] Accept authority-migration requirement.
- [ ] Accept release trains as children of work packages.
- [ ] Accept current classification of #754/#756/#787 as ACTIVE-UNADOPTED.
- [ ] Accept immediate top-20 execution order.
- [ ] Record adoption decision and effective commit SHA.

Until these boxes are explicitly approved, this document remains a **proposal**.

---

## 23. Source relationship

This plan synthesizes and supersedes **as a proposed forward hierarchy**, not by deletion, the planning role previously spread across artifacts such as:

- `JARVIS_TRADER_MASTER.md` / Part 2;
- `docs/plans/roadmap-2026-04-20-unified.md`;
- `docs/JARVIS_SOTA_PLAN.md`;
- Phase-0 / Phase-1 MIP artifacts;
- research-integrity work in #749;
- Command Center / TradeIntent work in #754/#756;
- current migration/governance work in #786/#788;
- later product/analysis changes such as #787.

Those sources remain useful historical and technical evidence. Conflicting implementation claims must be revalidated against current code and runtime before being carried forward.

---

## 24. One-sentence operating rule

> **JARVIS advances by proving truth, consolidating authority, validating edge, and earning capital scope—never by accumulating more parallel code.**
