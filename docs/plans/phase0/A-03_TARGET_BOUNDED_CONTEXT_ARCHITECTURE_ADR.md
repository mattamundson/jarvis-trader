# A-03 — Target Bounded-Context Architecture ADR

**Plan:** JARVIS-MIP-1.0  
**Program:** A — Platform & Architecture  
**Phase:** MIP-0  
**Decision class:** D0 design, future runtime boundary  
**Safety class:** S0 document, with S2/S3 downstream implications  
**State:** **DRAFT COMPLETE — ADOPTION BLOCKED BY A-01/A-02 AND PR #768**  
**Depends on:** A-01, A-02  
**Required for:** A-04, B/H/I/J/K/M foundations, ISG-0

## 1. Decision

JARVIS will remain a **single-repository modular monolith first**. The engine will be decomposed into explicit bounded contexts with one composition root, one mutation spine and versioned cross-context contracts. Network-service extraction is prohibited until profiling, failure isolation, scaling or deployment evidence demonstrates a measured need.

The architecture optimizes first for determinism, replayability, auditability, safety and operator clarity—not for microservice count.

## 2. Target system shape

```text
COMMAND CENTER
  │
  │ HTTP commands / WS-SSE observations
  ▼
API + COMPOSITION ROOT
  │
  ├── core
  ├── data
  ├── features
  ├── research
  ├── judge
  ├── strategies
  ├── portfolio
  ├── risk
  ├── execution
  ├── brokers
  ├── capital_path
  ├── intelligence
  ├── observability
  └── api
        │
        ▼
TradeIntent → Portfolio/Risk → OMS → Broker Adapter → Reconcile
        │                                           │
        └────────────── Audit/Event Ledger ◄────────┘
```

`engine/main.py` becomes bootstrap/composition only. Domain logic must migrate out of the composition root over time.

## 3. Bounded contexts

| Context | Owns | Must not own |
|---|---|---|
| `core` | shared IDs, clocks, money/qty/value objects, environment identity, contract primitives | business-specific persistence or broker calls |
| `data` | provider adapters, market observations, calendars/session interpretation, PIT availability, dataset manifests | strategy decisions, order placement |
| `features` | feature registry/compiler/store, versioning, causal/parity metadata | promotion verdicts or broker state |
| `research` | hypotheses, immutable trials, experiment orchestration, falsification artifacts | eligibility activation, active risk |
| `judge` | evidence bundles, lifecycle registry, statistical gates, degradation/retirement | broker routing, strategy self-promotion |
| `strategies` | deterministic candidate generation using approved inputs | position sizing authority, broker orders, risk overrides |
| `portfolio` | account projection, exposure, allocation, attribution, portfolio heat | broker truth ownership, active risk policy editing |
| `risk` | versioned risk policy, sizing, limits, halts, exposure checks | strategy alpha logic, LLM decisions |
| `execution` | TradeIntent contracts, OMS state machine, idempotency, order lifecycle | instrument discovery, research verdicts |
| `brokers` | IBKR adapter, contract mapping, transport, broker acknowledgements, broker observations | portfolio policy, strategy logic |
| `capital_path` | path simulations, ruin/target distributions, risk-policy sensitivity | active risk policy writes |
| `intelligence` | LLM/advisory context, critique, explanations, classification | hard safety, sizing, live enablement, broker mutation |
| `observability` | events, metrics, health, alerts, audit projections | canonical domain decision authority |
| `api` | transport models, auth boundary, request/response mapping | hidden business rules or duplicate state machines |

## 4. Dependency direction

The architecture uses inward, explicit dependencies. Domain contexts depend on contracts, not on FastAPI routers or dashboard models.

Allowed conceptual direction:

```text
api -> application/domain contracts
strategies -> data/features + judge eligibility read model
portfolio -> broker/account projection + core
risk -> portfolio + instrument/core contracts
execution -> eligibility/portfolio/risk contracts
brokers -> core execution transport contracts
observability -> domain events/read models
intelligence -> read-only context contracts
```

Prohibited:

- strategy -> broker adapter;
- dashboard -> broker;
- LLM -> risk mutation;
- router -> direct parallel broker state machine;
- feature code -> eligibility mutation;
- research code -> lifecycle PASS write;
- Redis/cache -> canonical domain truth;
- domain module importing `main.py` for runtime objects.

## 5. Canonical mutation spine

Every exposure-increasing order must traverse:

```text
Strategy/Human
  → TradeIntent
  → Eligibility check
  → Portfolio constraints
  → Risk policy + server sizing
  → Atomic OMS claim
  → Broker adapter
  → ACK/FILL/REJECT/AMBIGUOUS
  → Reconciliation
  → Audit + position projection
```

No second “manual order path,” “AI order path,” “approval order path,” or strategy-specific broker shortcut may remain authoritative.

Risk-reducing cancel/reduce/flatten commands may use specialized command types but still require authenticated identity, verified necessary broker state, durable audit and the same broker adapter/reconciliation domain.

## 6. OMS state contract

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

Additional recovery states may be introduced through I-02, but these invariants are fixed:

1. one durable state transition history;
2. atomic route claim;
3. request fingerprint/idempotency;
4. no automatic retry after ambiguous broker outcome;
5. partial-fill accounting;
6. restart recovery;
7. broker reconciliation before exposure truth is considered settled;
8. protective-order state linked to parent exposure where the broker supports it.

## 7. Data and time contracts

All decision-capable observations use the PIT contract:

```text
event_at
published_at        # when applicable
received_at
available_at
computed_at
known_at=max(available_at, computed_at)
decision_at
```

A feature is invalid for a decision when `known_at > decision_at`.

Executable market observations additionally require:

- approved provider class;
- resolved Instrument Master contract;
- correct session policy;
- acceptable freshness;
- quality/provenance pass;
- no unresolved fallback ambiguity.

## 8. Persistence architecture

### Operational through PAPER

SQLite/WAL remains the operational baseline. Domain repositories must own persistence access; routers and UI adapters should not embed SQL.

### Research

Immutable Parquet + manifests + DuckDB remain the research baseline. Mutable caches may accelerate reads but do not replace manifests/evidence identity.

### Redis

Optional for cache/realtime coordination only. It is never canonical state.

### Future datastore split

Postgres, QuestDB or service extraction require a new ADR with measured evidence. “Enterprise architecture” by itself is not sufficient justification.

## 9. Current-repository migration map

A-01 identified multiple overlapping execution authorities (`ib_gateway.py`, `ib_gateway_connector.py`, `ib_order_manager.py`, `ibkr_executor.py`, `oms_v2.py`, `order_router.py`, routing factories). A-03 does not select the survivor implementation by filename. J-02/I-02 must inventory behavior, define the target interfaces and harvest only the strongest pieces into the single spine.

Likewise, current routers, analytics, paper trackers and dashboard pages may remain temporarily while read models are migrated. Existing code is not declared obsolete merely because the target context name differs.

Migration order:

1. **A-04** define versioned core contracts and dependency rules.
2. **B-01** Instrument Master.
3. **H-01** active Risk Policy artifact.
4. **M-01** event/audit envelope.
5. **N-02** environment/authorization matrix.
6. **B/C/E** PIT data, feature and Judge contracts.
7. **F/H** canonical portfolio/risk evaluation.
8. **I-02/J-02/J-03** OMS/broker/reconciliation consolidation.
9. **K-01/K-xx** operator surfaces migrate to canonical read/command contracts.
10. Remove duplicate authorities only after equivalence/recovery evidence exists.

## 10. Composition-root rules

`main.py` may:

- load environment/config;
- instantiate repositories/services/adapters;
- wire dependency injection;
- start/stop schedulers and transports;
- expose health of constructed dependencies.

`main.py` should not own:

- risk algorithms;
- strategy logic;
- raw SQL business queries;
- broker-order lifecycle rules;
- eligibility rules;
- feature formulas;
- dashboard-specific financial transformations.

## 11. API boundary

Commands use authenticated HTTP mutations. Realtime observations use WebSocket or SSE where useful. The UI never holds broker credentials.

Every executable command must carry or resolve:

- actor/request identity;
- environment;
- command/idempotency identity;
- instrument identity;
- required policy/evidence versions;
- server-resolved authoritative state;
- durable outcome/audit reference.

## 12. Failure model

Exposure-increasing paths fail closed on:

- unknown/stale/ambiguous broker state;
- unknown active risk policy;
- unresolved instrument contract;
- stale or invalid executable market data;
- absent/expired eligibility;
- reconciliation mismatch;
- duplicate/ambiguous OMS claim;
- environment authorization uncertainty.

Read-only research/observability may degrade and surface partial state, but must label it.

## 13. Service-extraction criteria

A context may become a separate deployable service only when at least one is demonstrated:

- independent scaling requirement with measured saturation;
- fault-isolation requirement not achievable in-process;
- materially different deployment/security boundary;
- independent data-retention/throughput requirement;
- operational ownership boundary that reduces, rather than increases, system risk.

Any split must preserve deterministic contracts, idempotency, traceability and replay.

## 14. Spike disposition

- PR #749: harvest research/feature/Trial/Judge/Capital Path primitives into their contexts; never merge as one architecture bundle.
- PR #754: harvest control-plane patterns into the one canonical K-01 product; do not create permanent V2/V3 product trees.
- PR #756: harvest durable intent/idempotency/ambiguous-outcome patterns after H/I/J contracts are established.
- RT-3: frozen until M4/M6 dependencies.

## 15. Acceptance criteria

- [x] Bounded contexts and ownership are explicit.
- [x] One mutation spine is explicit.
- [x] Dependency direction prohibits strategy/UI/LLM-to-broker shortcuts.
- [x] Modular-monolith-first decision is explicit.
- [x] PIT/time contract is embedded in architecture.
- [x] Persistence baseline is explicit without premature migration.
- [x] Existing execution overlap is treated as a migration problem, not silently blessed.
- [x] Composition-root responsibilities are bounded.
- [x] Fail-closed architecture states are explicit.
- [ ] A-02 adopted after A-01 evidence.
- [ ] PR #768 adopted.
- [ ] Human review marks A-03 `ADOPTED`.

## 16. Decision status

**Draft decision:** ACCEPTED FOR REVIEW.  
**Runtime implementation authorization:** NOT GRANTED.  
**ISG-0 credit:** none until dependency ADRs are adopted.
