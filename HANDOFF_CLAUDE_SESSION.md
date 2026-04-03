# JARVIS TRADER — Claude Cowork Session Handoff
**Date**: 2026-04-03
**Session type**: Strategy, architecture, PRD authoring — NO code written this session (Cowork handles design; Claude Code in Cursor handles execution)
**Branch**: master
**Purpose of this document**: Allow any AI session (Claude Code, Claude Cowork, Node) to resume without context loss.

---

## 1. Session Summary — What Was Accomplished, In What Order

### Context Recovery
This session resumed from a prior context-compacted conversation covering Sprints 12–14. Full prior session log is at `docs/session-logs/session-2026-04-03-comprehensive.md`.

### Key decisions and work this session (in order):

1. **Received and absorbed Sprint 14 (Stark-Cohen) completion output** — all 8 stories confirmed complete (Cohen composite to MCL/MNQ, 15m scanner, conviction sizing, trade journal, rolling WFE, cost endpoint, SQLite state unification, IB E2E smoke test).

2. **Absorbed n-autoresearch experiment loop session** — 4 stories complete on what was referenced as `feat/experiment-loop` but that branch **does not exist** in the repo. The files are likely committed to master or sitting uncommitted on disk. See section 5 (Blockers) and section 8 (TODO) for resolution.

3. **Absorbed comprehensive session log** (`docs/session-logs/session-2026-04-03-comprehensive.md`) covering Sprints 12–13 — IB Gateway execution wiring, approval system, test suite cleanup, sidebar nav, Sprint 13 deliverables. All factored into Sprint 16 PRD.

4. **Identified 3 P0 blockers** preventing real paper trading:
   - Pipeline generates 115 HOLDs/day at 3–6% confidence — STC mid-range pre-filter is prime suspect (Anthropic credits NOW confirmed $50+, so credit exhaustion is ruled out)
   - DB may be corrupted (`jarvis_trader.db` "disk image malformed" reported in prior session)
   - Learning loop fully built but never wired into the trading cycle

5. **Authored Sprint 16 prd.json ("The Signal Unlock")** — 5 user stories targeting all P0 blockers. Written to root `prd.json`. All `passes: false` (not yet executed).

6. **Provided Sprint 16 Claude Code prompt** for user to paste into a fresh Cursor terminal.

7. **Updated Sprint 16 prompt** after user confirmed Anthropic credits are $50+ — credit exhaustion removed as suspect; STC mid-range pre-filter is now the unambiguous primary diagnosis target.

8. **Discussed MES as a trading instrument** — user requested adding MES to the live scanner. **Decision: REJECTED for now**. MES WFE = 0.09 (DO NOT TRADE). Proper path is Sprint 17 story: MES parameter re-optimization via n-autoresearch experiment loop → WFE gate must clear 0.50 before MES enters the scanner. RL agent already uses MES in isolation (correct).

9. **Established workflow division**:
   - **Cowork (this session)**: strategy, architecture, PRD writing, recommendations, decisions
   - **Claude Code in Cursor**: all actual coding, testing, git operations, `/ralph` execution

---

## 2. Files Created or Modified

### This Cowork session — NO code files were written
This session was strategy and planning only. The only file produced was `prd.json` (Sprint 16 PRD). All code execution happens in Cursor via Claude Code.

### prd.json (root) — REWRITTEN this session
**Path**: `C:\Users\mattm\ThinkorSwim\jarvis-trader\prd.json`
**What changed**: Full rewrite for Sprint 16 "The Signal Unlock"
**Why**: Previous prd.json covered completed sprints. Sprint 16 targets 5 P0 operational blockers.
**Status**: All 5 stories have `passes: false` — awaiting Claude Code execution in Cursor.

### Prior sessions — key files already committed (for reference)
| Sprint | Commits | Key Files |
|--------|---------|-----------|
| Sprint 13 | 55f98e8 | `engine/database/_mixins_llm_costs.py`, `dashboard/components/Sidebar.tsx`, `dashboard/components/ValidationGatesWidget.tsx`, `engine/routers/scheduler_router.py` |
| Sprint 14 | e1b7a8c, 82d3c87, c0a5726, 6f3ec61 | `engine/backtest/signals.py` (STC pre-filter), `engine/backtest/paper_config.py`, `engine/backtest/run_15m_walk_forward.py`, `dashboard/components/ApprovalPanel.tsx`, `dashboard/components/EODSummaryWidget.tsx`, `engine/routers/paper_validation_router.py`, `engine/tests/test_sprint14.py` |
| Sprint 14 cleanup | be8cf99, 48af2d1 | `engine/routers/pipeline_router.py` (inject_pipeline_deps wired), strategy canon HTML |

---

## 3. Current State

### Engine (port 8010)
- **Status**: Not confirmed running this session. Last known state: requires `.\restart_engine.ps1` to activate migration_009 (LLM cost table) + register scheduler jobs.
- **Tests**: 1,270 collected per prior session. 3 files with uncommitted changes (see git diff below).
- **DB**: `engine/jarvis_trader.db` — POSSIBLY CORRUPTED. Prior session reported "disk image malformed". US-1603 in Sprint 16 will diagnose. Engine may be running off a backup copy.
- **Anthropic credits**: CONFIRMED $50+ (user confirmed this session). LLM calls should work.
- **IB Account ID**: `YOUR_IBKR_ACCOUNT_ID` placeholder likely still in `engine/.env` — user must set this before paper trades can route to IB Gateway.

### Dashboard (port 3010)
- **Status**: Not confirmed running this session.
- **Build**: Last confirmed 26/26 routes, 0 TypeScript errors (Sprint 13 state).

### Paper Trading
- **Status**: Active — MCL + MNQ paper trading started 2026-04-02.
- **3 trades closed** (total +$7 per memory).
- **Portfolio balance anomaly**: $1,772.33 reported — may be data artifact from DB issue. US-1603 will investigate.
- **Signal frequency problem**: Pipeline generating ~115 HOLDs/day, ~0 real trades. US-1601 target.

### Git State (captured this session)
**Uncommitted changes** (3 files modified, not staged):
```
engine/agents/pipeline.py          | 46 +++ (STC pre-filter changes)
engine/routers/pipeline_router.py  | 28 +++ (likely signal-debug scaffolding)
engine/tests/test_pipeline_e2e.py  | 14 +++ (CRLF warning present)
```

**Recent commits (git log --oneline -20)**:
```
48af2d1 docs: strategy canon HTML review + builder script
be8cf99 fix: US-1605 — wire inject_pipeline_deps, remove deprecated strategy_router
6a4f1d4 docs: add strategy canon TRADING_RULES and EQUATIONS
67e52e2 fix: complete trading-days stats endpoint; extend CI with approval notify tests
6f3ec61 feat: Sprint 14 extended — cost tracking, SQLite paper state, E2E smoke, trade journal + WFE widgets
82d3c87 feat: add STC mid-range pre-filter to pipeline (Task 2)
c0a5726 feat: parallelize market scans + add MES to market_open_scan
e1b7a8c feat: Sprint 14 — trade management rules enforced in code
e15e96b fix: repair Sprint 12/13 agent truncations and missing imports
9a34845 docs: root cleanup - move stray session files to docs/ delete unknown artifacts
55f98e8 feat: Sprint 13 migration_009 LLM cost tracking + analytics router dedup
4fe50df fix: remove phantom cost_router/scheduler_router + strip null bytes
194418a feat: Sprint 12 — broker reconciliation, performance analytics, SPY walk-forward
2222ba9 feat: wire approval_router + scanner_router into main.py
25a7d27 feat: add scheduled signal scanner + API key validation
99ce6e6 feat: complete trade approval UI + fix localhost violations
24609de fix: resolve test failures and extract main.py modules
1aa83ca docs: Sprint 12 prd.json — all stories passes:true
f77c73c feat: Sprint 12 — Trade Approval UI
f840809 fix: float inf JSON crash + rl evaluate 422 + comprehensive session report
```

**git diff --stat**:
```
engine/agents/pipeline.py         | 46 ++++++++++++++++++++++++++++++---------
engine/routers/pipeline_router.py | 28 ++++++++++++++++++++++--
engine/tests/test_pipeline_e2e.py | 14 +++++++-----
3 files changed, 71 insertions(+), 17 deletions(-)
```

---

## 4. In-Progress Work

### Sprint 16 — NOT STARTED (awaiting Claude Code execution in Cursor)
The `prd.json` is written and ready. The user has the following prompt to paste into a fresh Cursor Claude Code terminal:

> **Sprint 16 Claude Code Prompt**:
> "Skip any branch merge steps. Read `prd.json` at the project root and run `/ralph` to execute Sprint 16.
> **Critical context for US-1601**: Anthropic credits are confirmed at $50+. Credit exhaustion is **ruled out**. The STC mid-range pre-filter (added Sprint 14 Task 2, skipping LLM when STC is between 25–73) is the **primary suspect** for the 115 HOLDs/day problem. Begin diagnosis there — read `engine/backtest/signals.py` to find the skip range constants, then trace the filter chain in `engine/agents/pipeline.py` with line numbers before touching anything.
> Work through all 5 stories in priority order (US-1601 → 1602 → 1603 → 1604 → 1605). Each story must pass `cd engine && .venv/Scripts/python -m pytest tests/ -v` with 0 failures before moving to the next."

### n-autoresearch experiment loop files — STATUS UNKNOWN
4 stories were completed in a prior Node session referencing branch `feat/experiment-loop`. That branch **does not exist** locally or remotely. The files may be:
- Committed to master without using that branch name (most likely — check git log for experiment_log.py, run_experiment.py, search_strategy.py)
- Sitting uncommitted on disk
- Lost

Files to look for: `engine/strategies/experiment_log.py`, `engine/strategies/run_experiment.py`, `engine/strategies/search_strategy.py`, `engine/strategies/rl_trainer.py` (WFE additions).

---

## 5. Blockers Discovered

### P0 — Pipeline Never Trades (US-1601)
**Root cause (suspected)**: STC mid-range pre-filter at `engine/agents/pipeline.py` — skips LLM pipeline when STC value is between 25–73. Added Sprint 14 Task 2 (commit 82d3c87). At 1h STC, instruments are almost always in mid-range during normal trading, so the pre-filter blocks nearly every signal.
**Confirming evidence**: 115 HOLDs/day, 3–6% confidence. Anthropic credits confirmed $50+ so credit exhaustion is ruled out.
**Resolution**: US-1601 — widen pre-filter range to only skip when STC is at true extremes (outside OS=15 / OB=83 thresholds), not mid-range.

### P0 — Database Corruption (US-1603)
**Root cause**: `engine/jarvis_trader.db` reported "disk image malformed" in prior session. Engine may be running off a backup.
**Impact**: All trade P&L data, portfolio balance, and paper trade history may be unreliable.
**Resolution**: US-1603 — run `PRAGMA integrity_check`, rebuild from WAL/backup if needed, reconcile $1,772.33 balance anomaly.

### P0 — Learning Loop Disconnected (US-1604)
**Root cause**: `engine/learning/` directory has 4 modules (consolidator, trade_classifier, pattern_extractor, recommendations) but none are wired into the trading cycle. The nightly consolidator is not an APScheduler job. Trade close events do not trigger classification.
**Impact**: System cannot improve over time. Every session starts cold.
**Resolution**: US-1604 — add consolidator as 6th APScheduler job (04:00 ET), hook trade classifier into `engine/portfolio/tracker.py` on close.

### P1 — feat/experiment-loop Branch Missing
**Root cause**: Prior Node session completed 4 RL experiment loop stories referencing this branch, but the branch does not exist in git.
**Impact**: Cannot merge experiment loop work into master for Sprint 17 RL experiments.
**Resolution**: Check if files exist on disk uncommitted. If so, commit to master. If not, recreate from session log `docs/session-logs/session-2026-04-03-n-autoresearch-experiment-loop.md`.

### P1 — MES Scanner Request (Deferred by Design)
**Root cause**: User requested adding MES to the live scanner. Denied — MES WFE = 0.09 (DO NOT TRADE per `CLAUDE.md`).
**Resolution path**: Sprint 17 story — run MES parameter re-optimization via n-autoresearch experiment loop. WFE must clear 0.50 before MES enters the scanner.

### P2 — 60-Trade Validation Gate at Risk
**Context**: Gate requires 60 trades in 30 days (~2/day). Paper trading started 2026-04-02 with only 3 trades closed in 2 days. With the pipeline HOLDing on everything, this gate will fail unless US-1601 is resolved quickly.
**Resolution**: US-1601 must land and signal frequency must be verified ≥2/day per instrument within 48h of Sprint 16 deploy.

### P2 — MCL Using Wrong Parameters
**Context**: `engine/backtest/signals.py` INSTRUMENT_PARAMS["MCL"] has `stc_os=15` (in-sample). Walk-forward consensus params are `stc_os=23, stop_atr_mult=0.50, t1_atr_mult=1.00`.
**Impact**: MCL is trading with overfit parameters, not validated ones.
**Resolution**: US-1602.

### P2 — Composite Backtester Exit Bug
**Context**: `run_composite_backtest.py` produces 581 trades with `exit_date=None` and `PF=0.41`. The composite signal path does not trigger the exit logic (ATR-based targets, trailing stop).
**Resolution**: US-1602.

### P3 — Uncommitted Changes in 3 Files
**Context**: `engine/agents/pipeline.py`, `engine/routers/pipeline_router.py`, `engine/tests/test_pipeline_e2e.py` have 71 lines of uncommitted changes. These may be partial Sprint 16 work or abandoned experiments.
**Resolution**: Claude Code should inspect these diffs at Sprint 16 start before running `/ralph` — they may already be the beginning of US-1601 work or they may need to be stashed.

---

## 6. Key Decisions Made

### STC Pre-Filter — Primary Suspect for 115 HOLDs/day
Anthropic credits confirmed $50+ this session. Credit exhaustion removed as suspect. The STC mid-range pre-filter (commit 82d3c87, added Sprint 14 Task 2) is the primary and only remaining suspect. The fix is to widen the skip range so mid-range signals go through the full LLM analysis rather than being fast-pathed to HOLD.

### MES — DO NOT ADD TO SCANNER
MES WFE = 0.09. The in-sample backtest results (PF ~5.3, Sharpe ~4.2) are overfit and do not generalize. Adding MES to the live scanner would corrupt the 30-day validation dataset and likely lose money systematically. The correct path is WFE-validated parameter discovery via the experiment loop, then a gate check before enabling.

### Cowork vs Claude Code Workflow Division
- **Cowork (Claude.ai desktop)**: Strategy, architecture decisions, PRD writing, recommendations, reading session logs, maintaining context across sessions, authoring handoff documents.
- **Claude Code in Cursor**: All actual code writing, test execution, git commits, `/ralph` loop execution. Never the other way around.
- **prd.json** is the handoff artifact from Cowork → Claude Code.

### Sprint 16 Execution Strategy
- Run on master branch (feat/experiment-loop branch does not exist — skip any merge steps)
- Stories in strict priority order: US-1601 → 1602 → 1603 → 1604 → 1605
- Each story gates on `pytest tests/ -v` passing before next story begins
- No parallel execution — each story must complete cleanly

### Signal Frequency Check Protocol
After Sprint 16 deploys and engine restarts: check signal frequency manually after 48 hours using:
```powershell
cd C:\Users\mattm\ThinkorSwim\jarvis-trader\engine
.venv\Scripts\python -c "
import sqlite3
conn = sqlite3.connect('jarvis_trader.db')
cur = conn.cursor()
cur.execute(\"SELECT symbol, COUNT(*) as signals, DATE(created_at) as day FROM trade_signals GROUP BY symbol, day ORDER BY day DESC LIMIT 20\")
for row in cur.fetchall(): print(row)
"
```
If fewer than 2 signals/instrument/day → Sprint 17 P0 is signal frequency, not RL/experiment loop.

### IB Account ID — Must Be Set by Matt
`engine/.env` likely still has `YOUR_IBKR_ACCOUNT_ID` placeholder. No automated resolution — Matt must set this manually before IB Gateway paper orders can route.

---

## 7. TODO Items — Planned But Not Started

### Immediate (before next market open)
- [ ] **Run Sprint 16 in Cursor**: Paste the Sprint 16 prompt into a fresh Claude Code terminal in Cursor
- [ ] **Set IB_ACCOUNT_ID** in `engine/.env`
- [ ] **Run** `.\restart_engine.ps1` after Sprint 16 lands to activate migration_009 + register scheduler jobs
- [ ] **Run smoke test**: `cd engine && .venv\Scripts\python ..\scripts\smoke_test_approvals.py`
- [ ] **Verify signal frequency** 48h after Sprint 16 deploy (query above)

### Sprint 17 — Shape (to be written as prd.json after Sprint 16 completes)
- [ ] **Verify n-autoresearch files on disk** — check if `engine/strategies/experiment_log.py`, `run_experiment.py`, `search_strategy.py` exist. Commit to master if present.
- [ ] **MES parameter re-optimization** via experiment loop — target WFE ≥ 0.50 before enabling in scanner. 20–30 experiment iterations across MES parameter space.
- [ ] **MultiMarketOrchestrator wiring** — confirm MCL + MNQ fire in true parallel (not sequential) in `market_open_scan` scheduler. Commit c0a5726 addressed this but needs verification.
- [ ] **First RL experiment batch** — run 50+ PPO episodes on MES in isolated env. Do not connect to live approval path until 500+ episodes.
- [ ] **Learning loop feedback validation** — after US-1604 lands, verify nightly consolidator is writing to pattern/classification tables. Check row counts after first overnight run.

### Longer Game (post-validation, 30+ days out)
- [ ] Switch IB Gateway port: 4002 (paper) → 7496 (live) — Tier 3 confirmation required
- [ ] 10 manual end-to-end approval → fill tests before live capital
- [ ] Start live: 1 MNQ contract only, no scaling until 90-day live track record
- [ ] RL agent (PPO, MES-only) viable training after 500+ paper training episodes

---

## 8. Full Current TODO List

| Priority | Item | Status | Sprint |
|----------|------|--------|--------|
| P0 | Fix pipeline HOLDs (STC pre-filter) | NOT STARTED | S16 US-1601 |
| P0 | MCL param reconciliation (stc_os 15→23) + composite exit bug | NOT STARTED | S16 US-1602 |
| P0 | DB integrity check + $1,772.33 anomaly | NOT STARTED | S16 US-1603 |
| P0 | Wire learning loop (APScheduler + trade close hook) | NOT STARTED | S16 US-1604 |
| P1 | Fix test_approval_to_order_e2e.py + duplicate RL routes | NOT STARTED | S16 US-1605 |
| P1 | Locate/recover n-autoresearch experiment loop files | NOT STARTED | Pre-S17 |
| P1 | Set IB_ACCOUNT_ID in engine/.env | Matt action | Immediate |
| P1 | Restart engine + run smoke test after S16 | Matt action | After S16 |
| P1 | Verify signal frequency 48h post-S16 | Matt action | After S16 |
| P2 | MES parameter re-optimization via experiment loop | NOT STARTED | S17 |
| P2 | MultiMarketOrchestrator parallel scan verification | NOT STARTED | S17 |
| P2 | First RL experiment batch (50+ PPO episodes, MES only) | NOT STARTED | S17 |
| P3 | Learning loop feedback validation (row count check) | NOT STARTED | Post-S17 |
| P3 | Write Sprint 17 prd.json | NOT STARTED | After S16 complete |

---

## 9. Git State

### Branch
```
master
```

### Uncommitted Changes (git diff --stat)
```
engine/agents/pipeline.py         | 46 +++ (STC pre-filter changes — may be partial S16 work)
engine/routers/pipeline_router.py | 28 +++ (signal-debug scaffolding likely)
engine/tests/test_pipeline_e2e.py | 14 +++ (CRLF warning; may have test additions)
3 files changed, 71 insertions(+), 17 deletions(-)
```

**IMPORTANT for Claude Code**: These uncommitted changes exist. Before running `/ralph` for Sprint 16, inspect `git diff engine/agents/pipeline.py` to determine if this is abandoned work that should be stashed or partial US-1601 progress that should be preserved. Do NOT blindly overwrite without reading the diff first.

### Recent Commits (git log --oneline -20)
```
48af2d1 docs: strategy canon HTML review + builder script
be8cf99 fix: US-1605 — wire inject_pipeline_deps, remove deprecated strategy_router
6a4f1d4 docs: add strategy canon TRADING_RULES and EQUATIONS
67e52e2 fix: complete trading-days stats endpoint; extend CI with approval notify tests
6f3ec61 feat: Sprint 14 extended — cost tracking, SQLite paper state, E2E smoke, trade journal + WFE widgets
82d3c87 feat: add STC mid-range pre-filter to pipeline (Task 2)
c0a5726 feat: parallelize market scans + add MES to market_open_scan
e1b7a8c feat: Sprint 14 — trade management rules enforced in code
e15e96b fix: repair Sprint 12/13 agent truncations and missing imports
9a34845 docs: root cleanup - move stray session files to docs/ delete unknown artifacts
55f98e8 feat: Sprint 13 migration_009 LLM cost tracking + analytics router dedup
4fe50df fix: remove phantom cost_router/scheduler_router + strip null bytes
194418a feat: Sprint 12 — broker reconciliation, performance analytics, SPY walk-forward
2222ba9 feat: wire approval_router + scanner_router into main.py
25a7d27 feat: add scheduled signal scanner + API key validation
99ce6e6 feat: complete trade approval UI + fix localhost violations
24609de fix: resolve test failures and extract main.py modules
1aa83ca docs: Sprint 12 prd.json — all stories passes:true
f77c73c feat: Sprint 12 — Trade Approval UI
f840809 fix: float inf JSON crash + rl evaluate 422 + comprehensive session report
```

### Untracked Files of Note
The git status output shows hundreds of untracked files — the entire project was never fully committed to git. This is expected per `CLAUDE.md` (root has ~59 files). Key untracked items:
- `engine/strategies/` — may contain experiment loop files (check for `experiment_log.py`, `run_experiment.py`, `search_strategy.py`)
- `n-autoresearch-skill/` and `n-autoresearch.zip` — present at root, likely the skill bundle from prior session
- `HANDOFF_NODE_SESSION.md` — prior Node session handoff (read for additional context if needed)
- `SESSION_CONTEXT_2026-04-03.md` — additional session context at root

---

## Appendix: Validated Instrument Status

| Symbol | TF | WFE | Status |
|--------|----|-----|--------|
| MCL | 1h | 0.82 | APPROVED — paper trading active (using WRONG params until US-1602) |
| MNQ | 1h | 0.57 | APPROVED — paper trading active |
| MGC | 1d | 0.14 | HALTED — overfit/small-sample |
| MES | 1h | 0.09 | DO NOT TRADE — WFE too low, RL experiment only |

## Appendix: Sprint 16 prd.json Stories Summary

| Story | Title | Priority |
|-------|-------|----------|
| US-1601 | Diagnose and fix pipeline signal generation (115 HOLDs/day) | 1 |
| US-1602 | MCL parameter reconciliation + composite backtester exit fix | 2 |
| US-1603 | Database integrity check + circuit breaker investigation | 3 |
| US-1604 | Wire learning loop into trading cycle | 4 |
| US-1605 | Fix pre-existing test failures + resolve duplicate RL routes | 5 |

All stories: `passes: false` — awaiting Claude Code execution.

## Appendix: Critical Safety Rules (Never Override)
- `LIVE_TRADING_ENABLED = False` — paper mode until Phase 3
- `REQUIRE_HUMAN_APPROVAL = True` — never disable
- Kill switch: -2% daily P&L OR -10% drawdown — absolute
- Port 4001 (IB live) PERMANENTLY BLOCKED during paper phase
- Safety layer is hardcoded Python — never use LLM for safety decisions

---

*Handoff generated: 2026-04-03*
*Session type: Cowork (strategy/planning only — no code written)*
*Next action: Run Sprint 16 prompt in Cursor Claude Code terminal*
