# Phase 2 — Execution Tracker

**Purpose:** Convert the canon-aligned Phase 1 cleanup into a provable, repeatable paper-trading operating loop with IBKR as the broker truth path, durable audit trails, and trusted validation metrics.  
**Audience:** Matt / operator sessions that need a single ordered checklist to work from start to finish.  
**Priority lens:** Ordered by **ROI** first, then dependency.  
**Related docs:** [P0_PAPER_IB_VERIFICATION.md](P0_PAPER_IB_VERIFICATION.md), [PAPER_SOURCE_OF_TRUTH.md](PAPER_SOURCE_OF_TRUTH.md), [PHASE3_READINESS.md](PHASE3_READINESS.md), [../strategic/07_EXECUTION_SPINE.md](../strategic/07_EXECUTION_SPINE.md), [../strategy/JARVIS-STRATEGY-v1.md](../strategy/JARVIS-STRATEGY-v1.md).

---

## Current Checkpoint — 2026-04-11

**Task 1 status:** In progress.

**Verified so far**

- [x] Engine is running in paper mode (`LIVE_TRADING_ENABLED=False`).
- [x] Canon-approved paper symbols confirmed: `MCL`, `MNQ`, `MES`.
- [x] 2-contract hard cap confirmed in config/env.
- [x] Dashboard proxy path to engine is healthy (`/api/engine/health` returns 200).
- [x] Scheduler status is visible.
- [x] Scanner pause regression remains green.
- [x] Alert cooldown regression remains green.
- [x] Health router patched so paper-mode broker health prefers the execution connector attached to `SafetyLayer`, not only the market-data IB object.

**Observed blockers**

- [ ] The currently running engine process has not yet picked up the health-router patch; `/health` still reports `ibkr_connected=false` until that process restarts.
- [ ] Live pipeline calls on approved symbols are defaulting to `HOLD`, so no pending approvals are being created.
- [ ] The most recent live pipeline traces indicate upstream failure modes including insufficient technical data and Anthropic billing/credit failure, which collapse to `HOLD`.

**Next action**

- [ ] Restart the engine process cleanly, then re-run `P0_PAPER_IB_VERIFICATION` health checks and retry pending-approval creation on an approved symbol.
- [ ] If the pipeline still returns `HOLD`, treat LLM/data availability as the next blocker and decide whether to restore that path or use a controlled/manual non-HOLD approval fixture to continue E2E approval plumbing verification.

---

## Definition Of Success

Phase 2 is complete when all of the following are true:

- [ ] One clean **IBKR paper** trade has completed end to end on a canon-approved symbol.
- [ ] Paper state has a documented and enforced **single source of truth**.
- [ ] Approval and alert paths are **auditable** even when delivery is suppressed or delayed.
- [ ] The validation window has started on **approved symbols only**.
- [ ] Critical operational paths are covered by **fast regression tests**.

---

## Working Rules

- [ ] Use **IBKR paper** as the broker truth path for execution evidence.
- [ ] Use canon-approved symbols only: **MCL, MNQ, MES** on **1h**.
- [ ] Treat [`.claude/imports/validated-instruments.md`](../../.claude/imports/validated-instruments.md) as the authority for approved symbols and validation gates.
- [ ] Do not change Tier-3 files without the required process gates.
- [ ] Do not start the validation window until Tasks 1 and 2 are functionally complete.

---

## ROI Ranking

| Rank | Task | Why it is highest ROI |
|------|------|------------------------|
| 1 | IBKR paper path end-to-end proof | Proves the system can actually trade through the canonical broker path. |
| 2 | Single source of truth for paper state | Prevents invalid metrics and split-brain debugging later. |
| 3 | Alert and approval reliability hardening | Makes the operational path observable and auditable. |
| 4 | Approved-symbol validation window kickoff | Starts collecting the only numbers that matter for Phase 3. |
| 5 | Contract and regression expansion | Locks in the path so later work cannot silently break it. |

---

## Task 1 — IBKR Paper Path End-To-End Proof

**ROI:** Highest  
**Primary outcome:** Prove signal → approval → paper order → persistence → dashboard visibility using the canonical IBKR paper path.  
**Exit criteria:** One clean paper trade is completed and evidenced from cold start to close.

### 1.1 Preconditions

- [ ] Confirm engine is running in **paper mode** and not live mode.
- [ ] Confirm API key alignment between engine and dashboard.
- [ ] Confirm IB Gateway paper is reachable on the host/port the engine expects.
- [ ] Confirm the approved symbol set for this phase is **MCL + MNQ + MES** only.
- [ ] Confirm the 2-contract hard cap is active.

### 1.2 Health and wiring

- [ ] Verify `GET /health` returns healthy state and expected paper flags.
- [ ] Verify IBKR connectivity is visible in health/status surfaces.
- [ ] Verify dashboard can reach the engine through `/api/engine/*` without 401 or proxy errors.
- [ ] Verify scheduler/scanner health is visible before attempting a trade.

### 1.3 Approval creation

- [ ] Trigger a real non-HOLD pipeline/scanner event on an approved symbol.
- [ ] Verify a pending approval row is created.
- [ ] Verify the approval row contains the minimum required signal context.
- [ ] Verify the approval is visible in both API and dashboard views.

### 1.4 Approval to routed order

- [ ] Approve a pending trade through the intended approval path.
- [ ] Verify the approval result maps to an IBKR paper order attempt.
- [ ] Verify the routed order result is visible in engine logs or order response surfaces.
- [ ] Verify no unexpected kill switch or safety gate blocked the happy path.

### 1.5 Persistence and closure

- [ ] Verify the open trade/position appears in the canonical paper ledger/state store.
- [ ] Verify the same open trade is visible in dashboard position views.
- [ ] Close the trade through the intended path.
- [ ] Verify the closed trade lands in history with realized PnL and timestamps.
- [ ] Verify no orphan open position remains after closure.

### 1.6 Evidence pack

- [ ] Save one health snapshot.
- [ ] Save one pending-approval snapshot.
- [ ] Save one approve/routed-order result snapshot.
- [ ] Save one open-position snapshot.
- [ ] Save one closed-trade snapshot.
- [ ] Save one dashboard confirmation screenshot or equivalent operator note.
- [ ] Link the evidence into a dated session log / handoff note.

---

## Task 2 — Single Source Of Truth For Paper State

**ROI:** Very high  
**Primary outcome:** Eliminate ambiguity between SQLite, JSON artifacts, in-memory trackers, and dashboard reads.  
**Exit criteria:** For the same trade set, DB truth, tracker truth, and dashboard truth all agree.

### 2.1 Inventory every paper-state surface

- [ ] List all sources that can represent open paper positions.
- [ ] List all sources that can represent closed paper trades.
- [ ] List all sources that can represent paper PnL.
- [ ] List all sources that can represent alert history tied to paper actions.

### 2.2 Classify authority

- [ ] Mark which source is authoritative for open positions.
- [ ] Mark which source is authoritative for closed trades.
- [ ] Mark which source is authoritative for PnL.
- [ ] Mark which sources are logs/audit artifacts only.
- [ ] Mark which sources are derived dashboard views only.

### 2.3 Reconcile startup and restart behavior

- [ ] Verify how open positions are rebuilt on startup.
- [ ] Verify how closed trades are reloaded on startup.
- [ ] Verify the tracker rebuild path uses the canonical store.
- [ ] Verify dashboard views after restart match the rebuilt state.

### 2.4 Remove ambiguity in operator workflow

- [ ] Update [PAPER_SOURCE_OF_TRUTH.md](PAPER_SOURCE_OF_TRUTH.md) so it matches actual runtime behavior.
- [ ] Add a concise “if these disagree, trust X” rule for operators.
- [ ] Add a post-restart reconciliation checklist.
- [ ] Add a one-command or one-checklist comparison for DB vs dashboard truth.

### 2.5 Validate on real trade data

- [ ] Use the Task 1 paper trade as the baseline reconciliation artifact.
- [ ] Verify the same trade appears consistently in all intended read paths.
- [ ] Verify no legacy artifact claims a conflicting open/closed state.
- [ ] Verify cumulative PnL matches across the canonical API and dashboard.

---

## Task 3 — Alert And Approval Reliability Hardening

**ROI:** High  
**Primary outcome:** Every approval and alert attempt becomes durable, observable, and explainable.  
**Exit criteria:** Sent, failed, and suppressed outcomes are all auditable without guesswork.

### 3.1 Alert outcome matrix

- [ ] Enumerate all relevant alert outcomes: sent, failed, suppressed cooldown, suppressed no channel, approval required.
- [ ] Verify each outcome has a durable persistence path.
- [ ] Verify each persisted outcome is queryable through an API/dashboard surface.

### 3.2 Approval path auditability

- [ ] Verify approval-created events are persisted even if downstream notification delivery fails.
- [ ] Verify approval action results are persisted with timestamps and identifiers.
- [ ] Verify rejected approvals are visible with reason codes.

### 3.3 Cooldown reliability

- [ ] Verify cooldown configuration comes from the intended settings field only.
- [ ] Verify cooldown suppression still logs an auditable record.
- [ ] Verify repeated signals do not disappear silently.
- [ ] Verify the current behavior matches `engine/tests/test_pipeline_alert_cooldown.py`.

### 3.4 Operator visibility

- [ ] Verify dashboard alert history distinguishes sent vs failed vs suppressed.
- [ ] Verify error copy is actionable when engine is healthy but delivery fails.
- [ ] Verify the operator has a way to inspect recent alert state before market open.

### 3.5 Documentation and runbook

- [ ] Update the relevant runbook with the actual alert/approval truth path.
- [ ] Mark the old D3 diagnostic note as historical evidence only.
- [ ] Add a troubleshooting branch for “pending approval exists but no alert arrived.”

---

## Task 4 — Approved-Symbol Validation Window Kickoff

**ROI:** High  
**Primary outcome:** Start collecting trusted validation metrics on approved symbols only.  
**Exit criteria:** Day 1 of the validation window is formally started with clear rules and operator cadence.

### 4.1 Validation scope freeze

- [ ] Freeze the approved paper symbols for this window: **MCL, MNQ, MES**.
- [ ] Confirm all symbols route through the intended analysis/execution path.
- [ ] Confirm all symbols respect the same risk cap logic.

### 4.2 Canon metrics alignment

- [ ] Verify backend validation endpoints reflect canon gates.
- [ ] Verify dashboard validation widgets reflect the same backend metrics.
- [ ] Verify [../strategy/JARVIS-STRATEGY-v1.md](../strategy/JARVIS-STRATEGY-v1.md) Section D matches the backend surfaces.

### 4.3 Start-of-window procedure

- [ ] Define the timestamp that counts as trading day 1.
- [ ] Record the starting paper capital.
- [ ] Record the approved-symbol set for the window.
- [ ] Record the expected daily operator checks.

### 4.4 Daily operating cadence

- [ ] Check engine health before RTH.
- [ ] Check broker connectivity before RTH.
- [ ] Check pending approvals / alert subsystem before RTH.
- [ ] Check state reconciliation after any restart.
- [ ] Check validation metrics after market close.

### 4.5 Failure protocol

- [ ] Define what happens if a contaminated trade appears.
- [ ] Define what happens if an alert is missing but approval exists.
- [ ] Define what happens if broker truth and dashboard truth diverge.
- [ ] Define what happens if a non-approved symbol enters the path.

---

## Task 5 — Contract Tests And Operational Regression Expansion

**ROI:** Medium-high  
**Primary outcome:** Lock in the new operational path so future work cannot reopen the same failures.  
**Exit criteria:** Critical operational paths are covered by fast, repeatable tests.

### 5.1 E2E contract coverage

- [ ] Add/extend a contract test for pending approval creation on non-HOLD signal.
- [ ] Add/extend a contract test for approval → routed paper order behavior.
- [ ] Add/extend a contract test for closed-trade persistence.

### 5.2 State consistency coverage

- [ ] Add/extend a regression test for restart rebuild from SQLite.
- [ ] Add/extend a regression test for open/closed/PnL consistency across the canonical read path.

### 5.3 Alert/approval coverage

- [ ] Add/extend tests for sent/failed/suppressed alert persistence.
- [ ] Add/extend tests for approval-created plus notification-failure behavior.
- [ ] Add/extend tests for approval rejection audit persistence.

### 5.4 Dashboard/proxy coverage

- [ ] Add/extend a lightweight guard against direct absolute engine URLs reappearing in dashboard runtime code.
- [ ] Add/extend a smoke check for the dashboard proxy path and environment assumptions.

### 5.5 Pre-session smoke suite

- [ ] Define the minimum smoke suite to run before each validation-day open.
- [ ] Define which failures are blocking vs non-blocking.
- [ ] Add the exact command list to the runbook.

---

## Recommended Execution Order

Work this tracker strictly in this order:

- [ ] Complete **Task 1** first.
- [ ] Complete **Task 2** immediately after Task 1.
- [ ] Complete **Task 3** before relying on unattended operational flow.
- [ ] Start **Task 4** only after Tasks 1 and 2 are trustworthy.
- [ ] Use **Task 5** continuously, but do not call it done until Tasks 1–4 are covered.

---

## Session Closeout Template

At the end of each work session, append a dated note covering:

- [ ] Which top-level task is currently active.
- [ ] Which subtasks were completed today.
- [ ] What evidence was collected.
- [ ] What blockers remain.
- [ ] What exact next action should start the next session.

---

## Immediate Next Action

Start with **Task 1.1 Preconditions** and do not skip ahead.

- [ ] Confirm engine paper-mode health
- [ ] Confirm IB Gateway paper connectivity
- [ ] Confirm dashboard auth/proxy health
- [ ] Trigger one real pending approval on an approved symbol
