# JARVIS Dashboard Readiness + Recommendation Audit Implementation Plan

> **For Hermes:** Execute this as a safe docs/evidence/scripts lane. Do not change live trading, risk parameters, kill-switch state, engine `.env`, dashboard `.env.local`, or trading-symbol gates without a dedicated `[safety-review]` PR.

**Goal:** Convert the ad-hoc JARVIS dashboard status/recommendation discussion into reproducible artifacts and a ranked enhancement queue.

**Architecture:** Add one read-only audit script that queries local dashboard/engine endpoints and the SQLite paper ledger, then emits timestamped JSON/Markdown evidence reports. Keep enhancements evidence-only first; runtime/dashboard UI changes require a clean authority worktree and full verification.

**Tech Stack:** Python stdlib (`sqlite3`, `urllib`, `socket`, `json`), local JARVIS dashboard `:3010`, engine `:8010`, SQLite DB `engine/data/jarvis_trader.db`.

---

## Task 1: Confirm safe operating scope

**Objective:** Keep this loop out of live trading/risk territory.

**Files:**
- Read: `C:/Users/mattm/.Codex/session_manifest.json`
- Read: `C:/Users/mattm/ThinkorSwim/jarvis-trader/CLAUDE.md`
- Read: `C:/Users/mattm/ThinkorSwim/jarvis-trader/engine/CLAUDE.md`
- Read: `C:/Users/mattm/ThinkorSwim/jarvis-trader/dashboard/CLAUDE.md`

**Steps:**
1. Verify the serving tree is operational but dirty/non-authoritative.
2. Restrict writes to docs/evidence/script artifacts.
3. Do not touch `engine/config.py`, `engine/risk/`, `engine/.env`, `dashboard/.env.local`, kill switch, or symbol routing.

**Verification:**
- `git status --short --branch` shows no unintended runtime/risk edits introduced by this plan.

## Task 2: Create a reproducible read-only audit script

**Objective:** Replace manual dashboard-health and recommendation-performance checks with a repeatable command.

**Files:**
- Create: `scripts/jarvis_dashboard_recommendation_audit.py`

**Steps:**
1. Read dashboard Basic Auth credentials only to call local authenticated endpoints; never print secrets.
2. Probe ports: `3010`, `8010`, `4002`, `9222`, `8030`.
3. Call endpoints: `/`, `/mission-control`, `/api/engine/health`, `/api/runtime-snapshot`, `/api/engine/backtest/paper-status`, `/api/engine/pnl/truth`, `/api/engine/safety/status`, `/api/engine/portfolio`, `/api/engine/pipeline/pending-approvals?limit=50`, `/api/engine/pipeline/actionable`, `/api/engine/portfolio/stats/drawdown`, `/api/engine/brokers/status`.
4. Query DB tables: `paper_trades`, `pipeline_runs`, `decisions`, `pending_trade_approvals`, `pipeline_approval_queue`, `wfe_snapshots`.
5. Convert paper-trade timestamps to Central time and count regular-trading-hours paper entries.
6. Emit stamped JSON + Markdown report under `docs/reports/`.

**Verification:**
- `python -m py_compile scripts/jarvis_dashboard_recommendation_audit.py` passes.
- Running the script writes both JSON and Markdown artifacts.

## Task 3: Run current evidence capture

**Objective:** Produce the current dashboard-readiness and recommendation-performance report.

**Files:**
- Create: `docs/reports/JARVIS_DASHBOARD_RECOMMENDATION_AUDIT_<timestamp>.json`
- Create: `docs/reports/JARVIS_DASHBOARD_RECOMMENDATION_AUDIT_<timestamp>.md`
- Update: `docs/reports/JARVIS_DASHBOARD_RECOMMENDATION_AUDIT_LATEST.json`
- Update: `docs/reports/JARVIS_DASHBOARD_RECOMMENDATION_AUDIT_LATEST.md`

**Verification:**
- JSON parses with `python -m json.tool`.
- Markdown file is non-empty.
- Script stdout prints artifact paths.

## Task 4: Rank enhancements

**Objective:** Split immediate operator-readiness improvements from deeper performance science.

**Enhancement queue:**
1. Add a dashboard-facing `Trading Readiness` card that separates monitoring-ready vs execution-ready.
2. Add a recommendation attribution join fix/report: `decision -> pipeline_run -> queue -> paper_trade`.
3. Add a confidence calibration report: expected hit rate by confidence decile and symbol.
4. Add stale/degraded widget badges for master-api dependent performance pages.
5. Add an intraday paper-test scoreboard separated from overnight/non-RTH trades.
6. Add a [safety-review] issue/PR proposal only for drawdown-source unification; do not implement in this lane.

**Verification:**
- Each enhancement must have an owner file path, safety classification, and acceptance criteria before implementation.

## Task 5: Execute split-session recommendation

**Objective:** Keep parallel work clean and fast.

**Session A:** Dashboard health / real-time analysis readiness.

**Session B:** Recommendation-performance forensic audit.

**Verification:**
- If code/UI changes are needed, create/use a clean authority worktree rather than editing the dirty serving tree.
