# JARVIS Trader Dashboard Hardening Design

**Date:** 2026-08-13
**Status:** Approved in chat; written-spec review pending
**Scope:** `dashboard/` plus narrowly required test and documentation changes

## Objective

Make the dashboard easier to operate, safer to trust, cheaper to maintain, and harder to regress without replacing the working application or changing trading behavior.

The implementation proceeds in this order:

1. Correct timestamp and provider-error presentation defects.
2. Establish authoritative ownership for trading and system operations.
3. Convert oversized validation and performance pages into summary-first workspaces.
4. Consolidate polling cadence and shared request keys.
5. Decompose the dashboard API client by domain.
6. Add engine-to-proxy-to-render numeric golden-path tests.
7. Create one canonical dashboard verification command.
8. Audit unreachable surfaces and archive approved retirements.

## Non-negotiable constraints

- Preserve paper-only behavior. Do not enable live trading or alter risk, order, kill-switch, or strategy-gate behavior.
- Preserve server-side engine credential injection. Do not expose an API key to browser code.
- Use `fetchEngine`/`postEngine` or domain wrappers built on them; no direct engine URLs or bare browser fetches.
- Missing, stale, degraded, or contradictory data must fail visibly and must never become a confident zero or fabricated value.
- Preserve existing public URLs. Consolidated routes redirect or remain as compatibility shells until a separate removal decision.
- Keep `127.0.0.1` for Windows-local service URLs.
- Use `pnpm`; use the repository's installed TypeScript binary.
- Implement behavior changes with red-green TDD.
- Preserve unrelated working-tree changes.
- Retired files move to `~/Archive/2026/jarvis-dashboard/`; they are not deleted.

## Chosen approach

Use an incremental strangler migration. Existing pages continue running while focused helpers, domain clients, page sections, and tests are introduced behind compatible interfaces. Each phase is independently testable and leaves the application usable.

A full rebuild was rejected because it creates a large verification gap across safety-adjacent numbers. A fixes-only pass was rejected because it leaves overlapping truth surfaces, polling amplification, and monolithic ownership intact.

## 1. Trust-defect remediation

### Timestamp contract

Create one shared relative-time formatter. It accepts an ISO string and an explicit `now`, validates the timestamp, and returns a structured display classification:

- past timestamps under one minute: `just now`
- ordinary past timestamps: minute/hour/day display
- future skew up to 60 seconds: `just now`
- future skew above 60 seconds: `clock skew (+<duration>)`
- invalid/missing timestamps: `unknown time`

Replace local `timeAgo` implementations on active operational surfaces, starting with Command Center signal/reasoning rows. The formatter must not emit negative ages.

The implementation also records enough information in tests to distinguish a frontend formatting defect from an upstream timezone-contract defect. It does not silently rewrite timestamps.

### Provider-error presentation

Create a pure diagnostic classifier that separates trading reasoning from provider/infrastructure failures. Known provider errors become a compact operator message with:

- consequence: `Decision defaulted to HOLD`
- failure class: billing, authentication, rate limit, timeout, capacity, or provider error
- provider when determinable
- an expandable diagnostic detail

The default collapsed surface must not expose raw request IDs, SDK dictionaries, stack traces, or billing instructions. Full raw detail may remain available only in an explicitly labeled diagnostic disclosure and must not be styled as market reasoning.

## 2. Authoritative information architecture

### Operate: `/command-center`

Command Center owns immediate trading decisions:

- execution readiness and data freshness
- kill-switch state
- pending approvals or autonomous-paper status
- current positions and broker acknowledgement
- current signal and reasoning consequence
- concise market context

It must not become the home for long historical reports, fleet administration, or validation archives.

### System: `/mission-control`

Mission Control owns operational infrastructure:

- engine and broker/data legs
- LLM/provider health
- TradingView and external service health
- process supervision and scheduler/fleet state
- data integrity and freshness summaries

`/health`, `/trust-pane`, and `/data-integrity` remain deep diagnostic routes linked from Mission Control. They are not peer "home" screens.

### Validate and review

- `/validation` becomes a summary-first workspace with sections for verdict, paper evidence, backtest comparison, WFE history, reconciliation, and export/audit.
- `/performance` becomes a summary-first workspace with account truth, risk/return, time analysis, execution quality, and research comparisons.
- Heavy sections mount only when selected or expanded.

### Navigation

The sidebar presents a smaller primary navigation and an explicit secondary/deep-tools area. Redirects and deep links preserve old URLs. Exploratory routes remain visibly marked and may not read as validated trading capabilities.

## 3. Page decomposition

Large pages are split by responsibility, not merely by line count. Page files own routing and section composition. Extracted components own one coherent operator question and receive typed data or use one domain hook.

Target structure:

```text
app/command-center/page.tsx
components/command-center/
  TradingReadinessSummary.tsx
  CurrentDecisionSection.tsx
  PositionsSection.tsx
  MarketContextSection.tsx

app/validation/page.tsx
components/validation/
  ValidationSummary.tsx
  PaperEvidenceSection.tsx
  BacktestComparisonSection.tsx
  WfeHistorySection.tsx
  ReconciliationSection.tsx

app/performance/page.tsx
components/performance/
  PerformanceSummary.tsx
  RiskReturnSection.tsx
  TimeAnalysisSection.tsx
  ExecutionQualitySection.tsx
  ResearchComparisonSection.tsx
```

Existing components are reused where their contracts are honest. Extraction must not change calculations without a value-level regression test.

## 4. Polling and real-time data

Every SWR refresh interval uses a named `POLL_INTERVAL` tier. The migration is grouped by endpoint/key so consumers of the same data share the same key and cadence.

Priority order:

1. health and degradation banners
2. positions, approvals, and execution state
3. signals and pipeline status
4. performance and validation summaries
5. settings, research, and slow aggregates

WebSocket events invalidate shared SWR keys for event-driven state. Polling remains the fallback. The guard changes from a frozen ceiling to a decreasing migration ceiling and ultimately zero numeric literals.

No cadence becomes faster merely as part of mechanical migration. The existing effective interval is mapped to the nearest named tier unless a dedicated test and operational rationale justify a change.

## 5. API client decomposition

`lib/api.ts` remains the low-level compatibility facade during migration. New domain modules wrap its authenticated proxy primitives:

```text
lib/api/core.ts          low-level proxy request/error handling
lib/api/health.ts        health, data integrity, supervision
lib/api/trading.ts       positions, approvals, execution, safety
lib/api/performance.ts   trades, P&L, account and risk metrics
lib/api/validation.ts    gate, WFE, paper-validation contracts
lib/api/research.ts      backtests, strategies, exploratory analytics
```

Types live with their domain. Existing imports continue through compatibility re-exports until consumers migrate. There is no flag-day rewrite.

The domain split must not duplicate authentication, retry, timeout, header, or error-envelope logic.

## 6. Numeric golden-path verification

Add deterministic browser tests that exercise the actual browser contract:

```text
fixture engine payload
  -> Next.js `/api/engine/...` proxy contract
  -> domain parser/formatter
  -> rendered value and provenance label
```

Initial required values:

- realized P&L with explicit lifetime/daily scope
- daily P&L
- account equity
- position symbol, side, and quantity
- drawdown percentage
- signal confidence
- gate-v2 metrics (`pf_ci_lower`, `p_edge`, `mc_95th_dd`, `dsr`)
- market-data source and freshness
- kill-switch state/distance where exposed

Fixtures use deliberately distinctive values to catch wrong-field binding, factor-of-100 errors, sign errors, and silent fallback zeros. Tests assert the source/provenance label alongside the number.

Live broker state is not required for deterministic CI. A separate live-data smoke remains observational and may not replace deterministic numeric assertions.

## 7. Canonical verification command

Add `pnpm run verify` with fail-fast stages:

1. typecheck
2. unit tests
3. source guards
4. clean production build with captured build log
5. bundle-budget check against that log
6. fresh-server Playwright suite

The fresh E2E server uses an isolated port and does not reuse `:3010`. The command must preserve the running production dashboard and clean up only its own temporary process/artifacts.

`pnpm run budget` must work without a manually supplied positional argument. The build-log path is owned by the scripts rather than remembered by the operator.

## 8. Orphan and retirement audit

Generate a reproducible reachability report from App Router entry points and intentional dynamic/link-only entries. Classify each unreachable component as:

- wire: valuable and backed by an honest data source
- retain: intentional library/test/dynamic use not visible to simple import scanning
- retire: superseded, duplicated, placeholder-only, or dead

No file is retired solely because a text-based import scan reports zero inbound imports. Dynamic imports, barrel exports, route conventions, tests, and documentation references must be checked.

Approved retirements move to `~/Archive/2026/jarvis-dashboard/<date>-orphan-pass/` with a manifest recording original path, reason, and commit. Archive moves happen only after the active code/test changes are verified.

## Error handling and operational behavior

- Widget failures remain contained by error boundaries.
- A failed endpoint renders `unavailable` or `degraded`, never a numeric zero unless zero is confirmed data.
- Contradictory health sources render a mismatch state.
- Provider failures state the operational consequence without masquerading as analysis.
- The verification workflow refuses stale-server reuse.
- No engine or dashboard restart is part of ordinary source refactoring; runtime restarts occur only when explicitly needed for final behavior verification and follow the existing health gates.

## Rollout and commit strategy

Use small conventional commits aligned to the eight phases. Each behavior change includes its failing test and implementation in the same commit. Refactors preserve behavior and keep compatibility exports until their consumers migrate.

Do not push or merge as part of this work without separate authorization. Work remains on the current feature branch unless branch-state analysis shows that would mix unrelated ownership; in that case stop before changing branches.

## Success criteria

- No active operational surface emits a negative relative age.
- Raw provider failures are not presented as market reasoning by default.
- Command Center and Mission Control have distinct documented ownership.
- Validation and Performance render summary-first and lazy-mount heavy sections.
- Hardcoded polling literals decrease to zero or an explicitly documented non-SWR exception set.
- New domain API modules own migrated contracts while compatibility imports continue to work.
- Numeric golden-path tests cover every initial required value and assert provenance.
- `pnpm run verify` runs the complete clean verification story without touching the live `:3010` server.
- Orphan classification is reproducible; all retirements are archived, never deleted.
- Existing unrelated working-tree changes remain untouched.

