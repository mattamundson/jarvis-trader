# Manual Trade Authority Migration Receipt — DRAFT

**Plan:** JARVIS-MIP-1.0  
**Migration ID:** I-MIG-001  
**State:** DRAFT / NOT APPROVED  
**Safety class:** S3 because the eventual cutover changes exposure-increasing order authority.  
**Observed baseline:** `master@99d75f31267294d7ff58520683d158408c3c3eeb`

## Purpose

Reconcile the two manual-order mutation spines now present on `master` with the target JARVIS architecture. This document does not disable either path and does not authorize a cutover.

## Current authorities

### Legacy manual order path

`POST /orders/place` in `engine/routers/orders_router.py`

Current behavior includes:
- browser-supplied quantity;
- futures routed through `SafetyLayer.submit_paper_order()`;
- non-futures delegated to `OrderRouter` after kill-switch check;
- LIMIT entry-price sanity where data manager is available;
- optional stop/target fields, with non-futures stop/target described as advisory metadata rather than broker-protective bracket orders;
- no durable TradeIntent lifecycle/idempotency receipt at this route boundary.

### RT-2 manual paper futures path

`POST /trade-intents/preview`, `GET /trade-intents/{id}`, `POST /trade-intents/{id}/submit` in `engine/routers/trade_intents_router.py`, mounted by `orders_router.py`.

Current behavior includes:
- PAPER-only and LIVE-disabled checks;
- approved futures symbol/watchlist gate;
- fresh current price + entry sanity;
- current equity requirement;
- server-authoritative zero-allowed sizing;
- requested quantity treated as a ceiling;
- short-lived durable SQLite intent;
- idempotency/request fingerprint and atomic submission claim;
- fresh re-sizing before submit, never increasing above preview quantity;
- broker/tracker reconciliation before submission;
- protected bracket submission through SafetyLayer;
- ambiguous broker acknowledgement remains `SUBMITTING` and is not automatically retried.

## Target authority

Target mutation spine under the MIP:

```text
Human / Candidate
→ A-04 TradeIntent
→ strategy eligibility / portfolio budget
→ H-01 versioned Risk Policy
→ canonical OMS durable claim/state machine
→ J broker adapter
→ broker acknowledgement/fill
→ reconciliation
→ M-01 audit event stream
```

The route/API surface may remain compatible, but only one server-side OMS may own submission state.

## Required disposition

Recommended long-term direction:

1. Treat `/trade-intents/*` as the stronger **migration candidate** for manual futures because it already contains zero-allowed server sizing, durability, idempotency, reconciliation, protected brackets, and ambiguous-ack no-retry semantics.
2. Do **not** declare it canonical yet. Its risk values and instrument metadata still come from legacy runtime authorities rather than adopted H-01/B-01 contracts.
3. Treat `/orders/place` as **legacy/transitional** for futures once parity is proven. Non-futures behavior requires a separate asset-class migration decision; it cannot simply be deleted with the futures path.
4. No third manual-order mutation spine may be introduced during this migration.

## Gaps before canonical cutover

- [ ] A-04 contract adopted and active path mapped without behavior loss.
- [ ] B-01 Instrument Master resolves symbol/root/multiplier/session used by sizing and broker qualification.
- [ ] H-01 Risk Policy supplies active version/hash and replaces ad-hoc config reads with parity evidence.
- [ ] Canonical OMS state model explicitly represents ambiguous broker outcomes and restart recovery.
- [ ] Broker adapter contract selected; current SafetyLayer/IB gateway path mapped to it.
- [ ] SQLite restart test proves `PREVIEWED/SUBMITTING/SUBMITTED` recovery.
- [ ] Crash after broker invocation / before local persistence is drilled.
- [ ] Partial fill and child-protection behavior is observed against real IB PAPER.
- [ ] Broker/local reconciliation mismatch blocks exposure and has recovery procedure.
- [ ] `/orders/place` futures behavior is compared against the new spine; any still-required capability is ported or explicitly retired.
- [ ] Audit envelope captures intent, risk decision, OMS transition, broker result, reconciliation result, actor/correlation IDs.
- [ ] Required V4 PAPER evidence completed.
- [ ] Independent S3 safety review approves cutover.

## Parity matrix

| Concern | `/orders/place` | `/trade-intents/*` | Target |
|---|---|---|---|
| Quantity authority | client supplies quantity | server sizes; request is ceiling | server only |
| Zero / NO TRADE | not primary route contract | explicit | explicit |
| Stop required | optional at request model | required | required for exposure increase |
| Target required | optional | required | required where strategy/order policy requires bracket |
| Durable intent | no dedicated intent state | yes | yes |
| Idempotency | not dedicated at route boundary | yes | yes |
| Atomic submission claim | not route-level | yes | yes |
| Pre-submit reconciliation | not equivalent | yes | yes |
| Fresh re-sizing | no equivalent manual ticket lifecycle | yes | yes |
| Ambiguous broker outcome | generic exception path | stays SUBMITTING / no retry | explicit AMBIGUOUS + reconciliation |
| Asset classes | futures + non-futures | futures only | asset-specific adapters behind one OMS |
| Browser-to-broker | no | no | prohibited |
| LIVE authorization | separate legacy controls | explicitly blocks LIVE | N-02/H-01/human gate |

## Failure drills required

1. process restart with PREVIEWED intent;
2. process restart with SUBMITTING intent;
3. broker accepts order, network response is lost;
4. broker succeeds, DB transition write fails;
5. duplicate submit from two clients;
6. broker and local position quantities disagree;
7. quote goes stale between preview and submit;
8. equity/risk budget decreases after preview;
9. kill switch activates between preview and submit;
10. child protective order submission/acknowledgement is incomplete.

## Rollback

Until the canonical cutover is approved, existing paths remain unchanged. A future cutover PR must state exactly how to restore the previous router/OMS behavior and must reconcile any broker-side effects before retry or rollback.

## Approval boundary

- Engineering reviewer: pending
- Safety reviewer: pending
- Operator/PAPER reviewer: pending
- Capital owner: not applicable until LIVE/canary work

**Invariant:** this receipt can become evidence for a cutover decision; it cannot authorize one.