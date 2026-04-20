# Unified Implementation Roadmap — JARVIS TRADER (2026-04-20)

> **Source synthesis**: This roadmap consolidates three prior session artifacts into one authoritative forward plan.
> - `docs/session-logs/handoff-2026-04-19-1939.md` — Session A (3 commits: `954b9cc`, `24bf216`, `69a631a`) discovered the multi-session race
> - `~/.claude/plans/is-this-completely-implemented-enumerated-storm.md` — Session B (8 commits, Phase 1 Tasks 1–5 + Phase 2 Task 10 partial)
> - **This session** (commits `7133878`, `2084070`, `ae1ad1a` interleaving, `fd8845a` CORRECTION 3) — paper-trading analysis + credit-exhaustion root cause + multi-DB analyzer + R1/R2 recovery verification
>
> Branch: `feat/tradingview-mcp-gamma-kraken` · HEAD: `fd8845a` · Tree: clean of tracked modifications · Engine uptime ~22h

---

## Ship manifest — 2026-04-19 → 2026-04-20 continuation (21 commits on `feat/tradingview-mcp-gamma-kraken`)

Phases 1, 4, 7 (partial), 8 (partial) shipped and pushed. Engine has been restarted; all batched fixes are now ACTIVE (not just on disk).

| Phase/Task | Commit | Summary |
| --- | --- | --- |
| **Phase 1 S1** | `980b048` | `fix(contract-specs)`: MES tick_value 10× error ($5/pt not $50/pt); MGC added to multipliers |
| **Phase 1 S2** | `c1b59be` | `fix(bayes-opt)`: hard PF<1 gate with −1e6 penalty; 101-assertion fuzz test |
| **Phase 4 D1** | `6c4d4c3` | `feat(research)`: Discord briefing as evidence input for bull/bear researchers |
| **Phase 4 D2** | `e3fb84c` | `feat(debate)`: Corey tie-break for INCONCLUSIVE low-confidence verdicts |
| **Phase 4 D3** | `978f853` | `feat(trader)`: Corey-contradiction triggers Advisor review + half-size on agreement |
| **Phase 4 D4** | `265f8a8` | `feat(debate)`: CoreyAuctionAnalyst Stage-1 weight floor for futures (MCL/MNQ/MES/MGC) |
| **Phase 7 I4** | `daee1ac` | `fix(llm)`: unwrap `tenacity.RetryError` at `client.py:452` to surface Anthropic body |
| **Phase 7 I3** | `5e37d24` | `feat(health)`: `llm_path_healthy` flag + WhatsApp alert on credit errors |
| **Phase 8 Q3** | `7560e36` | `refactor(learning)`: ghost-table reader redirected to `trade_outcomes` |
| **Phase 8 Q1.1** | `1ae121c` | `docs(session-logs)`: 64-file archive + engine X-API-Key redacted in 20 files |
| **Phase 8 Q1.2a** | `413b184` | `chore(orphans)`: 15 untracked production modules + 34 tests |
| **Phase 8 Q1.3** | `237a64b` | `chore(gitignore)`: exclude runtime state + test/scan output artifacts |
| **Phase 8 Q1.2b** | `c468fa4` | `ci`: Claude PR review + safety-invariant-check workflows |
| **Phase 8 Q1.4** | `9597ee1` | `chore(bucket4)`: 35 files — `.claude/*`, `.devcontainer/`, SessionHighlights archive, handoff bundle |
| **Phase 8 Q4** | `9edd5d0` | `fix(safety)`: wire `db_manager` into SafetyLayer — `pnl_snapshots` no longer silently disabled |
| **Phase 8 (obs)** | `f23195c` | `chore(safety)`: `_sync_safety_equity` scheduler DEBUG→WARNING + traceback; silent failure class closed |
| **Phase 8 (infra)** | `b9b398a` | `fix(restart)`: PM2-aware `restart_engine.ps1` with `pm_uptime` verification; closes the silent-no-op class that masked Q4 activation |
| **Phase B feature** | `7493753` | `feat(discord)`: bookmark pipeline for #general channel (6 files, 12 new tests, 172 Discord pass) |
| **Docs sync** | `ba684d5` | `docs`: DCE flag correction + concurrent-session plan refresh + gbrain v0.13 upstream issue body |
| **Phase B dashboard** | `584efb7` | `feat(scripts)`: zero-dep `overnight_status.py` HTML renderer covering Discord + pnl_snapshots + /health |
| **Phase 8 I1** | _pending this commit_ | `feat(git-hooks)`: per-session Claude identity injection in `Co-Authored-By` trailer; Task Scheduler wiring for overnight_status |

**Deferred / blocked**:
- ~~I1 (per-session git author)~~ — DONE this round via `.githooks/prepare-commit-msg`
- I2 (git worktree adoption) — docs-only; low urgency since concurrent sessions aren't currently overlapping
- I5 (TradingView lightweight-charts swap) — risky mid-R3 window; revisit after 2026-04-22 R4 analyzer run
- Q2 (analyzer cross-validation) — blocked on R4 data
- R4 (analyzer re-run + diff vs. Task 2 baseline) — scheduled 2026-04-22 evening per Phase 2 passive-accumulation plan
- Phase 5 (MES refactor) — blocked on R4 baseline
- Phase 6 (new markets: ETH, GC, BTC, ZB) — blocked on external connector work

**Engine restart status**: Cycled via `pm2 restart jarvis-engine` at 2026-04-20 01:54 CT. All five batched fixes (Phase 1 S1/S2, Phase 7 I3/I4, Phase 8 Q4) are active. `pnl_snapshots` confirmed advancing at 1 tick/60s. `restart_engine.ps1` (b9b398a) verified end-to-end across three consecutive test cycles.

## ⚠️ STRIKE — MES "PF 5.27 baseline" is a documentation artifact (forensic 2026-04-20 02:40 CT)

The PF 5.27 / Sharpe 4.16 / +47.2% claim propagated across this doc, `JARVIS-TRADER-MASTER-REPORT.md`, `JARVIS_TRADER_UNIFIED_CANON.md`, and MEMORY.md is a **look-ahead bias artifact** from a bugged backtester that was already fixed on 2026-03-29 in commit `c94aabf`. The bugged result lives in `engine/backtest/results/old_bugged/MES_1h_2024-06-01_2026-03-27.json` with the telltale `old_bugged/` parent dir. The commit message literally states: *"MES 1h: PF 5.27→0.82, Return +47.2%→-1.2% (was entirely look-ahead bias)"*.

**Honest post-fix MES 1h baseline** (from `engine/backtest/results/MES_1h_backtest_corrected.json`):
- PF **0.82**, Sharpe **-0.12**, Return **-1.25%**, Trades **9** over 2024-06-01 → 2026-03-27.
- Net-negative. Only 9 trades in 22 months — below statistical significance.

**Current composite runner** (STC+ORB+VWAP, threshold 0.35) is a DIFFERENT strategy family producing PF 0.13 with 413 trades — also net-negative, but via overtrading rather than under-firing.

**Directive (owner, 2026-04-20 02:36 CT)**: MES must be reproduced OR re-derived "over and over again until we find a trading strategy that is profitable. Nothing else matters until then." Since reproduction is conclusively impossible (the "baseline" was never real on corrected code), re-derivation is the only remaining path. Parallel Bayesian / grid search in progress.

**Phases currently suspended pending MES profitability resolution**: Phase 5 (MES refactor), Phase 6 (new markets), Q2 analyzer cross-validation, R4 pipeline analyzer, I2 worktree, I5 chart swap.

---

## Part 0 — Ground truth as of 2026-04-19 20:25 CT / 2026-04-20 01:25Z

### What's verified working (live-probed this session)
- **Anthropic credits**: RESTORED 2026-04-19 20:16 CT. R1 smoke test at 20:21 CT landed 4 `success=1` rows (news_analyst, social_analyst, fundamental_analyst, trader) totaling $0.021. `/llm/stats` reports `total_calls:4, success_rate:1.0`.
- **Engine**: PM2 `jarvis-engine` up 22h on port 8010, `status:ok`, `paper_mode:true`, `kill_switch:inactive`.
- **Pipeline smoke test**: `POST /pipeline/run MCL` produced a real scored debate (`BEAR_WINS`, not `INCONCLUSIVE` fallback) and a legitimate `HOLD` gated on `ATR=None` (data issue, not LLM issue).
- **DiscordBriefing facade** injected into `analyst_reports["discord_briefing"]` at `pipeline.py` per commit `a25981b`.
- **Git tree**: `fd8845a` on top; 86 untracked paths but zero tracked modifications. Both concurrent sessions confirmed idle.

### What's verified broken or degraded
- **MES tick-value** = $50/point in code (`$12.50 × 4 × 0.25`), CME spec = $5/point → **10× P&L error on every MES trade**. Highest-severity latent bug; protected only by paper mode and bypass status.
- **MNQ composite-score contradiction**: Bayesian optimizer emitted `Sharpe=2.78` with `PF=0.39` simultaneously — mathematically impossible. Objective function likely ignores PF.
- **ATR=None path** in technical analyst: `"Insufficient data"` on MCL 1h despite engine uptime 22h. Separate from credits; suggests IB market-data connector isn't delivering bars (confirmed earlier: IB Gateway port 4002 is down; execution connector is in paper-simulation mode).
- **9 empty or degraded tables** in `jarvis_trader.db`: `learning_events` (no writer at all), `pnl_snapshots` (writer exists at `_mixins_pnl.py:132` but trigger never fires), `supervisor_decisions` (writer at `supervisor.py:404` but empty), `trading_patterns` (nightly consolidator not firing), `pipeline_llm_costs` (dead — real cost lives in separate `llm_costs.db`), `daily_pnl` (3 distinct values across 11 rows → synthetic), `cot_data` (fetcher offline).
- **`/health` reports `status:ok` while LLM calls fail** — business-level liveness isn't reflected in the probe. Surfaced during credit outage.
- **DiscordChatExporter (DCE) exports** are 15 days stale. Upstream ETL pipeline is healthy; the manual export itself is the bottleneck.

### What just landed but has not activated
These features require an engine restart before their code paths go live:
- `scikit-optimize==0.10.2` pin (`954b9cc`) → `/wfe/optimize-bayesian` returns `"method":"bayesian"` instead of `"random_fallback"`
- APScheduler `corey_staleness_watchdog` cron (`9ff286d` + `a38cdf2`)
- `market_router.inject_dependencies()` and `GET /market/data-source-status` (`5c1b8ca` + `a38cdf2`)
- SEPA regime confirmation behind `REGIME_USE_SEPA=0` flag (`c5ade12`) — inert until env var flipped
- 5 production-critical orphan imports in `engine/notifications/` and `engine/services/` (`fa9a1a6`) — main.py already imports these; fresh clones will break without this restart triggering validation

### What is passively progressing (no action needed)
- **R3 organic-data accumulation** (per approved plan `progress-compressed-comet.md`): engine hourly cron hits MCL/MNQ/MES; 6 pipeline_runs already landed since 2026-04-20 midnight UTC. Continues hands-off through 2026-04-22 evening.
- **R4 analyzer re-run** scheduled for Tuesday 2026-04-22 evening with window `--start 2026-04-20 --end 2026-04-22`.

---

## Part 1 — Severity-ordered execution phases

The roadmap is organized by **risk-adjusted impact per hour**, NOT chronology. The MES tick-value bug is Phase 1 because it is the only item on this list that could corrupt real-capital P&L on the next live trade. Everything else is either deferred (paper mode tolerates it), recoverable, or observational.

### Phase key

| Phase | Cumulative effort | Unblocks | External dependency |
|-------|-------------------|----------|---------------------|
| Phase 1 — Safety correctness | ~2 h | Live-capital readiness | None |
| Phase 2 — Recovery verification | ~50 min active / 48 h passive | Real baseline for all tuning | Time (R3 wait) |
| Phase 3 — Activate landed features | ~1 h | Bayesian, watchdog, SEPA gate | User approves restart |
| Phase 4 — Discord consolidation finish | ~4 h | Corey signal reaches all debate/trader readers | Phase 3 complete |
| Phase 5 — MES refactor | ~12 h | MES promoted to primary | Phase 1 + 4 complete |
| Phase 6 — New market classes | ~10 h | TV + Kraken live | Phase 5 paper-validated |
| Phase 7 — Infrastructure & dev-ex | ~4 h | Multi-session safety, CI health | None |
| Phase 8 — Quality & cleanup | ~3 h | Test baseline, untracked triage | None |

**Total scope**: ~35 h across ~2 weeks, dominated by Phase 5 (MES refactor) which is the only big-effort item.

---

## Phase 1 — Safety correctness (SEVERITY: blocker for live capital)

Single motivation: the next time Matt flips `live_trading=true`, two latent bugs will either (a) 10× every MES P&L calculation or (b) cause the optimizer to promote losing-strategy params into production. Paper mode masks both.

### Task S1 — Fix MES tick-value bug (30 min)

**Problem**: `engine/config.py` (or `engine/data/market_data.py`) uses `tick_value=12.50` for MES, reading as $12.50 per 0.25 tick = $50/point. CME MES spec is **$5/point** (1 point = $5 for Micro E-mini S&P). The 10× discrepancy affects every downstream calculation: P&L, risk sizing, Sharpe, PF, and the composite score.

**Verification before fix**:
```bash
grep -rn "12\.50.*MES\|MES.*12\.50\|tick_value.*MES" engine/
grep -rn "5\.0.*MES\|MES.*5\.0" engine/
# Cross-reference against CME spec: https://www.cmegroup.com/markets/equities/sp/micro-e-mini-sandp-500.contractSpecs.html
```

**Files likely touched** (confirm during investigation):
- `engine/config.py` — contract-spec table
- `engine/data/market_data.py` — where `tick_value` is consulted
- `engine/execution/*.py` — price→USD conversion
- `engine/backtest/*.py` — backtest P&L aggregation

**Checklist**:
- [ ] **S1.1** Grep full codebase for `12.50`, `12\.5`, `tick_value.*MES`, and list every call site
- [ ] **S1.2** Cross-reference against MCL (crude, $10/point @ 0.01 = $10/tick) and MNQ (nasdaq micro, $2/point @ 0.25 = $0.50/tick) to confirm the formula shape is "tick_value = dollars_per_point × tick_size"
- [ ] **S1.3** Change MES tick_value to `5.00 × 0.25 = 1.25` (or whatever matches the established formula in your code)
- [ ] **S1.4** Run the full backtest on MES to confirm composite score changes by a factor approximating 10×
- [ ] **S1.5** Update any memory files that quote historic MES backtest numbers — those numbers are all 10× inflated and must be annotated (don't delete; mark as pre-fix artifacts)
- [ ] **S1.6** Add a regression test: `engine/tests/test_contract_specs.py` — parametrized over MCL/MNQ/MES/MGC, asserts `tick_value` matches published CME specs. Prevents re-introduction.
- [ ] **S1.7** Commit: `fix(contract-specs): MES tick_value 10× error — $5/point not $50/point`

**Done criteria**: Regression test passes; backtest P&L on MES changes by ~10×; MEMORY.md historical numbers annotated as pre-fix.

**Risk**: Changing `tick_value` invalidates every prior MES backtest result in memory and in `docs/session-logs/`. Mitigation: don't delete history, just annotate. Matt can re-run benchmarks after S1 lands.

---

### Task S2 — Fix composite-score PF-ignore bug (45 min)

**Problem**: Per Session B handoff §3: "bayesian_optimizer returned Sharpe=2.78 + PF=0.39 simultaneously, which is mathematically inconsistent — objective function may ignore PF." A Sharpe above 2 requires positive expectancy; a PF below 1 means net losses. They cannot coexist in a correctly-computed metric pair. The optimizer is therefore promoting loss-making parameter sets whose Sharpe appears good because the scoring function weights only positive runs.

**Files**:
- `engine/backtest/bayesian_optimizer.py` — `_compute_composite_score()` function
- `engine/analytics/validation_metrics.py` — `composite_score(PF, Sharpe, WFE, MaxDD)` reference

**Checklist**:
- [ ] **S2.1** Read both score functions. Document which one the optimizer calls.
- [ ] **S2.2** Grep for `sharpe`, `profit_factor`, and `pf` co-occurrences — find every place in the optimizer where these are combined
- [ ] **S2.3** Identify the ignore path. Candidates: (a) composite skips PF when `nan`/`inf`; (b) optimizer feeds only Sharpe into a single-objective acquisition function; (c) PF is computed on absolute returns not net
- [ ] **S2.4** Add a hard gate: `if pf < 1.0: return -inf` (or the equivalent penalty in your objective convention)
- [ ] **S2.5** Add `engine/tests/test_bayesian_optimizer_score_guard.py` — fuzz-test with 100 synthetic (PF, Sharpe) pairs; assert no (PF<1, Sharpe>1) combination scores above an empirically-chosen threshold
- [ ] **S2.6** Re-run the Task 1 / Phase 3 Bayesian smoke on MCL + MNQ; confirm `best_score > 0` with corresponding `best_params` producing PF > 1 in the backtest
- [ ] **S2.7** Commit: `fix(backtest): composite score rejects PF<1.0 regardless of Sharpe`

**Done criteria**: Fuzz test catches every (PF<1, Sharpe>1) combination; Bayesian smoke tests emit `best_params` producing PF > 1 on validation.

**Risk**: Existing "best_params" in config.py may fail the new gate, reverting MCL/MNQ to pre-tuning state. Accept this — it exposes the real overfit history. Re-tune as part of Phase 5.

---

## Phase 2 — Post-credit recovery verification (PASSIVE 48h + 30 min active)

This is the already-approved plan from `progress-compressed-comet.md`. R1 and R2 are done. R3 and R4 remain.

### Task R3 — 48h organic accumulation (passive)

**Window**: 2026-04-20 00:00 UTC → 2026-04-22 00:00 UTC.

**What happens**: engine hourly cron fires automatically. No action required unless the engine trips a kill switch or writes a trade that looks wrong. Existing safety layer + paper mode bound the blast radius.

**Spot-checks** (30 s each, Mon evening + Tue evening):
```bash
sqlite3 engine/data/jarvis_trader.db "SELECT COUNT(*), symbol, final_action FROM pipeline_runs WHERE created_at >= '2026-04-20' GROUP BY symbol, final_action"
sqlite3 engine/data/agent_feedback.db "SELECT COUNT(*) FROM trade_outcomes WHERE created_at >= '2026-04-20'"
curl -s -H "X-API-Key: ${JARVIS_API_KEY}" http://localhost:8010/llm/stats | jq
```

**Abort conditions** (per `progress-compressed-comet.md` §Rollback):
- Wrong-direction trade lands
- Inverted-stop HTTP-422 guard fires for a trade the engine placed itself (should be rejected client-side, not server-side)
- Cost-per-decision exceeds $1 (suggests prompt bloat or retry storm)

If any abort condition hits: `pm2 stop jarvis-engine` and surface to user before the 48h window completes.

### Task R4 — Analyzer re-run + CORRECTION 4 decision (30 min, 2026-04-22 evening)

```bash
./engine/.venv/Scripts/python engine/scripts/analyze_paper_results.py \
  --db engine/data/jarvis_trader.db --start 2026-04-20 --end 2026-04-22 \
  > docs/session-logs/paper-trading-fresh-2026-04-22.json
```

**Decision gate — write CORRECTION 4 if ANY of these are true**:
1. `hold_rate` drops meaningfully below the prior 97% → confirms credits were the only blocker; append a success confirmation section
2. `hold_rate` remains high but for different reasons (e.g., Corey session_bias neutral, VIX regime) → document the NEW blocker taxonomy
3. Organic `trade_outcomes` rows ≥ 5 → Track H ICWeightedEnsemble may now have enough data to switch from equal-weight fallback to real Spearman IC weights; note the transition

**If none are true** (engine running but still empty-ish): no CORRECTION 4; escalate to Phase 3 "engine restart to activate landed features" because a healthy LLM path with continued empty tables points at stagnant schedulers rather than pipeline logic.

---

## Phase 3 — Activate landed features via single clean restart (~1 h)

Six distinct landed commits require a single engine restart to take effect. Batching the restart conserves uptime data and minimizes operator risk.

### Task A1 — Pre-restart health snapshot (5 min)

```bash
curl -s -H "X-API-Key: ${JARVIS_API_KEY}" http://localhost:8010/llm/stats > /tmp/pre-restart-llm-stats.json
curl -s http://localhost:8010/health > /tmp/pre-restart-health.json
sqlite3 engine/data/jarvis_trader.db "SELECT COUNT(*), MIN(created_at), MAX(created_at) FROM pipeline_runs" > /tmp/pre-restart-pipeline-count.txt
pm2 describe jarvis-engine | grep -E "uptime|restarts" > /tmp/pre-restart-pm2-state.txt
```

### Task A2 — Restart engine (2 min)

```bash
.\restart_engine.ps1
# Wait 20 s for uvicorn to come up and APScheduler to register crons
sleep 20
curl -s http://localhost:8010/health | jq
```

**Critical**: DO NOT use `--reload` flag. MEMORY.md documents that reload causes duplicate IB connections.

### Task A3 — Activation smoke tests (20 min)

```bash
# Bayesian optimizer activation
curl -s -X POST http://localhost:8010/wfe/optimize-bayesian \
  -H "X-API-Key: ${JARVIS_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"symbol":"MCL","timeframe":"1h","start":"2025-01-01","end":"2025-06-01","n_calls":30}' \
  | jq '{method, best_score, best_params}'
# Expect method=bayesian, best_score>0 (after Phase 1 S2 fix lands)

# Data source probe
curl -s -H "X-API-Key: ${JARVIS_API_KEY}" \
  "http://localhost:8010/market/data-source-status?symbol=MCL&timeframe=1h" | jq

# Scheduler registration
curl -s -H "X-API-Key: ${JARVIS_API_KEY}" http://localhost:8010/scheduler/status | jq '.jobs[] | select(.id | contains("corey"))'
# Expect 1 job: corey_staleness_watchdog, hourly Mon-Fri 9-17 CT

# Discord briefing
curl -s -H "X-API-Key: ${JARVIS_API_KEY}" \
  "http://localhost:8010/discord/briefing?symbol=MCL&lookback_hours=24" | jq '{actionable, session_bias, key_levels}'

# Pipeline with cache invalidated
curl -s -X POST -H "X-API-Key: ${JARVIS_API_KEY}" \
  http://localhost:8010/pipeline/cache/invalidate/MCL
curl -s -X POST -H "X-API-Key: ${JARVIS_API_KEY}" -H "Content-Type: application/json" \
  -d '{"symbol":"MCL","is_futures":true}' http://localhost:8010/pipeline/run | jq '{final_action, cache_hit, "debate_verdict": .debate_result.verdict}'
```

### Task A4 — Test suite full sweep (15 min)

```bash
./engine/.venv/Scripts/python -m pytest engine/tests/ -q --tb=short 2>&1 | tee /tmp/post-restart-pytest.txt
grep -E "passed|failed|error|skipped" /tmp/post-restart-pytest.txt | tail -5
```

**Expected**: ~2031+ passed, 0 failed, some skipped. The `d79c8e2` baseline claim was "0-failure" but 14 commits have landed since. New tests from concurrent session (`test_discord_briefing.py`, `test_corey_staleness_alert.py`, `test_market_data_fallback.py`, `test_ib_paper_e2e.py`, `test_social_analyst_praw.py` expanded, `test_jarvis_analysis_contract.py`, `test_pipeline_alert_cooldown.py`, `test_sepa_debate_wiring.py`) add ~50 tests. If anything regresses: triage before proceeding.

### Task A5 — Commit post-restart state note (5 min)

**If any regressions**: document in `docs/incident-notes/2026-04-20-restart-regression.md`.
**If clean**: skip. No unsolicited doc writes.

---

## Phase 4 — Discord consolidation finish (~4 h)

Session B landed `912b7c2` (facade) + `a25981b` (pipeline injection) but stopped short of wiring the facade into the four agents that actually make decisions. Without this step the briefing is constructed-and-discarded — no behavior change.

### Task D1 — Wire DiscordBriefing into bull/bear researchers (60 min)

**Files**:
- `engine/agents/bull_researcher.py` — add `discord_evidence` to evidence scoring
- `engine/agents/bear_researcher.py` — same pattern

**Checklist**:
- [ ] **D1.1** Read current evidence scoring shape in both files
- [ ] **D1.2** Extract Corey session_bias from `analyst_reports["discord_briefing"]` → if `directional_bias=bullish` and conviction>0.5, add +0.1 evidence point to bull thesis (vice versa for bear)
- [ ] **D1.3** Pass `ib_levels` through into price-target sanity check — reject thesis price targets outside Discord-published IB range
- [ ] **D1.4** Unit tests: mock briefing with each (bias × conviction) combination, assert evidence adjustments match spec
- [ ] **D1.5** Commit: `feat(research): Discord briefing as evidence input for bull/bear`

### Task D2 — Wire DiscordBriefing into debate (45 min)

**File**: `engine/agents/debate.py` (the one that was left uncommitted in Session A handoff — may or may not still be in working tree)

**Checklist**:
- [ ] **D2.1** Check whether `debate.py` has any remaining uncommitted hunks from the concurrent-session activity: `git log -p engine/agents/debate.py | head -200`. If the SEPA commit `c5ade12` or any other session added Discord reads, merge — don't duplicate.
- [ ] **D2.2** Add tie-break rule: when `|bull_score − bear_score| ≤ 0.5`, consult `discord_briefing.session_bias` and tilt verdict accordingly. Log the tilt source explicitly.
- [ ] **D2.3** Regression test: seeded briefings × tied debates → assert tie-break fires
- [ ] **D2.4** Commit: `feat(debate): Discord tie-break for low-confidence verdicts`

### Task D3 — Wire DiscordBriefing into trader (45 min)

**File**: `engine/agents/trader.py`

**Checklist**:
- [ ] **D3.1** If `discord_briefing.session_bias` contradicts the trader's proposed direction with `conviction > 0.7`, trigger the existing `AdvisorClient` (Opus) review path. Reuses infrastructure from Track F.
- [ ] **D3.2** If Advisor says "override" → HOLD. If Advisor says "proceed" → size down by 50% (risk-adjusted to the signal conflict).
- [ ] **D3.3** Regression test: mock Advisor + briefing, assert size-reduction path and HOLD-override path both fire
- [ ] **D3.4** Commit: `feat(trader): Corey contradiction triggers Advisor review`

### Task D4 — Elevate CoreyAuctionAnalystAgent to Stage 1 priority (30 min)

Per Session B Blocker #2: don't build a new fundamental_analyst; raise Corey's existing agent weight instead.

**File**: `engine/agents/debate.py` or wherever agent weights are defined

**Checklist**:
- [ ] **D4.1** Find the weight table (grep `agent_weight`, `WEIGHT`, `stage_priority`)
- [ ] **D4.2** Raise CoreyAuctionAnalyst from its current (likely Stage 2 or 3) position to Stage 1 for futures symbols only — don't touch equity path
- [ ] **D4.3** Add to regression gate: the existing Corey-only futures sentiment test should verify the weight elevation is symbol-scoped
- [ ] **D4.4** Commit: `feat(debate): elevate CoreyAuctionAnalyst to Stage 1 for futures`

---

## Phase 5 — MES refactor (~12 h)

Session B's Phase 2 Task 6 verbatim, adjusted so Phase 1 S1 + S2 are prerequisites (otherwise every number produced here is wrong).

### Task M1 — Baseline-after-fixes benchmark (30 min)

Re-run the Phase 1 S1-fixed + S2-fixed backtest on MES before any param changes. This is the honest "before" number.

### Task M2 — Bayesian retune (3 h)

- [ ] **M2.1** n_calls=100 across widest param ranges the optimizer accepts
- [ ] **M2.2** 3 windows: in-sample (2024-Q1), validation (2024-Q2), OOS (2025-Q1-Q2)
- [ ] **M2.3** Reject any params where OOS < 0.8 × in-sample (anti-overfit gate, tighter than pre-existing 0.5×)
- [ ] **M2.4** Monte Carlo 10 000-trial shuffle — require median P&L > 0 AND 5th-percentile drawdown < 15%

### Task M3 — Promote to live config + paper validate (6 h + 10 calendar days)

- [ ] **M3.1** Update `engine/config.py` MES params; commit behind a new env flag `MES_NEW_PARAMS=0` (default off — same safety pattern as `REGIME_USE_SEPA`)
- [ ] **M3.2** Flip `MES_NEW_PARAMS=1` in `.env`; restart
- [ ] **M3.3** Run 10 paper trading days
- [ ] **M3.4** Promote flag to default-on only if realized Sharpe ≥ 1.5 AND no more than 2 consecutive losing days

### Task M4 — Elevate MES in pipeline ordering + capital (1 h)

- [ ] **M4.1** `engine/agents/pipeline.py` — iterate MES first when it qualifies on capital-efficiency score
- [ ] **M4.2** Re-balance: MES=$5K, MCL=$2.5K, MNQ=$2.5K
- [ ] **M4.3** Update `MAX_POSITION_SIZE_PCT` per symbol in `engine/config.py`

### Task M5 — Memory cleanup (15 min)

- [ ] **M5.1** Remove "MES Fund Manager bypassed by owner" note from `MEMORY.md` and topic files
- [ ] **M5.2** Remove "MES testing bypass active"
- [ ] **M5.3** Update WFE/Sharpe/PF numbers to post-S1-fix values

---

## Phase 6 — New market classes (~10 h)

### Task N1 — TradingView wake-up (4 h)

Session B's Task 7 unchanged. Wires `tradingview_feed.py` as Tier 2.5 snapshot source. Dependencies: TV Desktop installed + `pnpm link tv` + Chrome `--remote-debugging-port=9222`.

**Additionally integrated from repo-integrator batch 4 (`ae1ad1a`)**: the Apache-2.0 `tradingview/lightweight-charts` library is a separate integrate-now recommendation. 5KB+ bundle reduction + 3-5× render speedup vs. current recharts in dashboard. Task 7 of this roadmap ships the data source; a dashboard replacement is a separate follow-up (covered in Phase 7 Task I4).

### Task N2 — Kraken wake-up (6 h)

Session B's Task 8 unchanged. BTC/ETH only. Requires crypto-specific `_is_globex_open()` exemption and reduced `MAX_POSITION_SIZE_PCT` (2% per trade, half of futures).

---

## Phase 7 — Infrastructure & developer experience (~4 h)

### Task I1 — Per-session git author distinction (30 min)

Addresses the Session A discovery: concurrent Claude instances all author commits as `Claude <claude@anthropic.com>`, making multi-session forensics impossible.

**Implementation options** (pick one):
- **Option A**: `~/.claude/hooks/session-start.sh` sets `GIT_AUTHOR_EMAIL=claude-$(uuidgen | cut -c1-8)@anthropic.com` at session start
- **Option B**: per-project `.envrc` or shell-rc hook reads PID and sets env accordingly
- **Option C**: opt-in per commit via `git commit --author`

**Recommendation**: Option A (automatic, opaque to user). Session IDs are already distinct; use the first 8 chars as the email suffix.

### Task I2 — Git worktree adoption for multi-session work (1 h)

**Problem**: Session A's scope-mismatch incident (commit `24bf216`) happened because a concurrent session rewrote `engine/agents/social_analyst.py` between Session A's `git diff` review and `git add` — index hash jumped mid-stage.

**Implementation**:
- [ ] **I2.1** Document worktree-per-session flow in `docs/runbooks/multi-session-git.md`
- [ ] **I2.2** Add an agent skill `.claude/skills/worktree-setup/SKILL.md` that any `/loop` or concurrent session invokes at start to create `feat/tradingview-mcp-gamma-kraken-session-{id}` branch in its own worktree
- [ ] **I2.3** Merge strategy: each session PRs its own branch; user merges explicitly (no direct commits to the shared feature branch during multi-session work)

### Task I3 — Credit-exhaustion health probe + OpenClaw alert (45 min)

Deferred P3 from CORRECTION 3. Addresses the failure mode where `/health` says `status:ok` while 100% of LLM calls fail.

**Files**:
- `engine/routers/health_router.py` (or wherever `/health` lives) — add an `llm_path_healthy` field
- `engine/notifications/openclaw_notifier.py` — add `notify_credits_exhausted()` method

**Checklist**:
- [ ] **I3.1** Periodic probe: every 15 min, send a 10-token ping to Anthropic. If response is `invalid_request_error.credit_balance`, set `llm_path_healthy:false` in a module-level cache and fire WhatsApp alert (same-day dedupe)
- [ ] **I3.2** Surface `llm_path_healthy` in `GET /health` — default true, goes false on credit exhaustion or 5 consecutive 5xx errors
- [ ] **I3.3** Regression test: mock a credit-exhausted Anthropic client, assert alert fires, `/health` reports `llm_path_healthy:false`
- [ ] **I3.4** Commit: `feat(health): credit-exhaustion probe + WhatsApp alert`

### Task I4 — Surface raw Anthropic error body at `client.py:452` (30 min)

Deferred P3 from CORRECTION 3. The `except Exception` generic handler swallows `BadRequestError.body` when tenacity wraps it in `RetryError`. The raw JSON (`{"type":"error","error":{"type":"invalid_request_error","message":"..."}}`) never surfaces to structured logs. This cost a full week of investigation during the credit outage.

**File**: `engine/llm/client.py:452`

**Fix**:
```python
except Exception as e:
    last_error = e
    # Unwrap tenacity RetryError to expose underlying Anthropic error body
    raw = getattr(e, "last_attempt", None)
    if raw is not None:
        try:
            underlying = raw.exception()
            body = getattr(underlying, "body", None) or getattr(underlying.response, "text", None)
            logger.error(f"[{current_model}] {agent_name} final failure: {type(underlying).__name__}: {body or underlying}")
        except Exception:
            logger.error(f"[{current_model}] Unexpected error for {agent_name}: {e}")
    else:
        logger.error(f"[{current_model}] Unexpected error for {agent_name}: {e}")
    break
```

- [ ] **I4.1** Apply fix
- [ ] **I4.2** Add regression test simulating `BadRequestError` with `credit_balance` body; assert the body string appears in log output
- [ ] **I4.3** Commit: `fix(llm): surface Anthropic error body when wrapped in RetryError`

### Task I5 — TradingView lightweight-charts dashboard swap (2 h)

From repo-integrator batch 4 recommendation. Apache-2.0 license, S effort, replaces current `recharts` in `dashboard/` with financial-optimized charting. 5KB+ bundle reduction + 3-5× render speedup on OHLCV.

**Files**:
- `dashboard/package.json` — swap `recharts` for `lightweight-charts`
- `dashboard/components/**/*.tsx` — replace any `<LineChart>`, `<CandlestickChart>` imports

**Checklist**:
- [ ] **I5.1** `pnpm add lightweight-charts && pnpm remove recharts` in `dashboard/`
- [ ] **I5.2** Grep TSX for recharts components; migrate each
- [ ] **I5.3** Smoke test in browser: all charts render, no console errors
- [ ] **I5.4** Update `docs/repo-integrations/tradingview__lightweight-charts.md` recommendation from `integrate-now` → `shipped`
- [ ] **I5.5** Commit: `refactor(dashboard): swap recharts for TV lightweight-charts`

---

## Phase 8 — Quality & cleanup (~3 h)

### Task Q1 — Untracked-files triage (90 min)

86 untracked files sit in the working tree. Session A's handoff §7 lists them. Breakdown by owner-decision needed:

**Bucket 1 — Auto-commit safe** (~20 files)
- `docs/session-logs/*.md` — all prior session artifacts; commit as-is in a bulk `docs(session-logs): bulk archive` commit
- `docs/incident-notes/*.md` — same pattern
- `docs/digest/*.md`, `docs/repo-integrations/*.md` — already batched by concurrent session in `ae1ad1a`

**Bucket 2 — Inspect-before-commit** (~15 files)
- `engine/services/recipe_loader.py`, `engine/recipes/` — unknown integration; verify imports
- `engine/db/session_manager.py`, `engine/db/migrations/` — untracked migrations could cause schema drift if not carefully reviewed
- `engine/risk/tool_inspector.py` — confirm whether `main.py` imports this

**Bucket 3 — Archive or discard** (~20 files)
- `Jarvis-Trader-SessionHighlights.04.14.2026_v*.md` — 5 versions of the same doc, pick one and delete the rest
- `engine/test_output.txt`, `engine/scripts/test_results.txt` — test artifacts that shouldn't be tracked

**Bucket 4 — User decision** (~15 files)
- `.devcontainer/` — do we want devcontainer support?
- `.claude/commands/`, `.claude/hooks/`, `.claude/skills/*/` — scope: shared Matt's-machine skills vs. repo-scoped skills
- `jarvis_trader_handoff_bundle/` — bundle intent unclear
- `n-autoresearch-skill/mnt/` — legacy?

**Checklist**:
- [ ] **Q1.1** `git status --porcelain | grep "^??"` → dump to working list
- [ ] **Q1.2** Per bucket, either stage+commit or delete or leave untracked with a `.gitignore` entry
- [ ] **Q1.3** At the end: `git status` shows ≤10 intentionally-ignored paths
- [ ] **Q1.4** Commit sequence: one per bucket to preserve intent in history

### Task Q2 — Full test-suite baseline & analyzer cross-validation (30 min)

Already partly covered in Phase 3 A4. Additional cross-validation:
- [ ] **Q2.1** After R4 analyzer run, compare its output against direct SQL queries on the 4 DBs. Any discrepancy → fix the analyzer first, don't trust either until parity
- [ ] **Q2.2** Add `engine/tests/test_analyzer_multi_db.py` — seeds toy DB fixtures and asserts analyzer output shape

### Task Q3 — `learning_events` decide-or-drop (30 min)

Per `project_paper_trading_empty.md` open finding. The table has no writer anywhere in `engine/`. Migration 013 creates it; `learning_router.py:677` reads it.

**Decision matrix**:
- If the intent was parallel-to-`trade_outcomes` writing → add a writer alongside `record_outcome()` in `agent_feedback.py`
- If intent is a separate generic event log → add a migration to drop the table

**Recommendation**: drop. The `trade_outcomes` → `agent_feedback.db` table already captures the data; a duplicate sink is noise. Replace with a view if `learning_router.py` consumers need the name.

### Task Q4 — `pnl_snapshots` writer-fires investigation (30 min)

Writer exists at `_mixins_pnl.py:132`. Caller exists at `safety_layer.py:315`. Table is empty → SafetyLayer `check()` never fires in production.

**Likely causes**:
- Scheduler doesn't register SafetyLayer periodic check
- Guard condition (e.g., `if positions_open`) always false in paper mode
- Exception swallowed silently

**Checklist**:
- [ ] **Q4.1** Grep for SafetyLayer scheduler registration
- [ ] **Q4.2** Add structured logging to `check()` entry/exit
- [ ] **Q4.3** Restart, monitor for 1 h; confirm whether `check()` is called
- [ ] **Q4.4** Fix root cause; regression test that `pnl_snapshots` receives a row within 1 pipeline cycle of a paper open/close

---

## Part 2 — Cross-phase invariants (non-negotiable rules)

These apply to every task above. Derived from `docs/plans/2026-04-19-top-5-roi-tasks.md` plus new findings from this session.

1. **Every data source change must update `df.attrs["source"]`** (`5c1b8ca` contract). Any new tier in the fallback chain adds a test case in `test_market_data_fallback.py`.
2. **Every new alert must have same-day dedupe** (`9ff286d` Corey staleness pattern). Dedupe armed only on successful `_send()` so failed alerts retry.
3. **Every new paper order must pass through `SafetyLayer.submit_paper_order()`**. No direct DB inserts.
4. **Every commit message follows `feat:/fix:/refactor:/test:/docs:` convention** (MEMORY.md rule).
5. **Never mock the DB in migration-touching tests** (MEMORY.md testing rule).
6. **Futures sentiment = Corey #market-updates ONLY** (2026-04-19 owner directive). No Reddit, ApeWisdom, Twitter, or retail chatter. Equity sentiment via PRAW/ApeWisdom/StockTwits remains permitted for equity-only agents.
7. **Never skip hooks with `--no-verify` or bypass signing unless explicitly asked**. Pre-commit hook failure means the commit didn't happen; fix underlying issue and create a NEW commit.
8. **Before ANY code change informed by a memory**, verify the memory against current code (file exists, function signature matches, flag state unchanged). Memories can rot; production state is truth.
9. **Engine restarts are user-gated**. Batch changes so one restart activates multiple features. Paper mode lowers stakes but 19+ hour uptime windows represent data; don't bin them for a single dependency.
10. **Verify before reporting** (MEMORY.md UNIVERSAL RULE). Never tell Matt to act unless you've first probed the relevant endpoint/DB/log/process yourself.

---

## Part 3 — Suggested week-by-week execution order

### Week of 2026-04-20 → 2026-04-26

| Day | Phase tasks | Effort | Outcome |
|-----|-------------|--------|---------|
| **Mon 04-20** | S1 + S2 (Phase 1) | 2 h | Tick-value + PF-gate fixed; regressions locked in |
| **Tue 04-21** | R3 spot-check + A1 + A2 + A3 (Phase 3) | 40 min | Engine restarted; Bayesian/SEPA/crons active |
| **Tue 04-21 eve** | R4 + possible CORRECTION 4 | 45 min | Fresh paper-trading baseline published |
| **Wed 04-22** | D1 + D2 (Phase 4) | 1.75 h | Bull/bear + debate consume Discord |
| **Thu 04-23** | D3 + D4 + I4 (Phase 4/7) | 2 h | Trader consults Corey; Advisor consulted on contradictions; error bodies now log |
| **Fri 04-24** | I3 + Q1 (Phase 7/8) | 2.5 h | Credit probe shipped; untracked triage done |
| **Sat 04-25 AM** | M1 + M2 (Phase 5 start) | 3.5 h | MES retune candidates generated |
| **Sat 04-25 PM + Sun 04-26** | M3 (Phase 5 continued) | flag flip + 10 paper days start | MES new-params begin observation |

### Week of 2026-04-27 → 2026-05-03

| Day | Phase tasks | Effort | Outcome |
|-----|-------------|--------|---------|
| **Daily** | Monitor M3 paper trades | 10 min | Track Sharpe, consecutive-loss days |
| **Sat 05-02** | M4 + M5 (Phase 5 close) | 1.25 h | MES promoted to primary; memory cleaned |

### Week of 2026-05-04 → 2026-05-10

| Day | Phase tasks | Effort | Outcome |
|-----|-------------|--------|---------|
| **Sat 05-09 AM** | N1 (Phase 6) | 4 h | TradingView live as Tier 2.5 |
| **Sat 05-09 PM** | I5 (Phase 7) | 2 h | Dashboard chart swap shipped |
| **Sun 05-10** | N2 (Phase 6) | 6 h | Kraken BTC/ETH paper trading |

### Deferred / continuous

- I1 + I2 (Phase 7 multi-session safety): implement before the next known concurrent-session window
- Q2 + Q3 + Q4 (Phase 8 hygiene): interleave as low-priority tickets
- TradingView Desktop install + IB Gateway boot + Reddit app registration: **manual user steps**, not agent work. Do when convenient.

---

## Part 4 — Files explicitly out of scope until further notice

- `career-ops/*` — PRIMARY FOCUS DIRECTIVE: never touch from a trading session
- Greenfield Metal Sales (any GMS path) — archived
- Obsidian Web Clipper — already shipped 2026-04-19
- MES pre-fix backtest numbers anywhere in history — annotate, don't rewrite
- `engine/agents/debate.py` SEPA code path (`REGIME_USE_SEPA=0`) — inert until Matt explicitly flips the flag

---

## Part 5 — Open questions for user

Resolution required before Phase 5 or Phase 6 starts:

1. **Capital rebalance math**: Phase 5 M4.2 proposes MES=$5K, MCL=$2.5K, MNQ=$2.5K on the $10K book. Confirm this split (Session B's Task 6.7 proposed the same).
2. **SEPA flag activation timing**: `REGIME_USE_SEPA=1` is inert but present. Flip now (after Phase 1 S2) or wait for MES primary?
3. **Reddit app registration intent**: Policy gate blocks PRAW for futures. If Matt registers the app, equity-only paths still benefit — confirm whether equity sentiment is worth the registration cost.
4. **Untracked file buckets** (Phase 8 Q1): bucket 4 items (devcontainer, .claude/ scope, handoff_bundle, n-autoresearch) need user decision before commit.
5. **DCE automation vs. manual**: Corey staleness watchdog shipped; do we automate DCE exports to prevent alerts, or keep manual and act on alerts?

---

## Verification — how to audit this roadmap in 60 seconds

```bash
# 1. Confirm HEAD, uptime, credit health
cd C:/Users/mattm/ThinkorSwim/jarvis-trader
git log -1 --oneline
curl -s http://localhost:8010/health | jq '{status, uptime_seconds}'
curl -s -H "X-API-Key: ${JARVIS_API_KEY}" http://localhost:8010/llm/stats | jq '{total_calls, success_rate}'

# 2. Confirm Phase 1 hasn't been started elsewhere
git log --oneline --all | grep -iE "tick.value|composite.*pf" | head -5

# 3. Confirm R3 passive accumulation is proceeding
sqlite3 engine/data/jarvis_trader.db "SELECT DATE(created_at), COUNT(*) FROM pipeline_runs WHERE created_at >= '2026-04-20' GROUP BY DATE(created_at)"

# 4. Confirm no concurrent sessions active
tasklist 2>&1 | grep -i claude
git status --porcelain | grep -v "^??" | head
```

Expected responses:
1. HEAD at or beyond `fd8845a`, uptime > 22h, credits healthy (`total_calls>0, success_rate=1.0`)
2. Empty — no Phase 1 commits landed yet
3. Growing hourly counts for MCL/MNQ/MES
4. No claude processes found, no tracked-file modifications

If any diverges: reconcile state against this roadmap before taking the next step.

---

## Change log for this roadmap

- 2026-04-20 01:30Z — Created, synthesizing Session A + Session B + this session artifacts post-R1/R2 verification
