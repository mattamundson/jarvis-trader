# Active Pre-Plan Capabilities — 2026-09-04

**Plan:** JARVIS-MIP-1.0  
**Status:** observed on `master`; not equivalent to MIP adoption/completion.  
**Observed baseline:** `99d75f31267294d7ff58520683d158408c3c3eeb`

## Why this inventory exists

The Phase-0 planning record originally classified PRs #749/#754/#756 as frozen technical spikes. During the implementation loop, #756 and #754 were merged to `master`, followed by #748. The repository therefore contains active pre-plan functionality that must be governed as transitional capability rather than described as still frozen.

## Active pre-plan capabilities

### #756 — manual PAPER TradeIntent API

Merged commit: `410c52b80c7fc9eaa64e4945871fd0954c2d2423`

Observed active files include:
- `engine/trade_intents/core.py`
- `engine/trade_intents/store.py`
- `engine/routers/trade_intents_router.py`
- registration from `engine/routers/orders_router.py`

Governance status: **ACTIVE-ON-MASTER / UNADOPTED-AS-CANONICAL**.

Useful invariants to preserve:
- zero-allowed server risk sizing;
- requested quantity as ceiling;
- durable idempotent intent store;
- atomic submission claim;
- fresh price/equity revalidation;
- broker/local position reconciliation;
- protected PAPER bracket route;
- ambiguous broker acknowledgement is non-retryable pending reconciliation.

Blocking gaps before canonical status:
- A-04/B-01/H-01 contracts not yet adopted/migrated;
- canonical OMS cutover not complete;
- restart/crash/partial-fill/reconciliation V4 evidence incomplete;
- legacy `/orders/place` disposition unresolved;
- actual A-01 host runtime state remains unobserved in this planning session.

Migration receipt: `../phase1/MANUAL_TRADE_AUTHORITY_MIGRATION_RECEIPT_DRAFT.md`.

### #754 — Command Center V2 PAPER control plane

Merged commit: `0a6a3bd5b30d1b9ad5e2e412335c7ab5fcc06264`

Observed active files include:
- `dashboard/app/command-center-v2/page.tsx`
- `dashboard/app/command-center-v2/trade/page.tsx`
- `dashboard/app/command-center-v2/layout.tsx`
- `dashboard/lib/controlPlane.ts`
- `dashboard/lib/tradeIntent.ts`

Governance status: **ACTIVE-ON-MASTER / UNADOPTED-AS-CANONICAL**.

Useful invariants to preserve:
- fail-closed cockpit aggregation;
- candidate approval/reject UX through server endpoints;
- two-step Preview → Submit PAPER flow;
- server-sized quantity visibility;
- NO TRADE state;
- reconciliation-required/no-retry presentation for ambiguous intent state.

Blocking gaps before canonical status:
- permanent V2 product tree conflicts with K-01 one-product target;
- canonical navigation/surface migration not complete;
- source→API→render numeric evidence still required for critical financial values;
- V4 real IB PAPER operator evidence not established by route presence or unit tests.

Migration receipt: `../phase1/COMMAND_CENTER_V2_MIGRATION_RECEIPT_DRAFT.md`.

### #748 — local PR gate

Merged commit: `99d75f31267294d7ff58520683d158408c3c3eeb`.

Governance status: **MERGED TOOLING / VERIFICATION FALLBACK**.

It is useful when GitHub Actions cannot allocate a runner, but a local V1-style result does not substitute for host/broker V4 evidence or LIVE V5 evidence.

## Still not formal implementation completion

These facts are all simultaneously true:

1. code is present on `master`;
2. some unit/static/CI evidence may exist;
3. the capability can be active in a PAPER runtime;
4. the MIP authority/migration gate may still be incomplete.

Therefore the project must distinguish:

```text
CODE_PRESENT
ACTIVE_ON_MASTER
MIP_ADOPTED_AUTHORITY
VERIFIED_AT_REQUIRED_RUNG
PRODUCTION/CAPITAL_AUTHORIZED
```

No lower state implies a higher state.

## Required Phase-0 documentation update

Any adoption/status document that still says #754/#756 are “frozen” must be interpreted as historical and updated before adoption/merge. The accurate state is **active-on-master, transitional, migration-governed**.

## Capital boundary

This inventory changes no runtime setting, routes no order, changes no risk limit, and grants no PAPER/LIVE authorization.