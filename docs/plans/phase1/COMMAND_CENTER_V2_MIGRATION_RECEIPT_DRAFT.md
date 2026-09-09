# Command Center V2 → Canonical Operator Product Migration Receipt — DRAFT

**Plan:** JARVIS-MIP-1.0  
**Migration ID:** K-MIG-001  
**State:** DRAFT / NOT APPROVED  
**Safety class:** S2 for eventual executable operator-control migration; this document itself is S0.  
**Observed baseline:** `master@99d75f31267294d7ff58520683d158408c3c3eeb`

## Purpose

Move useful behavior from the now-active `/command-center-v2` tree into the single canonical operator product without preserving a permanent second dashboard generation.

## Active source surface

Merged #754 added:

- `/command-center-v2`
- `/command-center-v2/trade`
- shared V2 layout/navigation
- `dashboard/lib/controlPlane.ts`
- `dashboard/lib/tradeIntent.ts`
- candidate approval/reject controls
- manual PAPER TradeIntent workflow
- route and client gating tests

This presence on `master` is **ACTIVE-ON-MASTER / UNADOPTED-AS-CANONICAL**. It is not K-01 completion or PAPER V4 evidence.

## Canonical destinations

| V2 capability | Canonical target |
|---|---|
| broker/mode/safety/equity cockpit | `/command-center` Home + `/operations` + `/risk` |
| market/candidate context | `/command-center` + `/intelligence` |
| candidate approve/reject | `/trades` / Trade Workstation |
| manual trade preview/submit | `/trades` / Trade Workstation |
| position/order operational controls | future `/trades` + `/portfolio` + `/broker` |
| degraded-state provenance | shared operator component contract across all canonical surfaces |
| V2 navigation | retire after destination feature parity |

## Feature-parity inventory

Before any V2 redirect/deprecation:

- [ ] PAPER/LIVE mode and broker execution connectivity visible on canonical Home/Operations.
- [ ] Kill-switch/halt state visible with verified/unknown semantics.
- [ ] Equity, P&L and drawdown values carry source, timestamp and freshness.
- [ ] Position projection identifies broker-authoritative vs local/audit state.
- [ ] Candidate queue displays strategy/version/evidence/expiry and frozen geometry.
- [ ] Candidate approve/reject routes through server authority only.
- [ ] Trade preview shows server-calculated quantity, dollar risk, account equity, R:R and blocking reason.
- [ ] Zero-sized preview renders NO TRADE and cannot be overridden.
- [ ] Submit error re-reads durable intent state; ambiguous/submitting state displays reconciliation-required/no-retry semantics.
- [ ] Canonical Trade Workstation performs fresh server validation immediately before route.
- [ ] All mutating controls remain unavailable when broker/risk/data/reconciliation state is unknown.
- [ ] Critical numbers have source→API→render numeric E2E assertions.
- [ ] Browser has no broker credential/direct IB route.
- [ ] Route migration census shows no required capability remaining only on V2.

## Migration stages

```text
ACTIVE_V2
→ CANONICAL_READ_PARITY
→ CANONICAL_MUTATION_PARITY
→ V3_OPERATOR_E2E
→ V4_IB_PAPER_EVIDENCE where mutations exist
→ REDIRECT_V2
→ DEPRECATE_V2
→ REMOVE_V2
```

No stage may be skipped. Redirect/removal is explicitly unauthorized by this draft.

## Failure/degraded-state parity

Canonical surfaces must preserve or improve these V2 fail-closed cases:

- engine unavailable;
- broker unavailable/stale;
- live mode encountered on PAPER-only workflow;
- kill switch active;
- reconciliation mismatch;
- candidate expired/validation-only/incomplete;
- price unavailable/stale/failed sanity;
- equity unavailable;
- risk returns quantity zero;
- intent terminal or expired;
- broker acknowledgement ambiguous.

Unavailable data must never render as a fabricated zero or successful state.

## Acceptance evidence

Required before redirect:

1. route census + machine migration manifest current against `dashboard/app/**/page.tsx`;
2. component/API parity matrix signed;
3. canonical production build and 50+ route smoke passes;
4. numeric source-to-render tests for risk/equity/position/order fields;
5. executable control E2E through PAPER server path;
6. real IB PAPER observation for broker mutations;
7. rollback path from redirect documented/tested;
8. operator review accepts canonical navigation and degraded states.

## Rollback

Prior to V2 removal, rollback is removal of canonical redirect and restoration of V2 navigation. After any broker-side mutation, rollback is a UI routing action only and must never imply broker state rollback; broker reconciliation remains authoritative.

## Approval boundary

- Product/IA reviewer: pending
- Engineering reviewer: pending
- S2/S3 safety reviewer where executable controls move: pending
- Operator/PAPER reviewer: pending

**Invariant:** code reuse is allowed; permanent V2 product duplication is not the target.