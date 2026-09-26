# JARVIS Readiness + Recommendation Evidence Loop Implementation Strategy

> **For Hermes:** Execute this plan as a safe docs/evidence/scripts loop only. Do not modify live trading mode, risk parameters, kill-switch state, broker routing, `engine/.env`, `dashboard/.env.local`, or symbol routing. MCL and MNQ remain `DO_NOT_TRADE_SYMBOLS`; do not create any operational command path for them.

**Final Goal:** Make JARVIS independently auditable for real-time operator use by producing reproducible evidence that answers two separate questions: (1) whether the dashboard is currently usable for real-time monitoring/analysis, and (2) whether historical dashboard/engine recommendations have demonstrated statistically credible paper-trading edge.

**Why we are accomplishing this goal:** The dashboard can only be trusted during market hours if operator-facing readiness, engine health, data freshness, safety state, and recommendation state are shown from runtime truth rather than assumptions. Separately, recommendation profitability cannot be inferred from headline account P&L unless recommendations are durably linked to executed paper trades and compared against baselines. Splitting runtime readiness from recommendation-edge forensics prevents a green-looking dashboard from masking weak recommendation attribution, and prevents a positive historical ledger from being mistaken for execution-readiness.

**What this accomplishes:**
- A repeatable readiness audit script/report for dashboard + engine + safety + recommendation surface state.
- A repeatable recommendation attribution audit script/report for pipeline/approval/queue/paper-trade linkage.
- A conservative operator verdict separating `operator_analysis_ready`, `monitoring_ready`, and `execution_ready`.
- A ranked enhancement queue that can be executed safely without touching live/risk/kill-switch controls.
- A durable handoff so the loop can continue cleanly after context compression or session handoff.

---

## Non-negotiable safety boundaries

1. No live trading enablement.
2. No kill-switch changes.
3. No risk parameter changes.
4. No `.env` / `.env.local` edits.
5. No broker order-routing changes.
6. No symbol-routing changes.
7. No operational commands involving MCL or MNQ.
8. Any future risk/config/kill-switch/live-routing change requires a dedicated `[safety-review]` PR.
9. PM2/env inspection must be sanitized; never paste raw PM2 `describe`, `show`, `env`, or divergent environment output into reports.
10. Archive, never delete, if any artifact retirement is needed.

---

## Measurable finish line

The loop is complete when all of the following are true:

- `scripts/jarvis_dashboard_recommendation_audit.py` compiles and runs successfully.
- `scripts/jarvis_recommendation_attribution_audit.py` compiles and runs successfully.
- Latest readiness reports exist:
  - `docs/reports/JARVIS_DASHBOARD_RECOMMENDATION_AUDIT_LATEST.json`
  - `docs/reports/JARVIS_DASHBOARD_RECOMMENDATION_AUDIT_LATEST.md`
- Latest attribution reports exist:
  - `docs/reports/JARVIS_RECOMMENDATION_ATTRIBUTION_AUDIT_LATEST.json`
  - `docs/reports/JARVIS_RECOMMENDATION_ATTRIBUTION_AUDIT_LATEST.md`
- Enhancement queue exists:
  - `docs/reports/JARVIS_DASHBOARD_READINESS_ENHANCEMENT_QUEUE_2026-09-11.md`
- This implementation strategy exists:
  - `docs/plans/2026-09-11-jarvis-readiness-recommendation-loop-implementation-strategy.md`
- Handoff exists:
  - `C:/Users/mattm/.Codex/handoffs/HANDOFF_2026-09-11_jarvis-readiness-recommendation-loop.md`
- Secret scan on the new script/report artifacts returns zero hits for known secret patterns.
- Git state is recorded honestly, including the fact that the current repo has extensive pre-existing/unrelated dirty state and is not safe for a broad commit without a clean-lane split.

---

## Architecture

### Lane A — Runtime readiness audit

**Artifact:** `scripts/jarvis_dashboard_recommendation_audit.py`

Responsibilities:
1. Probe dashboard routes and API proxies.
2. Probe direct engine health.
3. Inspect critical ports/listeners safely.
4. Query engine database for current recommendation state and paper-ledger context.
5. Emit separate verdict flags:
   - `operator_analysis_ready`
   - `monitoring_ready`
   - `execution_ready`
   - `dashboard_ok`
   - `engine_ok`
6. Write stamped and latest Markdown/JSON reports.

Expected interpretation:
- `operator_analysis_ready=true` means a human can use the dashboard for analysis with known safety blockers displayed.
- `monitoring_ready=true` means all required monitoring surfaces are green enough to rely on.
- `execution_ready=true` is intentionally strict and should remain false while `live_trading=false` or `kill_switch_active=true`.

### Lane B — Recommendation attribution audit

**Artifact:** `scripts/jarvis_recommendation_attribution_audit.py`

Responsibilities:
1. Query raw DB tables:
   - `pipeline_runs`
   - `decisions`
   - `pending_trade_approvals`
   - `pipeline_approval_queue`
   - `paper_trades`
   - `wfe_snapshots`
2. Reconcile links:
   - `pending_trade_approvals.paper_trade_id -> paper_trades.trade_id`
   - `paper_trades.strategy_params.approval_id -> pending_trade_approvals.approval_id`
   - `pipeline_approval_queue.order_id -> paper_trades.trade_id/idempotency_key`
3. Separate linked paper trades from unlinked paper trades.
4. Count RTH-linked paper trades using Central Time weekday 08:30-15:00.
5. Compute cohort P&L statistics:
   - all paper trades
   - pending-approval-linked trades
   - strategy-params-linked trades
   - all unique linked trades
   - unlinked trades
   - RTH linked trades
   - queue-order-id matched trades
6. Emit a conservative edge verdict.

Expected interpretation:
- Positive linked ledger is useful evidence.
- It does not prove current recommendation edge until queue/order lineage and baseline comparison are durable.

### Lane C — Enhancement queue

**Artifact:** `docs/reports/JARVIS_DASHBOARD_READINESS_ENHANCEMENT_QUEUE_2026-09-11.md`

Responsibilities:
1. Rank fixes/enhancements by operator ROI and safety risk.
2. Keep scope split between dashboard-readiness and recommendation-performance.
3. Prevent the next session from drifting into live/risk/kill-switch changes.

---

## Exhaustive step-by-step execution plan

### Phase 0 — Re-ground and scope

1. Reload JARVIS, dashboard, PM2, verification, session-coordination, data-integrity, and loop-autonomy skills.
2. Search memory and Obsidian RAG for prior JARVIS dashboard/recommendation evidence.
3. Read session manifest and classify lane state.
4. Confirm the current task remains safe docs/evidence/scripts only.
5. Start or reconcile a task list.

**Verification:** Skill output present; manifest read; task list reflects current loop.

### Phase 1 — Runtime readiness evidence

1. Inspect dashboard/engine route health through the audit script.
2. Probe critical ports:
   - dashboard `3010`
   - engine `8010`
   - IBKR paper `4002`
   - TradingView/CDP `9222`
   - master API `8030`
3. Report endpoint truth separately from PM2 state.
4. Add `operator_analysis_ready` so the dashboard can distinguish analysis usability from strict monitoring/execution readiness.
5. Compile and run the audit script.
6. Read back latest JSON/Markdown reports.

**Verification:**

```bash
C:/Users/mattm/ThinkorSwim/jarvis-trader/engine/.venv/Scripts/python.exe -m py_compile scripts/jarvis_dashboard_recommendation_audit.py
C:/Users/mattm/ThinkorSwim/jarvis-trader/engine/.venv/Scripts/python.exe scripts/jarvis_dashboard_recommendation_audit.py --json
```

### Phase 2 — Recommendation attribution evidence

1. Create a separate attribution script instead of expanding the runtime script into a monolith.
2. Query DB schemas and table counts before relying on fields.
3. Build join logic in this order:
   - direct `paper_trade_id` linkage,
   - embedded `strategy_params.approval_id` linkage,
   - queue `order_id` linkage.
4. Compute linked/unlinked P&L cohorts.
5. Count RTH-linked trades.
6. Write stamped and latest attribution reports.
7. Interpret results conservatively.

**Verification:**

```bash
C:/Users/mattm/ThinkorSwim/jarvis-trader/engine/.venv/Scripts/python.exe -m py_compile scripts/jarvis_recommendation_attribution_audit.py
C:/Users/mattm/ThinkorSwim/jarvis-trader/engine/.venv/Scripts/python.exe scripts/jarvis_recommendation_attribution_audit.py
```

### Phase 3 — Integrity and safety checks

1. Parse latest readiness JSON.
2. Parse latest attribution JSON.
3. Verify required keys exist.
4. Scan new artifacts for known secret patterns.
5. Record git status, log, and diff stat.
6. Do not commit from the current dirty lane unless a clean scoped worktree is created.

**Verification:** JSON parse success; required artifact existence; secret hits = false.

### Phase 4 — Handoff and queue refresh

1. Write handoff to `C:/Users/mattm/.Codex/handoffs/HANDOFF_2026-09-11_jarvis-readiness-recommendation-loop.md`.
2. Include current state, key decisions, in-progress work, blockers, files modified, TODOs, git state, and one suggested next action.
3. Update task list to complete.
4. Final user response includes verdict, exact commands, files, and ranked next recommendations.

---

## Current ranked implementation queue

1. **Keep runtime readiness and recommendation attribution as separate lanes.** This is already implemented in two scripts/reports.
2. **Promote `operator_analysis_ready` into the dashboard UI** as a read-only badge after a clean worktree is created.
3. **Add durable recommendation IDs** to future pipeline/approval/trade records via a `[safety-review]` design if it touches execution/risk tables, or as a docs-first schema proposal if read-only.
4. **Add baseline comparison** for recommendation cohorts: buy-and-hold, random-entry same holding period, and symbol/time-of-day matched baselines.
5. **Add RTH/ETH split to the visible dashboard scorecard.** Keep it read-only.
6. **Restore/verify Master API `:8030`** if current dashboard trade-record widgets require it.
7. **Create a clean PR lane** before committing any scripts or dashboard code because the serving repo is heavily dirty with unrelated changes.
8. **Add a scheduled read-only report job** only after single-writer ownership is confirmed.
9. **Build Playwright smoke for the readiness card** after UI implementation begins.
10. **Only after attribution + baseline are green, consider recommendation-quality gating.** Any gating that affects routing/execution requires `[safety-review]`.

---

## Expected current outcome after implementation

- Runtime audit says dashboard/engine route truth can be measured reproducibly.
- Attribution audit says the linked recommendation cohort is positive, especially RTH-linked, but current recommendation edge is still not proven because queue-order lineage and baseline comparison remain incomplete.
- Dashboard can be used for operator analysis only when endpoint truth is green and safety blockers are explicitly visible.
- Execution readiness remains false unless live/risk/kill-switch state changes through the required safety-review process.
