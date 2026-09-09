# A-03 — Target Bounded-Context Architecture ADR

**Parent product candidate:** `JARVIS-MPP-1.0` (#789 / GOV-01 #791)  
**Implementation mapping:** `JARVIS-MIP-1.0` where still applicable  
**Program:** A — Platform & Architecture  
**Phase:** Phase 0 / ISG-0 design  
**Decision class:** design / future runtime boundary  
**Safety class:** S0 document with S2/S3 downstream implications  
**State:** **DRAFT CURRENT-MASTER REFRESH — ADOPTION BLOCKED BY GOV-01 + A-01/A-02**  
**Observed repository baseline:** `master@6afe8970b8a588a3b67131d960fe47bee6fa40cf`  
**Required for:** A-04, B/H/I/J/K/M foundations and authority migrations

## 1. Decision

JARVIS will remain a **single-repository modular monolith first** with explicit bounded contexts, one composition root, one exposure-increasing mutation spine, and versioned cross-context contracts.

Network-service extraction is deferred until measured scaling, fault-isolation, deployment, data-retention, or security evidence demonstrates a need.

The architecture optimizes for determinism, replayability, auditability, safety, recovery, and operator clarity before microservice count or autonomy.

## 2. Target system shape

```text
CANONICAL OPERATOR PRODUCT
        │
        │ HTTP commands / SSE-WS observations
        ▼
API + COMPOSITION ROOT
        │
        ├── core
        ├── data
        ├── features
        ├── research
        ├── strategy_lifecycle
        ├── strategies
        ├── portfolio
        ├── risk
        ├── execution / OMS
        ├── brokers / reconciliation
        ├── capital_path
        ├── intelligence
        ├── observability / audit
        └── authorization
                │
                ▼
Human / Strategy
→ TradeIntent
→ Eligibility
→ Portfolio constraints
→ RiskDecision / server sizing
→ Atomic OMS claim
→ Broker adapter
→ ACK / REJECT / AMBIGUOUS / FILL
→ Reconciliation
→ Audit + projections
```

`engine/main.py` should converge toward bootstrap/composition only. Domain logic migrates out of the composition root over time.

## 3. Bounded contexts

| Context | Owns | Must not own |
|---|---|---|
| `core` | IDs, clocks, money/qty/value objects, environment identity, shared contract primitives | broker calls, business persistence policy |
| `data` | provider adapters, market observations, calendars/sessions, PIT availability, dataset manifests | strategy decisions, order placement |
| `features` | feature registry/compiler/store, formula/version/causality/parity metadata | strategy promotion, broker state |
| `research` | hypotheses, immutable trials, experiment orchestration, falsification evidence | active eligibility or risk mutation |
| `strategy_lifecycle` | evidence bundles, lifecycle registry, promotion/demotion/degradation/retirement | broker routing |
| `strategies` | deterministic candidate generation from approved inputs | sizing authority, risk overrides, broker orders |
| `portfolio` | account projection, exposure, allocation, attribution, portfolio heat | broker truth ownership, risk-policy editing |
| `risk` | versioned policy, sizing, limits, halts, price sanity, exposure checks | alpha logic or LLM discretion |
| `execution` | TradeIntent, OMS lifecycle, idempotency, claims, protection, cancel/replace, ambiguity/restart semantics | research verdicts, instrument discovery |
| `brokers` | IBKR/other adapters, transport, broker observations, contract qualification, reconciliation inputs | strategy/risk policy |
| `capital_path` | path simulations, dependence-aware stress, capacity/risk sensitivity | active capital-policy writes |
| `intelligence` | advisory LLM/context synthesis, critique, explanations | hard safety, sizing, live enablement, broker mutation |
| `observability` | events, metrics, health, traces, audit projections, incident evidence | canonical business decision authority |
| `authorization` | environment/permission/capital-authorization evidence | strategy alpha, broker transport |
| `api` | transport/auth boundary, request/response mapping | hidden duplicate business rules/state machines |

## 4. Dependency direction

Conceptually allowed:

```text
api → application/domain contracts
strategies → data/features + lifecycle eligibility read model
portfolio → broker/account projection + core
risk → portfolio + instrument/core contracts
execution → eligibility + portfolio + risk contracts
brokers → execution transport contracts + instrument identity
observability → domain events/read models
intelligence → read-only context contracts
```

Prohibited:

- strategy → broker adapter;
- dashboard/browser → broker credential or direct IB mutation;
- LLM → risk/authorization mutation;
- router → independent broker lifecycle state machine;
- feature/research code → promotion eligibility mutation;
- cache/Redis → canonical truth;
- domain module → `main.py` runtime object import;
- active trading code importing draft `engine.domain.*` authorities before migration adoption.

## 5. Canonical exposure-increasing mutation spine

Every exposure-increasing action must traverse one canonical server-side path:

```text
Strategy / Human
→ TradeIntent
→ instrument + session resolution
→ strategy/manual authorization
→ portfolio constraints
→ deterministic risk policy + server sizing
→ quantity may become zero / NO_TRADE
→ atomic OMS claim
→ broker adapter
→ durable ACK / REJECT / AMBIGUOUS / PARTIAL / FILL state
→ reconciliation
→ audit + position projection
```

No permanent second manual path, AI order path, approval path, or strategy-specific broker shortcut may remain authoritative.

Risk-reducing cancel/reduce/flatten commands may use specialized command types, but still require authenticated identity, verified necessary broker state, audit evidence, canonical broker transport, and reconciliation.

## 6. Current dual-authority reality

This ADR does **not** pretend the target already exists.

Current master contains:

### Manual order mutations

- `POST /orders/place` — legacy/transitional multi-asset manual route.
- `POST /trade-intents/preview` and `POST /trade-intents/{intent_id}/submit` — merged #756, active-unadopted manual futures PAPER candidate.

I-MIG-001 in #786 governs their comparison and eventual consolidation. Neither is declared canonical by this ADR.

### Operator product

- `/command-center-v2` and `/command-center-v2/trade` from merged #754 are active-unadopted migration sources.
- The proposed canonical IA is defined by `docs/product/COMMAND_CENTER_PRODUCT_SPEC.md` in #789.
- K-MIG-001 in #786 governs V2 census/parity/redirect/deprecation.

No route is redirected or removed by this document.

## 7. OMS lifecycle contract

The target OMS must support at minimum:

```text
CREATED
→ VALIDATED
→ CLAIMED
→ ROUTING
→ ACKNOWLEDGED | REJECTED | AMBIGUOUS
→ PARTIALLY_FILLED | FILLED | CANCEL_PENDING | CANCELLED
→ RECONCILED
```

Required invariants:

1. one durable lifecycle history;
2. atomic route claim;
3. stable request fingerprint/idempotency;
4. no automatic submit retry after a broker call may have occurred;
5. explicit ambiguity/reconciliation state;
6. partial-fill accounting;
7. restart recovery;
8. broker reconciliation before exposure is considered settled;
9. protective child/order relationships linked to parent exposure;
10. external side effects outrank optimistic local state.

## 8. Data/time contract

Decision-capable observations use point-in-time semantics such as:

```text
event_at
published_at        # when applicable
received_at
available_at
computed_at
known_at = max(available_at, computed_at)
decision_at
```

A feature is invalid for a decision when `known_at > decision_at`.

Executable observations additionally require:

- canonical Instrument Master resolution;
- correct session/calendar semantics;
- approved provider/source class;
- acceptable freshness;
- provenance/quality pass;
- no unresolved fallback contradiction.

## 9. Persistence architecture

### Operational through current PAPER baseline

SQLite/WAL remains the current local operational baseline where configured. Persistence access should converge behind domain repositories rather than SQL embedded in routers/UI adapters.

### Research

Immutable Parquet/manifests with deterministic query/replay tooling remain appropriate research foundations. Mutable caches accelerate access but do not replace evidence manifests.

### Redis/cache

Optional coordination/cache only. Never canonical authority.

### Future datastore/service split

Postgres, QuestDB, separate services, or other infrastructure changes require measured evidence and a separate ADR/migration receipt. “Enterprise architecture” by itself is not sufficient justification.

## 10. Composition-root rules

`main.py` may:

- load environment/config;
- instantiate repositories/services/adapters;
- wire dependencies;
- start/stop schedulers/transports;
- expose construction/health state.

`main.py` should not own:

- risk algorithms;
- strategy logic;
- raw SQL business rules;
- broker order lifecycle;
- eligibility/promotion rules;
- feature formulas;
- dashboard-specific financial transformations.

## 11. API/transport boundary

Commands use authenticated HTTP mutations. Streaming observations may use SSE/WebSocket.

Every exposure-changing command must carry or resolve:

- actor/request identity;
- environment;
- authorization scope;
- idempotency/intent identity;
- canonical instrument identity;
- required policy/evidence versions;
- server-resolved authoritative state;
- durable outcome/audit reference.

A dropped stream or lost HTTP response never causes an automatic exposure mutation replay.

## 12. Failure model

Exposure-increasing paths fail closed on:

- unknown/stale/contradictory broker state;
- unknown active risk policy;
- unresolved instrument identity;
- stale/invalid executable market data;
- absent/expired strategy/manual authorization;
- reconciliation mismatch;
- duplicate/ambiguous OMS claim;
- persistence uncertainty after possible broker side effect;
- environment/capital authorization uncertainty.

Read-only research/observability may degrade and surface partial state, but must label it explicitly.

## 13. Service-extraction criteria

A context becomes a separate deployable service only when at least one is measured:

- independent scaling saturation;
- fault-isolation requirement not reasonably achievable in-process;
- materially different deployment/security boundary;
- independent throughput/retention need;
- operational ownership boundary that reduces overall risk.

Any split preserves deterministic contracts, idempotency, traceability, replay, and migration rollback.

## 14. Current migration order

1. **GOV-01** — explicit parent product-plan decision.
2. **A-01** — real host/runtime evidence and contradiction disposition.
3. **A-02/A-03** — adopt authority/dependency architecture.
4. **A-04/B-01/M-01/N-02/H-01/I-01** — adopt inert contracts authority-by-authority from #788.
5. **I-MIG-001** — shadow/parity/recovery path for `/orders/place` vs TradeIntent.
6. **K-MIG-001** — canonical read-only shell/projection and V2 migration.
7. **B/C research foundation** — PIT data/features/trial/evidence lifecycle.
8. **I/J execution consolidation** — one OMS/broker/reconciliation path.
9. **K operator migration** — canonical surfaces use adopted read/command contracts.
10. Old authorities become read-only/deprecated/removed only after parity, failure, restart, reconciliation, rollback, and required human approvals.

## 15. Relationship to legacy architecture PR #774

This file is the clean current-master refresh of the A-03 design intent from #774.

Changes from the stale version include:

- removes dependency on PR #768 adoption as a prerequisite;
- makes GOV-01/#789 the proposed parent product decision;
- explicitly records #754/#756 as **ACTIVE-UNADOPTED**, not frozen spikes;
- points operator-product migration to #789 + K-MIG-001;
- points execution migration to #786/#788 rather than inventing a new third path;
- retains modular-monolith-first, PIT, one mutation spine, fail-closed uncertainty, and broker-reconciliation invariants.

## 16. Acceptance criteria

- [x] Bounded contexts and ownership are explicit.
- [x] One target exposure-increasing mutation spine is explicit.
- [x] Dependency direction prohibits strategy/UI/LLM broker shortcuts.
- [x] Modular-monolith-first is explicit.
- [x] PIT/time contract is embedded.
- [x] Persistence baseline avoids premature migration.
- [x] Active dual manual-order paths are treated as migration debt, not silently blessed.
- [x] Active V2 product is treated as migration source, not canonical destination.
- [x] OMS ambiguity/restart/reconciliation requirements are explicit.
- [x] Fail-closed architecture states are explicit.
- [ ] GOV-01 parent hierarchy explicitly adopted/revised.
- [ ] A-01 host evidence completed or remaining blockers explicitly retained.
- [ ] A-02 adopted.
- [ ] Human architecture review marks A-03 `ADOPTED` with effective SHA.

## 17. Decision status

**Draft decision:** READY FOR REVIEW.  
**Runtime implementation authorization:** NONE.  
**Route/authority cutover authorization:** NONE.  
**PAPER/LIVE/capital authorization:** NONE.
