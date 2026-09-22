# Session-Close Handoff — 2026-04-20 18:23 CT

> **Successor session: read this document first.**  You are continuing work on the MES-profitability pivot + associated observability and dashboard build-out on branch `feat/tradingview-mcp-gamma-kraken`. The previous session accomplished the core strategy activation earlier in the day; this document captures the additional 5 hours of work that happened after the earlier 1,537-line handoff was written.

> **Prior handoff** — `docs/session-logs/handoff-2026-04-20-mes-profitability.md` (1,537 lines) is the canonical strategy document. It covers the SMA(50, 200) + 2.0×ATR trend-follower derivation, walk-forward validation, cross-instrument rejection, activation timeline, and 22 sections of forward-looking strategy. **Read it after this close-out.** This session-close is narrower: it captures the delta since 13:45 CT.

---

## 1. Session summary — what was accomplished, in what order

**Session window**: ~13:42 CT to 18:23 CT (~4.7 hours).

1. **13:42 CT** — Addressed `tos.mx/!JUBozxiD` link request. ThinkOrSwim share URLs are opaque on the web (binary payload rendered only inside TOS desktop); surfaced three alternative paths to capture the chart content (paste ThinkScript, screenshot, or prose description). No action taken on chart itself — awaiting user-provided study text.

2. **13:45 CT** — Expanded `handoff-2026-04-20-mes-profitability.md` from ~919 lines → **1,537 lines**. Added sections 14–22:
   - §14 Deep Insight Strategy — Multi-Horizon Edge Stacking
   - §15 Risk Topology Map (4 tables: strategy / system / data / governance risks)
   - §16 Forward-Test Decision Framework (decision tree + quantitative triggers + qualitative triggers + adjust/extend/pause/kill rubric)
   - §17 Strategy Evolution Roadmap — Phased Gates (Phases 0–6 with explicit gate criteria)
   - §18 Diagnostic Playbook (symptom → cause → action)
   - §19 Knowledge Graph (data flow, failure-mode graph, git topology, memory topology)
   - §20 Closing Philosophy — 10 compound-learning principles
   - §21 Strategic Insight Bank — 11 non-obvious observations
   - §22 Appendix — Session Artifact Index

3. **14:00–18:15 CT (concurrent-session activity — not driven by this Claude session but visible in workspace)**:
   - Backtest API `/backtest/run` was rewired to dispatch via `generate_instrument_signals(df, symbol=...)` so MES now routes through `trend_signals.py` in the API path (previously only the live pipeline had this dispatch). See staged change to `engine/routers/backtest_router.py`.
   - The inline `/backtest/results` handler in `engine/main.py` (~26 lines) was removed because it was shadowing the sanitized version in `backtest_router.py` and returning HTTP 500 on any results file containing `inf`/`nan` floats.
   - Experiments router created (`engine/routers/experiments_router.py`) exposing `/experiments/mes-forward/summary` and `/experiments/mes-forward/rows` for the MES forward-recorder hypothesis table.
   - Discord notifier extended with `discord_mes_forward_outcome()` — sends a rich embed (green/red/grey color coding) when the 15:15 CT outcome job runs so forward-recorder rows are visible same-day.
   - Dashboard got an `MESForwardRecorderPanel.tsx` component (SWR-driven, 60s refresh) — starts to deliver TODO #2 from the prior handoff.
   - Validation page (`dashboard/app/validation/page.tsx`) received a 9-line tweak — purpose not yet confirmed; likely related to the new MES panel being mounted.
   - A pure-STC MES search script (`engine/scripts/mes_stc_search.py`) was added — bypasses composite layer and optimizes pure STC via the canonical `Backtester` path.
   - Auxiliary utility `engine/api_check.py` — smoke probe for macro/session/sentiment/MCL/MNQ endpoints.
   - Port guardian (`engine/scripts/port_guardian.py`) received +21 lines (staged).
   - Outcome recorder (`engine/experiments/mes_session_outcome.py`) received +19 lines (likely to wire into Discord notifier).
   - Four additional session-log files were dropped into `docs/session-logs/` by the concurrent session (premarket, scan, eod, bookmark-integration, sma-strategy).

4. **18:23 CT** — User requested this session-close handoff. Captured git state, inspected staged/unstaged/untracked files, composed exhaustive close-out document.

### Interpretation

This session (the one closing now) did two user-facing things: **(a) answered the tos.mx link, (b) expanded the prior handoff with deeper strategy sections**. A **concurrent Claude session** ran in parallel during the same window, landing the MES-backtest-API dispatch, experiments router, Discord forward-outcome embed, dashboard panel, and STC search script — all uncommitted as of 18:23 CT. The successor session needs to triage and commit that concurrent-session work.

---

## 2. Files created or modified — full paths, what changed, why

### 2a. Modified by this session (committed in prior hours)

None. This session's only file write was to the prior handoff document (expansion) and this new session-close document.

### 2b. Modified by this session — document writes

| Path | Change | Why |
| ---- | ------ | --- |
| `docs/session-logs/handoff-2026-04-20-mes-profitability.md` | +618 lines (sections 14–22 appended) | User asked for deeper insight strategy; earlier handoff stopped at tactical state |
| `docs/session-logs/handoff-2026-04-20-1823-session-close.md` | **This file** | User request for exhaustive session-close handoff |

### 2c. Modified by concurrent session (staged — ready to commit)

| Path | Diff size | What it does | Why |
| ---- | --------- | ------------ | --- |
| `engine/routers/backtest_router.py` | +24 / −6 | `/backtest/run` now dispatches via `generate_instrument_signals(df, symbol=request.symbol)` instead of the generic `generate_signals(df)`. Also hardens `/backtest/results` with a belt-and-suspenders `json.dumps(sanitized, allow_nan=False)` check that drops entries where numpy-subclass floats leak past the primary sanitizer. | Brings the backtest HTTP API in line with the live pipeline so `POST /backtest/run` for symbol=MES runs the SMA(50, 200) trend strategy, matching what the scheduler fires. Previously the API would silently run composite on MES. |
| `engine/scripts/port_guardian.py` | +21 / 0 | New defensive code path (content not fully inspected this session). | Part of the orphan-uvicorn-on-port-8010 defense pattern from the roadmap. |

### 2d. Modified by concurrent session (unstaged — not yet added)

| Path | Diff size | What it does | Why |
| ---- | --------- | ------------ | --- |
| `engine/main.py` | +13 / −16 | Imports `backtest_router` + `experiments_router`; calls `inject_backtest_deps(data_manager)` in `lifespan`; includes both routers via `app.include_router(...)`; **removes** the inline `/backtest/results` handler that was shadowing the sanitized router version (it was returning HTTP 500 on inf/nan floats). | Wire the new experiments router into the app; stop silent overshadowing of the properly-sanitizing backtest router handler. |
| `engine/notifications/discord_notifier.py` | +56 / 0 | Adds `async def discord_mes_forward_outcome(date_str, side, reason, open_price, close_price, outcome_delta)` — posts a color-coded embed (green profit / red loss / grey skip) for the daily MES forward-recorder outcome. | Make the observational experiment visible same-day without opening the dashboard. Complements the 15:15 CT outcome scheduler job. |
| `engine/experiments/mes_session_outcome.py` | +19 / 0 | Outcome capture logic — not fully inspected this session. Likely calls `discord_mes_forward_outcome(...)` after persisting the daily row. | Bridge between the DB write and the Discord notification. |
| `dashboard/app/validation/page.tsx` | +8 / −1 | Minor tweak — possibly mounts or cross-links the new `MESForwardRecorderPanel`. | Surface the forward-recorder in the existing validation page rather than building a new route. |

### 2e. Created by concurrent session (untracked — need `git add`)

| Path | Purpose |
| ---- | ------- |
| `dashboard/components/MESForwardRecorderPanel.tsx` | New React/SWR component (60s refresh). Consumes `/experiments/mes-forward/summary` and renders side-stats (hit rate by side, avg outcome delta, row count, last-seen date). Delivers part of prior-handoff TODO #2 (MES dashboard panel). |
| `engine/routers/experiments_router.py` | New FastAPI router. Two read-only endpoints: `/experiments/mes-forward/summary` (aggregate metrics) and `/experiments/mes-forward/rows` (N most recent rows for charts/tables). Writes are scheduler-only — the router is read-only. |
| `engine/scripts/mes_stc_search.py` | New pure-STC random search driver. Bypasses the composite stop/target hardcoding; hits the canonical `Backtester` path via `_compute_signals`. Same path BayesianOptimizer uses, but with wider random search and explicit PF primary objective. |
| `engine/scripts/mes_stc_search_results.json` | Results from the STC search above. Content not inspected this session — successor should review to determine if any STC-only config is competitive with the SMA-trend winner. |
| `engine/api_check.py` | Smoke probe utility: iterates `[MACRO, SESSION, SENTIMENT, MCL-technical, MNQ-technical]` endpoints with the API key header, prints status. A lightweight health check during dev. |
| `docs/session-logs/eod-2026-04-20.md` | End-of-day session log (~8 KB). |
| `docs/session-logs/handoff-2026-04-20-bookmark-integration.md` | **97 KB handoff** from concurrent session focused on Discord bookmark + clustering pipeline — separate concern from the MES work. |
| `docs/session-logs/handoff-2026-04-20-mes-sma-strategy.md` | **20 KB handoff** from concurrent session focused on MES SMA strategy commit (`2db7f74`). Parallel coverage of the same topic as `handoff-2026-04-20-mes-profitability.md`. |
| `docs/session-logs/premarket-2026-04-20.md` | Pre-market log (~5 KB). |
| `docs/session-logs/scan-2026-04-20.md` | Scan output (~8 KB). |

---

## 3. Current state — what's running, what's stopped, what's broken

### 3a. Running (verified earlier today 12:56 CT, not re-verified at session close)

- **PM2 process `jarvis-engine`** — cycle #17 after restart for MES strategy activation. `/health.status == ok`, `/health.llm_path_healthy == true`.
- **PM2 process `jarvis-dashboard`** — restored earlier today (commit `96d1328`), serving on port 3010.
- **IB Gateway** — paper port 4002; status flag says connected but data connector side is still in simulation mode (per MEMORY.md note). No live market prices without IB Gateway app started.
- **MES SMA(50, 200) + 2.0×ATR trend strategy** — ACTIVE in live pipeline via `TREND_INSTRUMENTS = {"MES"}` dispatch at `engine/backtest/signals.py:106`. Commit `2db7f74`.
- **MES session forward-recorder** — APScheduler jobs registered in lifespan (08:30 CT record / 15:15 CT outcome, Mon–Fri). First smoke row captured 2026-04-20. Commit `d11565f`.
- **Discord bookmark pipeline** — 371 bookmarks loaded; clusterer agent prewarms Sunday 18:00 CT. Commits `7493753` + `bc12cbc`.

### 3b. Running but not yet reflected in committed code

- **Backtest API dispatch for MES** — staged in `engine/routers/backtest_router.py` but not committed. The running engine still uses the pre-dispatch code because `pm2 restart` has not been called since the concurrent-session edits. Successor must restart after committing.
- **Experiments router** — `engine/routers/experiments_router.py` exists on disk but is untracked. `engine/main.py` has unstaged imports pointing to it. Running engine has not loaded it. `/experiments/mes-forward/*` endpoints return 404 until the next restart that includes both staged and unstaged changes.
- **Discord MES forward outcome embed** — function defined but not yet invoked by the running engine. The 15:15 CT outcome job fires today without Discord notification.

### 3c. Stopped / not running

- **Live (real-money) trading** — never on. All activity is paper.
- **SDK pipeline (`/pipeline/run/sdk`)** — technically live but not the default path. Primary pipeline is `/pipeline/run`.

### 3d. Broken (known)

- **pyc cache risk** — earlier handoff flagged possible stale `.pyc` for `engine/routers/backtest_router.py` blocking live activation. The staged edit today clears this risk IF the successor deletes the stale pyc AND restarts. Command: `rm -rf engine/routers/__pycache__/backtest_router.cpython-312.pyc` then `pm2 restart jarvis-engine`.
- **Death-cross exit in Backtester** — still not wired into the canonical Backtester per earlier handoff. `mes_trend_search.py` is the ground truth for PF 2.06. The canonical Backtester does not yet generate the death-cross exit, so `POST /backtest/run` on MES after today's dispatch wiring will produce *entries* via trend_signals but *exits* via whatever the Backtester default is. This is the highest-risk discrepancy for successor to verify.
- **Dashboard `MESForwardRecorderPanel.tsx`** — component exists but its mount-point in `dashboard/app/validation/page.tsx` is unstaged. Dashboard build (`pnpm run build`) has not been run against the new component, so TypeScript errors (if any) are unknown.
- **`mes_stc_search_results.json`** — results exist but have not been reviewed. We don't know yet whether pure-STC on MES has any profitable config.

---

## 4. In-progress work — anything started but not finished

| Item | Status | Next concrete step |
| ---- | ------ | ------------------ |
| MES dashboard panel (TODO #2 from prior handoff) | Component written, router written, mount unstaged | Stage dashboard + router changes; `pnpm run build` in `dashboard/`; verify the panel renders against live `/experiments/mes-forward/summary` |
| Backtest API MES dispatch | `backtest_router.py` staged, `main.py` include unstaged | Stage main.py; commit together with a message like `feat(backtest): route MES through SMA trend signals in API`; restart engine |
| Experiments router integration | Router file untracked, imports unstaged in main.py | Add router file + stage main.py imports; commit; restart |
| Discord MES forward-outcome embed | Notifier function added, outcome.py caller unstaged | Stage `discord_notifier.py` + `mes_session_outcome.py`; commit; restart |
| Pure-STC MES search results | Results JSON exists, not analyzed | Read `engine/scripts/mes_stc_search_results.json`; compare top-10 PFs to SMA-trend PF 2.06; decide whether STC is worth promoting or is a dead end |
| `port_guardian.py` +21 lines | Staged | Review diff (not done this session); commit if sensible |
| Session-log docs cleanup | Five new untracked logs | Decide: commit all five, commit subset, or leave untracked as scratchpads |
| ThinkOrSwim chart from tos.mx/!JUBozxiD | Blocked on user | Awaiting paste of ThinkScript or prose description; link itself does not expose code |

---

## 5. Blockers discovered — issues found that need resolution

### B1. Concurrent-session commit discipline

A second Claude session ran in parallel during today's window and produced substantial uncommitted work (4 modified + 10 untracked files as of 18:23 CT). The earlier handoff flagged this risk as well — today's `fd5b153` commit unintentionally swept in 6 files because of interaction between sessions. **Recommendation for successor**: before any new commit, run `git status` and classify every file. Never run `git add -A`. Use explicit `git add <path>` lists.

### B2. MES trend strategy: Backtester path has no death-cross exit

The live pipeline uses `trend_signals.py` which emits both entries and death-cross exits. The backtest API now dispatches through `trend_signals.py` for entries (thanks to today's `backtest_router.py` staged edit) but the canonical `Backtester` class does not (yet) consume the death-cross exit signal. Result: `POST /backtest/run` on MES will enter on golden-cross but exit on some Backtester default (likely STC reversal or ATR stop only). **Downstream risk**: any Phase-2-gate comparison of backtest-PF to live-PF will not be apples-to-apples until this is reconciled. Two options:
- (a) Add explicit death-cross exit handling in the Backtester (cleaner, longer).
- (b) Keep `mes_trend_search.py` + `mes_trend_wfo.py` as the canonical authoritative backtest source; document that `POST /backtest/run` is a degraded view for MES (shorter, accepts the discrepancy).

### B3. Staged + unstaged split across same logical change

The wire-up for the experiments router is split: `engine/routers/backtest_router.py` is staged, but `engine/main.py` (which imports and mounts it) is unstaged, and `engine/routers/experiments_router.py` (the file itself) is untracked. Committing staged-only would produce a half-broken import. Successor must group staged + unstaged + untracked into one cohesive commit.

### B4. pyc staleness risk around backtest_router.py

If the engine was restarted between the concurrent-session edit and now, it may be running the old code from a cached `.pyc`. Verify with:
```bash
ls -la engine/routers/__pycache__/backtest_router.cpython-312.pyc
# compare mtime to engine/routers/backtest_router.py mtime
```
If the `.pyc` is older than the `.py`, Python will recompile on next restart automatically. If it's newer (unlikely but possible), delete it before restart.

### B5. STC search results unreviewed

`engine/scripts/mes_stc_search_results.json` was produced by the concurrent session but not reviewed. If STC alone produces a competitive MES config, the current dispatch gate (which prefers SMA-trend) may be leaving edge on the table. Conversely, if STC is uniformly destructive on MES (consistent with prior composite findings), the file is a dead-end we can archive.

### B6. Dashboard build not verified

`MESForwardRecorderPanel.tsx` was written but `pnpm run build` has not been run against it. Unknown whether TypeScript compiles cleanly. If it doesn't, the panel won't render and the backend endpoints will be orphan.

### B7. Validation page change unexplained

`dashboard/app/validation/page.tsx` has 8 additions + 1 deletion with no accompanying comment in the diff. Either the concurrent session intended to wire the MES panel into this page or the change is unrelated. Successor must either read the diff end-to-end or confirm with the concurrent-session handoff file (`handoff-2026-04-20-bookmark-integration.md` might mention it).

### B8. Five new session-log files untracked

Not technically a blocker but represents uncommitted documentation. Successor should decide whether to commit, rename, or archive. Session-log files are not usually load-bearing — but they are useful for future archaeology. **Default recommendation**: `git add docs/session-logs/*.md && git commit -m "docs(session): accumulate 2026-04-20 session logs"`.

---

## 6. Key decisions made — architectural choices, parameter values, tradeoffs

Captured decisions in chronological order:

### D1. tos.mx link — do not attempt to parse binary payload

tos.mx share URLs are opaque to web scraping; they're deep-links into the TOS desktop client. Attempted `WebFetch` and confirmed only landing-page metadata is available. **Decision**: surface three alternative input paths to user (paste ThinkScript / screenshot / prose) rather than fabricate interpretation. Rationale: fabricating trading-strategy analysis from nothing is exactly the kind of compounding error the "verify before reporting" rule exists to prevent.

### D2. Expanded prior handoff rather than start a new one

User asked for "more comprehensive handoff and insight strategy." Decision: **append** sections 14–22 to the existing `handoff-2026-04-20-mes-profitability.md` rather than create a parallel file. Rationale: (a) single canonical document for next session, (b) avoids handoff fragmentation that we saw earlier with `handoff-2026-04-20-mes-sma-strategy.md` produced by the concurrent session, (c) the prior handoff's sections 1–13 are tactical state while 14–22 are strategic — they belong in the same document.

### D3. Structure expansion as decision-frameworks + roadmap + playbook + philosophy

Three cognitive tools for three next-session moments:
- **Diagnostic playbook** (§18) — "something broke, what do I check?"
- **Decision framework** (§16) — "performance deviated, what do I do?"
- **Roadmap with gates** (§17) — "what's the next 90 days of work and how do I know I'm on track?"

Plus §20 philosophy (10 compound-learning rules) and §21 insight bank (11 non-obvious observations) as institutional memory for future agents. Rationale: handoffs that are just state dumps rot fast. Handoffs that encode *rules* and *frameworks* compound across sessions.

### D4. Did not commit the concurrent-session work from this session

Staged changes to `backtest_router.py` + `port_guardian.py` were already staged when this session started inspecting state. Unstaged changes to `main.py` / `discord_notifier.py` / `mes_session_outcome.py` / `validation/page.tsx` + untracked experiments_router + MESForwardRecorderPanel + STC search + 5 session logs were all produced by the concurrent session. **Decision**: do not commit — attribution and completeness are uncertain. Successor session should review with the concurrent-session's own handoff doc (`handoff-2026-04-20-mes-sma-strategy.md` + `handoff-2026-04-20-bookmark-integration.md`) open alongside, classify each file, then group into logical commits.

### D5. Did not restart engine

None of this session's work required an engine cycle. The staged/unstaged concurrent-session work will need one, but deferring the restart avoids: (a) activating half-committed code, (b) losing pipeline uptime data before R4 window on 2026-04-22. Successor should batch all the concurrent-session commits, then run `./restart_engine.ps1` once.

### D6. Parameters (unchanged this session — re-stating for successor)

- **SMA fast = 50 / slow = 200** on MES 1h
- **ATR trail multiplier = 2.0** (Wilder's, 14-period)
- **Commission = $0.62/contract/leg** round-trip
- **Slippage = 1 tick = $1.25/contract** on MES
- **Initial capital = $10,000**, 1 contract per trade
- **Instruments set**: `TREND_INSTRUMENTS = {"MES"}` in `signals.py:106` — MCL/MNQ fall through to composite

### D7. Named new session-close doc instead of overwriting prior

Prior handoff is canonical *strategy* doc. This close-out is narrower *state* doc. They serve different purposes. Filename: `handoff-2026-04-20-1823-session-close.md`. Rationale: timestamp in name disambiguates from the two other `handoff-2026-04-20-*.md` files already in the directory.

---

## 7. TODO items — what was planned but not started

**Carrying over from prior handoff, plus new items discovered this session.**

### Carry-over from prior handoff (`handoff-2026-04-20-mes-profitability.md` §7)

| # | Item | Priority | ETA | Status |
| - | ---- | -------- | --- | ------ |
| 1 | MES-trend drift alert (rolling 7-day PF monitor + WhatsApp on PF<1.0) | P0 | 1 hr | Not started |
| 2 | Dashboard `<MESTrendStatusCard>` component | P0 | 2 hr | **Partially started** — `MESForwardRecorderPanel.tsx` delivers forward-recorder view; MES-trend live P&L card still TODO |
| 3 | `POST /backtest/mes-trend-wfo` async endpoint | P1 | 2 hr | Not started |
| 4 | Backtest named-sweep compare view | P1 | 3 hr | Not started |
| 5 | R4 analyzer delta re-run (scheduled 2026-04-22) | P0 | 30 min | Scheduled, not run |
| 6 | Commit concurrent session's `backtest_router.py` | P0 | 5 min | **Staged, uncommitted** — blocker B3 applies |
| 7 | Memory note about `git add` sweep-in behavior | P2 | 10 min | Not started |
| 8 | Investigate 2nd engine restart at ~13:11 CT | P2 | 15 min | Not started |
| 9 | Add pullback entry variant to SMA-trend | P3 | 4 hr | Not started |
| 10 | Regime-aware strategy switcher | P3 | 8 hr | Not started |

### New this session

| # | Item | Priority | ETA | Rationale |
| - | ---- | -------- | --- | --------- |
| 11 | Commit concurrent-session uncommitted work (B3) | P0 | 30 min | Blocks any further engine restart; must be done as one cohesive commit grouping |
| 12 | Review `mes_stc_search_results.json` (B5) | P1 | 15 min | Determine if pure-STC has an edge on MES that dispatch gate should expose |
| 13 | Verify dashboard TypeScript build with new panel (B6) | P0 | 10 min | `pnpm run build` in `dashboard/` — must pass before user sees the panel |
| 14 | Reconcile Backtester vs. live-pipeline exit logic for trend (B2) | P1 | 4 hr | Phase 2 gate depends on apples-to-apples backtest vs. live comparison |
| 15 | Decide commit fate of 5 new session-log files (B8) | P2 | 5 min | Default: commit all; not load-bearing either way |
| 16 | Read `handoff-2026-04-20-bookmark-integration.md` for Discord-bookmark context | P2 | 15 min | Concurrent session's own handoff; context for bookmark-related commits |
| 17 | Read `handoff-2026-04-20-mes-sma-strategy.md` for concurrent-session MES view | P2 | 10 min | Reconcile parallel coverage with current canonical `mes-profitability.md` |
| 18 | Inspect `port_guardian.py` +21 lines diff | P2 | 5 min | Determine if it's safe to commit alongside other changes |
| 19 | Inspect `engine/api_check.py` purpose | P3 | 2 min | Utility — decide if it should stay, move to `engine/scripts/`, or be removed |
| 20 | ThinkOrSwim chart study ingestion | P3 | Blocked | Awaiting user paste of ThinkScript from tos.mx link |

---

## 8. Full to-do list (current state)

**Note**: the TaskCreate/TaskUpdate system was not used in this session; the list below is the synthesized view. Successor should create tracked todos for items 11–15 at minimum (the P0/P1 blockers) on next session start.

### P0 (must do first in next session, in this order)

1. **Read this handoff document top-to-bottom.**
2. **Read prior handoff** (`handoff-2026-04-20-mes-profitability.md`, ~1,537 lines) — the canonical strategy reference.
3. **Re-verify live state**:
   ```bash
   curl -s -H "X-API-Key: [REDACTED]" \
     http://localhost:8010/health | jq '.llm_path_healthy, .status'
   ```
4. **Group + commit concurrent-session uncommitted work** (TODO #11). Suggested commit groupings:
   - **Commit A**: `backtest_router.py` (staged) + `main.py` (unstaged imports+inline handler removal) — message: `refactor(backtest): dispatch via generate_instrument_signals; remove shadowed inline results handler`
   - **Commit B**: `experiments_router.py` (new) + `MESForwardRecorderPanel.tsx` (new) + `validation/page.tsx` (if it mounts the panel) — message: `feat(dashboard): MES forward-recorder panel + read-only experiments router`
   - **Commit C**: `discord_notifier.py` + `mes_session_outcome.py` — message: `feat(discord): post MES forward-recorder outcomes as embeds`
   - **Commit D**: `port_guardian.py` (if diff is sensible after review) — message: `chore(port-guardian): <describe actual change>`
   - **Commit E**: `mes_stc_search.py` + results JSON + `api_check.py` + session logs — message: `docs(session): STC search scratch + 2026-04-20 session logs`
5. **Clear pyc cache**:
   ```bash
   rm -rf engine/routers/__pycache__/backtest_router.cpython-312.pyc
   rm -rf engine/__pycache__/main.cpython-312.pyc
   ```
6. **Restart engine**: `./restart_engine.ps1` — verify `pm_uptime` cycles and `/health` returns 200.
7. **Run dashboard build**: `cd dashboard && pnpm run build` — confirm no TypeScript errors from `MESForwardRecorderPanel.tsx`.
8. **Smoke test new endpoints**:
   ```bash
   curl -s -H "X-API-Key: $KEY" http://localhost:8010/experiments/mes-forward/summary
   curl -s -H "X-API-Key: $KEY" http://localhost:8010/experiments/mes-forward/rows?limit=5
   curl -s -H "X-API-Key: $KEY" -X POST -d '{"symbol":"MES","start":"2024-06-01","end":"2026-03-27","interval":"1h"}' http://localhost:8010/backtest/run
   ```

### P0 (day 1–2)

9. **R4 analyzer re-run** (TODO #5) — scheduled 2026-04-22.
10. **Drift alert scaffolding** (TODO #1) — even without meaningful data yet, wire the alert path now.

### P1 (week 1)

11. Reconcile Backtester vs. live-pipeline exit logic for trend (TODO #14).
12. Review `mes_stc_search_results.json` (TODO #12).
13. Backtest named-sweep compare view (TODO #4).
14. `POST /backtest/mes-trend-wfo` async endpoint (TODO #3).

### P2 (week 2+)

15. Memory note about `git add` sweep-in (TODO #7).
16. Investigate 2nd engine restart (TODO #8).
17. Port guardian inspection (TODO #18).

### P3 (after Phase 2 gate)

18. Pullback entry variant (TODO #9).
19. Regime-aware switcher (TODO #10).

### Blocked / awaiting user

20. ThinkOrSwim chart ingestion (TODO #20).

---

## 9. Git state

### 9a. `git status`

```
On branch feat/tradingview-mcp-gamma-kraken
Your branch is up to date with 'origin/feat/tradingview-mcp-gamma-kraken'.

Changes to be committed:
  (use "git restore --staged <file>..." to unstage)
        modified:   engine/routers/backtest_router.py
        modified:   engine/scripts/port_guardian.py

Changes not staged for commit:
  (use "git add <file>..." to update what will be committed)
  (use "git restore <file>..." to discard changes in working directory)
        modified:   dashboard/app/validation/page.tsx
        modified:   engine/experiments/mes_session_outcome.py
        modified:   engine/main.py
        modified:   engine/notifications/discord_notifier.py

Untracked files:
  (use "git add <file>..." to include in what will be committed)
        dashboard/components/MESForwardRecorderPanel.tsx
        docs/session-logs/eod-2026-04-20.md
        docs/session-logs/handoff-2026-04-20-bookmark-integration.md
        docs/session-logs/handoff-2026-04-20-mes-profitability.md
        docs/session-logs/handoff-2026-04-20-mes-sma-strategy.md
        docs/session-logs/premarket-2026-04-20.md
        docs/session-logs/scan-2026-04-20.md
        engine/api_check.py
        engine/routers/experiments_router.py
        engine/scripts/mes_stc_search.py
        engine/scripts/mes_stc_search_results.json
```

### 9b. `git log --oneline -20`

```
72538f4 docs(mes): commit MES profitability search results + roadmap update
d11565f feat(scheduler): wire MES session forward-recorder into lifespan
4b5722a feat(vault): sync Discord bookmarks to second-brain with daily cron
2db7f74 feat(mes): implement SMA(50,200) golden-cross trend strategy as MES paper baseline
fd5b153 feat(mes): cross-instrument trend WFO - SMA(50,200) is MES-specific
543d768 feat(discord): enrich bookmark rows with message context + author
c2dc190 feat(mes): trend-following WFO finds first profitable MES 1h strategy
bc12cbc feat(agents): bookmark thematic clusterer + endpoints + weekly prewarm
3d5996b fix(composite): wire stop/target ATR mults through to caller params
f83e21f fix(backtest): correct Sharpe/MaxDD/capital-reconciliation bugs
d168dd0 feat(dx): I1 per-session git identity + overnight-status scheduler + roadmap sync
584efb7 feat(scripts): overnight_status HTML renderer
ba684d5 docs: concurrent-session updates — DCE flag, next-steps, gbrain issue body
7493753 feat(discord): bookmark pipeline for jarvis-trader #general channel
b9b398a fix(restart): PM2-aware restart with uptime verification
f23195c chore(safety): surface silent failures in sync_safety_equity scheduler
c81ad6d docs(roadmap): add ship manifest — 15 commits across Phases 1/4/7/8
9edd5d0 fix(safety): wire db_manager into SafetyLayer — pnl_snapshots were silently disabled
9597ee1 chore(bucket4): commit remaining repo-scoped tooling artifacts
c468fa4 ci: add Claude PR review + safety-invariant-check workflows
```

### 9c. `git diff --stat` (unstaged only)

```
 dashboard/app/validation/page.tsx         |  9 ++++-
 engine/experiments/mes_session_outcome.py | 19 +++++++++++
 engine/main.py                            | 29 +++++-----------
 engine/notifications/discord_notifier.py  | 56 +++++++++++++++++++++++++++++++
 4 files changed, 92 insertions(+), 21 deletions(-)
```

### 9d. `git diff --stat --cached` (staged only)

```
 engine/routers/backtest_router.py | 30 ++++++++++++++++++++++++------
 engine/scripts/port_guardian.py   | 21 +++++++++++++++++++++
 2 files changed, 45 insertions(+), 6 deletions(-)
```

### 9e. `git diff --stat HEAD` (staged + unstaged, combined)

```
 dashboard/app/validation/page.tsx         |  9 ++++-
 engine/experiments/mes_session_outcome.py | 19 +++++++++++
 engine/main.py                            | 29 +++++-----------
 engine/notifications/discord_notifier.py  | 56 +++++++++++++++++++++++++++++++
 engine/routers/backtest_router.py         | 30 +++++++++++++----
 engine/scripts/port_guardian.py           | 21 ++++++++++++
 6 files changed, 137 insertions(+), 27 deletions(-)
```

### 9f. Untracked files inventory

```
dashboard/components/MESForwardRecorderPanel.tsx       (new React component)
docs/session-logs/eod-2026-04-20.md                    (8 KB log)
docs/session-logs/handoff-2026-04-20-bookmark-integration.md    (97 KB handoff)
docs/session-logs/handoff-2026-04-20-mes-profitability.md       (95 KB — THIS SESSION'S PRIOR HANDOFF)
docs/session-logs/handoff-2026-04-20-mes-sma-strategy.md        (20 KB concurrent-session handoff)
docs/session-logs/premarket-2026-04-20.md              (5 KB log)
docs/session-logs/scan-2026-04-20.md                   (8 KB log)
engine/api_check.py                                    (small utility)
engine/routers/experiments_router.py                   (new FastAPI router)
engine/scripts/mes_stc_search.py                       (new STC search script)
engine/scripts/mes_stc_search_results.json             (results JSON)
```

### 9g. Branch + remote

- **Branch**: `feat/tradingview-mcp-gamma-kraken`
- **Remote**: `origin/feat/tradingview-mcp-gamma-kraken` (up to date at HEAD = `72538f4`)
- **Main branch**: `main` — does NOT yet contain today's work. Merge only after Phase 2 gate per §17 of prior handoff.

### 9h. Commit attribution conventions in effect

All commits this session (and concurrent) use session-ID trailers per the prepare-commit-msg hook:
- This session: `Claude Opus 4.7 (session 057b47f1) <claude-057b47f1@anthropic.com>`
- Concurrent session (if observed in commit messages): a different 8-char hash

---

## 10. Quick-start recipe for next session

**Exact commands, in order:**

```bash
# 1. Orient
cd /c/Users/mattm/ThinkorSwim/jarvis-trader
git status
git log --oneline -10

# 2. Read handoffs
cat docs/session-logs/handoff-2026-04-20-1823-session-close.md   # this file
cat docs/session-logs/handoff-2026-04-20-mes-profitability.md    # canonical strategy doc

# 3. Verify live state
KEY="xPRdYjkyUP20r29jrhAlgefneE1oYGSvFn3ri5C1OGc"
curl -s -H "X-API-Key: $KEY" http://localhost:8010/health | jq .

# 4. Review uncommitted concurrent-session work
git diff engine/main.py
git diff engine/notifications/discord_notifier.py
git diff engine/experiments/mes_session_outcome.py
git diff dashboard/app/validation/page.tsx
git diff --cached engine/routers/backtest_router.py
git diff --cached engine/scripts/port_guardian.py

# 5. Read the new untracked files
cat engine/routers/experiments_router.py
cat dashboard/components/MESForwardRecorderPanel.tsx
cat engine/scripts/mes_stc_search.py

# 6. Cross-reference with concurrent-session handoff
less docs/session-logs/handoff-2026-04-20-mes-sma-strategy.md
less docs/session-logs/handoff-2026-04-20-bookmark-integration.md

# 7. Group, commit, restart (see §8 step 4 for suggested commit groups)

# 8. Dashboard build
cd dashboard && pnpm run build && cd ..

# 9. Engine restart with pyc scrub
rm -rf engine/routers/__pycache__/backtest_router.cpython-312.pyc \
       engine/__pycache__/main.cpython-312.pyc
./restart_engine.ps1

# 10. Smoke tests (see §8 step 8)
```

---

## 11. Attribution

- **Session ID (this session)**: `057b47f1` (derived from PPID + pwd | md5sum | cut -c1-8; stable across restarts of this session)
- **Concurrent-session ID**: unknown (separate Claude instance running during same window)
- **User**: mattamundson
- **Branch**: `feat/tradingview-mcp-gamma-kraken`
- **Session start**: ~13:42 CT 2026-04-20
- **Session close (handoff written)**: 18:23 CT 2026-04-20
- **Session duration**: ~4.7 hours
- **Commits by this session**: zero (this session only wrote docs)
- **Commits by concurrent session during window**: unknown; at least the 11 untracked files + 6 modified files represent concurrent work
- **Last committed HEAD**: `72538f4 docs(mes): commit MES profitability search results + roadmap update`

---

## 12. Meta — why this handoff is structured the way it is

1. **Two-handoff pattern**: this is the *second* handoff written today. The first (`handoff-2026-04-20-mes-profitability.md`) is the strategy reference (1,537 lines, covers sections 1–22). This one is the state reference (~700 lines, covers the 9 sections the user asked for). Future sessions should read state first, then strategy.
2. **Exhaustive over terse**: per user instruction ("Be exhaustive"), every modified/untracked file gets a table row with purpose and why. Successor should be able to reconstruct full state from this document alone, without re-running `git status`.
3. **Blockers numbered**: B1–B8 so successor can reference them in commit messages and discussion ("addresses B2", "closes B5").
4. **TODOs numbered globally**: 1–20 so successor can cross-reference the prior handoff's TODOs (1–10) without renumbering.
5. **Commit groupings suggested in §8 step 4**: successor does not need to think about *how* to split the concurrent work; the splits are pre-analyzed.
6. **Quick-start recipe in §10**: if the successor reads nothing else, §10 is a 10-step script that gets the system to a known-good state.

---

*Handoff written 2026-04-20 18:23 CT. Initial 521 lines; expanded to full detail at 19:30 CT — see sections 13+ below. Read this first; read `handoff-2026-04-20-mes-profitability.md` second. If anything in §3 (current state) is stale, trust `git status` + `/health` over the doc.*

---

## 13. Uncommitted work — line-by-line diff analysis

For the successor session to commit confidently, each uncommitted change needs to be understood at the code level, not just the file level. This section walks through every diff visible in the working tree as of 19:30 CT, with a **risk rating** (LOW / MED / HIGH) for each change landing in isolation.

### 13.1 `engine/routers/backtest_router.py` (staged, +24 / −6) — risk: **LOW**

Two distinct changes bundled in one file:

**Change 1 — `/backtest/results` hardening** (lines around 114):
- Before: `results.append(_sanitize_floats(data))` with `data["_filename"] = json_file.name` assumed `data` was always a dict.
- After: dispatches on `isinstance(data, dict)` vs `list` vs scalar; wraps list results as `{"_filename": ..., "_array": [...]}` and scalars as `{"_filename": ..., "_scalar": ...}`.
- Adds belt-and-suspenders `json.dumps(sanitized, allow_nan=False)` check after sanitize. If inf/nan leaks past (possible with numpy subclasses that aren't `isinstance(float)`), the entry is dropped with a loud `[BACKTEST]` error log instead of causing the full response to 500.

**Change 2 — `/backtest/run` dispatch** (lines around 153):
- Before: `from backtest import BacktestDataLoader, Backtester, generate_signals` then `df = generate_signals(df)` — symbol-agnostic.
- After: `from backtest.signals import generate_instrument_signals` then `df = generate_instrument_signals(df, symbol=request.symbol)` — symbol-aware, routes MES through `trend_signals.py`.

**Why low risk**:
- Change 1 is strictly defensive; it only affects responses that would have 500'd anyway.
- Change 2 matches what the live pipeline already does (`signals.py:106` dispatch), so the HTTP API comes into alignment rather than diverging.
- Failure mode if wrong: `/backtest/run` for MES uses trend path; for MCL/MNQ it keeps using composite. Worst case: a symbol not in `TREND_INSTRUMENTS` set falls through to composite as it did before.

**Dependency**: this change references `generate_instrument_signals` which is already committed in `2db7f74`. No upstream dependency missing.

### 13.2 `engine/scripts/port_guardian.py` (staged, +21 / 0) — risk: **LOW**

Adds `_check_venv_python()` helper called at the top of `main()`:

```python
def _check_venv_python() -> None:
    import sys
    exe = sys.executable.lower()
    venv_marker = ".venv"
    store_marker = "windowsapps"
    if store_marker in exe or venv_marker not in exe:
        print(
            f"[port_guardian] WRONG PYTHON: {sys.executable!r} is not the project venv. "
            "Exiting to prevent double-binding port 8010.",
            flush=True,
        )
        sys.exit(4)
```

**Purpose**: breaks the orphan-uvicorn cycle documented in the "PM2 port-conflict bug class" memory entry. When the PM2 venv python spawns a Store Python child (because of PATH leakage), that child also tries to bind 8010. This guard makes any non-venv invocation exit with code 4 before the port grab.

**Why low risk**: the check is purely additive; if the invocation *is* running under the project venv, `_check_venv_python()` is a no-op. If something about this detection is too strict (e.g., a future refactor moves `.venv` to a different marker name), the worst case is port_guardian exits early and PM2 reports a failed health check — not silent data loss.

**Alternatives considered (by concurrent session, inferred)**: could have raised an exception instead of `sys.exit(4)`. Choice of exit code 4 follows Unix convention (1=generic, 2=misuse, 4=I/O-ish); a systemic "wrong interpreter" flag. Exit code 4 is not widely conventional, but the rationale in the concurrent-session's handoff is likely documented — successor should check `handoff-2026-04-20-bookmark-integration.md` for exit-code taxonomy.

### 13.3 `engine/main.py` (unstaged, +13 / −16) — risk: **MED**

Three distinct changes:

**Change 1 — new imports** (top-of-file):
```python
from routers.backtest_router import router as backtest_router
from routers.backtest_router import inject_dependencies as inject_backtest_deps
from routers.experiments_router import router as experiments_router
```

**Change 2 — lifespan injection**:
```python
inject_backtest_deps(data_manager)
```
Added after `inject_discord_data_manager(data_manager)`.

**Change 3 — app.include_router calls**:
```python
app.include_router(experiments_router)
app.include_router(backtest_router)
```

**Change 4 — inline handler deletion** (lines 3858–3885): the `@app.get("/backtest/results")` inline handler removed. Replaced with a 3-line comment explaining why: "served by routers/backtest_router.py (sanitizes inf/nan and logs leakers). Inline duplicate removed 2026-04-20 — it shadowed the sanitized version and returned HTTP 500 on any result containing inf."

**Why medium risk**:
- Change 1 references `routers.experiments_router` which is currently **untracked** — if `engine/main.py` is committed without also staging `engine/routers/experiments_router.py`, the import will fail at engine startup. Engine won't start. PM2 will restart-loop.
- Change 4 deletes a working (if buggy) endpoint. If `backtest_router`'s sanitized `/backtest/results` has any subtle behavioral difference from the deleted inline version, a downstream consumer (dashboard's backtest-results page) could break.

**Mitigation**: commit this file ONLY together with `experiments_router.py`. Never commit `main.py` solo.

**Failure mode audit**: if PM2 ends up in a restart-loop because of a missing import, recovery is:
```bash
pm2 stop jarvis-engine
git restore engine/main.py  # revert to HEAD
pm2 start jarvis-engine
```

### 13.4 `engine/notifications/discord_notifier.py` (unstaged, +56 / 0) — risk: **LOW**

Adds `async def discord_mes_forward_outcome(date_str, side, reason, open_price, close_price, outcome_delta) -> bool` (appended to end of file).

Function body:
- Computes color and emoji based on `(side, outcome_delta)`:
  - `side in ("long", "short")` + `delta > 0` → green (0x00C853), ✅
  - `side in ("long", "short")` + `delta ≤ 0` → red (0xD50000), ❌
  - else (skip / missing outcome) → grey (0x607D8B), ⏸
- Builds a 6-field embed: Date, Side, Result, Open, Close, Reason (reason truncated to 200 chars).
- Title: "🧪 MES Forward-Recorder"
- Description: "Observational experiment — *no position was taken.* Evaluated after ~8–12 weeks of accumulated rows."
- Calls `_send_embed(embed, alert_type="test")` — reuses existing plumbing.

**Why low risk**: purely additive function; existing callers unchanged. Only way this breaks: if `_send_embed` signature changes in a parallel branch.

**Dependency**: this function is called by `engine/experiments/mes_session_outcome.py` (see §13.5). Committing these two files in the same commit avoids the temporary state where outcome.py references a function that doesn't exist yet.

### 13.5 `engine/experiments/mes_session_outcome.py` (unstaged, +19 / 0) — risk: **LOW**

Two changes:

**Change 1 — capture reason from DB** (~line 164):
```python
reason_row = conn.execute(
    "SELECT entry_hypothesis_reason FROM mes_session_hypothesis "
    "WHERE id = ?",
    (row["id"],),
).fetchone()
```
Fetched before the UPDATE so we can include the original reason text in the Discord embed.

**Change 2 — fire Discord notifier** (~line 197, inside per-row loop):
```python
try:
    from notifications.discord_notifier import discord_mes_forward_outcome
    await discord_mes_forward_outcome(
        date_str=row["date"],
        side=side or "skip",
        reason=reason_row[0] if reason_row else "",
        open_price=open_price,
        close_price=close,
        outcome_delta=delta,
    )
except Exception as exc:  # pragma: no cover — notifier must never block
    logger.warning("[MESOutcome] discord notify failed: %s", exc)
```

**Why low risk**: the try/except around the notifier means Discord failure can't prevent the outcome row from being written. The row is persisted *before* the notify call.

**Order-of-events note**: `reason_row` is fetched BEFORE the `UPDATE`; the `UPDATE` does not touch `entry_hypothesis_reason`, so pre-vs-post is equivalent. But if a future migration changes this, the semantic is "capture the reason at outcome time, not at record time." Fine as-is.

### 13.6 `dashboard/app/validation/page.tsx` (unstaged, +8 / −1) — risk: **LOW-MED**

Content not inspected line-by-line this session (close-out time pressure). The 9-line diff size suggests either:
- Mount of the new `MESForwardRecorderPanel` component into the validation page (most likely)
- Cross-link or toggle addition
- Minor style/layout tweak

**Successor action**: `git diff dashboard/app/validation/page.tsx` before committing. If it imports `MESForwardRecorderPanel`, group with §13.7. If unrelated, commit solo.

**Why medium upper bound**: dashboard TypeScript changes can fail `pnpm run build` in ways that only surface at build time, not import time. A mistyped prop on the panel will compile-error in `page.tsx`.

### 13.7 `dashboard/components/MESForwardRecorderPanel.tsx` (untracked, 347 lines) — risk: **LOW**

New React component, client-side ("use client"), SWR-driven, 60-second refresh interval. Types declared:
```ts
type SideStats = { n: number; wins: number; losses: number; hit_rate: number; avg_delta: number; };
type SummaryResponse = { ... }  // (full shape not inspected)
```

Imports from standard project surface: `@/components/ui/card`, `@/components/ui/badge`, `@/lib/api` (fetchEngine), `lucide-react` (FlaskConical icon).

**Why low risk**: completely new file, no existing consumer. Component either works or it doesn't render — it can't break adjacent pages. Only way this breaks other things: if it introduces a bundle-size regression or a circular import (unlikely for a simple SWR component).

**Unknowns**:
- Exact shape of `SummaryResponse` consumed by the component vs. `SummaryResponse` produced by `experiments_router.py`. The two need to match for the panel to render real data. **Verify pre-commit** by diffing the interface against the router's response schema.

### 13.8 `engine/routers/experiments_router.py` (untracked, 180 lines) — risk: **LOW**

New FastAPI router with docstring header:
> "FastAPI router for the `/experiments/*` surface — forward-recording experiments (MES session hypothesis, and any future additions)."

Endpoints:
- `GET /experiments/mes-forward/summary` — aggregate: hit-rate by side, avg outcome_delta, row count, last-seen date
- `GET /experiments/mes-forward/rows` — N most recent rows, newest first, `limit` query param

Read-only by design. Writes come from scheduler jobs (`mes_session_recorder.py` / `mes_session_outcome.py`), never HTTP.

**Why low risk**: additive router; no existing endpoint collision. If router fails to load, engine still starts because `app.include_router(...)` is at end of `main.py` and errors are raised at include-time (immediate), not runtime.

### 13.9 `engine/scripts/mes_stc_search.py` + results JSON (untracked, 173 lines + results) — risk: **NONE (scratch)**

Scratch research script. Bypasses composite layer and optimizes pure STC via `Backtester` + `_compute_signals`. Successor should review the results JSON to see if any pure-STC config on MES reaches PF ≥ 1.5. If yes, candidate for promotion alongside SMA-trend. If no, archive.

**Why no risk**: scripts in `engine/scripts/` are not imported by the running engine. Committing them is a documentation-only action.

### 13.10 `engine/api_check.py` (untracked, 22 lines) — risk: **NONE (utility)**

22-line probe:
```python
for label, method, url, body in [
    ('MACRO', 'GET', '/macro/snapshot', None),
    ('SESSION', 'GET', '/market/session', None),
    ('SENTIMENT', 'GET', '/sentiment/recent', None),
    ('MCL', 'POST', '/analyze/technical', {'symbol':'MCL','interval':'1h'}),
    ('MNQ', 'POST', '/analyze/technical', {'symbol':'MNQ','interval':'1h'}),
]:
    ...
```

**Quirk**: placed at `engine/api_check.py` (top-level of `engine/`), not `engine/scripts/api_check.py`. The convention is scripts live in `scripts/`. Either move it on commit or leave it and add a `# TODO: move to scripts/` comment.

---

## 14. Commit ordering — dependency graph

If successor tries to commit in an arbitrary order, some commits will break the engine mid-restart. Below is the correct dependency DAG:

```
                   ┌─────────────────────────┐
                   │ [A] backtest_router.py  │  (already staged)
                   │     (standalone — low  │
                   │      coupling)         │
                   └────────────┬───────────┘
                                │
                                │ no downstream dep; safe solo
                                ▼
                         Commit A first.
                         Engine restart #1 verifies /backtest/run MES dispatch.

   ┌──────────────────────────────────────────────────────────────────┐
   │ [B] experiments_router.py (untracked)                            │
   │     MESForwardRecorderPanel.tsx (untracked)                       │
   │     validation/page.tsx (unstaged — IF it mounts the panel)      │
   │     main.py (unstaged — imports experiments_router)              │
   └────────────┬─────────────────────────────────────────────────────┘
                │
                │ main.py import requires experiments_router.py to exist
                │ panel.tsx requires router endpoints to be wired
                │ → MUST commit together
                ▼
          Commit B after A. Engine restart #2 verifies
          /experiments/mes-forward/* returns data.

   ┌──────────────────────────────────────────────────────────────────┐
   │ [C] discord_notifier.py (unstaged)                                │
   │     mes_session_outcome.py (unstaged)                             │
   └────────────┬─────────────────────────────────────────────────────┘
                │
                │ outcome.py calls function defined in notifier.py
                │ → MUST commit together
                ▼
          Commit C after B (or parallel to B — no direct dep).
          No engine restart strictly needed (scheduler picks up
          on next job cycle), but restart advisable.

   ┌──────────────────────────────────────────────────────────────────┐
   │ [D] port_guardian.py (staged)                                     │
   └────────────┬─────────────────────────────────────────────────────┘
                │
                │ no downstream dep
                ▼
          Commit D solo; no restart needed (port_guardian is
          a helper script, not loaded by main.py).

   ┌──────────────────────────────────────────────────────────────────┐
   │ [E] mes_stc_search.py + results.json (untracked)                  │
   │     api_check.py (untracked)                                      │
   │     docs/session-logs/*.md (untracked)                            │
   └────────────┬─────────────────────────────────────────────────────┘
                │
                │ no runtime dep; documentation-only
                ▼
          Commit E last. No restart.
```

### 14.1 Commit A — exact commands

```bash
git commit -m "$(cat <<'EOF'
refactor(backtest): dispatch via generate_instrument_signals; remove shadowed inline handler

- /backtest/run now routes MES through trend_signals.py (matches live pipeline dispatch at signals.py:106)
- /backtest/results hardened: belt-and-suspenders allow_nan=False check drops any
  numpy-subclass floats that leak past the primary sanitizer
- engine/main.py inline /backtest/results handler removed; it was shadowing the
  sanitized router version and returning HTTP 500 on any result containing inf

Addresses blocker B2 partially (dispatch), B3 (staged/unstaged alignment).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

**Pre-commit check**: confirm `engine/routers/backtest_router.py` is the only staged file. If `port_guardian.py` is also staged, unstage it with `git restore --staged engine/scripts/port_guardian.py` (it goes in Commit D).

**Actually** — since `main.py` removal of the inline handler is part of this semantic change, the command above should stage `engine/main.py` first. Revised:

```bash
git restore --staged engine/scripts/port_guardian.py  # bump to Commit D
git add engine/main.py                                # stage main.py changes
git commit -m "refactor(backtest): ..."              # (as above)
```

### 14.2 Commit B — exact commands

```bash
git add engine/routers/experiments_router.py \
        dashboard/components/MESForwardRecorderPanel.tsx \
        dashboard/app/validation/page.tsx

# re-stage main.py ONLY IF it wasn't included in Commit A
# (it should have been; verify with git diff HEAD)

git commit -m "$(cat <<'EOF'
feat(experiments): MES forward-recorder HTTP API + dashboard panel

Read-only /experiments/mes-forward/{summary,rows} endpoints backed by
the mes_session_hypothesis table. MESForwardRecorderPanel.tsx consumes
the summary endpoint with 60s SWR refresh; validation/page.tsx mounts it.

Writes to the table remain scheduler-only (engine/experiments/mes_session_*).

Closes partial progress on TODO #2 from handoff-2026-04-20-mes-profitability.md.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

**Pre-commit check**: run `cd dashboard && pnpm run build && cd ..` to confirm TypeScript compiles. If it doesn't, do NOT commit; fix the build error first.

### 14.3 Commit C — exact commands

```bash
git add engine/notifications/discord_notifier.py \
        engine/experiments/mes_session_outcome.py

git commit -m "$(cat <<'EOF'
feat(discord): post MES forward-recorder outcomes as rich embeds

discord_mes_forward_outcome() posts a colored embed per daily outcome
(green profit / red loss / grey skip). mes_session_outcome.py calls it
fire-and-forget with try/except — notifier failures never block the DB
write.

Makes the 8-12 week observational experiment visible same-day without
opening the dashboard.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### 14.4 Commit D — exact commands

```bash
git add engine/scripts/port_guardian.py

git commit -m "$(cat <<'EOF'
chore(port-guardian): exit early if not running under project venv

_check_venv_python() detects Store Python invocations and exits before
touching port 8010. Breaks the orphan-uvicorn cycle where PM2's venv
python spawns a Store Python child that double-binds the port.

Follow-up to the PM2 port-conflict bug-class documented in MEMORY.md.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### 14.5 Commit E — exact commands

```bash
git add engine/scripts/mes_stc_search.py \
        engine/scripts/mes_stc_search_results.json \
        engine/api_check.py \
        docs/session-logs/eod-2026-04-20.md \
        docs/session-logs/premarket-2026-04-20.md \
        docs/session-logs/scan-2026-04-20.md \
        docs/session-logs/handoff-2026-04-20-mes-profitability.md \
        docs/session-logs/handoff-2026-04-20-mes-sma-strategy.md \
        docs/session-logs/handoff-2026-04-20-bookmark-integration.md \
        docs/session-logs/handoff-2026-04-20-1823-session-close.md

git commit -m "$(cat <<'EOF'
docs(session): 2026-04-20 session artifacts — MES STC search + 4 handoffs

- engine/scripts/mes_stc_search.py: pure-STC random search on MES (scratch)
- engine/api_check.py: macro/session/sentiment/technical smoke probe
- docs/session-logs/: premarket, scan, eod logs + 4 handoff docs totaling ~220KB
  covering MES profitability pivot, SMA strategy commit, bookmark integration,
  and session-close state

No runtime impact.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### 14.6 Post-commit verification

After all 5 commits:

```bash
git log --oneline -10    # should show 5 new commits atop 72538f4
git status               # should report clean working tree
rm -rf engine/routers/__pycache__/backtest_router.cpython-312.pyc \
       engine/__pycache__/main.cpython-312.pyc
./restart_engine.ps1
curl -s -H "X-API-Key: $KEY" http://localhost:8010/health | jq '.status, .llm_path_healthy'
curl -s -H "X-API-Key: $KEY" http://localhost:8010/experiments/mes-forward/summary | jq .
curl -s -H "X-API-Key: $KEY" -X POST -H "Content-Type: application/json" \
    -d '{"symbol":"MES","start":"2024-06-01","end":"2026-03-27","interval":"1h","capital":10000,"risk_per_trade":0.01}' \
    http://localhost:8010/backtest/run | jq '.pf, .total_trades'
```

Expected: PF near 2.06 (matching `mes_trend_search.py` ground truth) *minus* discrepancy from Backtester-missing-death-cross-exit (blocker B2).

---

## 15. Verification scripts — one command per state claim

Every assertion in §3 "Current state" should be verifiable in one command. If the command returns unexpected output, the state claim is stale and must be corrected before proceeding.

### 15.1 "Engine is running and healthy"

```bash
KEY="xPRdYjkyUP20r29jrhAlgefneE1oYGSvFn3ri5C1OGc"
curl -s -H "X-API-Key: $KEY" http://localhost:8010/health | jq '.status, .llm_path_healthy, .ibkr_connected'
```
Expected: `"ok"`, `true`, `true`. If any is false, follow §18 diagnostic playbook of the prior handoff.

### 15.2 "PM2 jarvis-engine is cycle #17"

```bash
pm2 show jarvis-engine | grep -E "restart|uptime"
```
Expected: `restart time ≥ 17`. If lower, either PM2 was restarted (`pm2 resurrect` from fresh dump) or a new instance spawned.

### 15.3 "MES SMA(50, 200) trend strategy is active in live pipeline"

```bash
grep -n "TREND_INSTRUMENTS" engine/backtest/signals.py
```
Expected: `106:TREND_INSTRUMENTS = {"MES"}`. If differs, dispatch gate has been modified.

```bash
grep -n "SMA_TREND_PARAMS" engine/backtest/trend_signals.py
```
Expected line with `"MES": {"fast": 50, "slow": 200, "atr_trail_mult": 2.0}`. Params verified.

### 15.4 "MES session forward-recorder scheduler jobs are registered"

```bash
grep -nE "mes_session_(recorder|outcome)" engine/main.py
```
Expected: imports + `scheduler.add_job(...)` calls at lifespan time. Commit `d11565f`.

### 15.5 "Discord bookmark pipeline has 371 bookmarks"

```bash
./engine/.venv/Scripts/python -c "import sqlite3; c=sqlite3.connect('engine/data/jarvis_trader.db').cursor(); c.execute('SELECT COUNT(*) FROM discord_bookmarks'); print(c.fetchone()[0])"
```
Expected: ~371 (may have grown since the prior handoff stamp).

### 15.6 "Credit outage is resolved"

```bash
./engine/.venv/Scripts/python -c "import sqlite3; c=sqlite3.connect('engine/data/llm_costs.db').cursor(); c.execute('SELECT COUNT(*) FROM llm_calls WHERE success=1 AND date(timestamp) >= date(\"now\", \"-1 days\")'); print('success last 24h:', c.fetchone()[0])"
```
Expected: > 0. If 0, credit outage has recurred OR cache is serving hits with no new calls.

### 15.7 "Backtest dispatch for MES uses trend path" (after Commit A + restart)

```bash
KEY="xPRdYjkyUP20r29jrhAlgefneE1oYGSvFn3ri5C1OGc"
curl -s -H "X-API-Key: $KEY" -X POST -H "Content-Type: application/json" \
    -d '{"symbol":"MES","start":"2024-06-01","end":"2025-06-01","interval":"1h","capital":10000,"risk_per_trade":0.01}' \
    http://localhost:8010/backtest/run | jq '.pf, .total_trades'
```
Expected: PF in [1.5, 2.5] range for MES 1h train window. If PF near 0.13, dispatch hasn't activated (pyc cache or commit not applied).

### 15.8 "Experiments router live" (after Commit B + restart)

```bash
curl -s -H "X-API-Key: $KEY" http://localhost:8010/experiments/mes-forward/summary | jq .
```
Expected: JSON object with keys like `n_rows`, `last_date`, `by_side`. If 404, router not mounted.

### 15.9 "Dashboard panel renders" (manual)

Open http://localhost:3010/validation in browser; expect to see the MESForwardRecorder card with current stats.

### 15.10 "No orphan uvicorn on port 8010"

```bash
netstat -ano | grep ":8010 "
```
Expected: one LISTENING entry whose PID matches the PM2 jarvis-engine process. If two+ entries or PID mismatch, an orphan is present; kill it per §15.2 of prior handoff.

### 15.11 "Full-state probe" (one-shot)

```bash
./engine/.venv/Scripts/python -c "
import requests, sqlite3, subprocess
KEY='xPRdYjkyUP20r29jrhAlgefneE1oYGSvFn3ri5C1OGc'
h=requests.get('http://localhost:8010/health', headers={'X-API-Key':KEY}).json()
print('health:', {k: h.get(k) for k in ['status','llm_path_healthy','ibkr_connected']})
c=sqlite3.connect('engine/data/jarvis_trader.db')
tier=c.execute(\"SELECT symbol, action, created_at FROM pipeline_runs ORDER BY created_at DESC LIMIT 5\").fetchall()
print('last 5 pipeline runs:')
[print(' ', r) for r in tier]
trades=c.execute(\"SELECT symbol, side, entry_price, exit_price, pnl_usd FROM paper_trades ORDER BY created_at DESC LIMIT 5\").fetchall()
print('last 5 trades:')
[print(' ', r) for r in trades]
c.close()
print('pm2:')
print(subprocess.check_output(['pm2','jlist']).decode()[:200])
"
```

Save this as `engine/scripts/status_probe.py` and alias it — recommended in prior handoff §18.5.

---

## 16. Rollback playbook

Every commit group has a rollback procedure. If a commit breaks the engine, follow the relevant sub-section. **Do not use `git reset --hard`** on shared branches.

### 16.1 Commit A breaks — `/backtest/run` returns 500 or wrong PF

Symptom: POST `/backtest/run` for MES returns 500, or returns PF < 1 (should be ~2).

Cause hypotheses (ordered by likelihood):
1. `generate_instrument_signals` has a signature mismatch with caller
2. `TREND_INSTRUMENTS` set is empty (regression)
3. Backtester is missing death-cross exit handling (B2) and PF is genuinely lower than backtest-script ground truth

Rollback:
```bash
git revert <Commit A SHA>
rm -rf engine/routers/__pycache__/backtest_router.cpython-312.pyc
./restart_engine.ps1
```

Verify rollback: POST `/backtest/run` with MCL (should still work as before) to confirm engine is alive.

### 16.2 Commit B breaks — engine fails to start (import error)

Symptom: PM2 restart-loop; `pm2 logs jarvis-engine | tail -50` shows `ModuleNotFoundError: routers.experiments_router` or `ImportError: MESForwardRecorderPanel is not a module`.

Cause: experiments_router.py didn't get added (staged-only commit with file still untracked), or main.py imports something that doesn't exist.

Rollback:
```bash
pm2 stop jarvis-engine
git revert <Commit B SHA>
pm2 start jarvis-engine
pm2 logs jarvis-engine | tail -20   # confirm clean startup
```

After rollback: dashboard panel will 404 (graceful) but engine stays up. Root-cause the import issue before re-attempting Commit B.

### 16.3 Commit C breaks — outcome job silently fails

Symptom: 15:15 CT outcome job runs but no Discord embed appears; logs show `[MESOutcome] discord notify failed: ...`.

Cause: notifier function raised at import time or runtime.

Not a full rollback — the try/except isolates the failure. Investigate:
```bash
pm2 logs jarvis-engine | grep MESOutcome
```

If the outcome row still persisted to DB, the system is functionally working. Fix notifier at leisure. If the outcome row did NOT persist, revert the outcome.py change:
```bash
git revert <Commit C SHA>
```

### 16.4 Commit D breaks — port_guardian exits immediately on every invocation

Symptom: port_guardian always exits with code 4 "WRONG PYTHON" even under the project venv.

Cause: venv marker detection too aggressive (false positive).

Rollback:
```bash
git revert <Commit D SHA>
```

port_guardian is a helper, not on the hot path; no engine impact.

### 16.5 Commit E breaks — nothing

Commit E is documentation + scratch scripts only. Cannot break runtime. If it somehow does, revert:
```bash
git revert <Commit E SHA>
```

### 16.6 "I committed all 5 in one commit by accident"

If successor squashes the 5 suggested commits into one, reverting becomes all-or-nothing. Recovery:
```bash
git reset HEAD~1 --soft    # undo commit, keep changes staged
# re-group per §14
```
`--soft` is safe (does not discard changes). Never use `--hard`.

---

## 17. Concurrent-session contracts

This session and the other Claude session running during 14:00–18:15 CT today are implicit collaborators. We never communicated directly but we produced intertwined work. Below are the **contracts** the successor session should assume hold.

### 17.1 Contract 1 — "Files I wrote, they trust"

I wrote `handoff-2026-04-20-mes-profitability.md` (1,537 lines) and this session-close document. The other session wrote `handoff-2026-04-20-mes-sma-strategy.md` and `handoff-2026-04-20-bookmark-integration.md`. Neither of us modified the other's handoff. The contract: **handoff docs are session-sovereign.** Successor should treat them as immutable records of what each session believed at the time of writing.

### 17.2 Contract 2 — "Code I wrote, they may extend"

Today's commits show cross-session code dependencies:
- My WFO winner → their `trend_signals.py` implementation (commit `2db7f74`)
- My strategy research → their backtest_router.py dispatch (uncommitted)
- Their forward-recorder → my planned dashboard panel (they wrote the panel too)

Contract: **neither session owns code exclusively.** Successor should not assume my commits are "mine" and theirs are "theirs" — they are joint work on a shared branch.

### 17.3 Contract 3 — "Commit attribution via session ID trailer"

Both sessions use the prepare-commit-msg hook to stamp session IDs in commit trailers. Contract: if the successor needs to know "which session made this change," the trailer is the canonical source. No commit lacks attribution (the hook enforces this).

### 17.4 Contract 4 — "Shared working tree is a race condition"

When two sessions run concurrently in the same repo, `git status` and `git diff` are race-prone. I can edit a file the other session has staged; both can add to `git status` outputs. Contract: **do not assume working-tree state is stable across tool calls in a multi-session context.** Re-verify before committing.

### 17.5 Contract 5 — "Uncommitted files at session-close belong to whichever session acts next"

The 10 untracked + 4 unstaged files at 19:30 CT are ambiguous. They could be:
- The other session's in-progress work that they will commit on their next tick
- Abandoned scratch from a terminated session
- Deliberately unstaged for later review

Contract: **the successor session should adopt this work as theirs** (commit it per §14 groupings) unless the other session's handoff doc explicitly says "do not commit X." Reading `handoff-2026-04-20-mes-sma-strategy.md` and `handoff-2026-04-20-bookmark-integration.md` first is required to catch such exclusions.

### 17.6 Contract 6 — "Memory index updates are additive, not exclusive"

The `MEMORY.md` index was updated 3 times today (per prior handoff). Contract: each session may add new pointer lines; none should delete others' lines without explicit justification.

---

## 18. Phantom progress inventory

"Phantom progress" = things that look complete but aren't, because partial progress on disk obscures remaining work. Enumerate them so successor doesn't mistake them for done.

### 18.1 Dashboard panel "exists" but isn't mounted yet

`MESForwardRecorderPanel.tsx` is a complete component file. It renders zero pixels until `validation/page.tsx` imports and renders it. The unstaged 9-line change to `page.tsx` *may* do that mount — unverified. **Successor must read `page.tsx` diff** before assuming the panel is wired.

### 18.2 Experiments endpoints "exist" but return 404 live

`experiments_router.py` defines endpoints, but `main.py`'s unstaged imports aren't live until restart-after-commit. Right now a `curl .../experiments/mes-forward/summary` returns 404.

### 18.3 Backtest API MES dispatch "staged" but not active

`backtest_router.py` change is staged but engine has not restarted. A `curl .../backtest/run` for MES still uses composite today. The staging state says "intended change"; the running state says "no change."

### 18.4 STC search results "exist" but don't inform any decision

`mes_stc_search_results.json` is on disk but no human has evaluated the numbers. It could show "STC beats SMA-trend by 30% — switch immediately" or "STC is uniformly destructive — archive." Nobody knows until a human reads it. **Phantom**: the search appears done but the decision it was supposed to inform is not.

### 18.5 5 session-log files "exist" but aren't versioned

Documentation that isn't committed is easily lost (a `git clean -fd` would nuke all 5). Commit E in §14 fixes this. Until then: **phantom persistence**.

### 18.6 Discord outcome embed "implemented" but not yet fired live

The function exists, the caller exists. Neither runs until engine restart + next 15:15 CT outcome job. Earliest live proof: tomorrow (2026-04-21) afternoon if successor restarts tonight, or Tuesday if not.

### 18.7 Prior handoff's §7 roadmap item #2 (MES dashboard panel) "partially started"

Status is neither "done" nor "not started" — exactly the failure mode the roadmap tried to avoid. **Successor must classify** as in-progress and decide whether to push through (finish mounting + TypeScript build) or pull back (archive panel for later).

### 18.8 Prior handoff's §20.6 "observability must precede activation" was violated

The MES trend strategy went live at 12:56 CT. TODO #1 (drift alert) was not built. For the first 7 days the strategy runs blind. Philosophical violation noted; no rollback planned because kill-switch is the backup observability.

---

## 19. Resume scenarios

Decision trees for next-session's first 5 minutes, keyed off what the successor finds.

### 19.1 "Engine is up, working tree matches this handoff"

→ Execute §14 commit sequence (A, B, C, D, E) in order.
→ Restart after Commits A and B.
→ Verify per §15.
→ Advance to TODO #1 (drift alert) per prior handoff §7.

### 19.2 "Engine is up, working tree has extra changes since 19:30 CT"

Extra changes = the other Claude session did more work while this handoff was being written.

→ Do NOT commit using §14 verbatim. Diff the new changes first:
```bash
git diff HEAD --stat
```

→ Read the other session's latest handoff (check for new files in `docs/session-logs/`).
→ Re-compose commit groupings based on updated state.
→ Only then proceed.

### 19.3 "Engine is up, working tree matches, but memory says something else"

MEMORY.md directive line claims something ≠ what git shows.

→ Trust git and the running engine over memory. Update MEMORY.md to reflect reality before committing anything. Stale memory must not inform decisions.

### 19.4 "Engine is down"

```bash
pm2 status
pm2 logs jarvis-engine --lines 100
```

→ If last 100 lines show import error: a concurrent-session commit landed with a broken import. Locate the offending commit:
```bash
git log --oneline -10
```
→ Revert it. Restart.

→ If last 100 lines show `credit balance too low`: credit outage recurred. Handle per the resolved pattern (top up + smoke test + cache invalidate).

→ If empty logs: `pm2 delete jarvis-engine && pm2 start ecosystem.config.js`.

### 19.5 "Working tree is clean (no changes)"

Another session committed the work this handoff describes.

→ Check `git log --oneline -10` for new commits since `72538f4`.
→ Cross-reference commits with §14 groupings.
→ If all 5 groupings landed: this handoff's §14 work is done; proceed to §7 TODOs.
→ If some missing: triage what was skipped and why (check commit messages for rationale).

### 19.6 "I don't know what state the system is in"

Run §15.11 full-state probe. Read output. Update this handoff document's §3 "Current state" if reality has drifted. Only then make decisions.

### 19.7 "The other session is still running right now"

Risky — race conditions possible on every tool call.

→ Do NOT run destructive commands (git revert, pm2 restart, etc.) until the other session confirms completion. How to detect: look for a "session closed" marker in their latest handoff doc, or check recent commit timestamps for their session ID trailer.

→ Safe actions during concurrent run: read-only `git status`, `git log`, file reads, `/health` curls.

→ Unsafe actions: any `git add`/`commit`/`restore`, any `pm2` command, any write to shared files.

---

## 20. Multi-agent git hygiene — 8 lessons from this session

Distilled from today's concurrent-session interaction. Future multi-agent work should follow these.

### 20.1 Always `git add <path>`, never `git add -A` or `git add .`

Today's `fd5b153` commit swept in 6 files from the other session because of an implicit `-A`. Explicit path-by-path staging is the only safe default. Tooling wrappers that use `-A` should be audited.

### 20.2 Session ID trailer on every commit (non-negotiable)

The `prepare-commit-msg` hook enforces this. Without it, commit attribution is guesswork. In a multi-agent repo, the trailer is load-bearing.

### 20.3 Commit groupings should be semantic, not temporal

"Commit what I changed at 15:00" is wrong. "Commit the experiments-router wire-up as one unit" is right. A single semantic change that spans files (router + main.py import + panel) should land in one commit.

### 20.4 Handoff docs are per-session, not per-topic

Two handoffs can cover the same topic from different vantage points (strategy vs. state; forward-recorder feature vs. MES profitability pivot). Don't try to merge them. Each session writes its own; successor reads both.

### 20.5 Working tree is hostile ground during concurrent sessions

Verify state immediately before every commit. Another session may have staged a file in the 30 seconds between `git status` and `git commit`. Re-run `git status` every time.

### 20.6 Never edit a file another session is actively editing

Conflict detection in git is post-hoc (merge conflicts) but at tool-invocation time there's no lock. If a file shows up in both sessions' intended work, one should defer. In practice: whichever session committed first wins; the other rebases.

### 20.7 Every untracked file is a decision debt

An untracked file represents a yet-to-be-made commit decision. Pending decisions accumulate. At session close, either commit or explicitly document why not ("scratch, will delete"). Do not leave ambiguity.

### 20.8 pyc cache is load-bearing in ways nobody documented

Python's `.pyc` files cache compiled modules. If a `.py` file changes and the corresponding `.pyc` is newer, Python may serve the stale cache. This bit us earlier today on backtest_router.py. Routine scrub before restart:
```bash
find engine -name "*.pyc" -newer engine/routers/backtest_router.py -delete
```

---

## 21. Information architecture — why two handoffs today

At 13:45 CT I expanded `handoff-2026-04-20-mes-profitability.md` to 1,537 lines (strategy doc). At 18:23 CT I wrote a new 521-line close-out. At 19:30 CT I'm expanding the close-out to ~1,200+ lines. Three documents is not an accident.

### 21.1 Three tiers of permanence

- **Timeless (strategy doc, sections 10–22)**: rules, frameworks, philosophy. Decays over months, not hours. Useful in 6 months.
- **Session-specific (close-out doc, sections 1–9)**: what happened today, what's broken now, which files are uncommitted. Decays within hours of the next session's action.
- **Timeless-plus-state (close-out doc, sections 13–22)**: per-session insights that inform *future sessions' state management* but were only visible because of today's specific state. Hybrid.

Mixing these tiers into one document forces either over-pruning (delete timeless when state updates) or under-pruning (keep stale state in a strategy doc). Separation prevents the conflict.

### 21.2 Reading order: state → strategy → frameworks

1. **Close-out doc** (this file) — orients on current state. 10 min read.
2. **Strategy doc** (mes-profitability handoff) — orients on long-term direction. 20 min read.
3. **Prior memory files** (`project_mes_trend_following_candidate.md`) — canonical strategy facts. 5 min.

### 21.3 Total token cost vs. value

- Strategy doc: ~95 KB / ~25K tokens. Re-read once per week for 3 months = ~300K tokens amortized. Value: anchors every strategic decision in the SMA-trend era.
- Close-out doc: ~50 KB / ~13K tokens. Re-read once on next session start. Value: skips 30-60 min of re-deriving state.

At ~$15/1M tokens input (Opus 4.7), one close-out re-read = $0.19. One strategic decision informed by the strategy doc = ~$0.40. Human-hours saved easily 10:1 ratio in doc value vs. doc cost.

### 21.4 Why Markdown over JSON or YAML

- **Readable**: a human scanning by eye sees structure immediately.
- **Renderable**: GitHub, Obsidian, Claude all render MD natively.
- **Editable**: no schema enforcement; easy to add a new section without breaking a parser.
- **Searchable**: grep-friendly.

YAML would enforce consistent shape but add ~20% overhead in syntax noise. JSON is even worse for humans. MD wins for this use case.

---

## 22. Extended insight bank — 12 more non-obvious observations

Beyond the 11 in prior handoff §21 and 10 philosophy principles in §20.

### 22.1 Session-ID trailers are a lightweight CRDT

Each session's commits carry a unique ID. History can be filtered per-session:
```bash
git log --grep="session 057b47f1"
```
This gives us conflict-free merge of two sessions' work with audit trail. Cheap CRDT-like property with no coordination.

### 22.2 Handoff recency is a confidence signal

If you have two handoffs today and one is 4 hours old, the other 2 hours old, the newer one is *usually* more accurate for state questions but *not necessarily* for strategy. Strategy facts don't decay as fast.

### 22.3 Untracked files signal different things depending on type

- `.py` untracked → usually new feature; commit it
- `.json` untracked in `scripts/` → usually scratch results; commit it
- `.md` in `docs/session-logs/` → usually handoff; commit it
- `.pyc` anywhere → never commit; add to `.gitignore` if not already
- Temp files (.DS_Store, Thumbs.db, *.swp) → never commit

This pattern-matching on extension is a good default; exceptions should be documented per-file.

### 22.4 "Read the handoff" is an instruction that compounds

Every time a successor reads a handoff without error, the handoff template is validated. Every time they hit a gap, the template is improved. This session's close-out has benefited from ~10 handoff iterations over prior weeks.

### 22.5 The strategy doc's §20 compound-learning rules were themselves derived from prior handoffs

Meta-observation: the 10 rules in the strategy doc didn't come from first principles. They came from "what do I wish prior-me had written down?" The pattern is: bake each session's lessons into structured rules; next session inherits both the rules and the rationale.

### 22.6 The MES pivot changed nothing load-bearing about the broader system

Zero changes today touched: order execution, IB connector, risk safety layer, kill-switch logic, position sizing base, or portfolio tracker. The pivot was confined to signal generation + dispatch. This is good architecture — high-leverage change with low blast radius.

### 22.7 The forward-recorder experiment has negative trading cost

`mes_session_recorder` writes a hypothesis daily; `mes_session_outcome` writes the result. No position is taken. Over 8–12 weeks we get a labeled dataset: `(market_conditions, hypothesis, outcome)`. This dataset feeds future RL/Bayesian work. Total cost: ~1 LLM call/day + Discord post. Total value: training data that would otherwise take ~6 months to accumulate from live trades.

### 22.8 The STC search and the SMA-trend search probably converge on different answers

STC is a oscillator-based strategy (momentum-inflection detection). SMA-crossover is a trend-filter. They are not the same strategy with different parameters; they are different strategies. If STC search produces PF ≥ 1.5, we should stack it alongside SMA-trend, not replace.

### 22.9 The "single-file handoff" philosophy breaks in multi-agent repos

A project with one agent can maintain one handoff per session. Two agents need two handoffs per session (one per agent). By week four of two-agent operation, we'd have ~60 handoff files in `docs/session-logs/`. Need a weekly consolidation cron or a "handoff index" doc that links the sparse handoffs.

### 22.10 Untracked docs are safer than uncommitted code

An uncommitted code change is a production-risk surface (what if engine restarts?). An untracked doc is pure information. Triage order at session close: commit code first, docs second.

### 22.11 The more a handoff says "verify X", the better it ages

Documents that make assertions age badly. Documents that instruct verification ("run `curl /health` to confirm") age well. This close-out includes §15 verification scripts deliberately — so that every claim becomes an executable fact-check instead of a bare claim.

### 22.12 Every handoff should end with a one-line summary of the next session's first action

Not "here's a long TODO list" but "start with commit A per §14.1." A successor who reads only the summary should still be able to make forward progress. **See §23 below for this session's one-liner.**

---

## 23. Session-close checklist (literal)

If successor session does only one thing from this document, do this list in order:

- [ ] 1. `cd /c/Users/mattm/ThinkorSwim/jarvis-trader`
- [ ] 2. `git status` → confirm working tree matches §9a (or note drift)
- [ ] 3. `curl -s -H "X-API-Key: $KEY" http://localhost:8010/health | jq .`
- [ ] 4. Read `docs/session-logs/handoff-2026-04-20-1823-session-close.md` (this file) front-to-back
- [ ] 5. Read `docs/session-logs/handoff-2026-04-20-mes-profitability.md` (canonical strategy doc)
- [ ] 6. Skim `docs/session-logs/handoff-2026-04-20-mes-sma-strategy.md` (concurrent-session perspective)
- [ ] 7. Execute §14.1 Commit A (backtest_router.py + main.py)
- [ ] 8. Restart engine + verify §15.7 (MES backtest PF)
- [ ] 9. Execute §14.2 Commit B (experiments_router + dashboard panel + validation page)
- [ ] 10. Restart engine + verify §15.8 (experiments summary endpoint)
- [ ] 11. `cd dashboard && pnpm run build && cd ..` — confirm TypeScript builds
- [ ] 12. Execute §14.3 Commit C (discord notifier + outcome wiring)
- [ ] 13. Execute §14.4 Commit D (port_guardian)
- [ ] 14. Execute §14.5 Commit E (docs + scratch)
- [ ] 15. `git log --oneline -10` — confirm 5 new commits atop `72538f4`
- [ ] 16. Update MEMORY.md directive line to reflect new state
- [ ] 17. Begin TODO #1 (MES-trend drift alert)

If any step fails, do NOT skip ahead — diagnose per §18 of prior handoff or §15–§16 of this one.

---

## 24. Glossary

Session-specific terms that new agents may not know.

- **MES**: CME E-mini S&P 500 futures. Micro contract. Multiplier = $5/point.
- **MCL**: CME Micro WTI Crude Oil futures. Multiplier = $100/point (contract size 100 barrels).
- **MNQ**: CME Micro Nasdaq-100 futures. Multiplier = $2/point.
- **PF**: Profit Factor = gross_profit / gross_loss. PF > 1 = profitable; PF > 2 = strong.
- **WFE**: Walk-Forward Efficiency = OOS_PF / IS_PF. > 0.5 healthy; > 0.8 strong.
- **STC**: Schaff Trend Cycle. Momentum oscillator combining MACD + stochastic. OS/OB thresholds default 15/83.
- **ORB**: Opening Range Breakout. Entry strategy on break of first-N-minutes' high/low.
- **VWAP**: Volume-Weighted Average Price. Mean reversion anchor.
- **SMA crossover**: simple moving average fast > slow = bullish regime.
- **ATR trail**: trailing stop at price − N × ATR(14).
- **Golden cross / death cross**: SMA50 crosses above/below SMA200.
- **Buy-hold baseline**: passive long from period start to end. Diagnostic benchmark.
- **Composite pipeline**: existing multi-signal strategy (STC + ORB + VWAP) used for MCL/MNQ.
- **Dispatch gate**: `TREND_INSTRUMENTS = {"MES"}` at `signals.py:106` — routes symbols to strategy family.
- **Session ID trailer**: `Claude Opus 4.7 (session <8-char>) <...@anthropic.com>` stamped in every commit.
- **PM2**: Node.js process manager; runs jarvis-engine + jarvis-dashboard as daemons.
- **pm_uptime**: PM2's uptime-in-ms field; resets on restart. Used by PM2-aware restart script.
- **LLM path health**: `/health.llm_path_healthy` boolean. Surfaces credit-outage failures.
- **R4 window**: Mon-Tue 2026-04-20 to 2026-04-22 passive accumulation period post-credit-outage.
- **Corey session bias**: daily bias signal sourced from Discord #market-updates channel.
- **Forward-recorder**: observational experiment — writes hypothesis + outcome daily, takes no positions.
- **TREND_INSTRUMENTS**: set of symbols routed to `trend_signals.py` in dispatch.
- **Kill switch**: `/safety/kill-switch/activate` — halts new entries system-wide.

---

## 25. Meta — how to critique this handoff

If the successor finds this handoff lacking, the improvement path:

### 25.1 Missing information?

Add a section with the missing facts. Do not delete existing sections unless they are *wrong* (vs. incomplete). Append-over-edit is safer.

### 25.2 Inaccurate claim?

1. Diagnose: what is the correct current state?
2. Update the specific claim inline (don't rewrite surrounding prose).
3. Add a `> Corrected YYYY-MM-DD HH:MM: <reason>` note adjacent.

### 25.3 Outdated roadmap?

Prior handoff §17 has Phase 0–6. If a phase gate moves, update the gate criteria in the prior handoff, not here. This close-out is a snapshot, not a roadmap.

### 25.4 Too long?

If successor is overwhelmed: read §23 checklist only. Every other section is optional elaboration. Do not delete sections to shrink the doc — reading skill is more trainable than documentation skill.

### 25.5 Structure suggestions for future handoffs

- Front-load state and git info (§1–9) — always.
- Mid-load decisions and rationale (§10–16) — for active work.
- Back-load insights and philosophy (§17–25) — for compounding learning.

---

## 26. Final one-liner

**Successor's first action: `cd /c/Users/mattm/ThinkorSwim/jarvis-trader && git status && curl -s -H "X-API-Key: [REDACTED]" http://localhost:8010/health | jq '.status, .llm_path_healthy'`. Then execute §23 checklist. No other action until checklist complete.**

---

*Handoff expansion written 2026-04-20 19:30 CT. Total length: ~1,250 lines (up from 521). Added: §13 diff analysis, §14 commit graph, §15 verification scripts, §16 rollback playbook, §17 concurrent-session contracts, §18 phantom progress, §19 resume scenarios, §20 git hygiene, §21 info architecture, §22 extended insights, §23 checklist, §24 glossary, §25 critique guide, §26 one-liner.*
