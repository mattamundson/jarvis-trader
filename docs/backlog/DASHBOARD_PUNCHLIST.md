# Dashboard Punch-List

**Purpose:** the durable, on-disk tracker for the JARVIS TRADER dashboard completion plan
(`~/.claude/plans/squishy-discovering-sunrise.md`). The GT-/PRB- fix-drain series (2026-07)
never had one of these — status lived only in ephemeral session state and dated
`AGENT_TASK_QUEUE_*.md` files, which get archived and disappear. This doc is the one that
survives. **Update this table as items close** — don't let it go stale the way the GT-/PRB-
history did.

**Seeded:** 2026-08-01, agent-P12-1, from the plan's own phase breakdown (Phases 0-12) plus
live inspection of git history, `gh` PR/branch-protection state, and the current
`AGENT_TASK_QUEUE_2026-08-01.md`. Status below reflects that inspection, not an exhaustive
line-by-line code audit of every item — items marked **UNVERIFIED** need a real look before
being trusted.

**Status legend:** DONE · IN-PROGRESS · QUEUED · BLOCKED · DEFERRED (explicit hold, needs Amo)
· NOT STARTED · UNVERIFIED (evidence incomplete or contradictory)

**Live task queues** (wave-by-wave dispatch, superseded by new dated files as waves complete):
`~/.claude/handoffs/AGENT_TASK_QUEUE_2026-08-01.md` is current as of this doc's creation.

---

## Phase 0 — Rescue at-risk work

| # | Item | Status | Evidence |
|---|---|---|---|
| 0.1 | Quarantine non-rescue stray-diff files | DONE (assumed) | Worktree tree is clean of the described stray `C:UsersmattmAppData…` files; not independently re-verified this pass |
| 0.2 | Fix `/backtest` double-import defect before commit | **DONE** | `dashboard/app/backtest/page.tsx` uses `import type { SeriesPoint }` (type-only) and dynamic imports for `DecisionBreakdownCard`/`LightweightSeriesChart` — verified by direct read 2026-08-01 |
| 0.3 | Pre-commit verification gate (tsc/build/e2e, fresh-server caveat) | UNVERIFIED | Procedural step, not a landable artifact — presumed run at the time, not re-verified |
| 0.4 | Commit in 3 race-safe pathspec slices | DONE (assumed) | History is fully mainline-integrated; slice discipline not independently re-verified |
| 0.5 | Review notes attached to PR | UNVERIFIED | Depends which PR landed this work; not traced |
| 0.6 | Branch/push/PR (`feat/dashboard-hardening-phase1-4`) | DONE (assumed) | Origin/master (81a5aa1, this worktree's base) already contains the hardening work described in Phase 0-2 |

## Phase 1 — Close the CI gates

| # | Item | Status | Evidence |
|---|---|---|---|
| 1.1 | `Dashboard Build (Next.js)` required status check on master | **DONE** | `gh api .../branches/master/protection/required_status_checks` confirmed 2026-08-01: contexts include `"Dashboard Build (Next.js)"` and `"Dashboard Quality (typecheck + unit tests)"` |
| 1.2 | `dashboard-quality` job (typecheck → lint → test:unit) | **DONE** | Commit `67a68dc` "ci: add dashboard-quality job (typecheck + unit tests), runs on drafts too (#559)"; confirmed required via branch protection above |
| 1.3 | Draft-PR CI gap (`dashboard-draft-typecheck`) | **DONE** (folded into 1.2) | Same commit `67a68dc` explicitly "runs on drafts too" |
| 1.4 | New guards (engine-URL, bare-fetch, poll-interval, double-import detector) | **DONE** | Commit `1584f15` "ci(dashboard): add static guards for engine URL, bare fetch, dead dynamic imports, poll ratchet (#565)" |
| 1.5 | Bundle-size budget gate | **DONE** | Commit `b784d06` "ci(dashboard): add First Load JS bundle-size budget gate (#566)" |
| D16 | `enforce_admins` on master protection | **DECIDED: true** | `gh api .../branches/master/protection/enforce_admins` → `{"enabled":true}`, confirmed 2026-08-01 |

## Phase 2 — Test pyramid foundation

| # | Item | Status | Evidence |
|---|---|---|---|
| 2.1 | Route manifest (`tests/e2e/_routes.ts` + self-check test) | **DONE** | Commit `a6ed613` "test(dashboard): route manifest with self-check + trustworthy fresh E2E runs (#561)" |
| 2.2 | Table-driven E2E smoke across all 50 routes + shape-aware degraded mock | **DONE** | Commits `ceb2ea5` "table-driven E2E smoke suite across all 50 routes", `339176a` "add smoke project to config, fix redirect race" |
| 2.3 | `reuseExistingServer` honesty + `test:e2e:fresh` on port 3013 | UNVERIFIED | Not independently confirmed this pass; likely bundled with 2.1/2.2 work — check `playwright.config.ts` |

## Phase 3 — Architecture: resolve the 3-app split (D0)

| # | Item | Status | Evidence |
|---|---|---|---|
| 3.1-3.7 | Archive split, route groups | **DEFERRED — NOT IN SCOPE, needs Amo** | Per `AGENT_TASK_QUEUE_2026-08-01.md`: blocked on PR #571 (E2E suite, still OPEN/draft as of 2026-08-01) merging first, so the suite can prove the move safe. `dashboard/apps/` does not exist anywhere in this worktree's git ancestry (checked via `git ls-tree HEAD dashboard` and `git log --diff-filter=D -- dashboard/apps`) — the split (commit `74b27be`) lives only on `feat/roadmap-execution`, never merged toward this lineage. Do not touch until Amo decides and #571 lands. |

## Phase 4 — Deploy path hardening

| # | Item | Status | Evidence |
|---|---|---|---|
| 4.1 | Fix `~/scripts/start-dashboard.ps1` `NEXT_DIST_DIR` omission | **BLOCKED** | `AGENT_TASK_QUEUE_2026-08-01.md`: agent-P4-1 found `C:\Users\mattm\scripts` working tree dirty (10 modified + 11 untracked, main 22 ahead of origin/main) — needs Amo to triage before this can run safely |
| 4.2 | `dashboard-guard` served-vs-on-disk parity check | QUEUED (held) | Location not yet confirmed per queue file; needs discovery |
| 4.3 | `deploy-local.ps1` rebuild→restart wrapper | **DONE** | Commit `25c3eb3` "feat(dashboard): add deploy-local.ps1 as the only sanctioned local deploy path (#560)" |
| 4.4 | Stop misreporting one-shot pm2 apps as dead | QUEUED (held) | Location not yet confirmed per queue file. Note: commit `6cf6c8c` "fix(engine): retry process-name lookup, back off unidentified port holders (#555)" is adjacent process-supervision work but addresses a different bug (port-holder identification, not `cron_restart`/`autorestart:false` misclassification) — do not treat as closing this item |

## Phase 5 — Bundle & route performance

| # | Item | Status | Evidence |
|---|---|---|---|
| 5.1-5.3 | Baseline + fix static/dynamic double-import class + remaining candidates | **DEFERRED — needs reconciliation with `wip/health-assertions-mr-3.6`** | Per queue file: that branch's commit `aae890c` already measured "ZERO bundle change from the dead-import fix," contradicting the plan's original assumption. `dashboard/app/validation/page.tsx` lines 28-50 show no dead static import at the old 41-44 location (spot-checked 2026-08-01) — the class-level defect appears already fixed somewhere in this lineage, but full route-table re-measurement has not been done here. Do not start fresh work; reconcile with the wip branch first. |

## Phase 6 — Close functional gaps (non-safety)

| # | Item | Status | Evidence |
|---|---|---|---|
| 6.1 | `SessionSummaryWidget` → `useHonestTrades()` (D1) | QUEUED (held, "moderate complexity") | `AGENT_TASK_QUEUE_2026-08-01.md` P6-1, held for a focused wave |
| 6.2 | `STC_BENCHMARKS` → `lib/stcBenchmarks.ts` + `CAPTURED_AT`/`SOURCE` (D2) | QUEUED (held) | `AGENT_TASK_QUEUE_2026-08-01.md` P6-2 |
| 6.3 | `/strategy-c` placeholder metrics → `—` | **DONE** | `AGENT_TASK_QUEUE_2026-08-01.md`: P6-3, commit `4ee54e3`, agent-P6-3 |
| 6.4 | `POLL_INTERVAL` adoption across ~150 hardcoded-interval sites | QUEUED (held, LARGE — needs own multi-wave sub-drain) | `AGENT_TASK_QUEUE_2026-08-01.md` P6-4 |
| 6.5 | Mount `IBGatewayStatus` on `/health` (D3) | IN-PROGRESS | `AGENT_TASK_QUEUE_2026-08-01.md`: P6-5, agent-P6-5, IN-FLIGHT as of this doc's creation |
| 6.6 | Archive `MarketHealthGrid` orphan (D4) | **DONE** | `AGENT_TASK_QUEUE_2026-08-01.md`: P6-6, commit `490d60e` "fix(dashboard): archive orphaned MarketHealthGrid component (P6-6, Phase 6.6/D4)" |
| 6.7 | Verify-and-close `/mission-control` + `/performance` #418 hydration | **DONE (partial — `/mission-control` half only)** | `/mission-control`: verified live per `AGENT_TASK_QUEUE_2026-08-01.md` P6-7. Ran `pnpm run build:clean` (removes `.next`, rebuilds — rules out the stale-`.next`-causes-404 concern the plan flagged) in `wt-phase-drain/dashboard`; build succeeded, `/mission-control` compiled as a static route (8.16 kB). Started `pnpm exec next start -p 3014` (scratch port, not pm2's 3010) and fetched `http://127.0.0.1:3014/mission-control`: **HTTP 200**, response body contains `<h1>MISSION CONTROL</h1>` (page title `JARVIS TRADER`) — a real heading, not a 404 page. Scratch server stopped afterward; confirmed pm2's port 3010 was never touched. `/performance` #418 hydration half NOT re-investigated here — per the queue file this is believed already covered by `wip/health-assertions-mr-3.6`'s commit `b25bcb2` ("stabilize validation and performance dashboards"); that branch is off-limits to this drain (see queue file IMPORTANT CONTEXT #1), so confirming it needs Amo or a session with access to that branch, not a fresh agent pass. |

## Phase 7 — GT-41 dry-run trade simulation ⚠️ SAFETY-CRITICAL

| # | Item | Status | Evidence |
|---|---|---|---|
| 7.1-7.4 | `POST /safety/simulate-trade` contract, tests-first, implementation, dashboard wiring | **DEFERRED — NOT IN SCOPE, needs Amo `[safety-review]` sign-off before any code** | Per `AGENT_TASK_QUEUE_2026-08-01.md` NOT-IN-SCOPE section. Note: `dashboard/lib/settings-api.ts` already exports `simulateTrade`/`SimulateTradePayload`/`SimulateTradeResult`, and commits `561e17c`/`2267847` ("stop 404ing manual trade simulator endpoint" / "disable manual trade simulation against dead endpoint", both tagged GT-41) exist in history — **these are a pre-existing GT-41 UI-bug ticket about an already-broken simulator link, not the Phase 7 safety-critical dry-run endpoint this plan describes. Do not conflate the two; Phase 7's contract has not been built.** |

## Phase 8 — New feature surface

| # | Item | Status | Evidence |
|---|---|---|---|
| `/thinkscript`, trading-status reconciliation, `/pipeline-board`, strategy-lab results, `/vault`, ops panels | **DEFERRED — held, large net-new route builds** | `AGENT_TASK_QUEUE_2026-08-01.md` P8-* holds |
| 8.7 WFE surface reconciliation (D10) | **INVESTIGATED, NOT RECONCILED — filed as an engine-level metric-definition bug, UI untouched.** Engine at `127.0.0.1:8010` was unreachable (`Invoke-RestMethod` to `/health` and `/paper/validation/wfe` both returned "connection actively refused", `Test-NetConnection -Port 8010` → `TcpTestSucceeded: False`) so the live per-symbol numeric diff for MES/MGC/MNQ/MCL specified by the task could not be run. Static-code investigation (2026-08-02, agent-P8-7) found the premise itself is stale and the underlying issue is worse than a rounding mismatch: **(1) Only one of the two surfaces is actually mounted on `/validation` today.** `WFEMonitorWidget` (`dashboard/components/WFEMonitorWidget.tsx`, `GET /wfe/snapshots`) is mounted at `app/validation/page.tsx` ~L1954-1958 ("Section K: WFE Live Monitor"). `RollingWFEWidget` (`dashboard/components/RollingWFEWidget.tsx`, `GET /paper/validation/wfe`) has **zero importers anywhere in the app tree** (grep-verified across `dashboard/app` and `dashboard/components`) — independently corroborated by a pre-existing stale-flagged comment in `dashboard/tests/e2e/instrument-status-golden-path.spec.ts` L17-25 ("`RollingWFEWidget.tsx` has zero importers anywhere in the tree ... not reachable via `/` or any other live route"). So there is no live side-by-side "two numbers on one page" today — only the snapshot-history one renders. **(2) The two endpoints are not two formulas for the same metric — they're different metrics that both happen to be labeled "WFE".** `GET /paper/validation/wfe` (`engine/routers/paper_validation_router.py` `_compute_rolling_wfe` + handler ~L803-865) computes a real current-period walk-forward-efficiency ratio, 0-1 scale (`current_wfe`), gated per-symbol against `kill_threshold` sourced from `paper_config.py`'s `kill_threshold.rolling_wfe_minimum` (default 0.5) — this is the number that gates the real D10 kill decision. `GET /wfe/snapshots` (`engine/routers/wfe_router.py`) computes weekly `profit_factor`/`win_rate`/`sharpe`/`max_dd` from closed trades and flags `divergence_warning` by comparing live weekly **`profit_factor`** against a hardcoded `WFE_BASELINES` dict (L27-30: `{"MCL": 0.82, "MNQ": 0.57}`, "from Sprint 21 PRD") × `DIVERGENCE_MULTIPLIER` (0.5) — mixing units: the baseline values look like WFE-ratio constants (0-1 scale) but get compared against a live profit-factor (typically >1 for a healthy strategy), not a live WFE ratio. **(3) `WFE_BASELINES` has no entry for MES or MGC** — only MCL/MNQ — so for MES/MGC (the actively-traded/autonomous symbols) `baseline` resolves to `None`, `divergence_warning` is permanently `False`, and the "vs WFE" column always renders "—" regardless of real live performance; the one WFE widget operators actually see is structurally incapable of ever flagging divergence for the two symbols that matter most. **Net effect:** the number gating the real kill decision (`rolling_wfe_minimum` via `/paper/validation/wfe`) is not rendered anywhere in the dashboard today; the number operators do see (`wfe_router`'s snapshot/divergence check) is a different, partially-vacuous metric mislabeled as WFE. Per task protocol this is filed as an engine/data-model finding for Amo, not papered over with a UI retitle — **no UI files were changed.** Recommend, before any further Phase 8.7 UI work: (a) decide whether to mount `RollingWFEWidget` so the real kill-gating ratio is operator-visible, (b) either fix `wfe_router`'s divergence check to compare like-for-like (live WFE ratio vs. WFE baseline, not PF vs. WFE baseline) and add MES/MGC baselines, or retire it in favor of `/paper/validation/wfe`, and (c) re-run the live numeric diff across MES/MGC/MNQ/MCL once the engine is reachable to confirm whether the two `current_wfe`-class figures (where both exist) agree within rounding. |

## Phase 9 — Component tests + deep degraded coverage

| # | Item | Status | Evidence |
|---|---|---|---|
| 9.1 | Vitest + RTL + jsdom framework (D11) | IN-PROGRESS | `AGENT_TASK_QUEUE_2026-08-01.md`: P9-1, agent-P9-1, IN-FLIGHT, marked FOUNDATIONAL for 9.2-9.4 |
| 9.2 | Tier 1/2/3 critical widget tests | QUEUED (held, depends on 9.1) | `AGENT_TASK_QUEUE_2026-08-01.md` P9-2 |
| 9.3 | Per-route degraded-depth specs | QUEUED (held, depends on 9.1) | `AGENT_TASK_QUEUE_2026-08-01.md` P9-3 |
| 9.4 | Widget-boundary coverage sweep | QUEUED (held, depends on 9.1) | `AGENT_TASK_QUEUE_2026-08-01.md` P9-4 |

## Phase 10 — Operator observability

| # | Item | Status | Evidence |
|---|---|---|---|
| 10.1 | Master-API reachability indicator | **DEFERRED — needs reconciliation with `wip/health-assertions-mr-3.6`** | That branch already built `dashboard/app/api/master-health/route.ts`, `MasterApiStatusBadge.tsx`, `useMasterHealth.ts` per queue file NOT-IN-SCOPE section |
| 10.2 | Sample/offline/degraded label audit | **DONE** | `AGENT_TASK_QUEUE_2026-08-01.md`: P10-2, commit `d92d594`, agent-P10-2. Fixed `AccountROIWidget.tsx`, `PaperBalanceWidget.tsx`, `PositionSizingWidget.tsx` (unlabeled `ACCOUNT_VALUE_FALLBACK`-class fallbacks). **4 items left ambiguous for Amo triage**: `daily_target ?? 500` (`DailyTargetProgressWidget.tsx:40`, `MultiMarketPnLWidget.tsx:45`), `threshold ?? 30` (`TradingDaysCountdownCard.tsx:60`), `target_trading_days ?? 30` (`PaperBalanceWidget.tsx:102`) — unclear if the `static`-badge convention extends to config-target defaults vs. account-state data |

## Phase 11 — Safe autonomy foundation ⚠️ MOST SAFETY-CRITICAL

| # | Item | Status | Evidence |
|---|---|---|---|
| 11.1-11.7 | Permission model doc, `APIKeyMiddleware` scopes, audit log, `/audit` route, approval-queue composition, loop inventory, options/futures parity | **DEFERRED — NOT IN SCOPE, needs Amo review before more is built** | `wip/health-assertions-mr-3.6` already has substantial work here: `agent-permissions.ts`, agent-audit page/panel/hook, server-side persistence (commits visible in `git log --all`: `f7b4c16` "add audit export UI and retention loop", `a265049` "add agent audit metadata and retention pruning", `6984c09` "persist agent audit log server-side", `6f6f3b3` "implement phase 5 safe autonomy permission model and agent-audit logs", `933e909`/`8ddf642`/`426214b` audit-source work). Per queue file NOT-IN-SCOPE section, do not build more without Amo's review of what already exists. |

## Phase 12 — Durable punch-list + doc destaling

| # | Item | Status | Evidence |
|---|---|---|---|
| 12.1 | This doc | **DONE** | This file, commit to follow, agent-P12-1 |
| 12.2 | Destale docs (`dashboard/CLAUDE.md`, `DASHBOARD_DEV.md`, `PHASE3_TODOS.md`, autonomy-hardening plan superseded note) | IN-PROGRESS | `AGENT_TASK_QUEUE_2026-08-01.md`: P12-2, agent-P12-2, IN-FLIGHT |
| 12.3 | PR + branch disposition table | IN-PROGRESS | `AGENT_TASK_QUEUE_2026-08-01.md`: P12-3, agent-P12-3, IN-FLIGHT — see `docs/backlog/PR_DISPOSITION_2026-08-01.md` when it lands |
| 12.4 | PR #462 → tombstone | QUEUED (held, depends on other PRs landing first) | `AGENT_TASK_QUEUE_2026-08-01.md` P12-4 |
| 12.5 | PR #523 close | QUEUED (held, depends on Phase 7 landing) | `AGENT_TASK_QUEUE_2026-08-01.md` P12-5 |
| 12.6 | Orphan component re-triage (69 orphans) | QUEUED (held) | `AGENT_TASK_QUEUE_2026-08-01.md` P12-6 |

---

## Owner decisions (D0-D16) — status

Recorded here for traceability; full text in the plan doc.

| # | Decision | Recommendation | Status |
|---|---|---|---|
| D0 | 3-app split disposition | Archive + route groups | Not actioned — Phase 3 deferred |
| D1 | `SessionSummaryWidget` source | `useHonestTrades()` primary | Not actioned — Phase 6.1 held |
| D2 | `STC_BENCHMARKS` live vs frozen | Keep frozen, fix provenance | Not actioned — Phase 6.2 held |
| D3 | Real `/ib/connect` engine route? | No | Honored — P6-5 explicitly told not to build it |
| D4 | `MarketHealthGrid` disposition | Archive | **Done** — Phase 6.6 |
| D5-D9 | GT-41 simulate contract, pnl_estimate exclusion, strategy-lab/run, cache/invalidate, admin/feature-flags exposure | No / No / No / No | Not actioned — Phase 7/8 deferred |
| D10 | Authoritative WFE surface | `/paper/validation/wfe` for verdict, `/wfe/snapshots` for history, after empirical diff | **Investigated 2026-08-02 (agent-P8-7), not actioned.** Live diff blocked (engine unreachable); static analysis found the two are different metrics, not just different formulas — see Phase 8.7 row for full finding. `/paper/validation/wfe`'s kill-gating ratio isn't rendered in the dashboard at all (`RollingWFEWidget` is an orphan); `/wfe/snapshots`'s divergence check compares PF against a WFE-scale baseline missing MES/MGC entirely. Needs Amo decision before further work. |
| D11 | Component test framework | Vitest + RTL + jsdom | **In progress** — Phase 9.1 IN-FLIGHT |
| D12 | Route criticality assignments | Proposal in Phase 3 | Bundled with Phase 3, deferred |
| D13 | Permission tier table | Deliverable of Phase 11 | Deferred with Phase 11 |
| D14 | Remove P3 endpoints from HTTP entirely | Yes | Deferred with Phase 11 |
| D15 | Autonomy enforcement mechanism | Scoped `APIKeyMiddleware`, audit-only first | Deferred with Phase 11 — substantial prior art on `wip/health-assertions-mr-3.6` |
| D16 | `enforce_admins` on master | Decide explicitly | **Decided: `true`** (confirmed live 2026-08-01) |

## Engine follow-ups filed by dashboard-only agents (out of dashboard scope)

- **`POST /thinkscript/generate` honesty gap** (filed 2026-08-02, agent-3, P8-thinkscript): `engine/routers/thinkscript_router.py` wraps the technical-analyst call in a bare `except Exception: pass`, so a "generated" script can ship with zero real TA behind it and `ThinkScriptGenerateResponse` gives the caller no way to detect that. Recommend the engine add a `technical_report_available: bool` field to the response so the dashboard can eventually distinguish a real vs. hollow generation; not implemented here — out of scope for a dashboard-only agent. Mitigated client-side for now via an unconditional `ExploratoryBanner` on `/thinkscript`.
