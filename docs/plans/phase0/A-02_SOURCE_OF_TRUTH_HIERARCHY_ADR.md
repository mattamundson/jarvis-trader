# A-02 — Source-of-Truth Hierarchy ADR

**Plan:** JARVIS-MIP-1.0  
**Program:** A — Platform & Architecture  
**Phase:** MIP-0  
**Decision class:** D0 planning / future authority contract  
**Safety class:** S0 document, with S3/S4 implications  
**State:** **DRAFT COMPLETE — ADOPTION BLOCKED BY A-01 AND PR #768**  
**Depends on:** A-01 contradiction register, O-01 CI baseline  
**Required for:** A-03, H-01, M-01, N-02, ISG-0

## 1. Decision

JARVIS will use a domain-specific source-of-truth hierarchy rather than one global datastore or one configuration file. Every operator-visible or execution-relevant fact must resolve to exactly one canonical authority for its domain, with provenance, freshness and version metadata sufficient to determine whether the fact may be used.

No UI, README, cached response, LLM output, historical report or duplicate service may silently override a canonical authority.

This ADR defines **which class of source is authoritative**. It intentionally does not choose unresolved runtime risk values from A-01. H-01 will create the versioned active Risk Policy values after A-01 observes the actual machine.

## 2. Canonical hierarchy by domain

| Domain | Canonical authority | Required metadata | Non-authoritative examples |
|---|---|---|---|
| Broker account identity | Verified broker API | account alias/redacted ID, environment, observed_at, freshness | README, `.env.example`, UI labels |
| Executable positions | Verified broker API reconciled into JARVIS | symbol/contract, qty, avg price, broker timestamp, reconcile timestamp | tracker-only position, cached dashboard state |
| Open broker orders / fills | Verified broker API | broker IDs, state, timestamps, contract, reconcile status | local pending-order guess |
| JARVIS intents / decisions | Durable operational ledger | intent ID, fingerprint/idempotency key, actor, policy/evidence versions, timestamps | browser state, logs alone |
| JARVIS order lifecycle | Single OMS durable state machine | order/intent linkage, transition sequence, broker ack/reject/ambiguous state | parallel router-specific state |
| Operational ledger through PAPER | SQLite/WAL | schema version, DB identity, transaction timestamps, backup status | JSONL duplicate truth |
| Runtime risk policy | **Target:** versioned Risk Policy artifact + active hash; **Phase-0 interim:** loaded runtime config enforced by SafetyLayer | policy version/hash, loaded_at, environment, activation actor | docs, defaults, stale `.env.example` |
| Trading eligibility | Judge lifecycle registry keyed by strategy+instrument+TF+version | evidence bundle hash, lifecycle state, decided_at, expiry/degradation state | static PASS tables, symbol-wide flags |
| Instrument metadata | Instrument Master | version, exchange, timezone, sessions, tick/point/multiplier, contract resolution | scattered constants |
| Research dataset | Immutable dataset manifest + content hashes | provider, contract mapping, session policy, time range, content hash | mutable local cache filename alone |
| Feature definition | Versioned Feature Registry | source identity, formula version, causal status, parity status | same-name feature aliases |
| Feature observation | PIT Feature Store | event/published/received/available/computed/known timestamps, feature version | recomputed value without availability history |
| Research attempt | Preregistered Trial Ledger | hypothesis ID, parameter space, dataset/evidence versions, result including reject | selected winning notebook/result only |
| Strategy verdict | Judge Evidence Bundle + lifecycle registry | trial accounting, validation metrics, holdout/paper/canary evidence versions | README headline, prior Phase-3 status |
| Capital Path result | Versioned simulation report | model/resampling/risk assumptions, seed/run ID, evidence inputs | account-equity claim or risk policy |
| Runtime environment authorization | N-02 environment/authorization policy | environment ID, credential class, mutation rights, activation evidence | boolean flag alone |
| Operator UI | Never authority; server contracts only | source/provenance/freshness/version displayed | browser-calculated financial truth |
| Implementation plan | JARVIS-MIP + adopted ADR/WP evidence | plan version, WP ID, decision status | historical “complete” docs |

## 3. Authority rules

### 3.1 Broker truth

For executable account state, verified broker state outranks local state. JARVIS may maintain a local projection for latency, history and audit, but any disagreement that affects exposure must be explicit and exposure-increasing mutations must fail closed until reconciliation resolves it.

A local projection may never be relabeled as broker-verified merely because the broker is temporarily unreachable.

### 3.2 Operational truth

Through PAPER, SQLite/WAL is the canonical JARVIS operational ledger for intents, decisions, audit and local lifecycle state. JSONL may be retained as an export or emergency no-database fallback only where explicitly documented; it is not a second canonical ledger when SQLite is configured.

### 3.3 Risk truth

Until H-01 lands, A-01 must report the values actually loaded by the running process and SafetyLayer remains the enforcement authority. Git defaults and examples are evidence of possible configuration, not proof of runtime policy.

After H-01, one versioned Risk Policy artifact becomes the policy authority. Activation must produce an immutable policy hash and audit event. No LLM, UI or strategy may write the active policy.

### 3.4 Eligibility truth

Eligibility is not symbol-wide. The canonical key is at minimum:

```text
strategy_id + strategy_version + instrument_id + timeframe + evidence_bundle_version
```

Static Markdown status tables may summarize the registry but never authorize execution.

### 3.5 Research truth

Research datasets, feature versions, trial attempts and Judge evidence must be immutable or content-addressed enough to replay the claim. A result without dataset/feature/trial/evidence identity is informational only.

Failed/rejected trials remain part of truth and may not be deleted to improve apparent performance.

### 3.6 UI truth

The dashboard is a projection. It may request commands but may not originate broker facts, risk limits, eligibility, position size or financial totals that the server has not independently resolved. `UNAVAILABLE`, `STALE`, `UNKNOWN` and `AMBIGUOUS` are first-class states and must not be rendered as zero.

## 4. Freshness and uncertainty semantics

Every executable fact must be one of:

- `VERIFIED_FRESH`
- `VERIFIED_STALE`
- `UNKNOWN`
- `AMBIGUOUS`
- `UNAVAILABLE`

Only `VERIFIED_FRESH` may support exposure-increasing execution unless a later adopted policy explicitly permits a narrower safe case. Risk-reducing cancel/reduce/flatten operations remain separately governed and must retain availability when their required command identity and broker state are verified.

Cached data must preserve original provenance and observation time. Cache age never resets source freshness.

## 5. Conflict-resolution algorithm

When two sources disagree:

1. Identify the domain of the disputed fact.
2. Resolve the canonical authority from this ADR.
3. Verify source identity, version and freshness.
4. If the canonical source is unavailable, mark the fact unavailable/unknown; do not promote a lower authority silently.
5. Persist the discrepancy where it affects execution, risk, eligibility, accounting or operator decisions.
6. Block exposure-increasing mutation when the discrepancy is safety relevant.
7. Reconcile and close the discrepancy with evidence.

## 6. Explicitly rejected patterns

- README or runbook values as runtime configuration truth.
- Browser-calculated quantities or P&L as execution authority.
- Symbol-wide strategy authorization.
- Multiple order routers each maintaining independent lifecycle truth.
- Redis as canonical state.
- Duplicate JSONL + SQLite operational truth without an explicit primary/replica contract.
- Hidden fallback from broker truth to stale local state.
- Same feature name reused for materially different formulas without versioning.
- Research “PASS” written by the code under evaluation.
- LLM output changing hard risk, eligibility, environment authorization or broker mutation rights.

## 7. Migration implications

This ADR does not require immediate datastore migration. It requires **authority consolidation**.

Planned migrations:

1. A-03 maps existing modules to bounded contexts and identifies duplicate authorities.
2. B-01 centralizes instrument constants into Instrument Master.
3. H-01 replaces scattered risk values with a versioned policy artifact.
4. M-01 defines canonical event/audit envelopes.
5. E-03 establishes the strategy lifecycle registry.
6. I-02/J-02 consolidate execution lifecycle into one OMS/broker path.
7. K-01 maps overlapping dashboards to one operator product.

## 8. A-01 dependencies that remain open

The authority hierarchy can be designed without guessing current values, but adoption remains blocked until A-01 captures or explicitly blocks on:

- loaded PAPER/LIVE flags;
- loaded human-approval setting;
- loaded daily loss, drawdown, contract and position-size limits;
- current real-IB-paper versus simulator mode;
- running ports/process/commit;
- current operational database identity/schema/backup status;
- current runtime eligibility and data freshness.

A-01 may change **observed values**, but should not change the hierarchy defined here unless new evidence shows a domain lacks a viable canonical source.

## 9. Acceptance criteria

- [x] Every safety/operator/research domain has one declared canonical authority class.
- [x] Broker-vs-local precedence is explicit.
- [x] Runtime risk values remain unresolved rather than guessed.
- [x] Static eligibility tables are non-authoritative.
- [x] UI is explicitly a projection.
- [x] Fresh/stale/unknown/ambiguous/unavailable semantics are defined.
- [x] Conflict resolution fails closed for exposure increases.
- [x] Migration targets are mapped to downstream WPs.
- [ ] A-01 runtime receipt completed or blocking observations explicitly accepted as ISG-0 blockers.
- [ ] PR #768 adopted.
- [ ] Human review marks this ADR `ADOPTED`.

## 10. Decision status

**Draft decision:** ACCEPTED FOR REVIEW.  
**Repository authority:** NOT YET EFFECTIVE.  
**ISG-0 credit:** none until A-01 prerequisites are satisfied and this ADR is adopted.
