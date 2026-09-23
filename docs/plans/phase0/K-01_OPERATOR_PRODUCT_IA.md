# K-01 — Canonical Operator Product Information Architecture

**Plan:** JARVIS-MIP-1.0  
**Program:** K — Dashboard & Operator Product  
**Phase:** MIP-0  
**Safety class:** S0 design; downstream execution surfaces become S2/S3  
**State:** **DRAFT COMPLETE — MIGRATION NOT AUTHORIZED UNTIL A-01/A-02/A-03 ADOPTION**  
**Depends on:** A-02 source-of-truth hierarchy, A-03 target architecture  
**Required for:** Command Center consolidation and dashboard deprecation plan

## 1. Decision

JARVIS will have **one canonical operator product**, not parallel Command Center generations or multiple overlapping home/trading shells. The product is a control plane over server-authoritative state. It is never a second broker, risk engine, eligibility engine, portfolio calculator or order-management authority.

The existing `/command-center` remains the canonical shell name during migration. Experimental `/command-center-v2` or future version-numbered shells are not promoted as permanent product trees; their strongest components are harvested into the canonical product.

## 2. Canonical top-level navigation

The target information architecture is:

1. **Home**
2. **Trade**
3. **Portfolio**
4. **Risk**
5. **Research Lab**
6. **Strategies**
7. **Capital Path**
8. **Intelligence**
9. **Data**
10. **Operations**
11. **Broker**
12. **Learning**
13. **Settings**
14. **Audit**

Not every item must be a standalone URL initially. The invariant is one discoverable home for each operator task and one ownership model for each displayed fact.

## 3. Global operator chrome

Every execution-capable page must display or make one click away:

- environment: `PAPER`, `LIVE`, `UNKNOWN`;
- broker connectivity and broker-state freshness;
- active risk-policy identity/version once H-01 exists;
- kill-switch state;
- reconciliation state;
- account/equity source and freshness;
- pending/ambiguous order count;
- current operator identity/authorization where available;
- durable audit/trace ID for mutations.

`UNKNOWN`, `STALE`, `AMBIGUOUS` and `UNAVAILABLE` are visually distinct from numeric zero or “healthy.”

## 4. Canonical page responsibilities

### Home

Operational overview only:

- environment and safety posture;
- broker/account health;
- key portfolio/risk state;
- active incidents/degradations;
- pending approvals/actions;
- current strategy/eligibility summary;
- links into domain pages.

Home must not become another kitchen-sink implementation of every domain.

### Trade

Owns the human trading workflow:

```text
candidate/intent
→ frozen preview
→ authoritative risk/quantity
→ approval/submit
→ OMS lifecycle
→ broker acknowledgement/fill
→ reconciliation
```

No client-supplied quantity is execution authority. No direct browser-to-broker transport.

### Portfolio

Owns positions, exposure, allocation, realized/unrealized P&L projections and attribution, while visibly distinguishing broker-verified state from JARVIS projections.

### Risk

Owns active policy display, drawdown/utilization, risk budgets, halts, limits and reasons. Editing/activation remains separately permissioned and server-authoritative.

### Research Lab

Owns hypotheses, experiment runs, dataset/feature identities, WFO/CPCV/Monte Carlo outputs and trial accounting. Research results cannot mutate eligibility directly.

### Strategies

Owns strategy registry, versions, eligibility lifecycle, evidence bundle links, degradation/retirement and deployment state.

### Capital Path

Owns simulations from capital/risk assumptions to target/ruin/time distributions. It must state model/version assumptions and never present simulated policy as active risk configuration.

### Intelligence

Owns LLM/advisory explanations, critiques, research synthesis, Discord/other intelligence feeds and model-health visibility. It cannot change hard safety or execution authority.

### Data

Owns provider health, Instrument Master, data freshness/quality, PIT lineage, feature availability and provenance.

### Operations

Owns engine health, processes/jobs/schedulers, queues, latency, incidents, backups, readiness and environment diagnostics.

### Broker

Owns broker connectivity/read models, orders/fills/positions reconciliation, contract mapping and broker-paper/live environment truth. TWS/IB remains independent emergency truth during PAPER and early LIVE canary.

### Learning

Owns post-trade review, calibration, pattern/feedback learning and model-training status; learned artifacts cannot self-promote to execution.

### Settings

Owns non-secret configuration surfaces and feature toggles. Secret values are never exposed. Safety-sensitive activation is versioned/audited and not a generic browser preference.

### Audit

Owns immutable/operator-searchable intent, decision, policy, eligibility, order, broker and reconciliation history.

## 5. Current route inventory and target disposition

The current `dashboard/app` contains many overlapping pages. The migration goal is **harvest then consolidate**, not delete first.

| Current route | Target home | Disposition |
|---|---|---|
| `/` | Home | keep redirect to canonical shell while migration proceeds |
| `/command-center` | Home / Trade / Operations | **canonical shell; evolve in place** |
| `/dashboard` | Home | fold unique widgets into canonical Home; then redirect/deprecate |
| `/today` | Home | fold session snapshot into Home |
| `/master` | Home / domain launchpad | harvest domain-tile patterns; avoid a second top-level shell |
| `/mission-control` | Operations | harvest operational controls/health; deprecate duplicate shell |
| `/health` | Operations | consolidate as Operations > Health |
| `/portfolio` | Portfolio | canonical domain candidate |
| `/trades` | Trade / Audit | execution/open trades in Trade; history in Audit |
| `/trades/pending-approvals` | Trade | canonical approval sub-route candidate |
| `/trades/[id]/review` | Learning / Audit | retain deep link; navigation under Learning/Audit |
| `/paper`, `/parallel-paper` | Trade / Research Lab | migrate execution controls to Trade; experimental comparison to Research Lab |
| `/journal`, `/trades/journal`, `/journal-review` | Audit / Learning | consolidate duplicate journals and review flows |
| `/performance`, `/stats` | Portfolio / Learning | `/stats` already redirects to `/performance`; split operational portfolio metrics from learning analytics over time |
| `/strategies`, `/strategy-ledger`, `/trading-eligibility` | Strategies | consolidate registry, lifecycle and evidence views |
| `/strategy-research`, `/backtest`, `/research-log`, `/validation` | Research Lab | consolidate experiment/evidence lifecycle |
| `/signals`, `/signal-outcomes`, `/screener`, `/analysis`, `/regime` | Research Lab / Strategies | classify into candidate discovery, strategy evidence or operator read models; remove overlapping generic “analysis” ownership |
| `/atr-trail`, `/hidden-pivots`, `/strategy-c`, `/strategy-c-command` | Strategies / Research Lab | strategy-specific pages become registry/version deep links, not permanent top-level navigation |
| `/data-integrity`, `/thinkscript`, `/domflow` | Data | consolidate under provider/feature/market-structure sections |
| `/crypto`, `/options`, `/polymarket` | Trade / Strategies / Data | represent asset/venue context inside canonical domains rather than separate product shells where feasible |
| `/discord`, `/framing-brief`, `/jarvis` | Intelligence | consolidate advisory/intelligence surfaces |
| `/kairos`, `/vault` | Intelligence / Learning / Audit | preserve useful knowledge/history functions under explicit ownership |
| `/learning` | Learning | canonical domain candidate |
| `/config`, `/settings` | Settings | consolidate; distinguish runtime config read model from operator preferences |
| `/watchlist` | Home / Research Lab | shared watchlist capability, not a separate authority |
| `/scorecard`, `/trust-pane` | Operations / Audit | merge readiness/trust evidence into canonical status/audit surfaces |
| `/pipeline-board` | Operations / Research Lab | place according to whether board represents runtime workflow or research lifecycle |
| `/master/trading` | Trade | harvest; avoid nested parallel shell |
| `/master/finances` | Portfolio | harvest; avoid nested parallel shell |

This table is a migration map, not permission to remove routes without route-level regression and user-journey evidence.

## 6. Route lifecycle

Each legacy route moves through:

```text
ACTIVE
→ MAPPED
→ FEATURE_PARITY_PROVEN
→ REDIRECTED
→ DEPRECATED
→ REMOVED
```

A redirect may occur only after:

- unique widgets/actions are inventoried;
- authoritative API source is identified;
- deep links are preserved where required;
- route-manifest and Playwright coverage is updated;
- operator-critical actions remain reachable;
- no safety state is lost or relabeled.

## 7. Command Center integration rules

The canonical `/command-center` shell should become composition, not duplicated business logic.

It may compose read models from Home/Trade/Risk/Operations but should not:

- independently calculate authoritative P&L;
- independently size orders;
- reconstruct risk policy in TypeScript;
- infer broker connectivity from UI polling success alone;
- accept direct broker credentials;
- create a second approval/order lifecycle;
- silently convert stale state into zero.

PR #754 is a component/pattern source only. Its PAPER/LIVE badge, fail-closed cockpit concepts and candidate-card UX should be harvested into the canonical shell after the underlying API/OMS contracts are adopted.

## 8. Realtime UX contract

- HTTP: commands/mutations and explicit reads where cache semantics are clear.
- WebSocket/SSE: observation streams, lifecycle updates, health/events.
- reconnect does not imply data freshness; every payload retains source observation timestamps.
- optimistic UI may reflect command submission state, but never fabricate broker acknowledgement/fill.
- ambiguous broker outcomes display `AMBIGUOUS / RECONCILIATION REQUIRED` and disable exposure-increasing retry.

## 9. Safety controls

Risk-reducing controls should remain globally discoverable:

- kill/disable new exposure where policy permits;
- cancel open orders;
- reduce/flatten verified positions.

Their server endpoints require authenticated/audited command identity and verified state, but degraded alpha/intelligence/data subsystems should not unnecessarily hide emergency risk-reduction paths.

Exposure-increasing controls fail closed when any required source is stale/unknown/ambiguous.

## 10. Accessibility and operator ergonomics

- status is not encoded by color alone;
- critical values include units and source/freshness tooltips;
- dangerous actions use explicit verbs and consequence text;
- keyboard focus and confirmation flows are deterministic;
- mobile layouts may observe and manage safe operator workflows but do not weaken confirmation/safety requirements;
- financial values avoid unexplained rounding where it can change action decisions.

## 11. Acceptance criteria

- [x] One canonical operator-product IA is defined.
- [x] `/command-center` is selected as the migration shell; version-numbered shells are non-canonical.
- [x] Current top-level routes are mapped to target domains.
- [x] Route deprecation requires parity and E2E evidence.
- [x] Server authority/provenance/freshness rules are explicit.
- [x] Emergency risk-reducing controls remain discoverable.
- [x] Ambiguous broker outcomes cannot be hidden by optimistic UI.
- [ ] A-01/A-02/A-03 adopted.
- [ ] Route-by-route inventory of unique widgets/actions completed before deletion/redirect work.
- [ ] Human review approves the deprecation sequence.

## 12. Decision status

**Draft IA:** ACCEPTED FOR REVIEW.  
**Route removal authorization:** NONE.  
**Execution authorization:** NONE.
