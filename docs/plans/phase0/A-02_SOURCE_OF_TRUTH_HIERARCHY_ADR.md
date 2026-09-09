# A-02 — Source-of-Truth Hierarchy ADR

**Parent product candidate:** `JARVIS-MPP-1.0` (#789 / GOV-01 #791)  
**Implementation mapping:** `JARVIS-MIP-1.0` where still applicable  
**Program:** A — Platform & Architecture  
**Phase:** Phase 0 / ISG-0 design  
**Decision class:** planning / future authority contract  
**Safety class:** S0 document with S3/S4 downstream implications  
**State:** **DRAFT CURRENT-MASTER REFRESH — ADOPTION BLOCKED BY GOV-01 + A-01**  
**Observed repository baseline:** `master@6afe8970b8a588a3b67131d960fe47bee6fa40cf`  
**Required for:** A-03, B-01, H-01, I-01, M-01, N-02, authority migrations

## 1. Decision

JARVIS will use a **domain-specific source-of-truth hierarchy** rather than one global datastore, one configuration file, one dashboard, or one service claiming authority over every fact.

Every execution-relevant, risk-relevant, research-relevant, or operator-visible fact must resolve to one canonical authority for its domain and carry enough provenance, freshness, identity, and version information to determine whether that fact may safely be used.

No UI, README, cached response, LLM output, historical report, provider alias, or duplicate service may silently override the canonical authority.

This ADR defines **which class of source is authoritative**. It does not guess unresolved loaded values from the Windows/TWS runtime. A-01 remains the evidence gate for those facts.

## 2. Canonical hierarchy by domain

| Domain fact | Canonical authority | Required metadata | Non-authoritative examples |
|---|---|---|---|
| Broker account identity | Verified broker API / adapter | redacted account identity, environment, observed_at, freshness, connector identity | README, `.env.example`, UI label |
| Executable positions | Broker observations reconciled into JARVIS | canonical instrument, qty, avg price, broker timestamp, reconcile timestamp/state | tracker-only position, dashboard cache |
| Open orders / fills | Broker + canonical OMS reconciliation | broker IDs, order/child relationships, state, timestamps, reconciliation | local pending-order guess |
| JARVIS intent identity | Canonical OMS durable store | intent ID, fingerprint/idempotency key, actor, environment, policy/evidence versions | browser state, logs alone |
| Order lifecycle | Canonical OMS | durable transitions, broker ack/reject/ambiguous state, correlation, restart identity | router-specific parallel state machines |
| Operational ledger through PAPER | Current SQLite/WAL baseline until separately migrated | DB/schema identity, transaction timestamps, backup/recovery state | duplicate JSON/JSONL truth |
| Runtime risk policy | Target H-01 versioned active Risk Policy; interim loaded SafetyLayer-enforced runtime values | policy version/hash, loaded_at, environment, activation actor | docs/defaults/examples |
| Trading eligibility | Strategy lifecycle registry keyed by strategy/version/instrument/timeframe/evidence | evidence bundle, lifecycle state, decided_at, expiry/degradation | static PASS table, symbol-wide boolean |
| Instrument metadata | B-01 Instrument Master | canonical ID, provider aliases, exchange, timezone, sessions, tick/point/multiplier, contract resolution | scattered constants, `NQ=F` assumed equal to `NQ` |
| Market/session calendar | Canonical calendar/session authority | timezone, session type, holiday/early-close policy, version | ad-hoc datetime logic |
| Research dataset | Immutable manifest + content identity | provider, contract mapping, session policy, time range, content hashes | mutable cache filename |
| Feature definition | Versioned Feature Registry | source identity, formula version, causal/PIT status, parity status | same-name formula variants |
| Feature observation | PIT Feature Store / replayable observation record | event/published/received/available/computed/known timestamps | recomputed value without availability history |
| Research attempt | Immutable Trial Ledger | hypothesis ID, parameter space, dataset/features, code SHA, result including rejects | selected winning notebook |
| Strategy verdict | Judge/evidence bundle + lifecycle registry | trial accounting, validation metrics, holdout/PAPER evidence, version | README headline |
| Portfolio state | Canonical portfolio projection reconciled to broker truth | source timestamps, position/order linkage, exposure/risk provenance | browser-summed totals |
| Capital authorization | N authorization domain | scope, environment, actor, effective/expiry/revocation, evidence | `LIVE_TRADING_ENABLED` alone |
| Operator UI | Never authoritative; projection/command surface only | source/provenance/freshness/version shown | browser-calculated financial truth |
| Product/implementation governance | Adopted MPP + adopted ADR/WP evidence | plan version, WP/decision IDs, effective SHA/status | historical “complete” docs |

## 3. Authority rules

### 3.1 Broker truth

For executable account state, verified broker state outranks local state. JARVIS may maintain local projections for latency, history, analytics, and audit, but disagreement that affects exposure must be explicit.

Exposure-increasing mutations fail closed until reconciliation resolves any safety-relevant mismatch.

A local projection may never be relabeled as broker-verified merely because the broker is temporarily unreachable.

### 3.2 Operational truth

Through the current PAPER baseline, SQLite/WAL remains the canonical local operational ledger where configured. JSONL/export forms are secondary evidence unless a separate adopted contract explicitly says otherwise.

The target architecture may later migrate persistence, but migration must preserve identity, ordering, restart recovery, and reconciliation evidence.

### 3.3 Risk truth

A-01 determines what values are actually loaded by the current runtime. Repository defaults are not runtime truth.

Until H-01 is adopted and migrated, the active SafetyLayer/runtime configuration remains the enforcement source. After H-01, one versioned active Risk Policy becomes policy authority and activation must produce immutable evidence.

No LLM, UI, strategy, or test may silently write or relax the active policy.

### 3.4 Instrument truth

Provider aliases are not canonical contracts. B-01 must resolve aliases explicitly.

The already-identified contradictions such as provider/continuous-style aliases carrying different point values from canonical full-size contracts are treated as blocking metadata debt rather than normalized by name similarity.

### 3.5 Eligibility truth

Eligibility is strategy-version/instrument/timeframe/evidence specific. The canonical key is at minimum:

```text
strategy_id
+ strategy_version
+ instrument_id
+ timeframe
+ evidence_bundle_version
```

Static Markdown summaries may display lifecycle state but do not authorize execution.

### 3.6 Research truth

Datasets, feature versions, trial attempts, and evidence bundles must be immutable or content-addressed enough to replay a claim.

Rejected/failed trials remain part of truth. They may not be deleted to improve apparent performance.

### 3.7 UI truth

The dashboard is a projection and command surface. It may not originate broker facts, risk limits, eligibility, authoritative position size, account equity, or financial totals that the server has not independently resolved.

`STALE`, `UNKNOWN`, `CONTRADICTORY`, `AMBIGUOUS`, and `UNAVAILABLE` are first-class states and must not be rendered as reassuring zero/default values.

## 4. Freshness and uncertainty semantics

Every execution-relevant observation resolves to a state equivalent to:

- `VERIFIED_FRESH`
- `VERIFIED_STALE`
- `UNKNOWN`
- `CONTRADICTORY`
- `AMBIGUOUS`
- `UNAVAILABLE`

Only verified sufficiently fresh facts may support exposure increase unless a later adopted policy defines an explicitly safe narrower case.

Risk-reducing cancel/reduce/flatten operations are governed separately and should remain available when their required target identity and broker state are verified.

Cache age never resets the original observation/freshness clock.

## 5. Conflict-resolution algorithm

When two sources disagree:

1. identify the domain of the disputed fact;
2. identify the canonical authority from this ADR;
3. verify source identity, version, environment, and freshness;
4. if the canonical authority is unavailable, mark the fact unavailable/unknown — do not silently promote a lower source;
5. persist the discrepancy when it affects execution, risk, eligibility, accounting, or operator decisions;
6. block exposure increase if the discrepancy is safety relevant;
7. reconcile using canonical/broker evidence;
8. close the discrepancy with a correlated receipt.

## 6. Explicitly rejected patterns

- README/runbook values as runtime configuration truth.
- Browser-calculated quantities or P&L as execution authority.
- Provider aliases silently treated as equivalent instruments.
- Symbol-wide strategy authorization.
- Multiple routers each owning an independent order lifecycle.
- Redis/cache as canonical domain truth.
- Duplicate JSONL + SQLite operational truth without a declared primary/replica contract.
- Hidden broker→stale-local fallback.
- Same feature name reused for materially different formulas without versioning.
- Research code self-declaring promotion eligibility.
- LLM output changing hard risk, eligibility, environment authorization, or broker mutation rights.

## 7. Current-master reconciliation

The current repository contains transitional authorities that must be migrated rather than rewritten from history:

- merged #756 `/trade-intents/*` — **ACTIVE-UNADOPTED** manual futures PAPER mutation candidate;
- legacy `/orders/place` — **TRANSITIONAL ACTIVE** mutation path;
- merged #754 `/command-center-v2` — **ACTIVE-UNADOPTED** operator-product generation;
- merged #787 analysis/runtime additions — active code, not automatic canonical IA/strategy authority;
- draft #786 — current migration receipts for I-MIG-001/K-MIG-001;
- draft #788 — inert B/H/I/M/N/domain contract candidates;
- draft #789 — proposed parent product hierarchy;
- A-01 tooling on master — collection/visibility exists, actual host evidence remains external.

No one of these facts silently upgrades another artifact to `ADOPTED`, `VALIDATED`, `PAPER-QUALIFIED`, or capital-authorized.

## 8. Migration implications

This ADR requires **authority consolidation**, not immediate datastore or service migration.

Recommended sequence:

1. GOV-01 adopts/revises the parent product hierarchy.
2. A-01 records real runtime truth and human disposition of contradictions.
3. A-03 defines bounded contexts and one mutation spine.
4. B-01 centralizes instrument identity and aliases.
5. H-01 establishes versioned risk-policy authority.
6. M-01 establishes canonical event/audit envelope.
7. N-02 separates environment from authorization.
8. PIT data/feature/research authorities are established.
9. I/J migrate execution and broker reconciliation authority.
10. K-MIG-001 migrates operator surfaces without creating a second permanent product.
11. Old authorities become read-only/deprecated/removed only through migration receipts and parity/recovery evidence.

## 9. A-01 facts still required

The hierarchy can be reviewed without guessing current values, but authority adoption/cutover decisions still require real host evidence for items such as:

- loaded PAPER/LIVE/IB paper flags;
- loaded human-approval state;
- loaded daily-loss/drawdown/contract/size controls;
- real IB PAPER versus simulator mode;
- running ports/process/commit/worktree;
- current operational DB identity/schema/backup status;
- current eligibility and data freshness;
- current broker/account identity and connectivity evidence.

A-01 may change observed values. It should not silently change this hierarchy unless evidence shows a domain lacks a viable authority.

## 10. Acceptance criteria

- [x] Safety/operator/research domains have one declared canonical authority class.
- [x] Broker-vs-local precedence is explicit.
- [x] Runtime values remain unresolved rather than guessed.
- [x] Instrument aliases are explicitly non-canonical until mapped.
- [x] Static eligibility summaries are non-authoritative.
- [x] UI is explicitly a projection.
- [x] Fresh/stale/unknown/contradictory/ambiguous/unavailable behavior is defined.
- [x] Safety-relevant conflicts fail closed for exposure increases.
- [x] Active #754/#756 dual-authority reality is explicitly reconciled.
- [ ] GOV-01 parent hierarchy explicitly adopted/revised.
- [ ] A-01 host evidence completed or remaining blockers explicitly accepted as blockers.
- [ ] Human architecture review marks A-02 `ADOPTED` with effective SHA.

## 11. Decision status

**Draft decision:** READY FOR REVIEW.  
**Repository authority:** NOT EFFECTIVE.  
**Runtime/capital authority:** NONE.  
**ISG-0 credit:** none until required parent/runtime decisions are completed.
