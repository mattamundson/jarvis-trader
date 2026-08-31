# JARVIS Real-Time Trading Control Plane

Status: research design; no live authorization.

## Decision

Use the existing Next.js Command Center as the operator interface, but never let the browser talk directly to IBKR or construct broker orders. The dashboard submits or approves a **trade intent**. The engine rehydrates current broker/account/market state, runs deterministic risk and safety checks, then the broker adapter submits the resulting paper order.

```text
Dashboard / Command Center
        |
        | authenticated trade intent / approval
        v
Trade Intent API
        |
        v
Fresh-State Revalidation
  - broker connected
  - position reconciliation clean
  - market data fresh
  - candidate not expired
  - strategy eligible
        |
        v
SafetyLayer / Risk Policy
  - kill switch
  - daily loss / drawdown
  - size limits
  - correlation / heat
  - stop/target sanity
        |
        v
IBOrderManager
        |
        v
IB Gateway PAPER account
        |
        v
Order/fill events -> reconciliation -> dashboard
```

The existing code already provides important parts of this path:

- `engine/routers/approval_queue_router.py` exposes authenticated pending/history/approve/reject routes and re-checks safety before paper submission.
- `engine/execution/ib_order_manager.py` guarantees paper order submission flows through `SafetyLayer` and supports bracket orders plus broker-position reconciliation.
- `engine/risk/safety_layer.py` is deterministic/non-LLM and owns kill-switch and hard risk controls.
- `dashboard/app/command-center/page.tsx` already provides the natural operator surface.

## Why not direct dashboard -> broker

A direct browser-to-broker architecture would create a second execution path and make it possible for UI bugs, stale state, or manual overrides to bypass the engine's safety invariants. The dashboard should be a control plane, not an execution engine.

## Deployment phases

### Phase RT-0 — Read-only cockpit

Before adding a manual order ticket, the Command Center should present one reconciled real-time state:

- paper/live mode badge;
- IB Gateway connectivity;
- market-data freshness;
- kill-switch / halt state;
- broker equity and buying power;
- broker positions and internal-position reconciliation;
- open orders / fills;
- current portfolio heat and drawdown;
- pending JARVIS candidates;
- Judge/evidence status for candidate strategy;
- current stop / target / R geometry.

No order submission.

### Phase RT-1 — Candidate approval to paper broker

Use the existing `/approvals/{id}/approve` path as the first executable dashboard action.

The UI must show the exact values that will be revalidated on click:

- symbol/direction;
- strategy and evidence status;
- current price and quote age;
- planned entry;
- stop and take-profit;
- requested quantity;
- risk dollars and account-risk percentage;
- portfolio/sector heat after trade;
- candidate age/expiry;
- warnings / rejection reasons.

Approve must never mean "blindly place the stored order". The server must re-check fresh state at approval time.

### Phase RT-2 — Manual paper trade ticket

Add an operator-created trade-intent endpoint. The operator can request:

- symbol;
- BUY/SELL;
- marketable-limit or limit entry;
- proposed stop;
- proposed target;
- max account risk;
- optional strategy/candidate association.

The UI does **not** choose final size. The engine calculates allowed size from fresh equity, stop distance, risk policy, margin and heat. If requested size exceeds allowed size the intent is rejected or reduced according to an explicit policy.

A manual ticket must still pass the same SafetyLayer and reconciliation gates as system-generated candidates.

### Phase RT-3 — Position management

Dashboard actions:

- cancel unfilled order;
- replace limit within bounded rules;
- tighten stop;
- reduce position;
- flatten one position;
- emergency flatten all;
- activate kill switch.

High-risk mutations need confirmation dialogs and idempotency keys. The UI should never offer a one-click action that weakens a protective stop, increases risk after entry, disables the kill switch, or increases size beyond current policy without a separate privileged workflow.

### Phase RT-4 — Paper autopilot

Only Judge-approved strategies may auto-submit paper trades without per-trade human approval. The dashboard remains the supervisory interface and may halt/flatten/reject new entries.

### Phase RT-5 — Tiny live canary

Live mode is a separate promotion event, not a UI toggle. Requirements should include:

- validated strategy + Judge evidence;
- paper execution calibration;
- broker reconciliation passing;
- operational kill-switch tests;
- duplicate-submission tests;
- restart recovery;
- explicit live account identity;
- small canary risk policy;
- human approval of the promotion.

## Real-time transport

Use HTTP for mutations and snapshots. Use WebSocket or Server-Sent Events for broker/order/market-state updates once the read model is stable. Polling is acceptable for low-frequency candidate approvals, but order/fill/reconciliation state should eventually be event-driven.

Important separation:

```text
HTTP POST = intent / command
WebSocket/SSE = observations / state changes
```

The event stream should be read-only from the browser's perspective.

## Trade-intent state machine

```text
DRAFT
 -> SUBMITTED
 -> RISK_REVIEW
 -> REJECTED
 or APPROVED
 -> BROKER_SUBMITTED
 -> ACKNOWLEDGED
 -> PARTIAL
 -> FILLED
 -> PROTECTED
 -> CLOSED

Any state -> CANCELLED where valid
Any unsafe state -> HALTED
```

Every transition should be durable and auditable.

## Idempotency and double-click safety

Every mutation request receives a client-generated idempotency key. Duplicate requests return the original result and must not create another order. This is mandatory for browser execution.

## Freshness gates

Approval/manual execution should fail closed when any of these are stale or unknown:

- quote/price timestamp;
- account/equity snapshot;
- broker connectivity;
- broker/internal reconciliation;
- candidate expiry;
- strategy eligibility;
- stop/target validity;
- risk-policy version.

## Operator layout

Recommended Command Center arrangement:

```text
TOP BAR
Mode | Broker | Feed | Kill Switch | Equity | Daily P&L | DD | Heat

LEFT
Market / Regime / Sector / Watchlist

CENTER
Chart + VWAP/ORB/IB/profile + active signal geometry

RIGHT
Trade Intent / Candidate Approval
Entry | Stop | Target | Engine-computed size | $Risk | R:R | APPROVE/REJECT

BOTTOM
Open Orders | Positions | Stops | Fills | Reconciliation | Audit Events
```

## Security

Do not expose IB credentials or broker sessions to the browser. Dashboard uses same-origin server proxy/API authentication; broker credentials remain engine-side. Live activation requires a separate privileged control and must not be inferred from an ordinary order request.

## Build order

1. RT-0 real-time read model and reconciliation panel.
2. RT-1 wire existing approval queue into Command Center for paper only.
3. RT-2 manual trade-intent contract + risk preview + paper submission.
4. RT-3 protected position management.
5. RT-4 paper autopilot.
6. RT-5 tiny live canary only after explicit promotion.

## Recommendation

Build RT-0/RT-1 now, in parallel with Capital Path/Judge research. Do not wait for every research component to finish. The dashboard itself becomes part of the paper-validation process and gives us the operational evidence required before live trading.