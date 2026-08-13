# Native Trade Plan Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist every finalized JARVIS recommendation as a native trade plan and present its entry, stop, targets, live distance, validation, execution readiness, and lifecycle clearly on `/signals` and the Command Center.

**Architecture:** Add an immutable engine `TradePlan` contract and SQLite store at the finalized pipeline boundary, then enrich plans at read time with current-price context and lifecycle state. Replace the approval-backed actionable prototype with `/trade-plans`, and build focused dashboard components around that contract while retaining the external Amo Arbitrage feed as separately labeled advisory data.

**Tech Stack:** Python 3.11, dataclasses/Pydantic-compatible dictionaries, FastAPI, SQLite migrations and repository mixins, pytest; Next.js 15, React 19, TypeScript 5.8, SWR, Tailwind, Radix UI, Playwright.

**Spec:** `docs/superpowers/specs/2026-08-13-native-trade-plan-dashboard-design.md`

## Global Constraints

- Preserve gate-v2 verdict, policy authorization, execution readiness, and lifecycle as independent fields.
- `HOLD` and `NO_TRADE` are first-class outputs and can never be execution-eligible.
- Never fabricate geometry, entry zones, tick sizes, validation results, prices, or legacy history.
- Issued geometry is immutable; live context is derived at read time.
- This work does not enable live trading, alter risk thresholds, change symbol policy, or restart services.
- All dashboard engine requests use `fetchEngine`; no bare `fetch` calls.
- Numeric completion requires source-of-truth comparison between API values and rendered values.
- Use the existing SQLite migration registry; migration 042 is additive and idempotent.
- Do not modify or commit unrelated dirty-worktree files.

---

## File Structure

### Engine files

- Create `engine/trade_plans/models.py`: enums, immutable issued-plan model, live-context model, response model, and serialization.
- Create `engine/trade_plans/service.py`: finalized pipeline mapping, invariant validation, policy/readiness mapping, price enrichment, sorting, and lifecycle derivation.
- Create `engine/trade_plans/__init__.py`: public exports only.
- Create `engine/database/_mixins_trade_plans.py`: append-only insert, linkage updates, detail, active, and recent queries.
- Modify `engine/database/migrations.py`: migration 042 for `trade_plans` plus indexes.
- Modify `engine/database/manager.py`: compose `TradePlansMixin` and report its row count.
- Modify `engine/agents/pipeline.py`: persist one plan after final action/quantity resolution and before broadcasts or execution handoff.
- Create `engine/routers/trade_plans_router.py`: `/trade-plans` list/detail endpoints with price enrichment and honest degradation.
- Modify `engine/main.py`: import, inject, and register the router.
- Modify `engine/analytics/actionable.py`: delegate reusable lifecycle math to `trade_plans.service`; retain `/pipeline/actionable` as a compatibility adapter during rollout.

### Dashboard files

- Modify `dashboard/lib/api.ts`: canonical TypeScript trade-plan contract and `fetchTradePlans` helpers.
- Create `dashboard/lib/tradePlanFormatters.ts`: pure grouping, numeric formatting, geometry-scale, and status-label helpers.
- Create `dashboard/components/trade-plans/TradePlanCard.tsx`: accessible detailed card.
- Create `dashboard/components/trade-plans/PriceGeometryRail.tsx`: stop/entry/latest/T1/T2 rail.
- Create `dashboard/components/trade-plans/TradePlanSection.tsx`: titled grouped collection and empty/error states.
- Create `dashboard/components/trade-plans/ActionableNowStrip.tsx`: compact Command Center surface.
- Modify `dashboard/app/signals/page.tsx`: Trade Plans information architecture; options analysis becomes secondary.
- Modify `dashboard/app/command-center/page.tsx`: mount the compact strip in the existing signals region.

### Test files

- Create `engine/tests/test_trade_plan_models.py`.
- Create `engine/tests/test_trade_plan_service.py`.
- Create `engine/tests/test_trade_plan_database.py`.
- Create `engine/tests/test_trade_plans_router.py`.
- Modify `engine/tests/test_pipeline_e2e.py` with the finalized-plan persistence assertion.
- Create `dashboard/tests/tradePlanFormatters.node.test.ts`.
- Modify `dashboard/tests/e2e/trade-signals.spec.ts`.
- Modify `dashboard/tests/e2e/command-center.spec.ts`.

---

### Task 1: Canonical Trade Plan Contract and Geometry Invariants

**Files:**
- Create: `engine/trade_plans/__init__.py`
- Create: `engine/trade_plans/models.py`
- Create: `engine/trade_plans/service.py`
- Test: `engine/tests/test_trade_plan_models.py`
- Test: `engine/tests/test_trade_plan_service.py`

**Interfaces:**
- Consumes: finalized `pipeline_result: dict[str, Any]`, policy/readiness snapshot dictionaries, instrument tick metadata.
- Produces: `build_trade_plan(pipeline_result, *, decision_id, created_at, expires_at, policy, readiness) -> TradePlan`; `validate_geometry(action, entry_price, stop_price, target_1, target_2) -> list[ExecutionBlocker]`; `derive_live_context(plan, price, *, now) -> TradePlanView`.

- [ ] **Step 1: Write failing contract tests**

```python
def test_buy_plan_serializes_independent_truth_dimensions():
    plan = make_plan(action="BUY", entry_price=6000, stop_price=5990,
                     target_1=6010, target_2=6020)
    payload = plan.to_dict()
    assert payload["gate_verdict"] == "FAIL"
    assert payload["policy_authorized"] is True
    assert payload["paper_execution_eligible"] is True
    assert payload["lifecycle_state"] == "AWAITING_ENTRY"

def test_no_trade_never_has_execution_eligibility():
    plan = make_plan(action="NO_TRADE", paper_execution_eligible=True)
    assert plan.paper_execution_eligible is False
    assert plan.entry_price is None
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: `python -m pytest engine/tests/test_trade_plan_models.py -q`

Expected: collection fails because `trade_plans.models` does not exist.

- [ ] **Step 3: Implement enums and immutable models**

Define exact string enums `TradeAction`, `EntryType`, and `LifecycleState`; frozen dataclasses `ExecutionBlocker`, `GateMetrics`, `TradePlan`, `LiveContext`, and `TradePlanView`. Normalize absent numerics to `None`, uppercase actions/states, store `schema_version="1.0"`, and force `HOLD`/`NO_TRADE` quantity and eligibility to zero/false in `TradePlan.__post_init__`.

```python
@dataclass(frozen=True)
class ExecutionBlocker:
    code: str
    message: str

@dataclass(frozen=True)
class TradePlan:
    plan_id: str
    decision_id: str
    symbol: str
    action: TradeAction
    entry_type: EntryType
    entry_price: float | None
    stop_price: float | None
    target_1: float | None
    target_2: float | None
    proposed_quantity: int
    gate_verdict: str
    policy_authorized: bool
    paper_execution_eligible: bool
    execution_blockers: tuple[ExecutionBlocker, ...]
    schema_version: str = "1.0"
```

- [ ] **Step 4: Write failing long/short invariant and lifecycle tests**

Cover valid long and short geometry, stop inversion, target inversion, non-finite values, zero risk, T2 ordering, exact-entry tolerance, stale price, stop reached, T1 reached, explicit expiry, and missing tick/ATR.

```python
def test_stale_price_does_not_advance_state():
    view = derive_live_context(long_plan(), stale_price(), now=NOW)
    assert view.live.price_stale is True
    assert view.lifecycle_state == LifecycleState.AWAITING_ENTRY

def test_entry_tolerance_is_max_tick_or_tenth_atr():
    view = derive_live_context(long_plan(atr_used=10), price(5999.25), now=NOW)
    assert view.live.entry_tolerance == 1.0
    assert view.lifecycle_state == LifecycleState.TRIGGERABLE
```

- [ ] **Step 5: Implement mapping, validation, and live derivation**

Use `tolerance = strategy_tolerance or max(min_tick, 0.10 * atr_used)` with one known tick as the fallback when ATR is absent. Recompute `risk_per_unit`, `rr_t1`, and `rr_t2` from geometry. Invalid geometry adds `INVALID_GEOMETRY`, sets eligibility false, and starts as `UNAVAILABLE`; it never repairs values. Terminal event fields override price-derived status in the spec's precedence order.

- [ ] **Step 6: Run focused tests**

Run: `python -m pytest engine/tests/test_trade_plan_models.py engine/tests/test_trade_plan_service.py -q`

Expected: all tests pass with no warnings introduced by these modules.

- [ ] **Step 7: Commit the contract boundary**

```powershell
git add engine/trade_plans engine/tests/test_trade_plan_models.py engine/tests/test_trade_plan_service.py
git commit -m "feat(trading): define native trade-plan contract"
```

---

### Task 2: Append-Only Trade Plan Persistence

**Files:**
- Modify: `engine/database/migrations.py`
- Create: `engine/database/_mixins_trade_plans.py`
- Modify: `engine/database/manager.py`
- Test: `engine/tests/test_trade_plan_database.py`

**Interfaces:**
- Consumes: `TradePlan.to_dict() -> dict[str, Any]` from Task 1.
- Produces: `insert_trade_plan(plan) -> bool`; `get_trade_plan(plan_id) -> dict | None`; `get_trade_plans(scope, limit, filters) -> list[dict]`; `link_trade_plan(plan_id, *, approval_id=None, order_id=None, trade_id=None) -> bool`.

- [ ] **Step 1: Write failing migration and round-trip tests**

Assert schema version 42, all issued fields round-trip without numeric drift, duplicate `decision_id` is idempotently rejected, filters are parameterized, newest-first ordering is stable, and linkage updates cannot mutate issued geometry.

- [ ] **Step 2: Run the database test and verify failure**

Run: `python -m pytest engine/tests/test_trade_plan_database.py -q`

Expected: failure because migration 042 and `TradePlansMixin` do not exist.

- [ ] **Step 3: Add migration 042**

Create `trade_plans` with `plan_id TEXT PRIMARY KEY`, `decision_id TEXT NOT NULL UNIQUE`, indexed `symbol`, `action`, `created_at`, `expires_at`, and `resolved_at`; store the canonical immutable payload in `issued_plan_json TEXT NOT NULL`; store only linkage and lifecycle-event metadata outside that JSON. Add `migration_042` to both registries with description `Native trade plans: immutable issued geometry with execution linkage`.

- [ ] **Step 4: Implement the repository mixin and manager composition**

Deserialize JSON on reads; permit `approval_id`, `order_id`, `trade_id`, `resolved_at`, and `resolution_reason` updates only. Use the manager lock and connection-per-call pattern. Add `trade_plans` to `health_check()` row counts.

- [ ] **Step 5: Run database tests twice**

Run: `python -m pytest engine/tests/test_trade_plan_database.py -q && python -m pytest engine/tests/test_trade_plan_database.py -q`

Expected: both runs pass, proving migration and inserts are idempotent.

- [ ] **Step 6: Commit persistence**

```powershell
git add engine/database/migrations.py engine/database/_mixins_trade_plans.py engine/database/manager.py engine/tests/test_trade_plan_database.py
git commit -m "feat(database): persist immutable trade plans"
```

---

### Task 3: Persist Finalized Pipeline Decisions

**Files:**
- Modify: `engine/agents/pipeline.py:1015-1323`
- Test: `engine/tests/test_pipeline_e2e.py`
- Test: `engine/tests/test_trade_plan_service.py`

**Interfaces:**
- Consumes: `build_trade_plan(...)` and `DatabaseManager.insert_trade_plan(...)`.
- Produces: `pipeline_result["trade_plan"]` containing the exact persisted plan payload; persistence failures append an error and force execution eligibility false without crashing the pipeline.

- [ ] **Step 1: Write a failing finalized-plan pipeline test**

Build a deterministic pipeline fixture whose trader emits BUY geometry, risk approves, and fund manager sets final quantity. Assert one stored plan, exact entry/stop/T1/T2, final quantity rather than preliminary quantity, separate gate/policy fields, and the returned `plan_id`.

- [ ] **Step 2: Run the targeted pipeline test**

Run: `python -m pytest engine/tests/test_pipeline_e2e.py -k trade_plan -q`

Expected: failure because the pipeline does not persist `trade_plan`.

- [ ] **Step 3: Add the finalized-plan handoff**

Immediately after `pipeline_result["final_action"]`, `final_quantity`, and `requires_human` are assigned, call a focused `_persist_trade_plan(...)` helper. Pass the trader geometry unchanged, overlay only final action/quantity and explicit readiness/policy facts, and generate a stable decision identity. Do not place this after a broadcast or broker submission.

```python
plan = build_trade_plan(
    pipeline_result,
    decision_id=decision_identity,
    created_at=started_at,
    expires_at=decision_expiry,
    policy=policy_snapshot,
    readiness=readiness_snapshot,
)
inserted = self._db.insert_trade_plan(plan)
pipeline_result["trade_plan"] = plan.to_dict()
```

- [ ] **Step 4: Add fail-closed tests**

Prove risk/fund veto produces `NO_TRADE`, invalid geometry persists with `INVALID_GEOMETRY`, and a database write exception yields `TRADE_PLAN_PERSISTENCE_FAILED` and prevents the new plan from being advertised as execution-eligible.

- [ ] **Step 5: Run pipeline and contract tests**

Run: `python -m pytest engine/tests/test_pipeline_e2e.py engine/tests/test_trade_plan_service.py -q`

Expected: all selected tests pass.

- [ ] **Step 6: Commit pipeline integration**

```powershell
git add engine/agents/pipeline.py engine/tests/test_pipeline_e2e.py engine/tests/test_trade_plan_service.py
git commit -m "feat(pipeline): record finalized trade plans"
```

---

### Task 4: Trade Plan Read API and Compatibility Adapter

**Files:**
- Create: `engine/routers/trade_plans_router.py`
- Modify: `engine/main.py:115-118,3232-3318`
- Modify: `engine/analytics/actionable.py`
- Modify: `engine/routers/actionable_router.py`
- Test: `engine/tests/test_trade_plans_router.py`
- Test: `engine/tests/test_actionable.py`

**Interfaces:**
- Consumes: database query methods, `derive_live_context`, and `routers.prices_router.get_price_snapshot`.
- Produces: `GET /trade-plans?scope=active|recent&limit=1..100`; `GET /trade-plans/{plan_id}`; compatibility `GET /pipeline/actionable` mapped from native plan views.

- [ ] **Step 1: Write failing API contract tests**

Test active/recent scopes, plan detail 404, symbol/action/lifecycle/eligibility/gate filters, `available=false` on database failure, stale-price behavior, current provider/as-of fields, and independent gate versus policy exception values.

- [ ] **Step 2: Run router tests and verify failure**

Run: `python -m pytest engine/tests/test_trade_plans_router.py -q`

Expected: import or route-not-found failure.

- [ ] **Step 3: Implement the router**

Use prefix `/trade-plans`. Fetch persisted plans first, request one cached price snapshot for their distinct symbols, enrich server-side, then sort into executable, actionable-blocked, waiting, no-trade/blocked, and resolved order. Return this envelope:

```python
{
    "available": True,
    "generated_at": now.isoformat(),
    "latest_price_as_of": latest_as_of,
    "stale": any(view.live.price_stale for view in views),
    "plans": [view.to_dict() for view in views],
}
```

Database failure returns HTTP 200 with `available=false`, an empty list, and a concise note. A missing individual ID returns 404. Price failure retains issued plans with unavailable live context.

- [ ] **Step 4: Register dependencies and routes**

Follow `actionable_router`'s explicit injection pattern in `main.py`. Include `trade_plans_router` once and add a route-wiring assertion.

- [ ] **Step 5: Convert the old actionable path into an adapter**

Keep `/pipeline/actionable` during migration, but have it map native `TradePlanView` objects into the legacy `ActionableBoardResponse`. Remove approval-table-specific derivation from the primary path. Preserve pure-function tests for lifecycle math.

- [ ] **Step 6: Run API and compatibility tests**

Run: `python -m pytest engine/tests/test_trade_plans_router.py engine/tests/test_actionable.py engine/tests/test_routes_wired.py -q`

Expected: all selected tests pass and both routes are present exactly once.

- [ ] **Step 7: Commit API surface**

```powershell
git add engine/routers/trade_plans_router.py engine/routers/actionable_router.py engine/analytics/actionable.py engine/main.py engine/tests/test_trade_plans_router.py engine/tests/test_actionable.py engine/tests/test_routes_wired.py
git commit -m "feat(api): expose native trade plans"
```

---

### Task 5: Dashboard Contract, Grouping, and Numeric Formatting

**Files:**
- Modify: `dashboard/lib/api.ts`
- Create: `dashboard/lib/tradePlanFormatters.ts`
- Create: `dashboard/tests/tradePlanFormatters.node.test.ts`

**Interfaces:**
- Consumes: `/trade-plans` response from Task 4.
- Produces: `TradePlan`, `TradePlanResponse`, `fetchTradePlans(scope)`, `groupTradePlans(plans)`, `formatPlanPrice(value, tickSize)`, and `geometryPositions(plan)`.

- [ ] **Step 1: Write failing pure TypeScript tests**

Assert exact grouping precedence, separate gate/policy fields, em dash for null, zero preserved as zero, tick-aware price precision, long and short rail ordering, clamped rail positions, stale labels, and no-trade grouping.

- [ ] **Step 2: Run the formatter test and verify failure**

Run: `pnpm test:unit -- tests/tradePlanFormatters.node.test.ts`

Expected: module-not-found failure.

- [ ] **Step 3: Add exact API types and helpers**

Mirror snake_case response names exactly. `fetchTradePlans(scope)` calls `fetchEngine<TradePlanResponse>(\`/trade-plans?scope=${scope}\`)`. Do not derive gate verdict or eligibility in TypeScript.

- [ ] **Step 4: Implement pure presentation helpers**

Group in order: executable paper, actionable analysis, waiting for entry, no-trade/blocked, recently resolved. Compute rail positions from the min/max of available stop/entry/latest/T1/T2 values without changing their numeric labels; return `null` when fewer than two geometry points exist.

- [ ] **Step 5: Run unit tests and typecheck**

Run: `pnpm test:unit -- tests/tradePlanFormatters.node.test.ts`

Run: `pnpm typecheck`

Expected: both commands pass.

- [ ] **Step 6: Commit dashboard contract**

```powershell
git add dashboard/lib/api.ts dashboard/lib/tradePlanFormatters.ts dashboard/tests/tradePlanFormatters.node.test.ts
git commit -m "feat(dashboard): add trade-plan client contract"
```

---

### Task 6: Trade Plan Cards and Price Geometry Rail

**Files:**
- Create: `dashboard/components/trade-plans/PriceGeometryRail.tsx`
- Create: `dashboard/components/trade-plans/TradePlanCard.tsx`
- Create: `dashboard/components/trade-plans/TradePlanSection.tsx`
- Create: `dashboard/tests/tradePlanComponents.node.test.ts`

**Interfaces:**
- Consumes: `TradePlan` and formatter helpers from Task 5.
- Produces: reusable `TradePlanCard`, `PriceGeometryRail`, and `TradePlanSection` components.

- [ ] **Step 1: Write failing static/component contract tests**

Verify the components expose action text, entry/stop/T1/T2 labels, latest price, all distance units, planned R:R, quantity/risk, lifecycle, gate verdict, policy authorization, execution blockers, source/freshness, expandable reasoning, and accessible non-color direction labels.

- [ ] **Step 2: Run tests and verify failure**

Run: `pnpm test:unit -- tests/tradePlanComponents.node.test.ts`

Expected: component imports fail.

- [ ] **Step 3: Implement the geometry rail**

Render a relative horizontal scale with labeled markers for available stop, entry, latest, T1, and T2. Preserve directional numeric ordering for both BUY and SELL, use `aria-label` text containing exact values, and fall back to a compact exact-value row when scale construction is impossible.

- [ ] **Step 4: Implement the card and section**

Keep gate and policy badges adjacent but distinct. Render blockers as stable code plus message. Mark stale/unavailable prices above the rail. Put reasoning, risk notes, and gate metrics in a native `<details>` disclosure. Use existing Card and Badge primitives and JARVIS typography; add no new UI dependency.

- [ ] **Step 5: Run unit tests and typecheck**

Run: `pnpm test:unit -- tests/tradePlanComponents.node.test.ts`

Run: `pnpm typecheck`

Expected: both pass.

- [ ] **Step 6: Commit reusable components**

```powershell
git add dashboard/components/trade-plans dashboard/tests/tradePlanComponents.node.test.ts
git commit -m "feat(dashboard): render trade-plan geometry"
```

---

### Task 7: Rebuild `/signals` as Trade Plans

**Files:**
- Modify: `dashboard/app/signals/page.tsx`
- Modify: `dashboard/tests/e2e/trade-signals.spec.ts`

**Interfaces:**
- Consumes: `fetchTradePlans`, `groupTradePlans`, `TradePlanSection`, and the existing `OptionsSignalsPanel`.
- Produces: the complete Trade Plans page at the compatible `/signals` route.

- [ ] **Step 1: Replace the smoke fixture with deterministic plan states**

Mock `/api/engine/trade-plans*` with one executable MES BUY, one gate-blocked actionable SELL, one waiting plan, one `NO_TRADE`, and one resolved plan. Assert exact entry/stop/T1/T2 and separate `Gate FAIL` plus `Policy Authorized` copy. Assert options content occurs after native sections.

- [ ] **Step 2: Run the Playwright test and verify failure**

Run: `pnpm exec playwright test tests/e2e/trade-signals.spec.ts --project=chromium`

Expected: failure because the page still reads approval endpoints and says Trade Signals.

- [ ] **Step 3: Implement the new page hierarchy**

Poll `/trade-plans?scope=active` every 30 seconds and `/trade-plans?scope=recent` every five minutes. Render health/freshness first, then Executable Paper Plans, Actionable Analysis, Waiting for Entry, No Trade / Blocked, Recently Resolved, and finally Options Market-Implied Analysis. A response with `available=false` must say data is unavailable, never “no opportunities.”

- [ ] **Step 4: Add responsive and degraded-state assertions**

Test desktop and mobile widths, empty available response, unavailable response, stale price, null geometry, keyboard-opened reasoning, and absence of horizontal page overflow.

- [ ] **Step 5: Run focused browser and static checks**

Run: `pnpm exec playwright test tests/e2e/trade-signals.spec.ts --project=chromium`

Run: `pnpm typecheck`

Expected: both pass.

- [ ] **Step 6: Commit the page migration**

```powershell
git add dashboard/app/signals/page.tsx dashboard/tests/e2e/trade-signals.spec.ts
git commit -m "feat(dashboard): make signals page trade-plan first"
```

---

### Task 8: Add the Command Center Actionable Now Strip

**Files:**
- Create: `dashboard/components/trade-plans/ActionableNowStrip.tsx`
- Modify: `dashboard/app/command-center/page.tsx:1040-1065`
- Modify: `dashboard/tests/e2e/command-center.spec.ts`

**Interfaces:**
- Consumes: active trade-plan response and shared compact formatting.
- Produces: a compact, linked Actionable Now strip on the main Command Center.

- [ ] **Step 1: Write a failing Command Center test**

Mock two active plans and assert the strip shows symbol, action, entry, stop, T1, lifecycle, eligibility, stale state when applicable, and a link to `/signals`. Assert it does not render expanded reasoning or options analysis.

- [ ] **Step 2: Run the focused browser test**

Run: `pnpm exec playwright test tests/e2e/command-center.spec.ts --project=chromium -g "Actionable Now"`

Expected: failure because the strip is absent.

- [ ] **Step 3: Implement and mount the strip**

Fetch active plans at the shared 30-second cadence. Select at most three plans in server-provided priority order. Mount the strip immediately before the existing Recent Signals/Pipeline region and wrap it in the established widget error boundary. Keep cards compact and link the title and each item to `/signals`.

- [ ] **Step 4: Run focused and regression checks**

Run: `pnpm exec playwright test tests/e2e/command-center.spec.ts --project=chromium`

Run: `pnpm typecheck`

Expected: both pass and existing Command Center sections remain visible.

- [ ] **Step 5: Commit the compact surface**

```powershell
git add dashboard/components/trade-plans/ActionableNowStrip.tsx dashboard/app/command-center/page.tsx dashboard/tests/e2e/command-center.spec.ts
git commit -m "feat(dashboard): surface actionable trade plans"
```

---

### Task 9: Cross-Layer Verification, Documentation, and Handoff

**Files:**
- Modify: `docs/superpowers/specs/2026-08-13-native-trade-plan-dashboard-design.md` only if implementation decisions differ materially.
- Create: `docs/session-logs/HANDOFF_2026-08-13_native-trade-plans.md`

**Interfaces:**
- Consumes: all prior tasks.
- Produces: verified release candidate and complete session handoff; no service restart or deployment.

- [ ] **Step 1: Run focused engine verification**

Run: `python -m pytest engine/tests/test_trade_plan_models.py engine/tests/test_trade_plan_service.py engine/tests/test_trade_plan_database.py engine/tests/test_trade_plans_router.py engine/tests/test_pipeline_e2e.py engine/tests/test_actionable.py -q`

Expected: all selected tests pass.

- [ ] **Step 2: Run dashboard verification**

Run: `pnpm test:unit -- tests/tradePlanFormatters.node.test.ts tests/tradePlanComponents.node.test.ts`

Run: `pnpm typecheck`

Run: `pnpm exec playwright test tests/e2e/trade-signals.spec.ts tests/e2e/command-center.spec.ts --project=chromium`

Expected: all commands pass.

- [ ] **Step 3: Perform numeric source-of-truth verification**

Start only already-authorized local development processes; do not restart the engine. Capture one `/trade-plans/{id}` response and assert the rendered card text matches `entry_price`, `stop_price`, `target_1`, `target_2`, `rr_t1`, latest price, and distance fields exactly after documented formatting. Record the plan ID and compared values in the handoff.

- [ ] **Step 4: Run repository safety checks**

Run: `git diff --check`

Run: `git status --short`

Run: `git diff --stat`

Expected: no whitespace errors; unrelated pre-existing files remain untouched and uncommitted.

- [ ] **Step 5: Write the required handoff**

Include Current state, Key decisions made, In-progress work, Blockers discovered, Files created or modified, TODO items, Git state (`git status`, `git log --oneline -20`, `git diff --stat`), and one Suggested next action. Explicitly state that restart/deployment were not authorized or performed.

- [ ] **Step 6: Commit verification documentation**

```powershell
git add docs/session-logs/HANDOFF_2026-08-13_native-trade-plans.md docs/superpowers/specs/2026-08-13-native-trade-plan-dashboard-design.md
git commit -m "docs(trading): hand off native trade plans"
```

- [ ] **Step 7: Stop at the release boundary**

Report test evidence, numeric comparison, commits, dirty-worktree preservation, and the exact remaining deployment/restart action. Request explicit authorization before engine restart, production deployment, branch integration, or push.
