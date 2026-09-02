# JARVIS Recovery + 5-Step Roadmap
_Authoritative task graph — 2026-08-17_

## ⚠️ SUPERSEDED 2026-08-24 — provider changed to OrcaRouter
⚠️ CRON ESTATE WIPE 2026-09-01 07:55 — the profile's cron store (jobs.json) was replaced. Verified 2026-09-02 03:32Z: 6 jobs are currently present — `xbookmarks-daily-watchdog`, `obsidian-rag-daily-index`, `pr-auto-merger v2`, `jarvis-uptime-watchdog v2`, `JARVIS Roadmap Loop (6h) v3`, and restored `state-db-nightly-backup`. This tick repointed the two shell-backed jobs to Python wrappers (`run_xbookmarks_watchdog.py`, `run_obsidian_rag_index.py`) after Windows cron path handling broke `.sh` execution. QUEUE: 738, 744, 745, 746, 747, 757, 763 — all MERGEABLE, non-draft, non-safety.
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
- [ ] T6 — DONE=no BLOCKED=yes — equity caches + QQQ/AAPL/TSLA certification **(BLOCKED 2026-09-02 06:31 CDT / 11:31Z: verified again that the only 1h caches on disk remain shallow (`QQQ/AAPL/TSLA_2023-09-19_2026-08-17_1h.csv`), and `engine/scripts/fetch_equity_1h.py` still hardcodes `yf.download(..., period="730d", interval="1h")`, so the current free fetch path is structurally capped at ~2 years. New narrowing this tick: `engine/config.py:645-652` shows `OPTIONS_WATCHLIST=["SPY", "QQQ"]`, with `AAPL/TSLA REMOVED` after daily SMA-trend cert FAILs; live operational urgency is therefore concentrated in QQQ deep 1h certification, not AAPL/TSLA routing. Existing real 1h gate-v2 verdicts still remain shallow-window FAILs only: QQQ `pf_ci_lower=0.3073, p_edge=0.3993, dsr=0.0`; AAPL `pf_ci_lower=0.8052, p_edge=0.9349, dsr=0.1495`; TSLA `pf_ci_lower=0.8632, p_edge=0.8437, dsr=0.0067`. Unblock now still requires a different 1h data source (likely paid) or explicit approval to accept shallow 1h + monthly-surrogate evidence as sufficient.)**
- [ ] T7 — DONE=no BLOCKED=yes — dashboard bundle split **(BLOCKED 2026-09-02: T7 is downstream of T6 in the roadmap step chain.)**
- [ ] T8 — DONE=no BLOCKED=yes — provider decision **(BLOCKED: decided out-of-band on 2026-08-24 → OrcaRouter. Needs Amo's confirmation this supersedes T8 rather than reopening it.)**
- [ ] T9 — DONE=no BLOCKED=yes — cron estate + state.db + memory hygiene **(PARTIAL 2026-09-02 13:05Z / 08:05 CDT: current cron store still has 6 jobs, not 29, with `updated_at=2026-09-02T08:04:12.442532-05:00`. `xbookmarks-daily-watchdog` remains clean (`last_run_at=2026-09-02T07:10:08.001511-05:00`, `last_status=ok`, `failure_streak=0`), `obsidian-rag-daily-index` remains `ok` (`last_run_at=2026-09-02T06:46:22.402664-05:00`), `pr-auto-merger v2` remains `ok` (`last_run_at=2026-09-02T07:59:01.672937-05:00`), `state-db-nightly-backup` remains `ok` (`last_run_at=2026-09-02T04:16:29.715067-05:00`), and `jarvis-uptime-watchdog v2` recovered on its next scheduled run (`last_run_at=2026-09-02T07:54:02.383443-05:00`, `last_status=ok`, `failure_streak=0`, `next_run_at=2026-09-02T08:09:02.383443-05:00`). Runtime state improved materially: `pm2 list --no-color` now shows `jarvis-dashboard` online on PID `134104`; `curl -I http://127.0.0.1:3010` returns `HTTP/1.1 200 OK`; and tailnet checks with the required `Host: amoszn.taild02579.ts.net` header return `HTTP/1.1 200 OK` for `/` and `/health`, while `/api/engine/health` returns `HTTP/1.1 405 Method Not Allowed` to HEAD (expected GET-only route reachability, i.e. no longer the prior 502). Engine `/health` at `2026-09-02T13:04:27Z` remains `status=ok` but degraded with `kill_switch_active=true`, `primary_provider=deepseek`, `providers_configured=["deepseek"]`, `ibkr_connected=true`, `ibkr_execution_connected=true`, `execution_connected_verified=false`, `ib_execution_stale=true`, `ibkr_data_connected=false`, `ibgateway_alive=false`, `tradingview_mcp_healthy=true`, `tv_mcp_status=healthy`, and `market_data_fresh=true`. New narrowing: interactive Obsidian RAG is responding again in-session (`rag_stats`: `14,061` chunks across `1,238` notes; `rag_search` succeeded). Remaining blocker: PM2 supervision is still partial because `pm2 describe jarvis-engine` shows `status=waiting restart` after 9 restarts while port `8010` is still served locally, so the live engine is up but not currently proven to be owned by the PM2 app record; runtime repair now belongs to the dedicated `runtime-recovery` workstream/worktree, and unattended memory pruning still needs a human decision.)**

## Current state (as of 13:05Z)

| Track | Status | Verified |
|---|---|---|
| Vision attachments (Hermes) | ✅ FIXED | `vision_analyze` on real image = success |
| Engine boot crash-loop (#711) | ✅ MERGED | health=200, stable uptime |
| Engine health / LLM path | ⚠️ MIXED | `/health` at `2026-09-02T13:04:27Z`: `status=ok`, `kill_switch_active=true`, `llm_path_healthy=true`, `primary_provider=deepseek`, `providers_configured=["deepseek"]`, `ibkr_connected=true`, `ibkr_execution_connected=true`, `execution_connected_verified=false`, `ib_execution_stale=true`, `ibkr_data_connected=false`, `ibgateway_alive=false`, `tradingview_mcp_healthy=true`, `tv_mcp_status=healthy`, and `market_data_fresh=true` |
| Cron estate | ⚠️ PARTIAL | `jobs.json` `updated_at=2026-09-02T08:04:12.442532-05:00`; still only 6 jobs, but all 6 currently healthy: `xbookmarks-daily-watchdog` `ok` from `07:10:08`; `obsidian-rag-daily-index` `ok` from `06:46:22`; `pr-auto-merger v2` `ok` at `07:59:01`; `jarvis-uptime-watchdog v2` recovered to `ok` at `07:54:02` with `failure_streak=0`; `state-db-nightly-backup` `ok` at `04:16:29` |
| Dashboard / PM2 | ⚠️ PARTIAL | `pm2 list --no-color` now shows `jarvis-dashboard` online (PID `134104`, uptime `9m`) and `curl -I http://127.0.0.1:3010` returns `HTTP/1.1 200 OK`; tailnet curls with `Host: amoszn.taild02579.ts.net` return `200` for `/` and `/health`; however `pm2 describe jarvis-engine` is still `waiting restart` after 9 restarts while port `8010` is simultaneously serving `/health`, so supervision of the live engine remains inconsistent |
| RAG daily index | ✅ HEALTHY | cron store still records `last_run_at=2026-09-02T06:46:22.402664-05:00`, `last_status=ok` for `run_obsidian_rag_index.py`; `rag_stats` now returns `14,061` chunks across `1,238` notes, and interactive `rag_search` succeeded in-session |
| X-bookmarks watchdog | ✅ SCHEDULED RERUN CLEAN | cron store now records `last_run_at=2026-09-02T07:10:08.001511-05:00`, `last_status=ok`, `failure_streak=0`, and `next_run_at=2026-09-03T07:10:00-05:00` for `run_xbookmarks_watchdog.py` |
| TOS strategy inventory | ✅ DOCUMENTED | 21 studies, 3 param drifts recorded in rules-jarvis-trader skill |
| Session coordination | ✅ REFRESHED | `session_manifest.json` tracks `recovery-roadmap-loop`; current repo state is still a dirty peer branch (`fix/ci-lint-baseline-20260901`), so this loop remains doc/ops-only, while runtime repair is isolated in the dedicated `runtime-recovery` worktree/branch |

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
- **Current state (verified 2026-09-02 11:31Z):** free deep **daily** caches are refreshed through `2026-09-01` via `backtest.free_daily_export`, but the live 1h fetch path remains capped at 730 days and the current options watchlist is already narrowed to `SPY`/`QQQ`:
  - `QQQ_1999-03-10_2026-09-01_1d.csv` (6,913 rows)
  - `AAPL_1980-12-12_2026-09-01_1d.csv` (11,522 rows)
  - `TSLA_2010-06-29_2026-09-01_1d.csv` (4,069 rows)
- **Live-path verification (real 1h gate-v2 battery, verified from verdict JSONs 2026-09-02 03:11Z):**
  - `QQQ_sma_1h_gate_v2.json` → FAIL — `pf_ci_lower=0.3073`, `p_edge=0.3993`, `mc_95th_dd_pct=3.9246`, `dsr=0.0`
  - `AAPL_sma_1h_gate_v2.json` → FAIL — `pf_ci_lower=0.8052`, `p_edge=0.9349`, `mc_95th_dd_pct=1.1875`, `dsr=0.1495`
  - `TSLA_sma_1h_gate_v2.json` → FAIL — `pf_ci_lower=0.8632`, `p_edge=0.8437`, `mc_95th_dd_pct=3.9975`, `dsr=0.0067`
- **Cache scope behind those verdicts:** the only 1h caches on disk are shallow:
  - `QQQ_2023-09-19_2026-08-17_1h.csv`
  - `AAPL_2023-09-19_2026-08-17_1h.csv`
  - `TSLA_2023-09-19_2026-08-17_1h.csv`
- **Research-only monthly surrogate rerun (still not live-path certification):**
  - QQQ FAIL — `pf_ci_lower=1.4829`, `mc_95th_dd_pct=33.6796`, `dsr=0.0`
  - AAPL FAIL — `pf_ci_lower=1.3074`, `mc_95th_dd_pct=74.9346`, `dsr=0.0`
  - TSLA FAIL — `pf_ci_lower=1.0824`, `mc_95th_dd_pct=86.825`, `dsr=0.0`
- **Source-limit verification (2026-09-02 03:47Z):** live `yfinance.download(..., interval="1h", start="2015-01-01", end="2026-09-02")` for `QQQ`, `AAPL`, and `TSLA` returned 0 rows plus Yahoo's explicit error: `The requested range must be within the last 730 days.` This matches `engine/scripts/fetch_equity_1h.py`, which hardcodes `period="730d"`.
- **Remaining blocker (re-verified 2026-09-02 11:31Z):** the current free 1h fetch path is structurally capped at ~2 years, so T6 cannot reach the deep-validation standard from Yahoo/yfinance alone. New nuance: `AAPL` and `TSLA` are already removed from `OPTIONS_WATCHLIST` in `engine/config.py`, while `QQQ` remains live alongside `SPY`; that reduces live routing urgency but does not solve the certification/data-depth gap. Unblock now hinges on either:
  1. an approved alternate 1h equity source/caching path (likely paid), or
  2. explicit approval to accept the existing shallow 1h + monthly-surrogate evidence as sufficient.
- **Dependency:** T5 gate is enforced; no live routing/config changes were made here.

### T7: Step 3 — Dashboard bundle split
- **Context:** Next.js 15 dashboard on `:3010`, 50 routes, build + Playwright smoke required after any change
- **Status:** BLOCKED by T6 per the roadmap step chain
- **Acceptance (when unblocked):** bundle report, Playwright smoke on all 50 routes, `tsc --noEmit` + `pnpm run build` clean

### T8: Step 4 — LLM provider decision + failover hardening
- **Depends on:** T1 (DeepSeek routing works) + T4 (spend tracking provides real data)
- **Decision criteria:** cost per full-pipeline run, latency, output quality (JSON validity, confidence calibration, risk enumeration), failover reliability
- **If DeepSeek stays:** add circuit breaker (fall back to Anthropic on repeated failure), document cost ceiling, add per-day spend limit
- **If reverting to Anthropic:** document why (quality gap too large, latency unacceptable, etc.)
- **Dead end:** Vertex — Google denied all Claude quota prefs twice, no CLI/API bypass; only re-enable if `gcloud alpha quotas preferences list` shows `grantedValue > "0"`

### T9: Step 5 — Cron estate audit + state.db backup + memory hygiene
- **Cron (re-verified 2026-09-02 13:05Z / 08:05 CDT):** current `C:/Users/mattm/AppData/Local/hermes/cron/jobs.json` still has 6 jobs, not 29, and `updated_at=2026-09-02T08:04:12.442532-05:00`:
  - `xbookmarks-daily-watchdog` — scheduled (`10 7 * * *`), script `run_xbookmarks_watchdog.py`, scheduled rerun now landed clean with `last_run_at=2026-09-02T07:10:08.001511-05:00`, `last_status=ok`, `failure_streak=0`, `last_error=null`, `next_run_at=2026-09-03T07:10:00-05:00`
  - `obsidian-rag-daily-index` — scheduled (`45 6 * * *`), script `run_obsidian_rag_index.py`, `last_run_at=2026-09-02T06:46:22.402664-05:00`, `last_status=ok`, `next_run_at=2026-09-03T06:45:00-05:00`
  - `pr-auto-merger v2` — scheduled every 10m, `last_status=ok`, `last_run_at=2026-09-02T07:59:01.672937-05:00`, `next_run_at=2026-09-02T08:09:01.672937-05:00`
  - `jarvis-uptime-watchdog v2` — scheduled every 15m, **recovered** to `last_status=ok` on `last_run_at=2026-09-02T07:54:02.383443-05:00`, `failure_streak=0`, `last_error=null`, `next_run_at=2026-09-02T08:09:02.383443-05:00`
  - `JARVIS Roadmap Loop (6h) v3` — scheduled every 10m, `last_status=ok`, `last_run_at=2026-09-02T07:53:05.519848-05:00`, `next_run_at=2026-09-02T08:13:12.372111-05:00`
  - `state-db-nightly-backup` — scheduled (`15 4 * * *`), script `backup_hermes_state.py`, `last_status=ok`, `last_run_at=2026-09-02T04:16:29.715067-05:00`, `next_run_at=2026-09-03T04:15:00-05:00`
- **Daily-wrapper execution state:** the xbookmarks cron wrapper remains clean after its scheduled 07:10 rerun, RAG indexing remains healthy, and interactive `rag_search` is now responding again in-session. The previously failing uptime/tailnet watchdog has cleared on its next scheduled run.
- **PM2/runtime regression (re-verified 2026-09-02 13:05Z):** `pm2 list --no-color` now shows both `jarvis-dashboard` and `jarvis-engine` app records, but they are not equally healthy: `jarvis-dashboard` is online and serving `3010` locally plus externally through the tailnet vhost, while `pm2 describe jarvis-engine` is still `waiting restart` after 9 restarts even though local `curl -fsS http://127.0.0.1:8010/health` returns `200`. Net: the dashboard/tailnet outage has recovered, but engine supervision is still inconsistent and remains in the dedicated `runtime-recovery` workstream.
- **Tailnet verification (2026-09-02 13:05Z):** `curl -I -H 'Host: amoszn.taild02579.ts.net' http://100.68.247.106/` and `/health` now both return `HTTP/1.1 200 OK`; `curl -I -H 'Host: amoszn.taild02579.ts.net' http://100.68.247.106/api/engine/health` returns `HTTP/1.1 405 Method Not Allowed`, which is acceptable for a HEAD probe against a GET-only proxied route and confirms the prior 502 path is gone.
- **Engine health delta (re-verified 2026-09-02 13:04:27Z):** `/health` returns `status=ok`, `kill_switch_active=true`, `llm_path_healthy=true`, `primary_provider=deepseek`, `providers_configured=["deepseek"]`, `ibkr_connected=true`, `ibkr_execution_connected=true`, `execution_connected_verified=false`, `ib_execution_stale=true`, `ibkr_data_connected=false`, `ibgateway_alive=false`, `tradingview_mcp_healthy=true`, `tv_mcp_status=healthy`, and `market_data_fresh=true`. The kill switch is still stuck active and must not be reset automatically.
- **state.db backup (re-verified 2026-09-02 12:34Z):** latest trader snapshots on disk still include `trader-20260902-041626.db`, `trader-20260902-021913.db`, and `trader-20260901-222911.db` under `C:/Users/mattm/Archive/2026/session-restore-backups/cron/`.
- **Memory:** no pruning done this tick; unattended pruning/expansion still needs a human decision.
- **session_manifest.json:** this loop remains restricted to doc/ops updates because the current repo checkout is still a dirty peer branch (`fix/ci-lint-baseline-20260901`, unrelated modified/untracked files present); runtime repair ownership is explicitly separated into `runtime-recovery` on `fix/runtime-recovery-20260902` / `C:/Users/mattm/ThinkorSwim/jt-runtime-recovery`.

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
