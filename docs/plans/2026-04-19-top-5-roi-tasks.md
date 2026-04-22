# Top 5 ROI Tasks — JARVIS TRADER (2026-04-19)

**Date**: Sunday, April 19, 2026
**Author**: Claude (Opus 4.7) + Matt Morrison
**Scope**: Paper-approved instruments (MCL + MNQ). MES bypass still active.
**Ranking criterion**: dollar-delta-per-hour-of-effort, grounded in verified code state (see audit sub-agent report).
**Total effort**: ~15 hours. Weekend sprint.

---

## At a Glance

| # | Task | Effort | ROI Category | Gate? |
|---|------|--------|--------------|-------|
| 1 | Activate Bayesian optimizer → re-tune MCL & MNQ | ~3 h | Direct Sharpe/PF lift | No |
| 2 | PRAW Reddit credentials → live futures sentiment | ~1 h | New signal source | No |
| 3 | IB Gateway paper E2E integration test | ~4 h | Live-trade prerequisite | **YES — required before real capital** |
| 4 | Discord/DCE token refresh + staleness alert | ~2 h | Prevent Corey signal drift | No |
| 5 | Futures data fallback (IBKR historical primary) | ~5 h | Data-source redundancy | No |

---

## Task 1 — Activate Bayesian Optimizer + Re-Tune Paper-Approved Symbols

**Why this is #1**: scikit-optimize is already installed in `engine/.venv` (per MEMORY.md 2026-04-10 note) but not in `requirements-core.txt` — so any `pip install -r` in CI or rebuild will drop it. The `/wfe/optimize-bayesian` endpoint exists at `engine/routers/wfe_router.py:347-383` and currently falls back to random search because `_SKOPT_AVAILABLE` is False until engine restart + pinned dependency. One line of dependency + one restart unlocks real Bayesian parameter tuning on the 5-layer regime + STC(15,83) + ATR(0.70x/1.50x) stack.

**Files touched**:
- `engine/requirements-core.txt` (+1 line)
- `engine/backtest/bayesian_optimizer.py` (no change, verify import)
- `engine/routers/wfe_router.py` (no change, verify endpoint)

**Checklist**:
- [ ] **1.1** Open `engine/requirements-core.txt`, add `scikit-optimize==0.10.0` after the pytest deps (around line 84).
- [ ] **1.2** Activate venv: `C:\Users\mattm\ThinkorSwim\jarvis-trader\engine\.venv\Scripts\activate`
- [ ] **1.3** Verify install: `pip show scikit-optimize` (should report 0.10.0 or 0.10.2). If missing, `pip install scikit-optimize==0.10.0`.
- [ ] **1.4** Restart engine cleanly: `.\restart_engine.ps1` (do NOT use `--reload` — see MEMORY.md).
- [ ] **1.5** Confirm port 8010 has no orphan holder: `netstat -ano | grep ":8010 "` (only one PID should match the fresh PM2 process).
- [ ] **1.6** Smoke-test endpoint for MCL 1h (the paper-approved symbol with highest WFE=0.82):
  ```bash
  curl -X POST http://localhost:8010/wfe/optimize-bayesian \
    -H "X-API-Key: ${JARVIS_API_KEY}" \
    -H "Content-Type: application/json" \
    -d '{"symbol":"MCL","timeframe":"1h","start":"2025-01-01","end":"2025-06-01","n_calls":30}'
  ```
  Verify response has `"method":"bayesian"` (NOT `"random_fallback"`).
- [ ] **1.7** Repeat 1.6 for MNQ 1h (WFE=0.57, larger headroom for improvement).
- [ ] **1.8** Compare new `best_params` vs. current live config in `engine/config.py`. If improvement is ≥5 % on composite score (WFE × PF × Sharpe / σ), promote params to config via PR-style diff.
- [ ] **1.9** Re-run the affected walk-forward backtest to confirm the promoted params actually improve out-of-sample, not just in-sample. Reject promotion if OOS degrades.
- [ ] **1.10** Commit with message `feat(wfe): activate Bayesian optimizer + retune MCL/MNQ params`.

**Done criteria**: `method=bayesian` in endpoint response AND new params produce non-degraded OOS on at least one paper-approved symbol.

**Risk**: Over-fit to the specific window (2025-01-01 → 2025-06-01). Mitigation: step 1.9 OOS verification.

---

## Task 2 — PRAW Reddit Credentials → Live Futures Sentiment

**Why this is #2**: PRAW 7.8.1 is already in `requirements-core.txt:59`. The `social_analyst.py:347` agent lazy-loads PRAW and has `FUTURES_SUBREDDIT_MAP` at lines 30-35 routing MCL → `r/oil`, MNQ → `r/wallstreetbets`, etc. But production env is missing `REDDIT_CLIENT_ID` + `REDDIT_CLIENT_SECRET` → silent fallback to ApeWisdom (equity-only). One hour of paperwork unlocks a permanent new signal channel specifically for futures.

**Files touched**:
- `engine/.env` (+2 env vars)
- `engine/agents/social_analyst.py:341-360` (add warning log if creds missing)

**Checklist**:
- [ ] **2.1** Register a Reddit app at https://www.reddit.com/prefs/apps → "script" type. Name: `jarvis-trader-sentiment`. Redirect URI: `http://localhost:8080` (unused for script-type).
- [ ] **2.2** Copy `client_id` (under app name) and `client_secret`.
- [ ] **2.3** Add to `engine/.env`:
  ```
  REDDIT_CLIENT_ID=<id>
  REDDIT_CLIENT_SECRET=<secret>
  REDDIT_USER_AGENT=jarvis-trader/1.0 by u/mattamundson
  ```
- [ ] **2.4** Add a startup warning in `engine/agents/social_analyst.py` around line 341: if `REDDIT_CLIENT_ID` is empty, log `logger.warning("PRAW credentials missing — falling back to ApeWisdom (equities only)")`. One line, prevents silent degradation.
- [ ] **2.5** Restart engine: `.\restart_engine.ps1`.
- [ ] **2.6** Verify via health endpoint or agent log: query `GET /sentiment/futures?symbol=MCL` and confirm response contains `"source":"reddit_praw"` (not `"source":"apewisdom"`).
- [ ] **2.7** Manually inspect 3 sample sentiment payloads for MCL / MNQ / MES — confirm subreddit routing matches `FUTURES_SUBREDDIT_MAP`.
- [ ] **2.8** Add a regression test in `engine/tests/test_social_analyst.py`: mock PRAW response, assert the agent returns non-null sentiment when creds present, falls back when absent.
- [ ] **2.9** Commit: `feat(social): wire PRAW creds for live futures sentiment`.

**Done criteria**: `/sentiment/futures?symbol=MCL` returns PRAW-sourced data in prod; missing-creds path logs a warning instead of failing silently.

**Risk**: Reddit API rate limits (60 req/min for script apps). Mitigation: the agent already caches via `engine/utils/token_proxy.py` (300s TTL, 200 entries).

---

## Task 3 — IB Gateway Paper E2E Integration Test

**Why this is #3**: `engine/tests/test_ib_gateway_connector_offline.py:29-49` covers the unit slice (paper order submission to port 4002) but there is no test that exercises the *full* pipeline: signal generation → debate → trader agent → IB paper order → ledger capture → trade_outcomes row. This is a **gate**: without it, every live trade is unverified and Matt can't confidently commit real capital. The current state of `MEMORY.md` flags this as "passive item" but it's actually the highest-stakes gap in the system.

**Files touched**:
- `engine/tests/integration/test_ib_paper_e2e.py` (new, ~150 lines)
- `engine/connectors/ib_gateway.py` (verify paper-mode path)

**Checklist**:
- [ ] **3.1** Confirm IB Gateway is installed. If not: download from Interactive Brokers, install, login with paper account DUP662235.
- [ ] **3.2** Launch IB Gateway in PAPER mode → port 4002 (NEVER 4001 — permanently blocked per MEMORY.md).
- [ ] **3.3** Verify engine sees it live: `curl http://localhost:8010/health | jq .market_data_connector` — expect `"connected":true` for market data (not just execution).
- [ ] **3.4** Create `engine/tests/integration/__init__.py` if not present.
- [ ] **3.5** Write `engine/tests/integration/test_ib_paper_e2e.py` with the following scenarios:
  - [ ] **3.5.a** `test_signal_to_paper_order_mcl`: inject a deterministic MCL signal → run through full pipeline → assert paper order lands in IB paper account within 5 s.
  - [ ] **3.5.b** `test_paper_fill_captured_in_ledger`: wait for fill → assert `paper_trades` row inserted with correct side, qty, entry price, stop.
  - [ ] **3.5.c** `test_inverted_stop_rejected_at_patch`: submit a PATCH that flips stop to wrong side → assert HTTP 422 (validates the 2026-04-16 invariant fix stays wired).
  - [ ] **3.5.d** `test_kill_switch_blocks_new_orders`: activate kill switch → submit signal → assert order is suppressed and WhatsApp notification sent.
- [ ] **3.6** Mark test suite with `@pytest.mark.integration` and `@pytest.mark.requires_ib_gateway` so CI skips when IB isn't running.
- [ ] **3.7** Run: `pytest engine/tests/integration/test_ib_paper_e2e.py -v`.
- [ ] **3.8** If any test fails, FIX THE CODE, not the test (this is a real bug you want to catch).
- [ ] **3.9** Add a manual runbook entry in `docs/runbooks/paper-trade-smoke.md` — 10-step procedure for pre-session smoke test.
- [ ] **3.10** Commit: `test(integration): IB Gateway paper E2E pipeline coverage`.

**Done criteria**: All 4 scenarios pass against a live IB Gateway paper session. Test suite runs end-to-end in <60 s.

**Risk**: IB Gateway loses connection mid-test (known flaky in Windows). Mitigation: tests use retry decorator, health probe before each scenario.

---

## Task 4 — Discord/DCE Token Refresh + Staleness Alert

**Why this is #4**: Corey's alerts feed `corey_session_bias` (64,943 rows fresh through 2026-04-01) which is consumed by the debate + trader agents. The DCE (DiscordChatExporter) export script is scheduled at `engine/main.py:1483-1527` (Mon-Fri 06:00 CT via APScheduler) but DCE requires a valid Discord token. If the token silently expires, exports fail, `corey_session_bias` goes stale, and no alarm fires. This is a **silent-degradation class** — the worst kind of bug.

**Files touched**:
- `engine/scripts/nightly_discord_export.py:45-57` (add token validation)
- `engine/notifications/openclaw_notifier.py` (add `notify_corey_stale()` method)
- `engine/main.py` (wire staleness check to hourly scheduler)

**Checklist**:
- [ ] **4.1** Open `engine/scripts/nightly_discord_export.py`. Around line 45, add a pre-flight check: call the DCE CLI with `--help` or a 1-message dry run to validate token before attempting full export.
- [ ] **4.2** If validation fails, write a sentinel file `engine/data/discord_export_failed_<YYYY-MM-DD>.flag` AND log an error with the Discord error code.
- [ ] **4.3** Add a new method in `engine/notifications/openclaw_notifier.py`: `notify_corey_stale(days_stale: int, last_msg_date: str)` — sends a WhatsApp message to Matt with the last ingested Corey message date and a link to rotate the token.
- [ ] **4.4** In `engine/main.py`, add an hourly APScheduler job that queries `SELECT MAX(timestamp) FROM corey_session_bias` — if the max is more than 48 h stale during a weekday, fire `notify_corey_stale()`.
- [ ] **4.5** Write a regression test: `engine/tests/test_corey_staleness_alert.py` that seeds a 72 h-old bias row and asserts the notifier fires.
- [ ] **4.6** Document token-rotation procedure in `docs/runbooks/discord-token-rotation.md` (5-step, ~10 min).
- [ ] **4.7** Test rotation manually — rotate now, verify DCE still works, verify staleness alert doesn't fire.
- [ ] **4.8** Commit: `feat(discord): staleness alert + token validation`.

**Done criteria**: Simulating a 3-day-old `corey_session_bias` triggers a WhatsApp alert within 1 hour. Token validation fails loudly, not silently.

**Risk**: WhatsApp rate-limits on alert flood. Mitigation: alert fires once per 24 h per staleness window (dedupe key in the notifier).

---

## Task 5 — Futures Data Fallback (IBKR Historical as Primary)

**Why this is #5**: Polygon is disabled for futures (the stock-symbol-collision incident, 2026-04-16). The system currently depends on CSV cache for history and IBKR snapshots for current price. If the CSV cache goes stale (e.g., IB Gateway was off for 3 days), backtests + signal generation degrade with no warning. A fallback chain (IBKR historical bars → yfinance for equities → optionally Databento paid for futures) eliminates this single point of failure.

**Files touched**:
- `engine/data/market_data.py:get_historical_bars()` (new fallback chain)
- `engine/data/ibkr_historical.py` (new, ~80 lines)
- `engine/tests/test_market_data_fallback.py` (new)

**Checklist**:
- [ ] **5.1** Verify IBKR `reqHistoricalData` works for MCL/MNQ continuous contract via paper gateway (port 4002). IB supports this natively for futures without extra subscriptions.
- [ ] **5.2** Create `engine/data/ibkr_historical.py` with a single function `fetch_ibkr_bars(symbol, timeframe, start, end) -> pd.DataFrame`. Mirror the schema of the existing `fetch_polygon_bars` in `market_data.py`.
- [ ] **5.3** In `engine/data/market_data.py:get_historical_bars()`, add a fallback chain: attempt Polygon (for equities only, skip for futures via existing blocklist) → fallback to IBKR historical → fallback to CSV cache → raise.
- [ ] **5.4** Add a `data_source` field to the returned DataFrame's metadata so downstream consumers (backtest, signal, WFE) can log which source produced the bars.
- [ ] **5.5** Wire a health probe: `GET /data/source-status?symbol=MCL` returns which source the last request hit and the latency breakdown.
- [ ] **5.6** Add a test file `engine/tests/test_market_data_fallback.py` with:
  - [ ] **5.6.a** Polygon blocklist hit → IBKR path used for MCL.
  - [ ] **5.6.b** IBKR unavailable (mock exception) → CSV cache path used.
  - [ ] **5.6.c** CSV cache stale (>7 days) → exception raised with helpful message.
- [ ] **5.7** Re-run the existing `engine/scripts/audit_polygon_contamination.py` to confirm no contamination was reintroduced.
- [ ] **5.8** Benchmark: fetch 6 months of MCL 1h bars via each path. Target: IBKR < 5 s, CSV < 1 s. If IBKR is slow, cache-warm it.
- [ ] **5.9** Update `docs/data-source-audit-2026-04-16.md` with the new fallback chain diagram.
- [ ] **5.10** Commit: `feat(data): IBKR historical bars as fallback for futures`.

**Done criteria**: MCL/MNQ bar requests succeed via IBKR when Polygon is blocklisted AND gracefully fall through to CSV when IBKR is offline. All 3 test scenarios pass.

**Risk**: IBKR pacing violations (they're strict — 60 req/10 min historical). Mitigation: step 5.8 includes cache warming + rate limiter in `ibkr_historical.py`.

---

## Execution Order Recommendation

Do them in this sequence (lower-effort first — faster wins, context stays cached):

1. **Task 2 — PRAW** (1 h) — start here, one Reddit-app registration and you're done.
2. **Task 1 — Bayesian** (3 h) — restart engine after 2.5 to pick up BOTH changes at once.
3. **Task 4 — Discord staleness** (2 h) — quick notifier wiring.
4. **Task 3 — IB Gateway E2E** (4 h) — needs IB Gateway boot, so group with any other manual steps.
5. **Task 5 — Data fallback** (5 h) — largest scope, best done with a fresh mind.

---

## Out of Scope (explicit NOT-doing)

- MES overfit retune (WFE=0.09) — Matt has bypass active; deep work, not this weekend.
- TradingView/Kraken integration (2026-04-16) — dormant until `npm link tv` + kraken binary.
- career-ops submitter bug fixes — separate project per PRIMARY FOCUS DIRECTIVE.
- Obsidian Web Clipper — DONE 2026-04-19 (separate session, this turn).

---

## Verification Summary (post-sprint)

Run this at the end to confirm everything landed:

```bash
cd C:/Users/mattm/ThinkorSwim/jarvis-trader
git log --oneline -5   # 5 new commits
pytest engine/tests/integration/test_ib_paper_e2e.py -v
pytest engine/tests/test_market_data_fallback.py -v
pytest engine/tests/test_corey_staleness_alert.py -v
curl -s -X POST http://localhost:8010/wfe/optimize-bayesian \
  -H "X-API-Key: ${JARVIS_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"symbol":"MCL","timeframe":"1h","start":"2025-01-01","end":"2025-06-01","n_calls":10}' \
  | jq .method   # should print "bayesian"
curl -s http://localhost:8010/sentiment/futures?symbol=MCL | jq .source   # should print "reddit_praw"
```

All 5 green → sprint complete.

---

# PHASE 2 — Post-Sprint Plan

**Triggered by**: Matt's request to refactor MES as the primary trading tool and consolidate all Discord knowledge, plus wake up TradingView/Kraken.

**Prerequisites**: Phase 1 complete + IB Gateway live + Reddit creds registered. Do not start Phase 2 until Corey watchdog has fired at least one healthy "no-op" check in production (confirms the full pipeline).

## Phase 2 At a Glance

| # | Task | Effort | Risk |
|---|------|--------|------|
| 6 | **MES refactor → primary trading tool** (retune from WFE=0.09) | ~12 h | HIGH — tuning changes real-capital signal quality |
| 7 | **TradingView wake-up** — wire `tradingview_feed.py` into live pipeline | ~4 h | MED — TV is a snapshot source, not a bar source |
| 8 | **Kraken wake-up** — wire `kraken_adapter.py` for crypto paper trading | ~6 h | MED — new market class (crypto 24/7, no Globex gating) |
| ~~9~~ | ~~PRAW subreddit expansion~~ — **REMOVED 2026-04-19 by owner directive**: Reddit is NOT trusted for futures sentiment. Corey Sures #market-updates is the sole futures sentiment source. See Task 10 for the consolidation of that trusted source. | — | — |
| 10 | **Discord knowledge consolidation** — expand beyond 1 agent consumer | ~8 h | MED — touches 5 agents |

**Total Phase 2**: ~30 h. Two-weekend sprint. (Task 9 removed — see owner directive below.)

---

## Task 6 — MES Refactor: Un-Bypass, Retune, Elevate to Primary

### Grounded premise (verified 2026-04-19 audit)

MEMORY.md's "MES bypass active" note is **stale**. Current reality:
- `TRADING_SYMBOLS="MCL,MNQ,MES"` (engine/config.py:482) — MES is enabled.
- MES uses identical `tick_value=12.50`, `tick_size=0.25`, same stop/target arrays as MCL/MNQ.
- MES is **subject to** the MAX_CONTRACTS_PER_INSTRUMENT=2 hard cap (no owner exemption in code).
- MES WFE is 0.09 (severe overfit); best backtest: PF=5.27, Sharpe=4.16, +47.2% — likely in-sample only.

**What "refactor MES to be the tool we use" actually requires**:
1. **Retune** params to raise OOS WFE from 0.09 to ≥0.50 (the paper-approved threshold).
2. **Elevate** MES priority in pipeline ordering + capital allocation.
3. **Verify** contract specs match CME (MES = Micro E-mini S&P 500, $5/point — audit confirm tick_value formula).
4. **Update MEMORY.md** to remove "bypass active" notes.

### Subtasks

- [ ] **6.1** **Contract-spec audit**: Open `engine/data/market_data.py` + `engine/config.py`. Verify MES is $5/point (tick_value = 12.50 means $12.50 per 0.25 tick = $50/point — **THIS IS WRONG**, MES is $5/point). Grep for `12.50.*MES` and `5\.0.*MES`. File a FIXME breadcrumb if wrong. Compare against CME product spec (https://www.cmegroup.com/markets/equities/sp/micro-e-mini-sandp-500.contractSpecs.html).
- [ ] **6.2** **Baseline benchmark** — run full WFE on MES via `/wfe/refresh?symbol=MES` and record current params + metrics as the "before" snapshot in `docs/mes-retune/baseline-2026-04-19.json`.
- [ ] **6.3** **Bayesian retune** — `/wfe/optimize-bayesian` with n_calls=100 across the widest STC+ATR param ranges the optimizer will accept. 3 windows: in-sample (2024-Q1), validation (2024-Q2), out-of-sample (2025-Q1-Q2). Reject any params whose OOS score is ≥20% below in-sample (overfit detector).
- [ ] **6.4** **Composite-score bug check** — Phase 1 observed MNQ has Sharpe=2.78 + PF=0.39 simultaneously. Inspect `engine/backtest/bayesian_optimizer.py` `_compute_composite_score()` function — if it weights Sharpe without PF gate, add `if pf < 1.0: return -inf` so the optimizer can't pick losing strategies with high Sharpe.
- [ ] **6.5** **Monte Carlo verification** — run 10,000 shuffled-trade Monte Carlo on the retuned MES params. Require median P&L > 0 and 5th-percentile drawdown < 15%.
- [ ] **6.6** **Elevate MES in pipeline** — `engine/agents/pipeline.py` currently iterates symbols in TRADING_SYMBOLS order. Change to iterate MES first (it has the highest contract value = highest ROI per signal) or sort by a capital-efficiency score.
- [ ] **6.7** **Capital allocation update** — $10K total / $5K per instrument is current. If MES becomes primary, re-balance: MES=$5K, MCL=$2.5K, MNQ=$2.5K. Update MAX_POSITION_SIZE_PCT per symbol in `engine/config.py`.
- [ ] **6.8** **Paper-trade validation** — before going live, run MES-primary config for 10 paper trading days. Promote only if realized Sharpe ≥ 1.5 and no more than 2 consecutive losing days.
- [ ] **6.9** **Update MEMORY.md** — remove the "MES Fund Manager bypassed by owner" and "MES testing bypass active" notes. Replace with the new MES-primary config summary.
- [ ] **6.10** **Update all tests that reference MES as secondary** — grep tests for `paper_approved.*MCL.*MNQ` patterns, add MES.

**Done criteria**: MES paper-trade 10-day realized Sharpe ≥ 1.5, WFE ≥ 0.50, Monte Carlo median P&L > 0.

**Risk hedge**: Phase 1 Task 3 (IB E2E test) must be passing before starting Task 6.8.

---

## Task 7 — TradingView Wake-Up

### Grounded premise

`engine/data/tradingview_feed.py` is code-complete but not wired into the main data pipeline. It uses `tradingview-mcp` CLI and gracefully degrades. `engine/routers/tradingview_router.py` exposes endpoints but they aren't called by the pipeline.

### Subtasks

- [ ] **7.1** Verify TradingView Desktop is installed. If not, install + log in.
- [ ] **7.2** Install `tradingview-mcp` CLI: `pnpm link tv` (per MEMORY.md note). Verify with `tradingview-mcp --version`.
- [ ] **7.3** Chrome CDP setup: launch Chrome with `--remote-debugging-port=9222` so `tradingview_feed.py` can reach it. Add a one-line runbook entry in `docs/runbooks/tradingview-boot.md`.
- [ ] **7.4** Wire `tradingview_feed.py` as **Tier 2.5** in `MarketDataManager.get_bars()` — between IBKR and Polygon. It's a snapshot source, so wrap it: if request is for historical bars, skip TV; if current-price-only, include TV.
- [ ] **7.5** Add `attrs["source"] = "tradingview"` to the new branch and corresponding test case in `test_market_data_fallback.py`.
- [ ] **7.6** Expose `tradingview_router.py` endpoints under `/tradingview/*` via `main.py` — currently `include_router` is absent. Verify endpoints return HTTP 200.
- [ ] **7.7** Integration test: `engine/tests/test_tradingview_integration.py` — skips if TV Desktop not detected, else asserts price parity between TV and IBKR (within 0.5%).
- [ ] **7.8** Commit: `feat(market-data): wire TradingView feed as Tier 2.5 snapshot source`.

**Done criteria**: `/market/data-source-status?symbol=SPY&timeframe=1m` returns `"source":"tradingview"` when TV Desktop is running.

---

## Task 8 — Kraken Wake-Up (Crypto Paper Trading)

### Grounded premise

`engine/markets/crypto/kraken_adapter.py` is a full async wrapper around the `kraken-cli` Rust binary with paper/live mode switching. No pipeline integration.

### Subtasks

- [ ] **8.1** Install `kraken-cli` binary (per MEMORY.md note). Verify with `kraken --version`.
- [ ] **8.2** Add `KRAKEN_API_KEY` + `KRAKEN_API_SECRET` to `.env.example` (public-read paper keys OK to document as empty).
- [ ] **8.3** Define the minimum crypto watchlist: BTC, ETH only (24/7 markets, no Globex gating — this is a design change).
- [ ] **8.4** Update `engine/risk/safety_layer.py` `_is_globex_open()` → add crypto exemption: if symbol in crypto watchlist, skip Globex gate.
- [ ] **8.5** Wire the adapter into the pipeline: add `engine/markets/crypto/crypto_pipeline.py` that calls Kraken for bars and routes paper orders through the adapter (parallel to futures pipeline, not mixed).
- [ ] **8.6** New dashboard tab (if needed): `/crypto/positions` — mirror `/portfolio/positions` shape.
- [ ] **8.7** Integration test: `engine/tests/test_kraken_paper.py` — skips if `kraken-cli` not on PATH, else places a paper BTC order and verifies fill.
- [ ] **8.8** Weekly budget check — crypto exposure cap 10% of total capital ($1K on $10K book) enforced at safety layer.
- [ ] **8.9** Commit: `feat(crypto): wire Kraken adapter for BTC/ETH paper trading`.

**Done criteria**: A BTC paper BUY survives the full pipeline (signal → debate → trader → Kraken fill → ledger row).

**Risk**: Crypto volatility is higher than futures. Position sizing rules must adapt — add a crypto-specific MAX_POSITION_SIZE_PCT = 2.0 (half of futures).

---

## Task 9 — ~~PRAW Subreddit Expansion~~ **REMOVED (2026-04-19 owner directive)**

Verbatim directive: *"Futures-specific Reddit sentiment is not a signal I trust —
the only futures information I trust should be from the Corey Sures auction-theory
tools Discord in the channel #market-updates."*

**Enforcement landed in Phase 1 revert:**
- `engine/agents/social_analyst.py:328-356` — `_fetch_reddit_praw()` hard-gates off any
  symbol in `FUTURES_SUBREDDIT_MAP` and returns `None` before touching PRAW.
- Module docstring records the directive verbatim.
- `engine/tests/test_social_analyst_praw.py::test_praw_futures_policy_gate_never_queries_reddit`
  — parametrized over MES, MNQ, MCL, MGC — asserts `praw.Reddit` is never constructed
  for futures. Any future edit that leaks futures to PRAW breaks CI.
- `engine/.env.example` — Reddit env vars commented out; note that they only affect
  equity tickers if uncommented.

**Replacement path**: invest Task 9's budget into **Task 10 (Discord consolidation)**,
specifically elevating `discord_corey_commentary` → `corey_session_bias` as a
first-class evidence channel for every futures agent.

---

## Task 10 — Discord Knowledge Consolidation

### Grounded premise (from Phase 2 audit)

Discord already has:
- 4 DB tables (`discord_bot_signals`, `discord_ib_reports`, `discord_corey_alerts`, `discord_corey_commentary`)
- 8 ETL modules in `engine/discord/`
- 6 REST endpoints in `discord_router.py`
- 2 analytics modules in `engine/analysis/`
- 52 raw JSON files in `C:\Users\mattm\discord-export\`

**But only 1 agent consumes it**: `corey_auction_analyst.py`. The other 5+ pipeline agents (technical, debate, bull/bear researcher, trader) are blind to Discord signals.

### Consolidation goals

1. **Unified briefing interface** — one function (`get_discord_briefing(symbol, lookback_hours)`) that every agent can call.
2. **Expand consumption** — wire discord briefings into `debate.py`, `trader.py`, and `bull_researcher`/`bear_researcher`.
3. **Weekly auto-export** check — the PS1 Saturday export script should emit a completion event.

### Subtasks

- [ ] **10.1** Write `engine/discord/briefing.py` — new module exposing `get_discord_briefing(symbol, lookback_hours=24)` that returns: `{session_bias, bot_signals_active, corey_alerts_recent, key_levels, summary_text}`. Consolidate logic from `commentary_processor.py`, `signal_context.py`, and `ib_levels.py`.
- [ ] **10.2** Wire briefing into `debate.py` — both Bull and Bear researchers gain a `discord_evidence` field in their evidence scoring. Corey's session_bias becomes a +0.1 or -0.1 evidence adjustment.
- [ ] **10.3** Wire briefing into `trader.py` — if Corey's session_bias contradicts trader's direction with high conviction, require Advisor (Opus) consultation via existing `AdvisorClient`.
- [ ] **10.4** Add `engine/agents/fundamental_analyst.py` (NEW) if one doesn't exist — consumes Discord IB reports and Corey macro commentary for a "market structure" layer.
- [ ] **10.5** Briefing cache: 5-minute TTL in-process cache (reuse existing `engine/utils/token_proxy.py` pattern). Agents hitting the briefing many times per pipeline run don't pay the DB cost N times.
- [ ] **10.6** New router endpoint: `GET /discord/briefing?symbol=MCL&hours=24` — exposes the same briefing so dashboards can show it.
- [ ] **10.7** Regression tests: `engine/tests/test_discord_briefing.py` — golden-file test with 1 seeded commentary row per scenario, assert briefing output is stable.
- [ ] **10.8** **Weekly-export heartbeat** — `engine/scripts/discord_weekly_export.ps1` must write `.last_export_utc` file. Watchdog (similar to Task 4 Corey staleness) alerts if this file is > 8 days old.
- [ ] **10.9** Commit: `feat(discord): unified briefing + multi-agent consumption`.

**Done criteria**: In a pipeline run for MCL, at least 3 agents log that they consumed Discord briefings; `/discord/briefing` endpoint returns structured data; weekly-export heartbeat alert fires in simulation.

---

## Phase 2 Execution Order

Do Phase 2 tasks in this order (Task 9 removed):

1. **Task 10 — Discord consolidation** (8 h) — highest ROI. Corey's #market-updates is now the official futures sentiment channel; every futures agent should consume it.
2. **Task 6 — MES refactor** (12 h) — the big one. Requires Task 10 first so MES agents consume Corey's signal, not noise.
3. **Task 7 — TradingView** (4 h) — additive data source; no dependencies.
4. **Task 8 — Kraken** (6 h) — largest surface-area change. Crypto is a new market class; do it last.

---

## Cross-Phase Invariants

Regardless of execution order:

- Every data source change must update `attrs["source"]` (Task 5 contract).
- Every new alert must have same-day dedupe (Task 4 pattern).
- Every new paper order must pass through `SafetyLayer.submit_paper_order()` (existing invariant).
- Every commit message follows `feat:/fix:/refactor:/test:/docs:` convention (MEMORY.md rule).
- Never mock the DB in tests that touch migrations (MEMORY.md testing rule).
- **Futures sentiment = Corey #market-updates ONLY (2026-04-19 owner directive).** No Reddit,
  no ApeWisdom, no Twitter, no generic retail chatter. Any PR that opens a non-Corey
  futures sentiment path must be rejected. Equity sentiment via PRAW / ApeWisdom / StockTwits
  remains permitted since it never feeds futures decisions.
