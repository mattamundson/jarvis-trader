# JARVIS Trader — Dashboard Backlog (consolidated)

**Date:** 2026-08-05
**Scope:** the Next.js dashboard on port 3010 (`dashboard/`), plus the engine work required to make a dashboard surface honest.
**Method:** 3 exhaustive sweeps — (1) live dashboard code inventory, (2) `WIDGETS_AND_DECISIONS.md` + `research-backlog-from-discord.md` + `docs/digest/*`, (3) formal backlog/roadmap/handoff/PR/issue corpus. 96 raw candidates deduplicated to the items below.

**Verification tags:** `[V]` = I confirmed it directly this session. `[A]` = agent-reported, plausible, not independently re-checked. Tier 0 is all `[V]`.

---

## TIER 0 — Blockers

### RESOLVED during this session

| # | Item | Outcome |
|---|---|---|
| 0.1–0.3 | "Engine / dashboard / master-api down" | **FALSE ALARM — retracted.** The first port scan ran during the engine's ~229s startup window. Re-verified live `[V]`: engine `/health` → `status=ok`, `tradingview_mcp_healthy=true`, `llm_path_healthy=true` (full gate passes); dashboard HTTP 200 on 3010; 8030 and 4002 both listening. The stack is healthy. |
| 0.4 | `pm2 jlist` JSON parse failure | **ROOT-CAUSED `[V]`.** Not flap noise. The per-process env block contains both `username` and `USERNAME`; PowerShell's `ConvertFrom-Json` is case-insensitive and throws *"keys with different casing"*. Fix: `ConvertFrom-Json -AsHashtable` (+ join the job output before piping). With that, `jlist` parses fine. `pm2 ping` was always healthy — only `status`/`jlist` hung. **Apply this fix to `pm2-supervision-watch`.** |
| 0.5 | **Client-side engine API key** | **SCRUBBED `[V]`, ROTATION STILL OWED.** Confirmed real: the pre-scrub build had **3 hits** of the 64-char key, including the client-served chunk `.next/static/chunks/app/jarvis/page-*.js`. Removed `NEXT_PUBLIC_ENGINE_API_KEY` from `.env.local` (server-side `ENGINE_API_KEY` retained), archived the prior file and the stale `.env.local.bak.20260708234706` to `~/Archive/2026/jarvis-trader-secrets/`, and rebuilt to purge the inlined value. **Amo still owes a rotation at the issuer** — the old key sat in a browser-served bundle. |

**Cost of the scrub:** `usePipelineSocket` has exactly one consumer, `app/jarvis/page.tsx:125`, and `/jarvis` is deliberately not in the nav (`Sidebar.tsx:73`). The hook degrades gracefully. Note `engine-websocket-context.tsx:33-35`: the Next.js `/ws` rewrite proxies WS upgrades in `next dev` but **not** in `next start`, so `NEXT_PUBLIC_ENGINE_URL` must stay. A durable fix for authenticated WS in production = short-lived scoped WS token endpoint (**new item 4.35**).

### STILL OPEN — surfaced from the live engine logs `[V]`

| # | Item | Evidence |
|---|---|---|
| 0.6 | **`engine-error.log` is 846 MB** (`~/.pm2/logs/jarvis-engine-error.log` separately 418 MB) | Driven by 0.7 + 0.8 below. Needs rotation/truncation; the two loops write ~2×/sec each. |
| 0.7 | **TV streamer erroring ~2×/sec, continuously** | `[WARNING] jarvis_trader.tv_stream: [TVStreamer:CLI] [stream:all-panes] error: JS evaluation error: TypeError: Cannot read properties of undefined (reading '_chartWidgetCollection')` — note `/health` still reports `tradingview_mcp_healthy=true`, so the health gate does **not** catch this. |
| 0.8 | **Discord `reaction_watcher` stuck in a ~2s reconnect loop** | `WebSocket connected` → `sent IDENTIFY (intents=41473)` → `reconnecting in 2s...`, repeating indefinitely. Never reaches READY. |
| 0.9 | **IB market data NOT subscribed — prices are historical fallback, not live** | `[ERROR] ib_async.wrapper: Error 10168 ... Requested market data is not subscribed. Delayed market data is not enabled.` → `IBKR snapshot fallback: fetching last historical close for MES` → `7761.25`. **This confirms backlog item "IB data feed BLIND" as live today.** Every price-derived dashboard number is currently fallback data. |

---

## TIER 1 — Correctness & safety bugs in already-shipped UI

These render *wrong numbers* or fail silently. Highest priority after Tier 0 because a wrong number is worse than a missing one.

> **Re-validated live against a healthy stack, 2026-08-05.** The source audit is dated 2026-07-10 and was taken during a degraded window. **5 of 10 items are stale and are retired below.** Do not implement from the July audit without re-checking.

### RETIRED — verified false or already fixed `[V]`

| # | Claim | Live result |
|---|---|---|
| 1.1 | "`/` and `/trades` hang 15s+, zero content" — *"most safety-relevant Tier 1 item"* | **FALSE.** `/` → HTTP 200 in **134 ms** (100 KB), `/trades` → 200 in **174 ms** (95 KB). All 8 probed routes 200 in 17–174 ms. |
| 1.4 | "`/regime` silently falls back to sample data, masking an outage" | **FALSE.** `lib/regime.ts` types `source: "live" \| "sample"`; `buildSampleRegime` sets `source:"sample"` (`:168`), live path sets `"live"` (`:235`); `app/regime/page.tsx:167,177-183` renders a `static`-variant badge reading **"Sample Data"** with a non-pulsing dot. Explicitly badged, not silent. |
| 1.6 | "ValidationTracker returns 0 trades" | **Symptom gone.** `/paper/validation/trades/closed` → 200 with real closed trades (e.g. MES, pnl −80.83). |
| 1.8 | "`/mission-control` and `/framing-brief` 404" | **FALSE.** Both → HTTP 200. |
| 1.9 | "Duplicate Hidden Pivots nav entry" | **FALSE.** Exactly one entry, `Sidebar.tsx:101`. |

### REAL — open

| # | Item | Status |
|---|---|---|
| 1.7 | **`realized_pnl` means two different things on two endpoints** | **CONFIRMED, and re-diagnosed.** Not a SQLite-vs-in-memory storage divergence. Live: `/pnl/truth` → `realized_pnl: 4977.07` over 82 closed trades (`status:"TRUSTED"`), and `/portfolio/stats/summary` → `total_pnl: 4977.07` / 82 trades — **these two agree**. But `/portfolio/summary` → `realized_pnl: −80.83`, which is *today's* single closed trade. **The same field name carries lifetime scope on one endpoint and daily scope on another.** A widget binding the wrong one renders −$80 instead of +$4,977. Fix = disambiguate the field names in the engine contract, then audit every widget that reads `realized_pnl`. |
| 1.2 | `/parallel-paper` 100× understated drawdowns (GT-08) | **PR #570, DRAFT** — Amo-gated merge |
| 1.3 | Portfolio equity/cash/daily-pnl key mismatch (GT-01) | **PR #569, DRAFT** — Amo-gated merge |
| 1.10 | `trade-history.spec.ts` UTF-16LE breaks CI (#584) | **PR #590, DRAFT** — Amo-gated merge |
| 1.5 | React hydration error #418 on `/performance` | **UNVERIFIED — needs a browser.** SSR returns 200 in 22 ms; hydration errors only surface in a client console, so HTTP probing cannot confirm or refute it. |

---

## TIER 2 — Honesty debt: surfaces that render but are hollow

The codebase has a deliberate provenance system (`live` / `static` badges, `lib/provenance.ts`). These are the surfaces currently flying `static`/`stub`. Each is either *wire it* or *remove it*.

> **Re-validated against the live engine 2026-08-05 `[V]`.** 5 of 12 stale. Same ~50% staleness rate as Tiers 1 and 3.

### RETIRED — false, fixed, or intentional `[V]`

| # | Claim | Live result |
|---|---|---|
| 2.8 | `auction_bias_router` 503 "not wired" — *blocks Issue #310* | **ALREADY FIXED.** `/auction/bias/MES` → **200** with full real payload: `saty` (atr 99.67, call/put triggers), `tpo` (value area, profile target), `corey` bias, and a `synthesis` block with `line_in_sand`. The 503 line still exists but is a defensive `if _provider is None` guard; the provider is injected. **Issue #310's v1 engine dependency is already met.** |
| 2.6 | `/strategy-c` placeholder metrics at `:659,709` | **FALSE.** Those lines are the `title=` of the honesty `Badge`, not values. The real fallbacks (`:626,633,640,647`) are all dead branches — `/v1/strategy_c/metrics` returns every field live (cagr 0.1709, sharpe 2.1231, win_rate 0.576, final_multiple 4.123×), so `m.live === true` and no "Static" badge renders. |
| 2.5 | `STC_BENCHMARKS` "shown as if live" | **Half false.** Constants exist, but are labeled static in **three** places: code comment `:722-724`, user-visible text `:741` ("not recomputed live"), and the column header `:823` ("static BT"). No honesty defect. |
| 2.11 | `MTFConfirmationWidget` "Not wired · Phase 3" | **Dead branch.** `/analytics/mtf?symbol=MES` → `source:"live"`, all three timeframes live (1h/4h/1d with real STC values). Keep the branch as a defensive fallback. |
| 2.4 | Trust-pane "Execution & P&L" permanently `static` | **Intentional, not a defect.** amo-arbitrage is signal-generation only with no order execution, so there is no P&L feed to wire. This is correct honest-negative behavior. Remove from the backlog. |
| 2.9 | Discord "4 endpoints blocked" | **Endpoints NOT blocked.** All four return real data live (`/discord/signals`, `/ib-reports`, `/corey-alerts`, `/commentary`). Only the `channel_id` **query param** is a silent no-op — proven: `?channel_id=999999999999999999` still returns all 3 rows. TODOs are real but low priority; slug filtering already works. |

### REAL — open `[V]`

| # | Item | Status |
|---|---|---|
| 2.1 | **Regime: 4 of 5 layers stub** | **CONFIRMED**, but on `/analytics/regime` (overview), **not** the cited `/{sym}` path — `/analytics/regime/MES` returns no `layers` object at all. Live: `vix` active, `mtf`/`stc`/`ema_trend`/`volume` all `"stub"`. **Cheap win: the `mtf` layer is nearly free** — `/analytics/mtf` is already fully live (see 2.11); it just isn't plumbed into the overview's `layers` dict. |
| 2.2 | **`/regime` "Not wired" cards actively rendering** | **CONFIRMED.** `/regime/intraday?symbol=SPY` → `options_flow: null`. Two root causes: `engine/analytics/options_flow.py:136-160` requires a Polygon key (absent), **and** `regime_router.py:98` (`if not futures:`) skips options flow entirely for futures symbols. Note `compute_gex` (`options_flow.py:100-133`) already works — only the chain fetch is unwired. |
| 2.3 | `SessionSummaryWidget` hardcoded placeholder | **CONFIRMED**, still mounted at `app/paper/page.tsx:228`. Wire or unmount. |
| 2.7 | GT-41 — Simulate Trade dead panel | **CONFIRMED.** `/test/simulate-trade` → **404**, and the engine's OpenAPI (404 registered paths) contains no such route. `lib/settings-api.ts:180-186` throws unconditionally — no network call is even attempted. Needs a non-persisting dry-run endpoint, or delete the panel. |
| 2.10 | `proactive_validation_router` placeholder stop/target | **CONFIRMED**, low impact — fed to a Monte Carlo path that per the inline comment reads only `pnl`. **Verify that assumption before deprioritizing**: if any MC variant reads `stop_price`, these become silently wrong risk numbers. |
| 2.12 | `analysis_router.py:225-240` stub | **Dead code, unreachable.** `analytics_router` (prefix `/analytics`) is registered at `main.py:3220`, *before* `analysis_router` at `:3276`; FastAPI is first-match-wins, so the real impl serves it (live: 44 trades, sharpe −1.16). Note the stub has **no `db_manager` check at all** — it returns `{total_trades: 0}` unconditionally. **Latent hazard: if registration order ever flips, the dashboard silently shows zeros instead of erroring.** Delete it. |

---

## TIER 3 — Architecture & hygiene debt

> **Re-counted from source 2026-08-05, verified with the repo's own `scripts/check-guards.mjs` `[V]`.** Two of the largest supposed work blocks are already complete.

### RETIRED — already done `[V]`

| # | Claim | Live result |
|---|---|---|
| 3.1 | "33 widgets still use bare `fetch`" | **DONE — 0 violations.** `node scripts/check-guards.mjs` → `OK no-bare-fetch (0 violations)`. Of the 35 widgets named in `DASHBOARD_FETCHENGINE_BACKLOG.md:13-24`, 32 exist and are all migrated (15 direct `fetchEngine`, 17 via shared hooks like `useHonestTrades`); 3 were deleted. My independent recount found 1 apparent hit — `app/scorecard/page.tsx:344` — which is **inside a comment**. The backlog doc is stale; mark it DONE or delete it. |
| 3.2 | "~80+ components hardcode `http://localhost:8010`" | **DONE — 0 violations.** `OK no-direct-engine-url (0 violations)`. Only 4 runtime sites remain, all intentional and allowlisted: `next.config.ts:19` (rewrite default), `app/api/engine/[...path]/route.ts:12` (the proxy itself), `lib/engine-websocket-context.tsx:40` (WS cannot traverse the HTTP proxy), `app/strategy-c/page.tsx:733` (display text, issues no request). |

### REAL — open, with exact counts `[V]`

| # | Item | Exact scale | Notes |
|---|---|---|---|
| 3.3 | **`refreshInterval` migration — the single biggest mechanical item** | **128 literals across 81 files**; only 3 sites use `POLL_INTERVAL` | Guard confirms `hardcoded-refresh-interval (128, at ceiling 128)` — **zero progress** since the ceiling was set. `lib/polling-config.ts` exists and is unchanged since 2026-07-06. |
| 3.4 | **Orphaned components — worse than reported** | **96 of 258 have zero inbound imports** (not 90); **103 unreachable** from any entry point (7 are chain-orphans) | Split: **65 wire-it** (call a real engine endpoint or fetch via `useHonestTrades`/`useEngineStatus`) vs **38 archive**. The 5 files under `components/_archive/` are already tsconfig-excluded and safe to remove now. Traps ruled out: `IBGatewayStatus` hits are an unrelated interface in `lib/settings-api.ts`; `WatchlistScanWidget` is shadowed by an inline duplicate in `app/watchlist/page.tsx:78`; `widgets/LiveReadinessWidget.tsx` is a dead re-export shim, so both it and its target are dead. |
| 3.5 | **landmark debt** | **20** page-kind routes (ceiling is 21 — the doc quoted the ceiling, not the count) | **Coupled edit:** `tests/routeManifest.node.test.ts:89` asserts `LANDMARK_DEBT >= CEILING - 3`, so fixing 2+ landmarks without lowering `LANDMARK_DEBT_CEILING` **fails the suite**. |
| 3.6 | **E2E coverage** | **15 of 50 routes (30%)**; 18 spec files | 5 of the 18 specs all land on `/command-center`. **4 critical routes have neither a landmark nor a spec: `/portfolio`, `/performance`, `/validation`, `/options`.** |
| 3.7 | Default `playwright.config.ts` reuses the pm2 prod server | — | Its own comment: a green run in that mode "is not evidence." Only `test:e2e:fresh` (3013) gates honestly. |
| 3.8 | **Bundle sizes — the plan named the wrong routes** | Real worst: **`/regime` 234 kB** (116 kB page — the outlier) and **`/performance` 221 kB** | Then `/validation` 201 kB, `/analysis` 189 kB, `/trades/[id]/review` 183 kB, `/today` 176 kB. Shared baseline 103 kB. Source: `engine/logs/dashboard-build.log`, today, `BUILD_EXIT=0`, 49/49 static pages. |
| 3.9 | `public/strategy-c-command-center.html` | **337 KB**; **10 hardcoded `127.0.0.1:8020` fetches** | Correction: it does **not** call :8010 — the three 8010 occurrences are display text only. Also carries stale `:3000` and `:5173` references. |
| 3.10 | `dashboard/apps/ops-console/` | Only a 233 KB `.next/`, zero source | No `package.json`, not in `pnpm-workspace.yaml`, 0 references repo-wide. Safe to remove. |
| 3.11 | Open DRAFT dashboard PRs | #569 **CLEAN**, #570 **CLEAN**, #590 **CONFLICTING**, plus #571/#572/#579, #292 | All checks on these are Vercel/Supabase **deploy** checks — no test suite ran. Mergeable ≠ verified. |

---

## TIER 4 — New surfaces (the actual "new widget" backlog)

Sorted by **data-readiness**. `docs/digest/infra-synthesis.md:31` states it plainly: *"it is a visualization problem, not a data problem."*

### 4A — Data already exists in the engine. Pure visualization.

| # | Widget | Data source that already exists |
|---|---|---|
| 4.1 | **GEX / dealer-positioning overlay** ⚠️ **CORRECTED — this is NOT pure-frontend work** | See the dedicated breakdown below. Parsing exists; **no endpoint exposes it**. Belongs in 4B, not 4A. |
| 4.2 | **Monte Carlo / risk simulation viz** — risk-of-ruin, GARCH VaR/CVaR, Kelly, crisis stress | `engine/backtest/monte_carlo.py`, **18 simulation types**, zero UI anywhere |
| 4.3 | **Brier calibration / agent-quality panel** | `BrierCalibrationTracker`, `engine/analytics/ic_ensemble.py:340-479` |
| 4.4 | **Pair-spread / cointegration screen** — z-score, hedge ratio, half-life per pair | `engine/analysis/pair_spread.py` → `screen_all_pairs()` |
| 4.5 | **Strategy competition leaderboard** | `engine/strategy_lab/competition_harness.py` → `to_dict()` |
| 4.6 | **Options backtester results view** | `engine/backtest/options_backtester.py` → `BacktestResult.to_dict()` |
| 4.7 | **GEPA prompt-evolution viewer** — Pareto frontier + generation history | `engine/llm/prompt_evolution.py` → `optimizer.history` |
| 4.8 | **Per-analyst IC weight / signal contribution** | `ICWeightedEnsemble`, live in `debate.py:265-276` |
| 4.9 | **FRED macro widget** | `engine/data/fred_data.py` — wired, never surfaced |
| 4.10 | **Earnings calendar surface** | Scheduler built (4-job APScheduler); no widget was ever created |
| 4.11 | **Corrections / mistakes-and-learnings log** | `AgentFeedbackTracker` + `trade_outcomes`. "Data is captured; there is no surface" — Amo reads it via raw SQL today |
| 4.12 | **Cron / scheduler monitor** | APScheduler at `engine/main.py:1410-1463`; needs an introspection endpoint |
| 4.13 | **LLM cost / prompt-pattern monitor** | TokenProxy stats (`/obs/token-proxy/metrics`) — component exists but is **orphaned** |
| 4.14 | **Research-backlog / bookmark triage board** | `discord_bookmarks` table, 1,016 rows |
| 4.15 | **MTF 7-timeframe bias grid** (distinct from the confirmation widget) | `mtf_analyzer.py`; extending 3 TF → 7 TF is config |
| 4.16 | Tail-risk / Taleb veto panel | `DebateResult.tail_risk_report`; gated by `TAIL_RISK_RESEARCHER_ENABLED=false` |
| 4.17 | Layered decision-reasoning explainer (prior → adjustments → verdict) | `PipelineResult` already carries the full rejection-reason chain |
| 4.18 | Rules/discipline checklist widget | Journal already has mood tracking |

### 4B — Needs new engine work

| # | Widget | What's missing |
|---|---|---|
| 4.19 | **One-click approval UI** — APPROVE/REJECT, Y/N keyboard, badge counter, auto-refresh | `PendingApprovals.tsx` exists but is **orphaned**. Full spec already written: `docs/plans/APPROVAL_UI_TASKS.md`. Roadmap P4.3/P4.4. |
| 4.20 | **Kill-switch big-red-button + typed confirmation** ("I confirm killing at [price]") | `KillSwitch.tsx` exists, orphaned. Roadmap P4.5. Pairs with a new `/safety/flatten-all` endpoint (kill switch stops new orders but does **not** close open positions). |
| 4.21 | **Options Greeks panel** (delta/theta/IV) | `greeks_monitor.py` is a stub; needs Greeks computed over the existing chain fetcher |
| 4.22 | **Gamma levels auto-fetched daily** → `gamma_snapshot` table (schema v23) + `gamma_fetcher.py`, 16:30 CT | Roadmap P2.3 exit criterion |
| 4.23 | Data-integrity page backed by real freshness/error-rate per source (Redis `datasource:*:last_update`) | Route exists but is one of the two thinnest pages |
| 4.24 | Master-api reachability indicator | Currently the `/master/*` pages just fail (see 0.3) |
| 4.25 | Schwab OAuth2 flow + credential/connection-status component | Manual 7-day token refresh today |
| 4.26 | Snapshot diff — "what changed since yesterday" | Needs a daily snapshot writer |
| 4.27 | User-defined price alert rules | Needs rule storage |
| 4.28 | Standardized execution-error surface (9-category envelope w/ `retryable` + suggestion) | Needs `order_router.py` error refactor first |
| 4.29 | Vision pattern agent — annotated chart + classification | `chrome-devtools` MCP now registered; scaffold est. 2–8 hr |
| 4.35 | **Short-lived scoped WS token endpoint** — so authenticated WebSockets work in `next start` without a client-side API key | Engine issues a short-TTL token scoped to `/ws/pipeline`; client uses that instead of the raw key. Closes the 0.5 exposure class permanently rather than trading it against a broken socket. Blocks a real fix for `/jarvis` live pipeline events. |

---

### 4.1 GEX / dealer positioning — corrected analysis `[V]`

An earlier note in this doc claimed the dealer-positioning read was *"a visualization problem, not a data problem."* **That was wrong.** It is a **transport** problem: the data is parsed and then discarded before it reaches any API surface.

**What exists** (`engine/data/tv_indicator_bridge.py`):
- `:136-142` — `TVIndicatorSnapshot` carries `gex_flip`, `call_wall`, `put_wall`, `hvl`, `vol_trigger_up`, `vol_trigger_down`, `max_pain`
- `:153-162` — `_GAMMA_ALIASES` label-matching ("gex flip"/"zero gamma"/"flip", "call wall", "put wall", "hvl", vol triggers, "max pain")
- `:164` — `_GAMMA_FILTER = "MY FREE GAMMA LEVELS"` (closed-source TV overlay; values read via MCP label passthrough, never computed locally)
- Consumed internally by `engine/agents/technical_analyst.py:1015-1018, 1032-1042` for regime + stop policy. Tests: `engine/tests/test_gamma_levels_parser.py`

**Why no widget can read it:** `engine/routers/tradingview_router.py:26-45` — `TVSnapshotResponse` declares exactly 15 fields and **none are gamma**. The bridge snapshot is projected down and the gamma data is dropped. Grepping all of `engine/routers/` for `gamma` returns **zero matches**. Verified live:
```
GET /tv/snapshot?symbol=SPX → 200
{"symbol":"SPX","stc_value":null,...,"data_quality":"unavailable"}   ← no gamma keys at all
GET /tv/health → 200  {"available":false,"cli_found":false,"cdp_connected":false}
```

**Two blockers, in order:**
1. **No transport.** Add the 7 fields to `TVSnapshotResponse`. This is a ~7-line *additive* change — `model_config = ConfigDict(from_attributes=True)` at `:29` will populate them straight off the bridge snapshot. (Or add a dedicated `/tv/gamma` route.)
2. **No live source.** `/tv/health` reports `cli_found:false, cdp_connected:false` — the TradingView CDP bridge is **down**, so even after exposing the fields they return `null` until the TV CDP launcher runs with the "MY FREE GAMMA LEVELS" overlay on the chart.

**Two adjacent leads:**
- A **second, independent** GEX path exists: `engine/analytics/options_flow.py` → `{flow_signal, net_gex, gex_flip_level}`, already surfaced via `/regime/intraday` as `options_flow`. That is what the 2.2 "Not wired" cards consume. Currently `null` — Polygon-gated, and skipped for futures at `regime_router.py:98`.
- **Historical gamma is already archived** — `engine/database/migrations.py:939` defines `gamma_snapshot_json TEXT` holding the full serialized level set, written by `engine/analytics/tv_snapshot_archive.py` on the `tv_archive_scheduler.py` cadence. **A historical-GEX widget could ship without the live TV bridge at all.** This is the lowest-blocker path to a dealer-positioning view.

---

### 4C — Amo decision required (cost / policy)

| # | Item | Decision |
|---|---|---|
| 4.30 | **Real options-flow feed** (Unusual Whales or equivalent) | Paid vendor. No connector exists. |
| 4.31 | `recharts` → TradingView `lightweight-charts` swap | ~5 KB bundle cut + 3–5× OHLCV render speedup, Apache-2.0. Deferred once as "risky mid-window". Touches every chart. |
| 4.32 | Polymarket event-risk odds | Explicitly deferred: *"Not a P0, not even a P2"* |
| 4.33 | Trade journal → OneNote via MCP | Needs a new MCP connector |
| 4.34 | Grafana/Prometheus metrics per phase | Separate stack |

---

## Explicitly OUT of scope (`docs/ROADMAP_2026-Q2-Q4.md:507-514`)

Reddit/Twitter futures sentiment · GMS integration · HFT sub-second · **dark pool prints** (no reliable free futures source) · copy-trading/signal-publishing · iOS native app.

---

## Recommended sequencing

1. **Tier 0** — revive engine + dashboard + master-api, unwedge pm2, rotate the exposed key. Nothing else is verifiable first.
2. **Tier 1** — wrong numbers before missing numbers. Land the 4 draft PRs that already fix some of these.
3. **Tier 2.1 / 2.2 / 4.1** together — the regime + GEX cluster is the single highest-value block: the data is already parsed, and it converts three "Not wired" cards into the dealer-positioning read.
4. **Tier 3.1 + 3.2** — the fetchEngine migration and the orphan wire-or-archive pass are mechanical and parallelize cleanly.
5. **Tier 4A** — pure-visualization wins, roughly in listed order.
6. **Tier 4B / 4C** — engine work and paid-vendor calls.
