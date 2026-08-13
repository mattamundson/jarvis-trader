# JARVIS Trader Dashboard Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidate the JARVIS dashboard into trustworthy trading and system surfaces, eliminate observed presentation defects and polling debt, modularize data access, and make numeric UI truth part of one repeatable verification gate.

**Architecture:** Apply an incremental strangler migration. Pure helpers and domain modules are introduced behind compatibility exports, large pages are decomposed without changing calculations, and old URLs continue working. Every behavior change uses red-green TDD; every numeric assertion includes provenance.

**Tech Stack:** Next.js 15 App Router, React 19, TypeScript 5.8, SWR 2, Node test runner, Playwright, Tailwind CSS, PowerShell/Windows 11.

**Spec:** `docs/superpowers/specs/2026-08-13-dashboard-hardening-design.md`

## Global Constraints

- Paper-only behavior remains unchanged; do not alter execution, risk, kill-switch, or strategy gates.
- Use the same-origin `/api/engine` proxy; no browser API keys, direct engine URLs, or bare fetches.
- Missing or contradictory numeric data renders unavailable/degraded, never a fabricated zero.
- Preserve existing URLs through redirects or compatibility shells.
- Use `127.0.0.1` for Windows-local service URLs.
- Use `pnpm` and `./node_modules/.bin/tsc`.
- Preserve unrelated untracked files.
- Archive retirements under `~/Archive/2026/jarvis-dashboard/`; never delete them.
- Stage and commit exact paths only.

---

### Task 1: Relative-time and provider-diagnostic trust fixes

**Files:**
- Modify: `dashboard/lib/timeAgo.ts`
- Create: `dashboard/lib/providerDiagnostic.ts`
- Modify: `dashboard/components/LiveTradeReasoningWidget.tsx`
- Modify: `dashboard/components/RecentSignalsWidget.tsx`
- Test: `dashboard/tests/timeAgo.node.test.ts`
- Create: `dashboard/tests/providerDiagnostic.node.test.ts`

**Interfaces:**
- Produces: `relativeTime(isoString: string | null | undefined, now: Date): RelativeTimeDisplay`
- Produces: `classifyProviderDiagnostic(text: string | null | undefined): ProviderDiagnostic | null`
- `RelativeTimeDisplay = { text: string; state: "past" | "near-now" | "clock-skew" | "invalid" }`
- `ProviderDiagnostic = { title: string; consequence: string; failureClass: "billing" | "authentication" | "rate-limit" | "timeout" | "capacity" | "provider"; provider: string | null; detail: string }`

- [ ] **Step 1: Add failing relative-time tests**

```ts
test("future timestamps never render a negative age", () => {
  const result = relativeTime("2026-08-13T12:00:00Z", new Date("2026-08-13T07:00:00Z"));
  assert.equal(result.state, "clock-skew");
  assert.equal(result.text, "clock skew (+5h)");
});

test("invalid timestamps render unknown time", () => {
  assert.deepEqual(relativeTime("not-a-date", new Date()), {
    text: "unknown time",
    state: "invalid",
  });
});
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `node --test --experimental-strip-types --import ./tests/_register-alias.mjs tests/timeAgo.node.test.ts`

Expected: failure because `relativeTime` and structured states do not exist.

- [ ] **Step 3: Implement the minimal formatter and migrate active Command Center consumers**

Implement parsing, a 60-second future-skew tolerance, compact duration formatting, and compatibility `timeAgo()` delegating to `relativeTime().text`. Remove local time helpers from the two active widgets.

- [ ] **Step 4: Run the focused time tests and verify GREEN**

Run the command from Step 2. Expected: all time tests pass.

- [ ] **Step 5: Add failing provider-diagnostic tests**

```ts
test("billing failures become compact HOLD diagnostics", () => {
  const result = classifyProviderDiagnostic("trader LLM call failed: credit balance is too low; request_id=req_secret");
  assert.equal(result?.failureClass, "billing");
  assert.equal(result?.consequence, "Decision defaulted to HOLD");
  assert.equal(result?.title.includes("req_secret"), false);
});

test("ordinary market reasoning is not classified as infrastructure failure", () => {
  assert.equal(classifyProviderDiagnostic("Momentum weakened below VWAP"), null);
});
```

- [ ] **Step 6: Run provider tests and verify RED**

Run: `node --test --experimental-strip-types --import ./tests/_register-alias.mjs tests/providerDiagnostic.node.test.ts`

Expected: module/function missing.

- [ ] **Step 7: Implement classifier and presentation**

Add deterministic pattern classification. Render the compact title/consequence by default and raw detail only inside a labeled disclosure. Keep ordinary reasoning unchanged.

- [ ] **Step 8: Run focused tests, unit suite, and typecheck**

Run:

```powershell
pnpm run test:unit
pnpm run typecheck
```

- [ ] **Step 9: Commit exact files**

Commit: `fix(dashboard): clarify timestamps and provider failures`

### Task 2: Authoritative navigation and page ownership

**Files:**
- Modify: `dashboard/components/Sidebar.tsx`
- Create: `dashboard/lib/navigation.ts`
- Modify: `dashboard/app/command-center/page.tsx`
- Modify: `dashboard/app/mission-control/page.tsx`
- Create: `dashboard/tests/navigation.node.test.ts`
- Modify: `dashboard/tests/routeManifest.node.test.ts`
- Modify: `dashboard/tests/e2e/command-center-golden-path.spec.ts`
- Modify: `dashboard/tests/e2e/mission-control.spec.ts`

**Interfaces:**
- Produces: `PRIMARY_NAV_GROUPS`, `DEEP_TOOL_GROUPS`, and `routeOwner(pathname: string): "operate" | "system" | "analyze" | "validate" | "admin" | "research"`

- [ ] **Step 1: Add failing ownership/navigation tests**

```ts
test("command-center and mission-control have distinct ownership", () => {
  assert.equal(routeOwner("/command-center"), "operate");
  assert.equal(routeOwner("/mission-control"), "system");
});

test("primary navigation contains at most twelve destinations", () => {
  assert.ok(PRIMARY_NAV_GROUPS.flatMap((group) => group.items).length <= 12);
});
```

- [ ] **Step 2: Run focused navigation tests and verify RED**

Expected: navigation module missing.

- [ ] **Step 3: Implement route ownership and a primary/deep-tools sidebar**

Keep every existing route reachable. Primary navigation contains the authoritative workflow destinations; diagnostic, exploratory, and specialist pages live under clearly labeled deep tools.

- [ ] **Step 4: Add explicit ownership copy to Command Center and Mission Control**

Command Center copy states that it owns immediate paper-trading decisions. Mission Control copy states that it owns infrastructure and data-path operations.

- [ ] **Step 5: Run navigation, route-manifest, typecheck, and focused E2E tests**

Use the fresh Playwright configuration, never the reused `:3010` configuration.

- [ ] **Step 6: Commit exact files**

Commit: `refactor(dashboard): establish authoritative workspaces`

### Task 3: Validation and Performance summary-first workspaces

**Files:**
- Modify: `dashboard/app/validation/page.tsx`
- Modify: `dashboard/app/performance/page.tsx`
- Create: `dashboard/components/validation/ValidationWorkspace.tsx`
- Create: `dashboard/components/validation/validationSections.ts`
- Create: `dashboard/components/performance/PerformanceWorkspace.tsx`
- Create: `dashboard/components/performance/performanceSections.ts`
- Create: `dashboard/tests/workspaceSections.node.test.ts`
- Modify: `dashboard/tests/e2e/trading-eligibility.spec.ts`
- Create: `dashboard/tests/e2e/performance-summary.spec.ts`

**Interfaces:**
- Produces: `VALIDATION_SECTIONS` and `PERFORMANCE_SECTIONS`, each with stable `id`, `label`, `summary`, and lazy component loader.
- Workspace URL contract: `?section=<id>`; absent/invalid section resolves to `summary`.

- [ ] **Step 1: Add failing section-contract tests**

```ts
test("validation defaults to summary and exposes all required drill-down sections", () => {
  assert.equal(resolveWorkspaceSection(VALIDATION_SECTIONS, null), "summary");
  assert.deepEqual(VALIDATION_SECTIONS.map((s) => s.id), [
    "summary", "paper", "backtest", "wfe", "reconciliation", "audit",
  ]);
});
```

- [ ] **Step 2: Verify RED**

Expected: section modules do not exist.

- [ ] **Step 3: Extract existing page blocks without changing calculations**

Move coherent JSX/data blocks into section components. Preserve endpoint keys, labels, numeric formatting, provenance, and error handling.

- [ ] **Step 4: Implement summary-first URL-driven workspaces**

Only the selected heavy section mounts. Summary cards link to the corresponding section. Browser back/forward preserves selection.

- [ ] **Step 5: Add and run Playwright assertions**

Assert initial summary headings, section navigation, deep-link loading, and that a non-selected heavy section is absent from the DOM.

- [ ] **Step 6: Run unit, typecheck, and fresh focused E2E suites**

- [ ] **Step 7: Commit exact files**

Commit: `refactor(dashboard): make review pages summary first`

### Task 4: Polling cadence and shared-key migration

**Files:**
- Modify: `dashboard/lib/polling-config.ts`
- Modify: active `dashboard/app/**/*.tsx`, `dashboard/components/**/*.tsx`, and `dashboard/hooks/**/*.ts` files containing numeric `refreshInterval`
- Modify: `dashboard/scripts/check-guards.mjs`
- Create: `dashboard/tests/pollingConfig.node.test.ts`

**Interfaces:**
- Produces: `pollingIntervalForMs(ms: number): PollInterval`
- Produces: canonical keys for health, positions, approvals, and execution state.

- [ ] **Step 1: Add failing cadence-map tests**

```ts
test("existing cadences map without becoming faster", () => {
  assert.equal(pollingIntervalForMs(5_000), POLL_INTERVAL.FAST);
  assert.equal(pollingIntervalForMs(15_000), POLL_INTERVAL.STATUS);
  assert.equal(pollingIntervalForMs(60_000), POLL_INTERVAL.MINUTE);
});
```

- [ ] **Step 2: Verify RED**

- [ ] **Step 3: Add named tiers covering all current effective cadences**

Do not round a slower interval down to a faster tier. Add a named tier where required to preserve behavior exactly.

- [ ] **Step 4: Migrate literals by shared endpoint group**

After each group, run typecheck and unit tests. Health/positions/approvals/signals move first; slow research pages move last.

- [ ] **Step 5: Tighten the guard to zero numeric SWR refresh literals**

The guard must fail on `refreshInterval: <number>` outside allowlisted test fixtures.

- [ ] **Step 6: Verify zero literals, guards, unit tests, and typecheck**

- [ ] **Step 7: Commit exact migrated paths**

Commit: `refactor(dashboard): centralize polling cadence`

### Task 5: Domain API modules with compatibility exports

**Files:**
- Create: `dashboard/lib/api/core.ts`
- Create: `dashboard/lib/api/health.ts`
- Create: `dashboard/lib/api/trading.ts`
- Create: `dashboard/lib/api/performance.ts`
- Create: `dashboard/lib/api/validation.ts`
- Create: `dashboard/lib/api/research.ts`
- Modify: `dashboard/lib/api.ts`
- Create: `dashboard/tests/apiDomains.node.test.ts`
- Modify: existing API contract tests

**Interfaces:**
- `core.ts` owns proxy request construction and error envelopes.
- Domain modules own domain types and functions.
- `lib/api.ts` re-exports migrated public symbols during compatibility period.

- [ ] **Step 1: Add failing domain-boundary source tests**

```ts
test("domain modules do not duplicate direct request primitives", () => {
  for (const file of domainFiles) {
    const source = readFileSync(file, "utf8");
    assert.doesNotMatch(source, /fetch\s*\(/);
    assert.match(source, /from ["']\.\/core["']/);
  }
});
```

- [ ] **Step 2: Verify RED**

- [ ] **Step 3: Extract core without changing request behavior**

Run engine-proxy header and path tests immediately.

- [ ] **Step 4: Move contracts one domain at a time**

After each move, retain `export { ... } from "./api/<domain>"` in the facade and run typecheck.

- [ ] **Step 5: Migrate active authoritative screens to domain imports**

Deep tools may continue using compatibility imports until a later focused migration.

- [ ] **Step 6: Run unit, guards, and typecheck**

- [ ] **Step 7: Commit exact files**

Commit: `refactor(dashboard): split API client by domain`

### Task 6: Numeric engine-proxy-render golden paths

**Files:**
- Create: `dashboard/tests/e2e/fixtures/numericTruth.ts`
- Create: `dashboard/tests/e2e/numeric-truth.spec.ts`
- Modify: `dashboard/playwright.fresh.config.ts`
- Modify: authoritative components only when stable selectors/provenance labels are missing

**Interfaces:**
- Produces: `NUMERIC_TRUTH_FIXTURE` with distinctive values and intercepted proxy responses.
- Stable selectors use `data-testid="truth-<metric>"` and `data-source`.

- [ ] **Step 1: Add failing proxy-to-render assertions**

```ts
await expect(page.getByTestId("truth-realized-pnl")).toHaveText("$12,345.67");
await expect(page.getByTestId("truth-realized-pnl")).toHaveAttribute("data-scope", "lifetime");
await expect(page.getByTestId("truth-drawdown")).toHaveText("-4.25%");
await expect(page.getByTestId("truth-drawdown")).toHaveAttribute("data-source", "engine");
```

Fixtures must also cover daily P&L, equity, position side/quantity, confidence, four gate-v2 values, market-data freshness/source, and kill-switch state.

- [ ] **Step 2: Run fresh focused E2E and verify RED**

Expected: selectors/provenance contract missing or wrong-field bindings exposed.

- [ ] **Step 3: Add minimal stable truth attributes and correct any demonstrated bindings**

Do not change a calculation without a corresponding distinctive fixture assertion.

- [ ] **Step 4: Re-run focused E2E and verify GREEN**

- [ ] **Step 5: Run unit, typecheck, and full fresh E2E**

- [ ] **Step 6: Commit exact files**

Commit: `test(dashboard): verify numeric truth end to end`

### Task 7: Canonical verification command

**Files:**
- Modify: `dashboard/package.json`
- Modify: `dashboard/scripts/check-bundle-budget.mjs`
- Create: `dashboard/scripts/verify-dashboard.mjs`
- Create: `dashboard/tests/verifyScript.node.test.ts`
- Modify: `dashboard/DASHBOARD_DEV.md`

**Interfaces:**
- `pnpm run budget` locates the canonical build log without a positional argument.
- `pnpm run verify` runs typecheck, unit, guards, clean build with captured log, budget, and fresh E2E.

- [ ] **Step 1: Add failing command-contract tests**

```ts
test("package scripts provide self-contained budget and verify commands", () => {
  assert.equal(pkg.scripts.budget.includes("<build-log>"), false);
  assert.match(pkg.scripts.verify, /verify-dashboard\.mjs/);
});
```

- [ ] **Step 2: Verify RED**

- [ ] **Step 3: Implement fail-fast orchestration**

Use `spawnSync` with inherited stdio, explicit Windows-safe `pnpm.cmd` resolution, an isolated fresh-E2E port, and cleanup in `finally`. Do not stop or reuse port 3010.

- [ ] **Step 4: Repair budget default-log discovery**

The checker accepts an optional explicit log for CI but defaults to the verification script's generated log.

- [ ] **Step 5: Run command-contract tests and focused script smoke**

- [ ] **Step 6: Run full `pnpm run verify`**

- [ ] **Step 7: Commit exact files**

Commit: `build(dashboard): add canonical verification gate`

### Task 8: Reproducible orphan audit and archive-only retirement

**Files:**
- Create: `dashboard/scripts/audit-component-reachability.mjs`
- Create: `dashboard/tests/componentReachability.node.test.ts`
- Create: `docs/audits/DASHBOARD_COMPONENT_REACHABILITY_2026-08-13.md`
- Create in archive: `~/Archive/2026/jarvis-dashboard/2026-08-13-orphan-pass/MANIFEST.md`
- Move only files classified and verified as `retire`.

**Interfaces:**
- Script output: JSON rows `{ path, reachable, classificationEvidence[] }`.
- Exit nonzero only for parse errors or unclassified unreachable production components.

- [ ] **Step 1: Add failing reachability-fixture tests**

Cover static import, dynamic import, barrel re-export, App Router entry, test-only import, and truly unreachable component fixtures.

- [ ] **Step 2: Verify RED**

- [ ] **Step 3: Implement graph construction and classification evidence**

Use source imports plus known App Router entry points. Do not retire based on regex count alone.

- [ ] **Step 4: Generate and manually inspect the report**

Cross-check documentation references, dynamic imports, and test imports for every proposed retirement.

- [ ] **Step 5: Archive approved retirements and write manifest**

Move original paths into the dated archive with original path and reason. Do not use deletion commands.

- [ ] **Step 6: Run typecheck, unit, guards, build, and fresh E2E**

- [ ] **Step 7: Commit active-tree removals, audit report, and script**

Commit: `chore(dashboard): archive retired component surfaces`

### Task 9: Final verification and handoff

**Files:**
- Create: `C:/Users/mattm/.codex/handoffs/HANDOFF_2026-08-13_dashboard-hardening.md`

- [ ] **Step 1: Run `pnpm run verify` fresh and capture exact results**

- [ ] **Step 2: Run live read-only checks**

Check dashboard HTTP, engine health, `/brokers/positions`, and `/system/data-integrity`. Report degraded dependencies exactly; do not restart services merely to obtain green status.

- [ ] **Step 3: Inspect git scope**

Run `git status`, `git diff --stat origin/<branch>...HEAD`, `git log --oneline -20`, and review every changed path.

- [ ] **Step 4: Check each design success criterion against evidence**

Any unmet criterion remains explicitly open; passing tests do not waive it.

- [ ] **Step 5: Write the required handoff**

Use the mandated sections: Current state, Key decisions made, In-progress work, Blockers discovered, Files created or modified, TODO items, Git state, Suggested next action.

- [ ] **Step 6: Report outcome without pushing or merging**

