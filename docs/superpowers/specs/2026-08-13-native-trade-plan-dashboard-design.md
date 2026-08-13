# Native Trade Plan Dashboard Design

**Status:** Approved direction; implementation pending specification review  
**Date:** 2026-08-13  
**Owner:** JARVIS Trader

## Decision

JARVIS will gain a native, durable Trade Plan contract and a redesigned `/signals` experience that presents recommendations with the same operational clarity as Amo Arbitrage: direction, entry, stop, targets, risk/reward, distance to entry, lifecycle state, validation, and execution blockers.

The implementation will reuse JARVIS's existing native `TradeDecision` calculations. It will not couple JARVIS execution to Amo Arbitrage, copy exploratory Amo setups into the native recommendation stream, weaken gate-v2, or fabricate missing levels.

## Problem

JARVIS already calculates `entry_price`, `stop_price`, `target_1`, `target_2`, ATR, risk/reward, sizing, reasoning, and risk notes. Those values are not preserved and exposed consistently in the primary dashboard contract. The current `/signals` page therefore emphasizes symbol, direction, strategy, confidence, gate status, and TTL while omitting the trade geometry an operator needs to evaluate a recommendation.

Amo Arbitrage demonstrates a stronger presentation model through its Trade Targets and Actionable Now views. Its cards communicate the planned trade, live distance, lifecycle state, and validation status in one place. JARVIS should adopt that information hierarchy while preserving its own stricter policy, validation, and execution semantics.

## Goals

- Make every native recommendation understandable without reconstructing prices mentally.
- Preserve the exact levels issued by the decision pipeline.
- Separate statistical validation, policy authorization, execution readiness, and lifecycle state.
- Keep `NO_TRADE` visible and first-class.
- Show source, freshness, contract, and blocker provenance.
- Support autonomous paper trading without treating the human approval queue as the system of record.
- Add the capability without redesigning the rest of the dashboard.

## Non-goals

- Replacing JARVIS strategy logic with Amo Arbitrage logic.
- Treating exploratory or pending-validation research as executable advice.
- Enabling live trading or changing risk limits.
- Changing gate-v2 thresholds, symbol halt policy, or existing MES authorization policy.
- Inventing entry zones or historical levels that were not produced by the native pipeline.
- Removing the Trust Pane's external Amo Arbitrage advisory feed.

## Truth Model

A trade plan has four independent truth dimensions. The UI and API must never collapse them into a single green or red state.

1. **Recommendation:** `BUY`, `SELL`, `HOLD`, or `NO_TRADE`.
2. **Validation:** gate-v2 verdict and supporting metrics.
3. **Execution eligibility:** policy authorization, symbol policy, broker readiness, kill switch, operating mode, and blockers.
4. **Lifecycle:** waiting, near entry, triggered, resolved, invalidated, expired, stale, or unavailable.

An explicit policy exception may make a paper plan execution-eligible even when gate-v2 is not `PASS`. That exception must be shown by name and reason; the UI must not relabel the gate verdict.

`NO_TRADE` remains a valid output. It may contain reasoning and blockers, but it must not display invented trade geometry.

## Canonical Contract

Introduce an additive Pydantic contract named `TradePlan`. It is the stable boundary between the decision pipeline, persistence, API, and dashboard.

### Identity and timing

- `plan_id`
- `decision_id`
- `symbol`
- `asset_class`
- `contract_id` and `contract_expiry`, when applicable
- `strategy_id`
- `timeframe`
- `created_at`
- `expires_at`

### Recommendation

- `action`: `BUY | SELL | HOLD | NO_TRADE`
- `confidence`
- `signal_score`, when produced
- `reasoning[]`
- `risk_notes[]`

### Trade geometry

- `entry_type`: `MARKET | LIMIT | STOP | ZONE | NONE`
- `entry_price`
- `entry_low` and `entry_high`, only when the native strategy explicitly supplies a zone
- `stop_price`
- `target_1`
- `target_2`
- `atr_used`
- `risk_per_unit`
- `rr_t1`
- `rr_t2`

### Live context

- `latest_price`
- `latest_price_as_of`
- `distance_to_entry_abs`
- `distance_to_entry_pct`
- `distance_to_entry_atr`
- `distance_to_entry_ticks`
- `current_r`
- `price_stale`

Live context is derived at read time from the current market price. It does not overwrite issued trade geometry.

### Sizing

- `proposed_quantity`
- `sizing_method`
- `estimated_dollar_risk`
- `estimated_notional`

### Validation and authorization

- `gate_verdict`
- `gate_metrics`: `pf_ci_lower`, `p_edge`, `mc_95th_drawdown`, and `dsr` when available
- `gate_evaluated_at`
- `policy_authorized`
- `policy_name`
- `policy_exception`
- `policy_reason`

### Execution readiness

- `trading_mode`
- `paper_execution_eligible`
- `approval_mode`
- `kill_switch_active`
- `broker_ready`
- `symbol_allowed`
- `execution_blockers[]`, each with a stable code and human-readable message
- optional links to `approval_id`, `order_id`, and `trade_id`

### Provenance and state

- `level_source`
- `price_provider`
- `generated_by`
- `schema_version`
- `lifecycle_state`
- `resolved_at`
- `resolution_reason`

Unavailable numeric values are serialized as `null` and rendered as an em dash. Zero is never used as a missing-value sentinel.

## Generation and Validation

Create the plan after the trader, risk, and fund-manager stages have finalized a decision and before any execution attempt. The mapper must preserve the pipeline's exact numeric levels and sizing inputs.

Before persistence, validate these invariants:

- `BUY`: `stop < entry < target_1`, and `target_2 >= target_1` when T2 exists.
- `SELL`: `stop > entry > target_1`, and `target_2 <= target_1` when T2 exists.
- Risk per unit is positive.
- R multiples are recomputed server-side from persisted geometry and checked against supplied values.
- Required prices are finite and positive.
- `HOLD` and `NO_TRADE` cannot be execution-eligible.

If geometry is unsafe or contradictory, persist the recommendation for auditability with `lifecycle_state=unavailable`, clear execution eligibility, and add a structured `INVALID_GEOMETRY` blocker. Do not silently repair or invert levels at the presentation boundary.

Entry zones remain optional. Version one displays the exact native entry price unless a strategy explicitly supplies a zone.

## Persistence

Add a dedicated append-only `trade_plans` store keyed by `plan_id`, with unique linkage to the source decision. Do not use pending approvals as the source of truth: autonomous paper decisions may bypass the human approval queue, and approvals represent workflow state rather than recommendation history.

Issued geometry and recommendation fields are immutable. Mutable lifecycle observations are stored separately or as append-only events so the original plan remains reproducible. Links to approvals, orders, and trades may be attached after issuance.

Existing records are not backfilled with guessed levels. Legacy candidates may appear with a `LEGACY_GEOMETRY_UNAVAILABLE` blocker if needed for continuity.

## Lifecycle Derivation

Lifecycle is derived server-side using issued direction, current price, expiry, tick size, ATR, and terminal events.

Terminal states take precedence:

1. `INVALIDATED`
2. `TARGET_REACHED`
3. `EXPIRED`
4. `TRIGGERED`
5. `TRIGGERABLE`
6. `AWAITING_ENTRY`
7. `UNAVAILABLE`

For version one, the entry tolerance is `max(one minimum tick, 0.10 * ATR)`. If ATR is unavailable, use one minimum tick. Strategy-supplied tolerances override this default and must be recorded in provenance.

A stale price cannot advance a plan into `TRIGGERABLE`, `TRIGGERED`, or a terminal price-derived state. It instead retains the last confirmed lifecycle state and is prominently marked stale. Expiration uses the plan's native timeframe and explicit `expires_at`; it does not copy Amo Arbitrage's expiry window.

## API

Add versioned, additive endpoints:

- `GET /trade-plans?scope=active`
- `GET /trade-plans?scope=recent&limit=<n>`
- `GET /trade-plans/{plan_id}`

Collection responses include `available`, `generated_at`, `latest_price_as_of`, `stale`, and `plans`. Filtering may include symbol, action, lifecycle, eligibility, and validation verdict.

Existing approval and signal-candidate endpoints remain compatible during migration. The dashboard uses the new contract for the new surface and does not join unrelated client-side responses to reconstruct trade plans.

## Dashboard Information Architecture

Rename the primary `/signals` heading to **Trade Plans** while retaining the route for compatibility. The page order is:

1. Compact health and freshness summary.
2. **Executable Paper Plans** — policy-authorized and operationally ready.
3. **Actionable Analysis** — at or near entry but blocked from execution.
4. **Waiting for Entry**.
5. **No Trade / Blocked** — visible, compact, and expandable.
6. **Recently Resolved**.
7. Options market-implied analysis in a secondary section or tab.

The main dashboard receives a compact **Actionable Now** strip showing the highest-priority native plans. It links to `/signals` and does not duplicate the full Command Center or Trust Pane.

The Trust Pane continues to show Amo Arbitrage as an external advisory source. Native and external plans use explicit source badges and are never blended into a single recommendation without a future, separately designed consensus contract.

## Trade Plan Card

Each card presents:

- Symbol, contract, direction, strategy, timeframe, and age.
- A clear action label: buy, sell, hold, or no trade.
- Entry, stop, T1, and T2.
- Planned R:R and proposed size/risk.
- Latest price and distance in price, percent, ATR, and ticks.
- Lifecycle state.
- Gate verdict and policy authorization as separate badges.
- Paper execution eligibility and blockers.
- Source, provider, and freshness.
- Expandable reasoning, risk notes, and validation metrics.

The distinctive visual is a compact price-geometry rail: stop, entry, latest price, T1, and T2 appear in directional order on one scale. The rail communicates risk and reward faster than another grid of generic metric tiles. Exact numeric labels remain visible for accessibility and verification.

The design retains JARVIS's current visual language, density, and responsive behavior. Direction is conveyed by text and iconography as well as color. Mobile cards stack geometry and status without horizontal page scrolling.

## Failure Behavior

- Missing price: show issued geometry, mark live context unavailable, and block price-derived lifecycle transitions.
- Stale price: show age and provider, preserve last confirmed state, and block execution eligibility if freshness policy requires it.
- Missing validation: retain the plan as analysis-only with a `VALIDATION_UNAVAILABLE` blocker.
- Gate failure with an authorized exception: show both facts independently.
- Engine unavailable: show a clear unavailable state; never generate demo recommendations in production.
- Conflicting or non-finite levels: preserve the rejected plan for audit, mark invalid geometry, and prevent execution.
- Unknown contract or tick size: omit tick distance and add provenance detail; do not assume a tick size.

## Rollout

1. Add the contract, invariant validation, and persistence migration.
2. Map finalized native `TradeDecision` objects into immutable plans.
3. Add read APIs and server-side live-context/lifecycle derivation.
4. Build the `/signals` Trade Plans page using fixture-backed component states.
5. Add the compact Actionable Now strip to the main dashboard.
6. Run focused engine, API, dashboard, and browser verification.
7. Deploy the dashboard and engine changes through the existing release path.
8. Perform any required engine restart only after explicit authorization and peer-session coordination.

## Verification Strategy

### Engine and contract

- Unit fixtures for valid and invalid long/short geometry.
- Exact numeric checks for risk per unit, R:R, distance, ATR, percent, and tick calculations.
- Mapping tests proving every relevant `TradeDecision` field survives serialization and persistence.
- Tests proving `HOLD`, `NO_TRADE`, stale prices, invalid geometry, and missing validation fail closed.
- Lifecycle tests for both directions at every threshold and terminal precedence.

### Persistence and API

- Migration and round-trip tests.
- Immutability and duplicate-decision tests.
- Approval, order, and trade linkage tests.
- Contract tests for null handling, freshness, filtering, and backward compatibility.

### Dashboard

- Component tests for every action, lifecycle, gate, eligibility, blocker, and unavailable state.
- Formatter tests preserving precision appropriate to each instrument.
- Responsive and keyboard-accessibility checks.
- Playwright flows with deterministic mocked contracts.
- A real-engine smoke test that compares rendered entry, stop, targets, and R:R to the API response value by value.

Completion requires both behavioral verification and direct numeric source-of-truth validation. A visually correct card with mismatched levels is a release blocker.

## Safety and Compatibility

This change is additive. It does not authorize live trading, modify risk thresholds, bypass validation, change symbol policies, or restart services. Execution remains governed by the existing engine controls. The plan surface explains those controls; it does not replace them.

## Rejected Alternatives

### Render existing approval rows more richly

Rejected because approvals are not a complete source of autonomous decision history and currently omit reliable geometry.

### Consume Amo Arbitrage targets as JARVIS's primary plan feed

Rejected because the systems have different validation maturity, lifecycle semantics, and execution authority. This would create unsafe coupling and ambiguous provenance.

### Recompute levels in the dashboard

Rejected because UI-side reconstruction can drift from the executed decision and breaks auditability. The engine-issued plan is the sole source of truth.
