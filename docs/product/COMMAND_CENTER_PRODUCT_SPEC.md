# JARVIS Command Center & Operator Product Specification v1.0

**Spec ID:** `JARVIS-K-UI-1.0`  
**Parent:** `JARVIS-MPP-1.0`  
**Status:** **DRAFT — PRODUCT SPECIFICATION; NOT A CLAIM OF DELIVERED UI**  
**Snapshot:** 2026-09-08  
**Target primary surface:** `/command-center`

> This document defines what must be rendered, how it must behave, what data it may trust, and what evidence is required before JARVIS may claim the canonical operator application is delivered. Existing `/command-center-v2` code is a migration/harvest source, not proof that this specification is implemented.

---

# 1. Product objective

The operator product must answer five questions in under ten seconds:

1. **Is the system safe and trustworthy right now?**
2. **What does JARVIS believe about the market and why?**
3. **What capital/exposure exists right now?**
4. **What actions are pending, blocked, or recently executed?**
5. **What requires human attention?**

Everything visible in the top-level Command Center must support one of those questions.

---

# 2. Product principles

## 2.1 Truth before aesthetics

If a fact is unknown, stale, contradictory, delayed, simulated, or unavailable, the interface displays that condition explicitly. It must never convert missing evidence into a reassuring green state.

## 2.2 Projection, not authority

The dashboard reads and commands through governed APIs. Browser state is never execution truth, risk truth, broker truth, or authorization truth.

## 2.3 One product generation

There is one canonical shell. Experimental routes may exist temporarily, but their useful components are harvested into canonical surfaces and then retired through parity evidence.

## 2.4 Safety has visual priority

Risk state, broker state, data freshness, reconciliation state, execution environment, and kill switch are always more visually prominent than P&L or opportunity scores.

## 2.5 PAPER and LIVE are unmistakable

The operator must not be able to confuse environments. Environment state is persistent in the shell, action confirmation, receipts, and broker panel.

## 2.6 Mutations are deliberate

Exposure-increasing actions require preview, deterministic risk result, confirmation, idempotency identity, and post-submit lifecycle tracking. Emergency risk-reducing actions remain visually distinct.

## 2.7 Real-time without hidden retry

Streaming state updates may reconnect automatically. Exposure mutations never automatically replay merely because a WebSocket/SSE or HTTP response was lost.

---

# 3. Canonical information architecture

```text
JARVIS
├── Command Center        /command-center
├── Trade Workstation     /trades
├── Portfolio             /portfolio
├── Risk Center           /risk
├── Research Lab          /research-lab
├── Strategies            /strategies
├── Capital Path          /capital-path
├── Intelligence          /intelligence
├── Data                  /data
├── Operations            /operations
├── Broker                /broker
├── Learning              /learning
├── Settings              /settings
└── Audit                 /audit
```

### Route policy

- No new top-level route without a durable operator job-to-be-done.
- Detail pages may nest below canonical surfaces.
- Existing route sprawl maps into this IA through K-MIG-001.
- `/command-center-v2` is transitional until parity and deprecation evidence exist.
- `/performance` is transitional; final metrics belong primarily to Portfolio, Learning, Strategies, and Audit.

---

# 4. Global application shell

## 4.1 Desktop layout

```text
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│ JARVIS  | PAPER | IBKR: CONNECTED | DATA: FRESH | RISK: SAFE | RECONCILED | 09:42:17 CT   │
├───────────────────┬─────────────────────────────────────────────────────────────────────────┤
│ Command Center    │                                                         Alerts / User  │
│ Trade Workstation │                                                         ─────────────  │
│ Portfolio         │                                                         page content   │
│ Risk Center       │                                                                       │
│ Research Lab      │                                                                       │
│ Strategies        │                                                                       │
│ Capital Path      │                                                                       │
│ Intelligence      │                                                                       │
│ Data              │                                                                       │
│ Operations        │                                                                       │
│ Broker            │                                                                       │
│ Learning          │                                                                       │
│ Settings          │                                                                       │
│ Audit             │                                                                       │
└───────────────────┴─────────────────────────────────────────────────────────────────────────┘
```

### Persistent header facts

Always visible:

- application identity;
- environment: `SIM`, `PAPER`, `LIVE-CANARY`, `LIVE`;
- broker connection and account mode;
- data freshness/trust state;
- risk state;
- reconciliation state;
- kill-switch state if active;
- clock with timezone;
- critical alert count.

P&L is **not** a substitute for those facts.

## 4.2 Environment treatment

### PAPER
- explicit `PAPER` badge remains visible on every screen;
- mutation dialogs repeat `PAPER`;
- broker source specifies simulated gateway vs real IB PAPER;
- no language such as “live” for streaming data should imply live-capital execution.

### LIVE-CANARY
- only appears after explicit authorization evidence exists;
- persistent canary scope displayed: account, strategy, instrument, max size, expiry;
- visual shell treatment differs materially from PAPER;
- emergency controls permanently visible;
- no automatic scope expansion.

### LIVE
- out of scope until explicit production authorization exists.

---

# 5. Universal status semantics

Use semantic tokens, not ad-hoc page colors.

| State | Meaning | Interaction rule |
|---|---|---|
| **SAFE** | Required evidence is current and within deterministic constraints. | Normal permitted actions still require their own checks. |
| **DEGRADED** | System can continue observing but confidence/functionality is reduced. | Exposure increase may be blocked depending on dependency. |
| **STALE** | Required observation exceeded freshness threshold. | Exposure-increasing mutation blocked. |
| **UNKNOWN** | Truth cannot be established. | Fail closed. |
| **CONTRADICTORY** | Authorities disagree. | Fail closed; reconciliation required. |
| **BLOCKED** | Deterministic gate denied requested action. | Show exact reason codes and remediation. |
| **AMBIGUOUS** | External side effect may have occurred but acknowledgement is unresolved. | Never blind retry; reconcile. |
| **HALTED** | Kill switch or hard safety condition active. | Only explicitly permitted risk-reducing/emergency operations. |
| **SIMULATED** | State is generated by simulator, not real broker. | Never present as real IB PAPER evidence. |

### Display rule

Every status has:

- short human label;
- machine reason code;
- last-observed timestamp;
- age/freshness where applicable;
- source authority;
- details link.

---

# 6. Command Center — canonical home

## 6.1 Page objective

One-screen operational awareness. Detailed analysis belongs elsewhere.

## 6.2 Desktop anatomy

```text
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│ TRUST: SAFE         PAPER         IBKR PAPER        RECONCILED        KILL SWITCH: OFF  │
├──────────────────────┬──────────────────────┬──────────────────────┬─────────────────────┤
│ PORTFOLIO            │ TODAY                │ ACTIVE RISK          │ DATA TRUST          │
│ Equity               │ Realized P&L         │ Risk used            │ Fresh feeds         │
│ Buying power         │ Unrealized P&L       │ Open risk $          │ Stale feeds         │
│ Open positions       │ Trades               │ Drawdown             │ PIT/source status   │
├──────────────────────┴──────────────────────┬──────────────────────┴─────────────────────┤
│ MARKET / REGIME                            │ RISK GOVERNOR                              │
│ regime, volatility, session, catalysts     │ limits, blocks, kill switch, next gate     │
├─────────────────────────────────────────────┴────────────────────────────────────────────┤
│ TOP SETUPS / CANDIDATES                                                                  │
│ Symbol | Strategy | Direction | Conviction | Entry context | Risk qty | State | Reason   │
├─────────────────────────────────────────────┬────────────────────────────────────────────┤
│ OPEN POSITIONS                              │ ORDERS / RECONCILIATION                   │
│ broker-observed exposure + protection      │ pending/working/ambiguous/drift            │
├─────────────────────────────────────────────┴────────────────────────────────────────────┤
│ SYSTEM TAPE / ATTENTION QUEUE                                                              │
│ timestamp | domain | event | severity | correlation | action                              │
└──────────────────────────────────────────────────────────────────────────────────────────┘
```

## 6.3 Trust banner

The trust banner is computed from deterministic inputs such as:

- market-data freshness;
- account freshness;
- broker connectivity;
- broker reconciliation;
- risk/kill-switch state;
- required strategy evidence availability;
- system health required for the intended action.

It must not be computed by an LLM.

Possible states:

```text
SAFE
DEGRADED
BLIND
HALTED
UNKNOWN
```

`SAFE` means required operating dependencies are healthy; it never means “a trade should be placed.”

## 6.4 Top setups

A setup row must separate:

- market observation;
- strategy signal;
- confidence/calibration;
- strategy eligibility;
- risk eligibility;
- execution readiness;
- human approval state.

Do not collapse these into one opaque “score.”

Example row:

```text
MES | Momentum-v3.4 | LONG | 0.71 calibrated | signal valid | qty ceiling 1 | PAPER READY
Reason: fresh IB bars; strategy PAPER-qualified; risk $42/$50; no reconciliation drift
```

Blocked example:

```text
MNQ | ORB-v2.1 | LONG | 0.78 | BLOCKED
Reason: DATA_STALE: newest 1m bar age 184s > 90s threshold
```

---

# 7. Trade Workstation — `/trades`

## 7.1 Jobs

- review generated candidates;
- inspect deterministic risk preview;
- create manual PAPER TradeIntent;
- approve/reject candidates where policy requires;
- monitor order lifecycle;
- cancel/modify through canonical OMS semantics;
- inspect ambiguity/reconciliation;
- navigate to correlated audit evidence.

## 7.2 Manual futures workflow

```text
Enter symbol/side/order parameters
→ fetch fresh market/account/broker state
→ validate instrument + session + freshness
→ deterministic risk preview
→ requested quantity treated as ceiling
→ quantity may become 0 / NO_TRADE
→ show stop/target/protected-order structure
→ user confirms PAPER intent
→ create idempotent TradeIntent
→ atomic OMS claim
→ broker submit
→ ACK/FILL/REJECT/AMBIGUOUS
→ reconciliation
→ receipt + audit link
```

### Required pre-submit panel

- symbol + canonical instrument identity;
- side;
- order type / limit if applicable;
- market reference and timestamp;
- stop;
- target;
- requested quantity ceiling;
- risk-calculated quantity;
- dollar risk;
- risk-policy version;
- account equity source/age;
- market data source/age;
- environment;
- broker mode;
- deterministic blocks/warnings;
- idempotency/intent identity after preview.

### Confirmation copy must distinguish

- `PREVIEW` — no broker mutation;
- `SUBMIT PAPER ORDER` — broker/simulator mutation depending broker mode;
- `LIVE-CANARY` — only after explicit future authorization and separate treatment.

## 7.3 Ambiguous acknowledgement

When broker invocation may have occurred but the response is lost:

```text
Order state: AMBIGUOUS
Automatic retry: DISABLED
Next action: RECONCILE WITH BROKER
```

The UI must never show a generic “Try again” button for an exposure-increasing ambiguous mutation.

## 7.4 Candidate approval

Approval is not equivalent to execution. UI shows distinct states:

```text
CANDIDATE
→ APPROVED_FOR_EVALUATION
→ RISK_VALIDATED
→ INTENT_CREATED
→ SUBMISSION_CLAIMED
→ BROKER_STATE...
```

---

# 8. Portfolio — `/portfolio`

Display:

- broker-observed positions;
- internal reconciled projection;
- discrepancy indicator;
- realized/unrealized P&L with source/time;
- gross/net exposure;
- exposure by instrument/strategy/regime;
- open protective orders;
- capital utilization/margin;
- risk-at-stop;
- concentration and correlation;
- drill-down to fills and decision lineage.

### Non-negotiable

If broker and internal position disagree, the discrepancy is more prominent than P&L.

---

# 9. Risk Center — `/risk`

Display:

- current risk state;
- active policy version;
- effective time;
- daily loss used/remaining;
- drawdown;
- open trade risk;
- per-instrument risk;
- correlated exposure;
- position/contract limits;
- margin utilization;
- price sanity state;
- kill switch;
- recent blocks and reason codes;
- policy-change audit history.

### Risk change policy

No inline casual editing of capital-critical thresholds. Future risk-policy change UX must use versioned proposal → review → explicit activation with audit evidence.

---

# 10. Research Lab — `/research-lab`

Organize around evidence, not attractive charts.

Sections:

1. Hypothesis registry
2. Data/PIT coverage
3. Trial ledger
4. Backtest/replay
5. Purged/CPCV/walk-forward
6. Cost/slippage stress
7. Parameter sensitivity
8. Regime analysis
9. Source parity
10. Defects/leakage findings
11. Judge verdict and reasons
12. Promotion evidence

Every result displays:

- strategy/research fingerprint;
- dataset identity/window;
- availability semantics;
- code SHA;
- parameters;
- trial number / multiple-testing context;
- IS/OOS split;
- costs;
- sample size;
- known limitations;
- promotability state.

---

# 11. Strategies — `/strategies`

Strategy registry card:

```text
Name / Version
Lifecycle: RESEARCH | PAPER_CANDIDATE | PAPER | SUSPENDED | RETIRED
Evidence state
Eligible instruments
Eligible sessions/regimes
Risk profile
Code/data fingerprint
Last validation
Drift status
Known defects
Promotion history
```

No strategy self-promotes.

---

# 12. Capital Path — `/capital-path`

Display scenario and uncertainty explicitly:

- starting capital scenario;
- contribution/withdrawal assumptions;
- strategy ensemble;
- dependence-preserving resampling;
- return distribution;
- drawdown distribution;
- risk-of-ruin proxy;
- time-to-target distribution where meaningful;
- edge degradation;
- slippage/capacity sensitivity;
- risk-policy alternatives / Pareto frontier;
- confidence intervals;
- assumption registry.

The page must state that simulations are not guarantees or live authorization.

---

# 13. Intelligence — `/intelligence`

Advisory context:

- regime;
- volatility;
- session context;
- scheduled catalysts;
- macro/news/social summaries;
- model disagreements;
- confidence/calibration;
- provenance and timestamps.

LLM-generated text is visually labeled as analysis/advisory and never presented as a deterministic risk fact.

---

# 14. Data — `/data`

Primary purpose: prove input truth.

Display per source/instrument:

- connection status;
- latest observation timestamp;
- age;
- expected interval;
- quality result;
- provenance;
- PIT availability coverage;
- missing/duplicate/outlier counts;
- wrong-era checks;
- source disagreement;
- replay coverage;
- source-integrity fingerprint.

Stale/failing sources link directly to affected strategies/candidates.

---

# 15. Operations — `/operations`

Display:

- engine processes;
- component health;
- runtime version/SHA;
- environment;
- queues;
- scheduled jobs;
- DB/storage health;
- event-stream health;
- recent restarts;
- reconciliation health;
- incidents;
- degraded dependencies;
- CI/deploy evidence link;
- current canonical-serving-tree state.

This is where useful mission-control concepts from existing routes may be harvested.

---

# 16. Broker — `/broker`

Broker truth page:

- connector type: simulator vs real IB PAPER vs future live;
- account identifier in appropriately masked form;
- connection health;
- TWS/Gateway mode/port classification;
- broker-observed positions;
- open orders;
- recent fills;
- execution errors;
- reconciliation discrepancies;
- request/ack timestamps;
- protective-order relationships;
- emergency operator instructions.

The page explicitly states that TWS/IB remains an independent operator truth/fallback during PAPER and LIVE canary.

---

# 17. Learning — `/learning`

Display:

- realized vs expected performance;
- calibration/Brier-style metrics;
- slippage drift;
- strategy degradation;
- regime-specific outcomes;
- block reason frequency;
- false-positive/false-negative review where definable;
- proposed experiments;
- recommendations awaiting human review.

Learning may propose; it may not activate risk/strategy/capital changes.

---

# 18. Audit — `/audit`

Searchable lineage across:

```text
market observation
→ feature observation
→ signal
→ candidate
→ risk decision
→ approval
→ TradeIntent
→ OMS transitions
→ broker order
→ fill
→ position
→ realized outcome
→ learning record
```

Filters:

- correlation ID;
- symbol;
- strategy/version;
- environment;
- event kind;
- intent/order/fill ID;
- reason code;
- time;
- operator/actor;
- policy version.

---

# 19. Real-time data model

## 19.1 Observation transport

Preferred:

- SSE/WebSocket for high-frequency projections and event tape;
- reconnect with last-event/cursor where supported;
- projection timestamps included in payload;
- stale threshold evaluated server-side and may also be rendered client-side.

## 19.2 Commands

Use HTTP commands with:

- authentication/authorization;
- stable idempotency key;
- intent/request ID;
- expected environment;
- expected version/precondition where useful;
- deterministic validation;
- explicit success/block/ambiguity response.

## 19.3 Never infer mutation success from connection state

A lost HTTP response or stream disconnect is not proof an order failed. The next UI state must query/reconcile by intent/idempotency/broker identity.

---

# 20. Data provenance component

Any capital-relevant fact supports an expandable provenance row:

```text
Source: IBKR
Observed: 09:42:03.214 CT
Age: 1.8 s
Quality: PASS
Authority: broker_position
Reconciled: yes
Correlation: corr_...
```

For research facts:

```text
Dataset fingerprint
Availability timestamp policy
Feature version
Trial fingerprint
Code SHA
```

---

# 21. Confirmation and control patterns

## 21.1 Exposure-increasing mutation

Require:

1. preview;
2. deterministic validation result;
3. explicit environment display;
4. protection/risk display;
5. human confirmation when manual workflow requires it;
6. idempotent command;
7. lifecycle receipt.

## 21.2 Risk-reducing mutation

Cancel/flatten controls may use a faster path, but still require:

- exact target identity;
- current broker state;
- explicit result;
- audit event;
- reconciliation.

## 21.3 Emergency flatten/halt

Design principles:

- visually isolated from routine actions;
- impossible to trigger by ordinary navigation accident;
- confirmation states exact scope;
- action routes through deterministic safety authority;
- result reports broker observations and unresolved positions/orders;
- kill-switch state persists according to adopted safety semantics;
- recovery/reset requires explicit human action.

---

# 22. Failure and degraded states

The product must be intentionally designed for these states:

1. engine unavailable;
2. broker unavailable;
3. market data stale;
4. account data stale;
5. position disagreement;
6. open-order disagreement;
7. persistence unavailable;
8. event stream unavailable but command API reachable;
9. command response lost after broker invocation;
10. kill switch active;
11. strategy evidence unavailable;
12. risk policy unavailable/unknown;
13. authentication expired;
14. CI/deployed-version mismatch;
15. source-integrity failure.

For each state, specify:

- what the operator sees;
- what is disabled;
- what remains available;
- whether exposure increase is permitted (default: no when relevant truth is unknown);
- recovery action;
- audit behavior.

---

# 23. Accessibility and responsive behavior

Minimum requirements:

- keyboard navigable;
- visible focus states;
- no status conveyed by color alone;
- sufficient contrast;
- status text and icons include accessible labels;
- tables remain usable at common laptop resolutions;
- critical states do not require hover;
- responsive narrow mode prioritizes Trust/Risk/Broker/Positions/Alerts before analytics;
- motion can be reduced;
- numeric formatting preserves sign/unit/context.

Mobile is primarily supervisory initially; exposure-increasing order-entry may remain desktop-only until independently designed and validated.

---

# 24. Visual hierarchy

Order of prominence:

1. Environment / halt / trust
2. Broker + reconciliation
3. Data freshness
4. Current exposure and risk
5. Pending mutation/ambiguity
6. Human attention queue
7. Candidates/opportunities
8. Performance
9. Research/intelligence detail

A profitable P&L must never visually overpower a safety or reconciliation defect.

---

# 25. K-MIG-001 — V2 to canonical migration

Existing `/command-center-v2` is treated as a source inventory.

## Step 1 — Census

For every V2 component, record:

- source route/component;
- data reads;
- mutations;
- refresh model;
- degraded behavior;
- canonical destination;
- keep/rework/drop decision;
- tests/evidence available.

## Step 2 — Authority check

Prove that:

- browser does not directly own broker/risk truth;
- mutations route through server safety/OMS;
- stale/unknown states fail closed;
- no hidden duplicate execution path is introduced.

## Step 3 — Component harvest

Move/reimplement components into canonical surfaces while preserving or strengthening tests.

## Step 4 — Parity

Compare V2 and canonical behavior for agreed functions, including failure states.

## Step 5 — V3 acceptance

Run operator E2E and visual review on the canonical routes.

## Step 6 — Redirect/deprecate

Only after parity and rollback evidence:

```text
V2 ACTIVE-UNADOPTED
→ SHADOW/PARITY
→ CANONICAL COMPLETE
→ REDIRECTED
→ DEPRECATED
→ REMOVED
```

No step is authorized by this document alone.

---

# 26. Design acceptance matrix

| Capability | Code exists? | Rendered? | V3 E2E? | V4 PAPER? | Can claim delivered? |
|---|---:|---:|---:|---:|---:|
| Route scaffold only | yes | maybe | no | no | **No** |
| Static visual mockup | yes | yes | no | no | **Design proof only** |
| Interactive canonical shell | yes | yes | partial | no | **Prototype** |
| Canonical workflows + failure states | yes | yes | yes | no | **Operator product implemented** |
| Integrated real PAPER operation | yes | yes | yes | yes | **PAPER-qualified product** |
| LIVE canary | yes | yes | yes | yes + V5 | only with explicit capital authorization |

---

# 27. Definition of UI Done

The canonical operator product is not “done” until:

- [ ] `/command-center` is the implemented canonical shell;
- [ ] target IA is navigable;
- [ ] component inventory/migration from V2 is complete;
- [ ] no permanent duplicate Command Center exists;
- [ ] desktop visual review completed;
- [ ] critical narrow/responsive view reviewed;
- [ ] accessibility baseline passes;
- [ ] unit/component tests pass;
- [ ] V3 E2E covers normal and degraded workflows;
- [ ] stale/unknown/contradictory states visibly fail closed;
- [ ] PAPER and broker-mode distinctions are unmistakable;
- [ ] Trade Workstation uses canonical OMS rather than a parallel mutation path;
- [ ] ambiguous acknowledgement has no blind retry path;
- [ ] broker/internal discrepancies are prominently displayed;
- [ ] emergency controls have safety-reviewed semantics;
- [ ] audit links connect operator actions to lifecycle evidence;
- [ ] V4 PAPER campaign validates integrated behavior where claimed.

---

# 28. First implementation slices after spec adoption

1. **K-01A — Canonical shell and semantic status system**
2. **K-01B — V2 component/read/mutation census**
3. **K-02A — Command Center read-only projection**
4. **K-02B — degraded/unknown-state test harness**
5. **K-03A — Trade Workstation preview on canonical OMS contract**
6. **K-03B — PAPER submission + ambiguity/reconciliation visualization**
7. **K-04 — Portfolio/Risk/Broker truth triad**
8. **K-05 — Audit lifecycle explorer**
9. **K-06 — Research/Strategy evidence surfaces**
10. **K-07 — visual/accessibility/E2E acceptance campaign**

No new exposure-increasing backend capability is required merely to start K-01/K-02; the initial implementation should favor read-only truth and migration containment.

---

# 29. Final product rule

> **The Command Center earns trust by exposing uncertainty and authority boundaries, not by making JARVIS look certain.**
