# JARVIS TRADER — Implementation Roadmap 2026 Q2–Q4

**Created:** 2026-04-21
**Horizon:** 6–9 months (April 2026 → December 2026)
**Author:** Claude (Opus 4.7) with Matt Morrison
**Source-of-truth doc.** Other roadmap fragments (multi-market-trading-framework.md, Sprint A–G manifest, prd.json) feed into this one.

---

## 0. Vision

Transform JARVIS TRADER from a **single-strategy, single-instrument, paper-only** system into a **multi-strategy, multi-instrument, semi-autonomous** trading platform with:

- **Real-time data fabric** (no more stale CSVs)
- **Strategy ensemble** (trend + mean-reversion + breakout per instrument, router decides)
- **Agent-native intelligence** (LLM reasoning chains do the heavy lifting; humans approve, don't decide)
- **Continuous learning loop** (n-autoresearch + A/B paper-canary + Gate v2 governance)
- **Multi-surface approval** (WhatsApp, voice, dashboard — whichever you're near)

**Success metric (end of 2026):** 3+ validated strategies live across 2+ instruments, ≥90 days forward-test profitable, ≥$X live capital deployed (Tier 3 decision, not set here), agent-driven signal generation with <60s human approval latency.

---

## 1. Current State Snapshot (2026-04-21)

| Area | State | Evidence |
|---|---|---|
| Data feed | **STALE** — OHLC cache last bar 2026-03-27; engine `/analyze/bars` returns empty; 2-day staleness guard blocks live signals | `market_data.py:754`; today's debug session |
| TradingView MCP | **ACTIVATED TODAY** — CDP port 9222 live, `tv` CLI linked, `.mcp.json` registered | This session's activation work |
| MES strategy | **LIVE** — SMA(50,200) + 2.0× ATR trail, PF 1.765 live (36 trades, Sharpe 3.113) | Commit `5816aae` |
| MCL/MNQ | **GATED HOLD** via `DO_NOT_TRADE_SYMBOLS` | Commit `c4a1ef1` |
| Gate v2 governance | **Phase 1+2+3-LIGHT shipped** — advisory verdicts only; Phase 3-FULL (block routing) not yet | Commits `c8f4610`, `3198364` |
| Forward-recorder | **LIVE** — records 08:30 CT hypothesis, checks 15:15 CT outcome | Commit `fd5b153` |
| RL strategy discovery | **SCAFFOLDED** — `engine/strategies/` has base_strategy, discovery_loop, llm_sandbox, mes_search_space | Existing code |
| Bookmark harvester | **LIVE** — 371 bookmarks, Haiku clusterer, Sunday prewarm | Commit `7493753` |
| Paper trading | **ACTIVE** — $10,330 equity, +$180 today, 8.26% drawdown | `/safety/status` this session |
| Multi-MCPs | **INSTALLED BUT UNDERUSED** — voicemode, playwright, codex-cli, figma, gamma, claude-mem | `.mcp.json` |
| IB Gateway | **CONNECTED** (paper port 4002) | `/health` response |
| LLM cost controls | **PARTIAL** — token_proxy + optimizer built, advisor path live, IC-weighted ensemble live | Commits from Apr 10 Track F/G/H |

**Biggest gaps:**
1. No live bar ingestion → every signal decision runs on stale data
2. Only one strategy family active (SMA trend)
3. Gate v2 still advisory — doesn't block anything
4. Forward-recorder doesn't feed back into signal generation
5. Voice/mobile approval infra installed but unused
6. Options layer completely absent
7. No regime-switching between strategy families

---

## 2. Phased Roadmap

### PHASE 0 — Foundation Lock-In (1 week: 2026-04-21 → 2026-04-28)

**Goal:** Stop the bleeding on known infra gaps before stacking new capability on top.

| Task | Deliverable | File(s) touched | Size |
|---|---|---|---|
| **P0.1** TV MCP startup persistence | **SHIPPED 2026-04-21 ~17:05 CT** — scheduled task `JARVIS-TV-CDP-AtLogon`, launcher is idempotent (port 9222 check → exit 0/1/2), docs at `docs/tv-mcp-startup.md`. | `scripts/launch-tv-with-cdp.ps1`, `scripts/install-tv-cdp-startup-task.ps1` | S |
| **P0.2** Wire TV MCP → engine bar pipeline | **SHIPPED 2026-04-21 ~17:20 CT** — TV inserted as **Tier 0** (above IBKR) in `market_data.get_bars()`. `tradingview_feed.get_bars()` serializes chart state via `threading.Lock`, saves/restores symbol + timeframe, honors staleness cutoff (72h). End-to-end verified: `/analyze/bars/MES?timeframe=1h&days=5&futures=true` returns 300 bars, last bar `2026-04-21T22:00:00Z` close 7127.25. 11 new tests pass. | `engine/data/market_data.py`, `engine/data/tradingview_feed.py`, `engine/tests/test_new_features.py` | M |
| **P0.3** `/analyze/bars/{symbol}` `interval` alias | **SHIPPED 2026-04-21 ~17:45 CT** — `interval` accepted as alias for `timeframe`. Precedence: explicit `timeframe` > `interval` > default `5m`. Fixed in BOTH `main.py:2554` (live route) and `routers/analysis_router.py:86` (dormant duplicate — flagged for P1 consolidation). 3 unit tests pass; 3 live-curl precedence cases verified. **Surprise finding**: `main.py` has ~50 route-handler duplicates of `routers/*` — router migration is incomplete. Tracked as new P1.7. | `engine/main.py`, `engine/routers/analysis_router.py`, `engine/tests/test_new_features.py` | S |
| **P0.4** Gate v2 Phase 3-FULL decision | **SHIPPED 2026-04-21 17:11 CT** — decision memo at `docs/decisions/gate_v2_phase3_full.md` (commit `266e1d9`); enforcement ACTIVE via `GATE_V2_ENFORCE_ROUTING=1` in `engine/.env`. Hard-blocks any symbol without a fresh PASS verdict. Fail-safe: missing/stale/FAIL → NO_TRADE. MES currently has a fresh PASS so only live-traded symbol is unaffected. | `docs/decisions/gate_v2_phase3_full.md`, `engine/backtest/gate_v2_policy.py` | S |
| **P0.5** MES forward-recorder feedback loop | **SHIPPED 2026-04-21 ~20:30 CT** — `feedback_aggregator.py` (pre-existing) now surfaced via new `TradingPipeline._inject_forward_recorder()` method. Injects `analyst_reports["forward_recorder_metric"]` (hit_rate, samples, degraded, last_hypothesis) for MES only. Because Bull/Bear/Trader prompts serialize `analyst_reports` as JSON, the metric becomes LLM-visible with zero prompt rewrite. 5 new tests (MES injects, degraded flag, non-MES no-op, exception swallowed, casing normalized). | `engine/agents/pipeline.py`, `engine/tests/test_feedback_aggregator.py` | M |
| **P0.6** `tradingview_mcp_healthy` in `/health` | **ALREADY SHIPPED** — `engine/routers/health_router.py:26-55` probes CDP port 9222 with 30s TTL cache, surfaces `tradingview_mcp_healthy` + optional `tradingview_mcp_details`. Live verified: `curl /health` → `"tradingview_mcp_healthy": true`. | `engine/routers/health_router.py` | XS |

**Exit criteria:**
- [ ] `/pipeline/run` returns non-empty signal with freshness ≤ 1 hour
- [ ] TV MCP auto-starts on login
- [ ] `/health` surfaces TV MCP state
- [ ] Gate v2 Phase 3-FULL: shipped OR explicitly deferred with signed memo
- [ ] Forward-recorder hit-rate visible in pipeline output

---

### PHASE 1 — Multi-Strategy Expansion (4 weeks: 2026-04-28 → 2026-05-26)

**Goal:** Break the single-strategy monoculture. Run 3 strategy families, one per instrument, with an honest regime-based router.

Current memory notes already analyzed what works per symbol:
- **MES** → SMA trend works (PF 1.765 live)
- **MCL** → mean-reversion family candidate (per-symbol decision memo `c4a1ef1`)
- **MNQ** → breakout family candidate (Donchian already scoped)

| Task | Deliverable | File(s) | Size |
|---|---|---|---|
| **P1.1** MCL mean-reversion family | Bollinger(20,2) + RSI divergence for MCL. Backtest Jan 2024 → present. Run gate v2. Ship if rank ≥ MARGINAL on ≥3/5 criteria. Remove MCL from `DO_NOT_TRADE_SYMBOLS` if it passes. | `engine/backtest/meanrev_signals.py`, router update in `signals.py` | L |
| **P1.2** MNQ breakout family | Donchian(20) + volume confirmation + opening-range filter. Same validation bar as MCL. | `engine/backtest/breakout_signals.py`, router update | L |
| **P1.3** Regime-aware strategy router | `engine/backtest/regime_classifier.py` → classifies current bar as TREND/MEANREV/RANGE/VOLATILE. Router dispatches to the appropriate strategy family per-symbol. | `engine/backtest/signals.py`, new `regime_classifier.py` | M |
| **P1.4** Per-strategy gate v2 verdict | Extend `gate_v2_orchestrator.py` to emit verdicts per (symbol, family) tuple. Live routing respects both per-symbol AND per-family verdicts. | `engine/scripts/gate_v2_orchestrator.py` | M |
| **P1.5** Shadow-mode for new strategies | Before any new family routes paper trades, it runs in shadow for ≥14 days — logs what it WOULD have done, compared to what actually happened. Exit criterion: ≥10 shadow trades with positive expectancy. | `engine/validation/shadow_mode.py` (new) | L |
| **P1.6** MES RV filter decision | Re-validate realized-vol filter at 9% and 13% thresholds after 60+ live trades (currently 36). If validated, switch from OFF default to ON. | `engine/backtest/trend_signals.py`, validation script | S |
| **P1.7** Consolidate duplicate routes (main.py → routers/) | Discovered during P0.3: `main.py` has ~50 route handlers that duplicate `routers/*` definitions. FastAPI registers main.py first, so router edits are silently ignored. Move all handlers out of `main.py`, leave only `app.include_router(...)`. Audit OpenAPI against pre-migration snapshot to confirm zero behavioral drift. | `engine/main.py`, `engine/routers/*.py` | L |
| **P1.8** Decouple scanner from uvicorn lifespan | Current state: lifespan runs ~3-4 min of pre-yield setup (RL model load, scheduler registration, SDK pipeline init) before uvicorn binds port 8010. Task 22's 20s TV timeout × 3-symbol chart-lock serialization made this worse — one first-pass scan can now consume up to 60s inside lifespan. Symptom: `/health` unreachable for 3-4 min after every restart; `restart_engine.ps1` prints ERROR on every restart even though the engine is healthy seconds later. Fix: move non-critical init (first scanner pass, cost-tracker warmup, MES forward-recorder schema ensure) to `asyncio.create_task` AFTER `yield`, so uvicorn binds first and heavy init runs in the background. Uvicorn should bind within ~10s of process start. Memory `feedback_restart_engine_ps1_slow_startup.md` documents the operator impact. | `engine/main.py:333-2018` (lifespan) | M |
| **P1.9** `/portfolio/summary` perf: cache or deflake `get_current_price` | Handler at `portfolio_router.py:147` awaits `_data_manager.get_current_price(sym)` per open position. Since TV became Tier 0 (P0.2), each call routes through the TV chart-lock + 11-20s symbol-switch subprocess. Observed latency: 24-26s consistently even with a single open position. Cascading impact: `test_portfolio_endpoint` had to bump urllib timeout 5s → 60s (commit `f252756`); `/portfolio/summary` is the default live-engine probe in `live_engine_probe.py`, so every test run penalizes startup. Fix options: (a) 30s TTL cache on current_price per symbol, (b) prefer IBKR ticker over TV for ticker-only reads, (c) `asyncio.wait_for` with 3s timeout + stale-price fallback. Pick (b) as primary; IBKR is already connected on port 4002 and delivers ticks in <100ms. | `engine/routers/portfolio_router.py`, `engine/data/market_data.py` (ticker vs bars split) | S |

**Exit criteria:**
- [ ] 3 strategy families live OR explicitly deferred per-symbol
- [ ] Regime classifier outputs reliably (≥70% agreement with manual labels on backtest sample)
- [ ] Gate v2 verdicts per (symbol, family) stored in JSON
- [ ] Shadow-mode framework reusable for any future strategy

---

### PHASE 2 — Real-Time Data Fabric (3 weeks: 2026-05-26 → 2026-06-16)

**Goal:** Replace batch CSV with event-driven data. Every price tick is a potential trigger.

| Task | Deliverable | File(s) | Size |
|---|---|---|---|
| **P2.1** TV MCP streaming | Subscribe to `tv stream all` (quote + bars + values) via WebSocket. Stream deltas into Redis. Replace polling `tv quote` with event-driven consumer. | `engine/data/tradingview_stream.py` (new), Redis pub/sub | L |
| **P2.2** Event-driven bar close hooks | When a new 1h bar closes, fire `bar_closed` event → router → strategies evaluate → pipeline decides → alert. Replaces scheduler-based polling. | `engine/events/` (new package) | M |
| **P2.3** Gamma Levels daily fetch | Gamma Levels indicator is already on your chart. Add daily scrape of gamma levels at 16:30 CT into `gamma_snapshot` table (schema v23). Feed into `mes_session_recorder`. | New `engine/data/gamma_fetcher.py`, schema migration | M |
| **P2.4** Corey bias ingestion | Corey is in your Discord. The bookmarks pipeline can filter Corey's bias posts. Aggregate daily bias into `corey_bias_daily` table. Already referenced in `mes_session_recorder` but feed is incomplete. | `engine/discord/corey_bias_extractor.py` | M |
| **P2.5** IBKR options chain fetch | Use `ib_async` to pull SPY/QQQ weekly chain daily at 09:00 CT. Write to `options_chain_snapshot` table. Foundation for Phase 5 options layer. | `engine/execution/ib_options_reader.py` | M |
| **P2.6** Data-integrity dashboard | New dashboard page showing each data source's freshness + error rate. Redis key: `datasource:*:last_update`. | `dashboard/app/data-integrity/page.tsx` | M |

**Exit criteria:**
- [ ] Bar-closed events fire within 2 seconds of TV bar close
- [ ] Gamma Levels auto-fetched daily, visible on dashboard
- [ ] Corey bias daily aggregate populated
- [ ] Options chain snapshots stored (not yet used — foundation)

---

### PHASE 3 — Agent Intelligence Upgrade (4 weeks: 2026-06-16 → 2026-07-14)

**Goal:** Replace rule-based decisions with LLM reasoning chains where reasoning genuinely helps. Skip where it's overkill.

Honest assessment of what LLM reasoning actually improves:
- ✅ **Debate orchestrator** — already works (Bull/Bear + scoring)
- ✅ **Advisor (Opus) for inconclusive debates** — already works per Track F
- ❓ **DeepSeek-R1 pre-processor** — unvalidated; skip unless RL experiments prove value
- ❌ **Full LLM-driven entries** — hallucinates; keep strategy engine as source of truth
- ✅ **Post-trade analysis** — strong use case (why did the trade win/lose?)

| Task | Deliverable | File(s) | Size |
|---|---|---|---|
| **P3.1** Multi-model ensemble routing | Opus: inconclusive debates + post-trade analysis. Sonnet: standard pipeline agents. Haiku: health checks, cache operations, bookmark clustering. Enforce via `engine/llm/model_router.py`. | `engine/llm/model_router.py` (new) | M |
| **P3.2** Confluence scoring | Replace single debate score with structured confluence across 6 dimensions: trend, mean-rev, breakout, volatility, macro, sentiment. Output 0–1 score per dimension. Trade requires ≥4/6 agreement at ≥0.6. | `engine/agents/debate.py` extension | L |
| **P3.3** Post-trade LLM analysis | After every closed paper trade, Opus writes a 200-word analysis: what fired, what worked, what didn't. Store in `trade_post_mortem` table. Monthly: aggregate common patterns. | `engine/agents/post_mortem.py` (new) | M |
| **P3.4** Trading Agent Reasoning Chains | Per installed skill `compound-engineering:trading-agent-reasoning-chains`. Wire DeepSeek-R1 as optional pre-processor for Bull/Bear researchers. A/B test: R1-preprocessed vs baseline over 30 days. | Skill integration + A/B harness | L |
| **P3.5** claude-mem cross-session memory | Agents currently have no cross-session context. Wire claude-mem so TraderAgent remembers last 20 trade outcomes + agent feedback patterns. | `engine/agents/memory_bridge.py` (new) | M |
| **P3.6** Agent reliability metrics | Per-agent accuracy tracking already exists (AgentFeedbackTracker). Extend: which agents contribute to winners vs losers? Auto-mute agents whose signal is inversely correlated with P&L over 30 trades. | `engine/analytics/agent_reliability.py` | M |

**Exit criteria:**
- [ ] Each pipeline run names the model used per agent + reason
- [ ] Confluence score visible on every decision
- [ ] Post-trade analyses generated automatically
- [ ] At least 1 agent muted automatically based on reliability data

---

### PHASE 4 — Automation & Approval Surfaces (3 weeks: 2026-07-14 → 2026-08-04)

**Goal:** You should be able to approve/reject/modify a trade within 60 seconds, from whatever device you're near.

| Task | Deliverable | File(s) | Size |
|---|---|---|---|
| **P4.1** WhatsApp interactive approval | Current WhatsApp alerts are informational. Upgrade: reply "Y" to approve, "N" to reject, "S 7095" to modify stop. Twilio supports interactive templates. | `engine/notifications/whatsapp_interactive.py` | L |
| **P4.2** voicemode approval | Use installed `voicemode` MCP: "JARVIS, approve MES long at 7141 stop 7093 target 7213" → parse → route to engine. Voice trigger for session-start brief. | MCP integration + grammar | L |
| **P4.3** Dashboard one-click approval | Pending-approvals widget on dashboard home. Large green APPROVE / red REJECT buttons. Keyboard shortcut Y/N. | `dashboard/app/page.tsx`, `dashboard/components/PendingApprovals.tsx` | M |
| **P4.4** Approval timeouts with fallback | If no approval within N minutes, trade auto-cancels (NOT auto-approves). Configurable per trade type. Default: 10 min for overnight, 5 min for RTH. | `engine/risk/approval_timeout.py` | M |
| **P4.5** Kill-switch remote triggers | WhatsApp: "KILL". Voice: "JARVIS, kill switch". Dashboard: big red button. All require typed confirmation "I confirm killing at [price]" to prevent fat-finger. | Router updates across notifications | M |
| **P4.6** Trade queue & batching | When multiple signals fire within a 10-min window, batch them into a single approval prompt ("3 signals: MES LONG, MCL SHORT, MNQ LONG — approve all? modify?"). | `engine/execution/trade_queue.py` | M |

**Exit criteria:**
- [ ] WhatsApp one-tap approval working end-to-end
- [ ] Voice approval works from phone (voicemode iOS)
- [ ] Dashboard auto-refreshes with pending approvals
- [ ] Kill switch triggerable from 3 surfaces

---

### PHASE 5 — Options Layer (6 weeks: 2026-08-04 → 2026-09-15)

**Goal:** Add defined-risk options strategies on SPY/QQQ. This is a significant scope expansion — handle with care.

| Task | Deliverable | File(s) | Size |
|---|---|---|---|
| **P5.1** Options chain ingestion (live) | Builds on P2.5 foundation. Poll full Greeks + IV surface every 15 min during RTH. Store in Redis + timescaledb. | `engine/data/options_chain_live.py` | L |
| **P5.2** Vertical spread strategies | Debit spreads on trend signals (match underlying SMA(50,200) state), credit spreads on mean-rev signals. Max risk defined by spread width. | `engine/backtest/options_spread_signals.py` | XL |
| **P5.3** Greeks-aware risk model | Portfolio delta, gamma, vega, theta caps. Block trades that push portfolio outside bounds. | `engine/risk/greeks_guard.py` | L |
| **P5.4** IV rank filter | Never enter short premium when IV rank < 25 (no edge). Never enter long premium when IV rank > 75 (too expensive). | Add filter to `options_spread_signals.py` | S |
| **P5.5** Options backtest harness | Backtest against 3 years of cached chains. Gate v2 equivalent for options (different metrics: max_loss_per_trade, % of time in drawdown, ITM expiration rate). | `engine/backtest/options_harness.py` | XL |
| **P5.6** Earnings calendar avoidance | Scrape Earnings Whisper / Zacks via Playwright MCP. Block options trades on underlyings with earnings in next 7 days. | `engine/data/earnings_calendar.py` | M |
| **P5.7** Assignment risk monitor | Track short-option positions within 5% of strike near expiration. Alert at 3 DTE. | `engine/risk/assignment_monitor.py` | M |

**Exit criteria:**
- [ ] Options paper trades logged for ≥30 days
- [ ] Gate v2 options-variant passes for at least one strategy
- [ ] No assignment surprises on shorts (or 100% handled pre-expiry)

---

### PHASE 6 — Instrument & Intelligence Expansion (8 weeks: 2026-09-15 → 2026-11-10)

**Goal:** Diversify beyond equity index futures. Add macro-calendar awareness.

| Task | Deliverable | File(s) | Size |
|---|---|---|---|
| **P6.1** Kraken MCP activation | Install kraken binary, activate MCP. Start with BTC spot/futures (no altcoins). | Kraken MCP setup + `engine/adapters/kraken_adapter.py` | M |
| **P6.2** BTC trend + mean-rev families | Same architecture as MES/MCL but on BTCUSD. Validate via gate v2. | New signal files | XL |
| **P6.3** Sector rotation ETFs | Weekly RSI of 11 sector SPDRs (XLF, XLK, XLE, etc.). Long top 2, short bottom 2. Paper-only initially. | `engine/backtest/sector_rotation.py` (extend existing) | L |
| **P6.4** Calendar-aware trading | Fed meetings, FOMC minutes, CPI, NFP, PCE. Block opening new positions in the 30 min before / 60 min after release. Known catalysts only. | `engine/data/macro_calendar.py` | M |
| **P6.5** News NLP on Fed statements | When FOMC statement drops, Opus reads it + dot plot + prior statement → 5-bullet diff → feed as context to next pipeline run. | `engine/agents/fed_nlp.py` | L |
| **P6.6** Multi-timeframe confluence | 1h signal + 4h trend + daily regime must align. Reject signals against higher-timeframe trend. | Router update + `timeframe_aligner.py` | M |

**Exit criteria:**
- [ ] BTC in live paper rotation
- [ ] Sector ETF strategy running 30+ days shadow
- [ ] Macro-calendar blocks working on ≥3 test events

---

### PHASE 7 — Meta-Learning Loop (ongoing from 2026-11-10)

**Goal:** System improves itself without you watching.

| Task | Deliverable | File(s) | Size |
|---|---|---|---|
| **P7.1** n-autoresearch loop live | Already scaffolded (`engine/strategies/discovery_loop.py`, `llm_sandbox.py`, `mes_search_space.json`). Turn on for 5-min GPU sessions nightly. | Activation + monitoring | M |
| **P7.2** Strategy drift detection | Every strategy tracked for PF degradation week-over-week. If live PF < 60% of backtest PF for 3 consecutive weeks, auto-shadow-mode the strategy and alert. | `engine/analytics/drift_detector.py` | M |
| **P7.3** A/B paper-canary framework | New strategies ALWAYS start as A/B canary: 50% of signals go to new, 50% to old. Run 30 days. Winner promotes, loser rolls back. | `engine/validation/ab_canary.py` | L |
| **P7.4** Auto-regenerating search space | Bayesian optimizer re-runs monthly against latest 90 days. If new optimal parameters differ from current by > 15%, alert — don't auto-deploy. | `engine/optimization/scheduled_rebayes.py` | M |
| **P7.5** Compound engineering skill integration | Use installed `compound-engineering:ce-compound` skill to document every solved problem into institutional knowledge. `ce-review` before shipping any Phase 1–6 task. | Skill usage conventions | XS (just discipline) |
| **P7.6** Weekly self-audit | Every Sunday 18:00 CT, a meta-agent runs: reviews past week's trades, identifies common patterns (winning regimes, losing setups), writes to `weekly_audit.md`. | `engine/agents/self_audit.py` | M |

**This phase never "ends" — it's the operating mode from here forward.**

---

## 3. Cross-Cutting Concerns

### 3.1 Observability

Every phase ships with:
- Metrics emitted to Grafana (latency, error rate, signal count, P&L delta)
- Structured logging (JSON, correlation IDs)
- Health endpoint updates

### 3.2 Cost controls

- Token proxy already live (Track G). Extend to log LLM cost per pipeline run.
- Monthly budget cap per model: Opus $200, Sonnet $100, Haiku $50 (adjust based on actuals).
- Hard kill-switch on any single pipeline run > $5.

### 3.3 Testing discipline

- **Unit tests**: every new signal function
- **Integration tests**: every new pipeline stage
- **End-to-end paper simulation**: every new strategy family, minimum 30 days shadow
- **Gate v2 verdict**: every new strategy before routing

Tier rule: **no live capital routes to any strategy that hasn't passed gate v2 AND 30 days shadow**.

### 3.4 Security

- Secrets stay in `engine/.env` (never commit)
- API_KEY rotation every 90 days
- IBKR paper port 4002 only until live-cutover decision (Tier 3)
- WhatsApp approval must include a 4-digit confirm token for live trades (when applicable)

### 3.5 Documentation

- Every new feature: one-pager in `docs/features/`
- Every Tier 3 decision: memo in `docs/decisions/`
- Every incident: incident note in `docs/incident-notes/`
- Roadmap (this file): review and update monthly

---

## 4. Quick Wins — THIS WEEK

Ordered by highest-value-per-minute:

1. **TV MCP startup persistence** (P0.1) — 30 min. Prevents re-doing today's activation.
2. **TV MCP → engine bar pipeline wire** (P0.2) — 4 hours. Unlocks every downstream feature. **Biggest single lever.**
3. **`/analyze/bars/MES` unblock test** (P0.3) — 1 hour. Confirms P0.2 works end-to-end.
4. **Gate v2 Phase 3 decision memo** (P0.4) — 2 hours of writing. Resolves the most architecturally-loaded open question.
5. **Forward-recorder feedback aggregator** (P0.5) — 3 hours. Turns observational data into decision-influencing signal.

Done in 1 week → full Phase 1 unblocked.

---

## 5. Decision Points Requiring Matt's Input

| # | Decision | When | Tier |
|---|---|---|---|
| D1 | Gate v2 Phase 3-FULL: adopt as routing-blocker, or keep advisory? | Week 1 | 3 |
| D2 | MCL mean-reversion: paper-trial approval to remove MCL from `DO_NOT_TRADE_SYMBOLS` after gate v2 passes | Week 4 | 3 |
| D3 | MNQ breakout: same as D2 for MNQ | Week 4 | 3 |
| D4 | MES RV filter: activate at 9% threshold after 60+ live trades | Week 6 | 3 |
| D5 | Options layer scope: SPY+QQQ only, or add individual equities? | Week 16 | 3 |
| D6 | Kraken activation: BTC paper-only first, or BTC+ETH from day 1? | Week 24 | 3 |
| D7 | Live capital cutover: any subset, or wait for all 3 strategies validated? | Phase 6 completion | 3 (highest stakes) |

Each of these gets its own decision memo under `docs/decisions/` when the time arrives.

---

## 6. Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| TV MCP breaks on TV Desktop update | Med | High | Nightly health check → WhatsApp alert if CDP dead |
| Gate v2 blocks all live trades (overly strict) | Low | Med | Phase 3-FULL gated behind explicit decision (D1); fallback to Phase 3-LIGHT |
| LLM cost explosion | Med | Med | Token proxy + monthly budget caps + per-run kill switch |
| Strategy family overfits on recent data | High | High | 30-day shadow + A/B canary is mandatory; no direct promotion |
| IB Gateway disconnect mid-position | Low | High | Heartbeat monitor → WhatsApp alert; all stops are broker-side (GTC) |
| Single-machine failure | Med | High | Weekly snapshot of `engine/data/` to cloud storage; infrastructure docker-composable |
| Regulatory (futures tax, Section 1256 reporting) | Low | Med | Annual review with CPA; trade journal export ready for tax |
| Burnout (feature velocity > maintenance) | High | High | Every new feature must come with shadow-mode period; no multi-phase skips |

---

## 7. Out of Scope (Explicitly Deferred)

- Reddit/Twitter sentiment for futures (per existing memory rule `futures_sentiment_source`)
- Greenfield Metal Sales integration (per primary focus directive)
- HFT / sub-second strategies (structural mismatch with 1h signal cadence)
- Dark pool prints (no reliable free data source for futures)
- Copy-trading or signal-publishing to other users (single-user system by design)
- iOS native app (voice + WhatsApp + dashboard is sufficient surface coverage)

---

## 8. Definition of "State of the Art" for JARVIS TRADER

Not every cutting-edge capability belongs. The system is state-of-the-art when:

1. **Signal-to-decision latency < 60 seconds** (event-driven, not polling)
2. **Zero stale-data decisions** (all signals gated on freshness)
3. **Multi-strategy + regime-aware** (right tool for the tape)
4. **Statistically-governed promotion** (gate v2 + shadow + A/B; no vibes)
5. **Paper-parity with live** (same code path, different broker flag)
6. **Multi-surface approval** (you're never forced to a specific device)
7. **Self-documenting** (every trade has post-mortem; every decision has memo)
8. **Continuously learning** (n-autoresearch + drift detection)
9. **Full cost accounting** (every LLM call, every API call, every trade has $ attribution)
10. **Agent-native by default** (any action you can take, an agent can take too)

Checklist stays here. Monthly self-audit marks progress.

---

## 9. References

- `C:\Users\mattm\.claude\projects\C--windows-system32\memory\MEMORY.md` (recent commits + state)
- `C:\Users\mattm\ThinkorSwim\jarvis-trader\docs\CURRENT_STATE.md`
- `C:\Users\mattm\ThinkorSwim\jarvis-trader\docs\JARVIS_TRADER_UNIFIED_CANON.md`
- `C:\Users\mattm\.claude\skills\jarvis-trader\SKILL.md`
- `C:\Users\mattm\.claude\plans\utilize-tradingview-mcp-and-twinkling-sprout.md` (today's plan)
- Gate v2 proposal: `project_gate_v2_proposal.md`
- MES session hypothesis: `project_mes_forward_recorder.md`
- `engine/strategies/` — RL scaffolding

---

**Next review:** 2026-05-21 (1 month)
**Status:** Draft v1 — awaiting Matt's sign-off on D1 (Gate v2 Phase 3-FULL) before Phase 0 ships.
