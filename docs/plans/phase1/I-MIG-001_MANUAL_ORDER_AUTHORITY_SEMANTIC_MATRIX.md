# I-MIG-001 — Manual Order Authority Semantic Matrix

**Parent receipt:** `MANUAL_TRADE_AUTHORITY_MIGRATION_RECEIPT_DRAFT.md`  
**Plan:** JARVIS-MIP-1.0 / proposed JARVIS-MPP-1.0 mapping  
**State:** DRAFT EVIDENCE — NO CUTOVER AUTHORIZED  
**Safety class of eventual cutover:** S3  
**Observed source baseline:** `master@6afe8970b8a588a3b67131d960fe47bee6fa40cf`

## 1. Purpose

Freeze the current source-level semantics of the two manual order mutation spines before either is adopted, changed, redirected, or retired. This matrix is deliberately stricter than an endpoint inventory: it compares who owns quantity, what is revalidated, what is persisted, how broker ambiguity is represented, and what recovery evidence is still missing.

The intended result is **one canonical OMS mutation spine**, not permanent coexistence.

---

## 2. Source identities

| Authority | Current source | Observed blob | Current role |
|---|---|---|---|
| Legacy manual order | `engine/routers/orders_router.py` | `2049c1d85a94d39588e5db5efe1129f6d094cf44` | active/transitional multi-asset manual mutation |
| RT-2 TradeIntent | `engine/routers/trade_intents_router.py` | current at `master@6afe8970…` | active-unadopted manual PAPER futures candidate |
| RT-2 store/core | `engine/trade_intents/store.py`, `engine/trade_intents/core.py` | merged via #756 | durable intent/idempotency + zero-allowed sizing evidence source |
| Safety execution | `engine/risk/safety_layer.py` | current master | deterministic safety/broker routing dependency |

`orders_router.py` unconditionally mounts `trade_intents_router` at the observed baseline. This matrix does not change that fact.

---

## 3. Request/contract semantics

| Concern | `/orders/place` | `/trade-intents/*` | Canonical requirement / disposition |
|---|---|---|---|
| Asset scope | futures plus non-futures | futures only | one OMS with asset-specific adapters; non-futures must receive a separate migration decision |
| Symbol normalization | uppercase request; futures inferred by stripping digits and root membership | uppercase request; futures-only root + approved watchlist | B-01 Instrument Master must become canonical identity authority before final cutover |
| Client quantity | required integer `1..100` and used as requested routed quantity | optional integer >=1; treated as a **ceiling** | server-authoritative size; human value may only cap, never force exposure |
| Zero / NO TRADE | request contract cannot express zero | explicit risk outcome can produce zero and BLOCKED | canonical behavior must allow deterministic zero / NO_TRADE |
| Market order | supported | supported | retain |
| Limit order | supported; client supplies limit | supported; client proposes limit | fresh server sanity/freshness required immediately before exposure increase |
| Stop | optional | mandatory positive | required for exposure-increasing futures intent |
| Target | optional; non-futures target is advisory metadata | mandatory positive and used for protected bracket | required where adopted order/strategy policy requires protection; futures path must not silently downgrade to advisory metadata |
| Risk fraction | not supplied as route contract | client proposes max fraction, default 0.5%, capped 1% | H-01 determines active policy; UI request cannot raise policy limit |
| TTL/expiry | no dedicated intent TTL | short-lived intent TTL | canonical intent needs explicit expiry/staleness semantics |
| Idempotency key | no dedicated route-level key | required stable key plus request fingerprint | mandatory for exposure-changing commands |

---

## 4. Preconditions and fail-closed checks

| Check | `/orders/place` | `/trade-intents/preview` | `/trade-intents/{id}/submit` | Target |
|---|---:|---:|---:|---|
| Order router initialized | yes | inherited dependencies | inherited dependencies | yes |
| Safety layer initialized | yes | yes | yes | yes |
| Explicit PAPER-mode gate | not equivalent at route boundary | yes | yes | environment + authorization domain, server-side |
| Explicit LIVE-disabled gate | not equivalent at route boundary | yes | yes | LIVE requires separate explicit authorization |
| Kill switch | futures via SafetyLayer; non-futures explicit precheck | explicit | explicit again | recheck at mutation boundary |
| Approved futures universe | no equivalent route-level approved-watchlist gate | yes | yes | B/D strategy/instrument eligibility authority |
| Current market price | MARKET does not require route-level reference | yes | yes, refreshed | fresh authoritative observation required |
| Entry price sanity | LIMIT only when enabled/data manager available | yes | yes, refreshed | deterministic fail-closed check |
| Current positive equity | no equivalent route-level requirement | yes | yes, refreshed | authoritative account snapshot required |
| Server risk sizing | futures SafetyLayer receives client quantity; not equivalent preview sizing contract | yes | yes, recomputed | H-01 authoritative sizing |
| Quantity may shrink after preview | no preview lifecycle | n/a | yes; cannot increase above preview | retain |
| Broker/tracker reconciliation | no equivalent pre-submit route contract | no broker mutation yet | yes before claim/submit | J reconciliation required before exposure increase |
| Candidate/strategy authorization | manual route does not encode strategy evidence | approved watchlist only; manual intent | approved watchlist only; manual intent | canonical decision path must distinguish manual authorization from strategy eligibility |

---

## 5. Mutation, persistence, retry, and broker semantics

| Concern | Legacy `/orders/place` | RT-2 TradeIntent | Canonical requirement |
|---|---|---|---|
| Durable pre-broker intent | none dedicated at route boundary | SQLite `PREVIEWED` | yes |
| Durable submission claim | none dedicated | atomic `PREVIEWED → SUBMITTING` | yes |
| Duplicate client submit | no dedicated intent idempotency | idempotency/request fingerprint + claim | duplicate-safe |
| Futures broker path | `SafetyLayer.submit_paper_order()` | `SafetyLayer.submit_paper_bracket_order()` | adopted protected-order OMS/broker contract |
| Protective bracket | not equivalent; stop parameter only on futures legacy call | broker-protected bracket path | explicit parent/child/protection lifecycle |
| Non-futures protection | stop/target explicitly advisory metadata | unsupported | separate asset adapter; never imply broker protection if advisory only |
| Broker acknowledgement ambiguity | generic exception can produce uncertain external side effect without dedicated route state | remains `SUBMITTING`; UI says reconcile/do not retry | first-class `AMBIGUOUS`/equivalent durable state; blind resubmit prohibited |
| Automatic retry after possible broker invocation | no dedicated route-level state preventing caller retry | intentionally prohibited | prohibited |
| Broker result persisted | no dedicated intent aggregate | stored with terminal transition on success | yes |
| DB failure after broker success | no dedicated intent lifecycle | design preserves ambiguous/non-retry posture | reconciliation before retry; external side effect wins over local optimism |
| Restart recovery | route itself has no intent aggregate | store survives process restart, but full restart campaign not yet proven | V2 restart/recovery evidence required |
| Partial fill state | not route-level lifecycle | current intent model does not yet prove complete partial-fill aggregate behavior | canonical OMS must represent and reconcile partial fills |
| Cancel/replace | outside this route contract | not complete in RT-2 intent API | canonical OMS semantics required before operator controls |

---

## 6. Error-contract differences that matter to migration

### Legacy path

- `RuntimeError` from broker/routing becomes HTTP 503.
- generic exception becomes HTTP 500.
- response carries a placed/other status but no durable intent lifecycle identity.
- a caller receiving an uncertain transport/error response lacks a dedicated route-level state machine that proves whether retry is safe.

### RT-2 path

- terminal and blocked intent state is durable.
- submit first re-reads a durable intent and can return a previously `SUBMITTED` result idempotently.
- after possible broker invocation, uncertain state is not converted back to PREVIEWED.
- UI client explicitly re-reads the durable intent after submit errors and displays `RECONCILIATION REQUIRED — DO NOT RETRY` when state remains `SUBMITTING`.

**Migration consequence:** preserve RT-2's ambiguity/idempotency model even if endpoint names or implementation classes change.

---

## 7. Non-futures carve-out

The futures migration must not delete useful equity/options/crypto behavior by accident.

Before legacy `/orders/place` can be retired:

1. inventory each non-futures asset class actually used by the current `OrderRouter`;
2. define canonical instrument identity and broker adapter for each retained class;
3. define whether protective orders are broker-native, synthetic, or unsupported;
4. define server-authoritative sizing and risk policy;
5. add durable idempotent OMS state;
6. prove broker acknowledgement/reconciliation semantics;
7. migrate consumers;
8. then deprecate the old path.

If a non-futures class is not a product priority, explicitly mark it deferred/unsupported rather than silently inheriting legacy semantics.

---

## 8. Required test/recovery campaign before futures cutover

| Drill | Setup | Expected invariant | Required rung |
|---|---|---|---|
| PREVIEWED restart | create intent, restart before submit | intent survives; expiry honored; no order emitted | V2 |
| SUBMITTING restart | durable claim exists, restart | system does not create a second order; reconciliation required | V2/V4 |
| Lost broker response | broker accepts; response path fails | no blind retry; broker queried by identity/reconciliation | V4 |
| Persistence failure after broker side effect | force local terminal write failure after accepted submit | state remains conservative; operator sees unresolved condition | V2/V4 |
| Concurrent duplicate submit | two clients submit same intent simultaneously | one mutation claim only | V2 |
| Broker/tracker disagreement | inject quantity delta | exposure-increasing submit blocked | V2/V4 |
| Quote stale between preview and submit | advance freshness age | revalidation blocks | V2 |
| Equity drops after preview | reduce available risk budget | size shrinks or becomes zero; never grows | V2 |
| Kill switch activates after preview | activate before submit | submit blocked, no broker call | V2/V4 |
| Partial fill | broker partially fills parent | OMS exposes partial state; protection/reconciliation remains correct | V4 |
| Child protection incomplete | one protective child missing/rejected | exposure flagged unsafe; no false “protected” state | V4 |
| Duplicate HTTP retry after ambiguous response | repeat submit call | no duplicate exposure; durable state directs reconciliation | V4 |

A simulator-only pass cannot satisfy drills whose purpose is to prove real broker behavior.

---

## 9. Cutover decision sequence

```text
CURRENT_DUAL_PATH
→ CONTRACTS_ADOPTED (B-01 / H-01 / OMS / audit / auth as applicable)
→ SHADOW_PARITY
→ FAILURE_AND_RESTART_PROVEN
→ REAL_IB_PAPER_PROVEN
→ S3_SAFETY_REVIEW
→ CUTOVER_APPROVED
→ CANONICAL_FUTURES_OMS
→ LEGACY_FUTURES_READ_ONLY/UNAVAILABLE
→ OBSERVATION_WINDOW
→ DEPRECATED
→ REMOVED
```

No transition in this document is self-executing.

---

## 10. Current recommendation

**Preferred long-term futures migration candidate:** the TradeIntent lifecycle, because it already has the stronger server-sizing, durability, idempotency, fresh-state, reconciliation, protected-bracket, and ambiguous-ack posture.

**Current decision:** **NO CUTOVER.** It still reads legacy instrument/risk authorities, full restart/partial-fill/real-IB evidence is incomplete, and the governing contracts are draft/unadopted.

**Invariant:** this matrix is evidence for a future human S3 decision. It changes no route, order, broker state, risk limit, or capital authority.
