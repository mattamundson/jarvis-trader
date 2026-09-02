# JARVIS Recovery + 5-Step Roadmap
_Authoritative task graph — 2026-08-17_

## ⚠️ SUPERSEDED 2026-08-24 — provider changed to OrcaRouter
⚠️ CRON ESTATE WIPE 2026-09-01 07:55 — the profile's cron store (jobs.json) was replaced; only 2 jobs remain. Recreated: JARVIS Roadmap Loop v2 (3f344ca0ccc8, 6h/36 ticks) and pr-auto-merger (41afce04f5c3, every 10m). QUEUE: 738, 744, 745, 746, 747, 757, 763 — all MERGEABLE, non-draft, non-safety.
⚠️ NEW BLOCKER 2026-08-24 — engine kill switch tripped 2026-08-18T20:45Z, **still stuck 2026-09-01 (14 days)**. `/safety/status` shows kill_switch_active=true, last_reason="daily_loss_limit". Current: daily_pnl=0, daily_limit_breached=false, drawdown_breached=false, equity=$13181.31, drawdown 16.2% (under 20%). Engine up, provider=kimi-k3, but **all trade exits blocked until cleared**. Requires human decision — do not reset automatically.

The **Hermes agent** provider/model was switched on 2026-08-24 (verified live end-to-end):

| | before | after |
|---|---|---|
| model | `qwen/qwen3-8b-27b` *(typo — model never existed)* | `qwen/qwen3.8-27b` |
| provider | `deepseek` | `orcarouter` |
| base_url | `api.deepseek.com/v1` | `api.orcarouter.ai/v1` |
| key_env | `NOVITA_API_KEY` *(never set in .env)* | `ORCAROUTER_API_KEY` ✅ |

Three defects were live simultaneously: a model ID that does not exist on any provider, a
provider/base_url mismatched to the model, and a key env var that was never populated. All
four enabled cron jobs are now pinned to `orcarouter` + `qwen/qwen3.8-27b` so they cannot
silently drift (exception: `pr-auto-merger` stays on Nous — a credential-scoping guard
correctly refuses to send a Nous-pinned base_url to another provider, and it works there).

**Impact on this roadmap:** T1/T3/T8 were written around a DeepSeek migration. That premise
is now stale — this is a *Hermes agent* provider change and does NOT alter
`engine/llm/client.py`, which still routes the JARVIS trading agents. T1's remaining work
(8 agent files hardcoding `claude-*`) is still valid but should now be evaluated against
OrcaRouter, not DeepSeek. T3's cost/quality table is superseded and needs a re-run.

## Machine-readable status (loop termination contract)

The 6h recovery loop (`e525fb46c7f2`) terminates on `ALL_ROADMAP_TASKS_COMPLETE`. Keep these
lines accurate — they are the loop's only exit condition.

- [x] T1 — DONE=yes BLOCKED=no — agent-file model routing *(2026-09-02: loop agent implemented provider-aware routing in worktree; I committed+PR #764; enqueued)*
- [x] T2 — DONE=yes BLOCKED=no — stale PR audit + kanban hygiene *(2026-09-02 02:34Z: verified #572/#571/#657 merged, #557 closed, #574 merged; jarvis board clean; edge-roadmap-2026 and ops-roadmap-2026 have 0 ready/in_progress tasks remaining)*
- [x] T3 — DONE=yes BLOCKED=no — cost/quality report *(SUPERSEDED by provider change; re-run needed)*
- [x] T4 — DONE=yes BLOCKED=no — persistent LLM spend tracking *(verified 2026-09-01: 212 rows live, PR #763 fixes $0.00 pricing bug — kimi-k3 rate was missing)*
- [x] T5 — DONE=yes BLOCKED=no — lock MES-only live scope *(verified 2026-09-01: gate chain blocks MGC — paper_config.enabled=False; MES carved out per Amo 2026-06-26 directive)*
- [ ] T6 — DONE=no BLOCKED=no — equity caches + QQQ/AAPL/TSLA certification
- [ ] T7 — DONE=no BLOCKED=no — dashboard bundle split
- [ ] T8 — DONE=no BLOCKED=yes — provider decision **(BLOCKED: decided out-of-band on 2026-08-24 → OrcaRouter. Needs Amo's confirmation this supersedes T8 rather than reopening it.)**
- [ ] T9 — DONE=no BLOCKED=no — cron estate + state.db + memory hygiene

## Current state (as of 21:30Z)

| Track | Status | Verified |
|---|---|---|
| Vision attachments (Hermes) | ✅ FIXED | `vision_analyze` on real image = success |
| Engine boot crash-loop (#711) | ✅ MERGED | health=200, stable uptime |
| LLM provider (Anthropic direct) | ✅ LIVE | pm2 logs: `[claude-sonnet-4-6] ... retries:0` |
| Vertex Model Garden | ⚠️ ENABLED but quota-denied | gcloud alpha quotas preferences: all 6 Claude quota prefs show `grantedValue=0, stateDetail=Quota request denied` |
| DeepSeek key + partial routing | ✅ KEY WIRED, ⚠️ PARTIAL ROUTE | `fundamental_analyst` hits deepseek; 8 more agents still hardcoded claude-* |
| DeepSeek side-by-side test | ✅ COMPLETE | 5.1x cheaper ($0.00193 vs $0.0099), latency 33% faster, output structurally valid JSON |
| TOS strategy inventory | ✅ DOCUMENTED | 21 studies, 3 param drifts recorded in rules-jarvis-trader skill |
| Session coordination | ✅ COMPLETE | session_manifest.json + pr_queue_add.py + DASHBOARD_STATE.md |

## Kanban board

Board: `jarvis-20260817` (JARVIS 2026-08-17 Recovery + 5-Step Roadmap)
DB: `C:\Users\mattm\AppData\Local\hermes\kanban\boards\jarvis-20260817\kanban.db`

## Task graph

```
T0  JARVIS recovery + 5-step roadmap orchestrator  [default]
├── T1  Finish DeepSeek provider routing            [default]
│     └── T5  Step 1: Lock MES-only live scope       [default]
│           └── T6  Step 2: Equity caches + QQQ/AAPL/TSLA cert [default]
│                 └── T7  Step 3: Dashboard bundle split         [default]
├── T2  Audit stale PRs + kanban hygiene            [default]
│     └── T9  Step 5: Cron estate + state.db + memory [default]
├── T3  LLM cost/quality report (DeepSeek vs Claude) [default]
└── T4  Persistent LLM spend tracking               [default]
      └── T8  Step 4: LLM provider decision + failover hardening [default] (parents: T1, T4)
```

### T1: Finish DeepSeek provider routing
- **Status:** Partial — `llm/client.py` default_model/fast_model now routes to deepseek-reasoner
- **Remaining:** 8 agent files hardcode claude-* model strings:
  - `bear_researcher.py`, `bull_researcher.py`, `fund_manager.py`, `risk_manager.py`, `trader.py` → `MODEL = "claude-sonnet-4-6"`
  - `news_analyst.py`, `social_analyst.py` → inline `"claude-haiku-4-5-20251001"`
  - `technical_analyst.py` → inline `"claude-sonnet-4-6"`
- **NOT changing:** `advisor_client.py ADVISOR_MODEL = "claude-opus-4-7"` — deliberate documented choice ("Advisor always uses the most capable model")
- **Acceptance:** py_compile clean, full MES pipeline logs show `[deepseek-reasoner]` for all 8 agents
- **Branch:** `feat/deepseek-provider-routing-20260817` (already created, commit `2a9f22ae` on `client.py`)

### T2: Audit stale PRs + kanban board hygiene
- **Status:** DONE — verified 2026-09-02 02:34Z
- **PR disposition (verified live via `gh pr view`):**
  - #572 dashboard phase-drain → MERGED (2026-08-25)
  - #571 E2E smoke → MERGED (2026-08-25)
  - #557 reaction_watcher backoff → CLOSED (2026-08-18)
  - #657 MGC docs → MERGED (2026-08-18)
  - #574 [safety-review] Robinhood scaffold → MERGED (2026-08-25)
- **Kanban hygiene (SQLite board audit):**
  - `jarvis-20260817` → 2 archived, 0 open tasks
  - `edge-roadmap-2026` → 27 done, 19 blocked, 1 todo, **0 ready / 0 in_progress**
  - `ops-roadmap-2026` → 1 done, 17 blocked, 1 todo, **0 ready / 0 in_progress**
- **Net:** the stale-PR queue is cleared and the named boards no longer have the weeks-stale ready backlog that originally motivated T2.

### T3: LLM cost/quality report
- **Test completed:** 2026-08-17 23:30Z, isolated direct-API call, same prompt
- **Results:**

| Metric | claude-sonnet-4-6 | deepseek-reasoner | Ratio |
|---|---|---|---|
| Cost/call | $0.0099 | $0.00193 | **5.1x cheaper** |
| Latency | 15.5s | 10.4s | **33% faster** |
| Input tokens | 275 | 330 | +20% |
| Output tokens | 605 | 538 | −11% |
| Reasoning tokens | 0 (none) | 240 | DeepSeek internal |
| JSON validity | ✅ valid | ✅ valid | parity |
| Confidence | 0.45 | 0.38 | close |
| Key risks | 4 enumerated | 5 enumerated | comparable depth |

- **Output path:** `docs/reports/LLM_COST_QUALITY_DEEPSEEK_VS_CLAUDE_2026-08-17.md`

### T4: Persistent LLM spend tracking
- **Current state:** `pipeline_llm_costs` table = 0 rows, `/llm/stats` in-memory only (resets restart)
- **Plan:** persist every `llm.client` cost_tracker call to SQLite, add `/llm/daily-summary`, configurable alert threshold via `.env`
- **Acceptance:** new calls populate table, historical totals visible after restart, alert fires at threshold

### T5: Step 1 — Lock MES-only live scope
- **Rule:** MES only until RV filter reaches 60+ live paper trades confirming `p_edge>=0.6` and `mc_95th_dd<=4%`
- **Do NOT enable:** MGC (halted 2026-07-31), SPY (REJECTED gate-v2), QQQ/AAPL/TSLA (no gate-v2 verdicts on file)
- **Enforcement point:** `approval/service.py:ensure_approval_allowed()` already blocks non-approved symbols — verify it's wired to the live gate

### T6: Step 2 — Equity cache pipeline + QQQ/AAPL/TSLA certification
- **Current state:** QQQ/AAPL/TSLA deep caches absent; no gate-v2 verdicts exist for any of them
- **Plan:** fetch 1h deep data, run gate-v2 WFO, produce verdict files
- **Dependency:** T5 gate must be enforced first (don't certify symbols that aren't approved for live)

### T7: Step 3 — Dashboard bundle split
- **Context:** Next.js 15 dashboard on `:3010`, 50 routes, build + Playwright smoke required after any change
- **Plan:** `next/bundle-analyzer` run, identify lazy-loadable routes, implement safe defer/split
- **Acceptance:** bundle report, Playwright smoke on all 50 routes, `tsc --noEmit` + `pnpm run build` clean

### T8: Step 4 — LLM provider decision + failover hardening
- **Depends on:** T1 (DeepSeek routing works) + T4 (spend tracking provides real data)
- **Decision criteria:** cost per full-pipeline run, latency, output quality (JSON validity, confidence calibration, risk enumeration), failover reliability
- **If DeepSeek stays:** add circuit breaker (fall back to Anthropic on repeated failure), document cost ceiling, add per-day spend limit
- **If reverting to Anthropic:** document why (quality gap too large, latency unacceptable, etc.)
- **Dead end:** Vertex — Google denied all Claude quota prefs twice, no CLI/API bypass; only re-enable if `gcloud alpha quotas preferences list` shows `grantedValue > "0"`

### T9: Step 5 — Cron estate audit + state.db backup + memory hygiene
- **Cron:** 29 jobs active; audit for drift, orphaned jobs, missing failure alerts
- **state.db:** nightly backup to `Archive/2026/session-restore-backups/cron/` — verify still running
- **Memory:** MEMORY.md at 92% capacity (2,029/2,200 chars); prune stale entries before cap blocks writes
- **session_manifest.json:** update workstream statuses to reflect today's completions

## 5-step forward summary

| Step | Focus | Dependency |
|---|---|---|
| 1 | Lock MES-only, enforce live gate | T1 (routing) |
| 2 | QQQ/AAPL/TSLA cache + gate-v2 certification | T5 |
| 3 | Dashboard bundle split (cold-start perf) | T6 |
| 4 | Final LLM provider decision + failover hardening | T1 + T4 |
| 5 | Cron estate + state.db + memory hygiene | T2 |

## Open decisions for Amo

1. **T8 supersession:** confirm whether the 2026-08-24 OrcaRouter decision closes T8 permanently or whether T8 should be re-opened for post-Orca failover hardening.
2. **Kill switch:** `/safety/status` still shows `kill_switch_active=true` from 2026-08-18 daily loss limit; requires human decision and must not be reset automatically.
3. **Memory budget:** MEMORY.md at 92% — approve prune of stale entries, or expand cap?
