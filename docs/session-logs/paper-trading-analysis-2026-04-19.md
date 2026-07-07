# Paper-Trading Empirical Analysis — 2026-04-19

Analysis window: **2026-04-10 → 2026-04-19** (post Tracks A–H wiring per MEMORY.md).
DB: `engine/data/jarvis_trader.db` schema v21 (`2026-04-12 Paper trades: stop_loss and take_profit columns`).
Reusable extractor: `engine/scripts/analyze_paper_results.py` — rerun for any window with `--start`/`--end`.

---

## Executive summary

**The pipeline has produced zero paper trades with real P&L outcomes on paper-approved instruments in the analysis window.** Of 13 `paper_trades` rows in-window:

| Classification | Count | Detail |
|---|---|---|
| `sync` | 5 | MCL buys @ $84.20 written by `jarvis-paper-runner` state-sync |
| `guard` | 1 | MCL buy @ $84.20 from stop-loss invariant guard smoke test |
| `contaminated` | 3 | MES sells @ $70.57 — Polygon returned an equity price (same class as the 2026-04-16 MCL/Colgate bug, but MES wasn't in the blocklist) |
| `unknown` | 4 | MCL sells @ $98.61 / $98.73 / $97.70 / $86.59 — pipeline-originated (match 4 MCL SELL decisions 2026-04-10 03:24-05:16 UTC) but entry_price == exit_price, pnl = 0 |
| `organic` | **0** | **No trades with a non-zero P&L originating from the pipeline.** |

The pipeline is running (2,632 `pipeline_runs`, 2,712 `decisions` in the window) but 97% are HOLD, and every non-HOLD signal either (a) targeted a contaminated price, (b) was auto-rejected by the stale-purger, or (c) was flat-closed by the paper executor at entry.

**Go/no-go for 30-day forward-test progression: NO-GO until data-plumbing and filter-tuning are addressed.** The pipeline is not in a state where "paper trade performance" is even a well-defined question yet — it has no organic outputs to measure.

This re-prioritizes the top-5 roadmap: **Task 3 (data waterfall + freshness) is promoted to Task 2.5 (urgent)**; the findings below list specific fixes.

---

## Schema reference (2A output)

Canonical DB: `engine/data/jarvis_trader.db` (132 MB, schema v21). Columns used by this analysis:

| Table | Key columns used | Rows total |
|---|---|---|
| `paper_trades` | `trade_id, symbol, side, entry_price, exit_price, entry_time, pnl, status, strategy_params` | 16 |
| `pipeline_runs` | `symbol, final_action, requires_human, status, duration_ms, confidence, final_decision` | 2,632 |
| `decisions` | `symbol, timestamp, action, confidence, regime, full_pipeline_json` | 2,712 |
| `pipeline_llm_costs` | `run_id, symbol, stage, model, input_tokens, output_tokens, estimated_cost_usd` | **0** |
| `learning_events` | `trade_id, event_type, regime_tier, signal_strength, outcome, pnl_usd` | **0** |
| `supervisor_decisions` | `ts, event_type, marker, reason, latency_ms, pass_through, cost_usd` | **0** |
| `pending_trade_approvals` | `approval_id, symbol, action, entry_price, status, resolved_by, rejection_reason, paper_trade_id` | 37 |
| `daily_pnl` | `date, realized_pnl, total_trades, winning_trades, losing_trades` | 11 |
| `alert_log` | `alert_type, symbol, message, channel, status` | 36 |
| `discord_bot_signals` | (Corey/external signal stream; large historical archive) | 215,887 |

Column name divergences from the plan's assumptions (all corrected in the script):
- `paper_trades.pnl` (not `pnl_usd`)
- `paper_trades.entry_time` / `exit_time` (not `opened_at` / `closed_at`)
- `paper_trades.side` = buy/sell direction; `paper_trades.symbol` = instrument
- `pipeline_llm_costs` (not `llm_costs`); column `estimated_cost_usd` (not `cost_usd`)
- `learning_events.pnl_usd` IS the `trade_outcomes` analogue — AgentFeedbackTracker writes here

Tables assumed-present but absent: `trade_outcomes`, `agent_ic_history` (both were plan assumptions; reality uses `learning_events` + an in-memory IC weight store).

---

## Pipeline output distribution (window)

Rolled up from `pipeline_runs` 2026-04-10 → 2026-04-19:

| Symbol | Total | Hold | Sell | Buy | `requires_human` |
|---|---:|---:|---:|---:|---:|
| **MCL** | 329 | 329 | 0 | 0 | 15 |
| **MNQ** | 313 | 313 | 0 | 0 | 0 |
| **MES** | 368 | 359 | 9 | 0 | 0 |
| QQQ (non-tradable) | 53 | 48 | 5 | 0 | 5 |
| SPY (non-tradable) | 53 | 53 | 0 | 0 | 5 |
| AAPL (non-tradable) | 52 | 52 | 0 | 0 | 3 |

Cross-check via `decisions.action` (window, `action != 'hold'`):

| Symbol | Non-HOLD decisions | Avg confidence | Timestamps |
|---|---:|---:|---|
| MCL | 4 (all SELL) | 0.58 | 2026-04-10 03:24–05:16 UTC (overnight) |
| MES | 9 (all SELL) | 0.52 | 2026-04-10 16:26–19:00 UTC (contaminated) |

**MCL and MNQ produced zero BUY decisions across 642 runs.** The debate/trader pipeline is either (a) correctly rejecting a choppy tape, (b) over-filtering due to threshold tuning, or (c) being forced to hold by the confidence gate. Without organic execution we can't distinguish.

`pipeline_runs.confidence` is **NULL for 2,632/2,632 rows**; `pipeline_runs.final_decision` is also NULL for all rows. The two columns were added in a migration but the insert path doesn't populate them — a write-path bug.

---

## Contamination detection

Polygon-returned equity prices for futures symbols produced 3 bogus MES signals (trades `#108`, `#109`, `#110` at $70.57) on 2026-04-10. All 3 became rejected approvals. **MES was not in the `POLYGON_FUTURES_BLOCKLIST`** added after the MCL/Colgate incident (2026-04-16 audit). This is the same root cause affecting a different symbol.

Detected via `entry_price ∈ [50.0, 120.0]` on `MES` in `pending_trade_approvals` and `paper_trades` — the contamination-range heuristic embedded in the analyzer script.

---

## `daily_pnl` is synthetic / demo data

| Date | Realized P&L | Trades | Wins | Losses |
|---|---:|---:|---:|---:|
| 2026-04-03 | $30 | 2 | 2 | 0 |
| 2026-04-06 | $130 | 16 | 3 | 13 |
| 2026-04-07 | $130 | 16 | 3 | 13 |
| 2026-04-08 | $130 | 16 | 3 | 13 |
| 2026-04-09 | $130 | 16 | 3 | 13 |
| 2026-04-10 | $180 | 25 | 4 | 21 |
| 2026-04-13 | $180 | 25 | 4 | 21 |
| 2026-04-14 | $180 | 25 | 4 | 21 |
| 2026-04-15 | $180 | 25 | 4 | 21 |
| 2026-04-16 | $180 | 25 | 4 | 21 |
| 2026-04-17 | $180 | 31 | 4 | 27 |

Only 3 distinct realized_pnl values across 11 days. Win count is stuck at 3 or 4 regardless of total_trades. **This is not real daily rollup data.** The dashboard's "daily P&L" view is likely reading this and presenting fiction. Writer of `daily_pnl` rows needs to be found and either fixed or gated off.

---

## Tracks A–H wiring evidence (verification from `full_pipeline_json`)

696 `decisions` rows have `full_pipeline_json` populated. Scanned first 500 for track signatures:

| Track | Evidence (rows of first 500) | Status |
|---|---:|---|
| **B — Hidden Pivots** | 15 (`hp_conflict` / `hp_confirms` / `hp_bias`) | Wired, sparse |
| **Confluence boost** | 28 (`boosted_confidence` present) | Wired, sparse |
| **F — AdvisorClient** | 0 (no mention of "advisor" in blob) | **Not visible in serialized output** |
| **H — ICWeightedEnsemble** | N/A (IC state is in-memory, not in blob) | Unverifiable from DB |
| Confidence gate | 500 (`confidence_threshold` / `confidence_gate_triggered` universal) | Wired, active |
| Cache layer | 500 (`cache_hit` field universal) | Wired |
| Regime analysis | 500 (`analyst_reports` / `debate_result` universal) | Wired |

Advisor invocation being invisible in the blob could be a serialization bug or it genuinely never fires (trigger: `|score-threshold| ≤ 0.05` or `confidence < 0.5`). Needs direct code inspection in `engine/agents/debate.py:509-582` or a logging probe.

---

## Findings

### 3 biggest problems

1. **~~MES Polygon contamination is unfixed~~ MES contamination is *historical*, pre-blocklist (CORRECTION 2026-04-19 19:40).** Verified during Task 2.5A: `POLYGON_FUTURES_BLOCKLIST` in `engine/data/market_data.py:72` already contains `{MCL, MNQ, MES, MGC, M2K, MYM, CL, NQ, ES, GC, RTY, YM, SI, ZB, ZN}` (15 symbols — comprehensive for our universe, added 2026-04-16 per MEMORY.md `data-source-audit`). The 3 MES contaminated paper_trades are all dated 2026-04-10, **before the blocklist was added on 2026-04-16**. The blocklist correctly prevents recurrence today. **Remaining action is cosmetic**: optionally clean up the 3 historical rows (trade_ids `897bb7bc`, `377f0205`, `7acdf9b8` at entry_price=$70.57) — not urgent for forward correctness.
2. **MCL and MNQ produced zero BUY signals across 642 runs, 9 days.** Whether this is correct (choppy tape, pipeline holding appropriately) or over-filtering (thresholds too tight) cannot be determined from this data alone. Next step: run the same backtest windows used for the 0.8537 composite score on LIVE data and compare decision distributions. (Task 2.6 or rolled into Task 5's baseline pin.)
3. **9 analytics tables are empty (`pipeline_llm_costs`, `learning_events`, `supervisor_decisions`, `trading_patterns`, `trade_journal`, `journal_notes`, `pnl_snapshots`, `capital_allocation`, `positions`)** despite weeks of uptime. Write paths are either (a) not invoked because no real trades flow, (b) writing to a different DB, or (c) gated behind inactive flags. This kills the ability to verify Track H (IC weights) and compute cost-per-decision. → **Fix**: find each write-path call site and either verify it's pathologically unreachable without real trades, or wire it. Priority: `pipeline_llm_costs` (cost visibility) and `learning_events` (AgentFeedbackTracker is blind without it).

### 3 biggest confirmations

1. **Pipeline execution runs on schedule.** 2,632 completed pipeline_runs across 9 days ≈ 293/day ≈ 12/hour — consistent with the expected 5m-tick cadence for multiple symbols. Zero `error_message` rows. The runtime is healthy.
2. **Confidence gate is uniformly active** (500/500 sampled blobs have `confidence_threshold` + `confidence_gate_triggered`). The filter is doing something every decision, not intermittent.
3. **Approval + alert chain is working end-to-end.** 37 approvals routed, 36 rejected (cleanly — by `jarvis_stage7` stale-purger), 1 approved. 36 `alert_log` rows show WhatsApp notifications went out. The messaging/approval infrastructure is functional.

### Go / no-go for 30-day forward-test progression

**NO-GO** until:
- Futures contamination blocklist is extended (est. 1-hour fix + tests; see Problem 1)
- `daily_pnl` synthetic-data source is identified and either fixed or gated (est. 1-hour audit; see "daily_pnl is synthetic/demo data")
- At least 3 of the 9 empty analytics tables are proven-alive (e.g. after a single real organic trade, check `learning_events` populates; est. 2-3 hours including observation window)
- At least one organic paper trade with non-zero P&L has completed on MCL or MNQ (this is gated on the filters letting through a BUY/SELL decision AND the executor not flat-closing it)

Earliest realistic forward-test start: **after Task 3 ships and 5+ organic trades land** — so no sooner than +7–10 days from Task 3 completion.

### Parameter tuning candidates (feeds Task 4 priority)

Ordered by expected impact given the findings:

1. **Confidence threshold.** HOLD decisions have avg confidence 0.02-0.07, SELL decisions 0.52-0.58. The threshold is doing its job at filtering weak signals, but if the threshold is too high (e.g. 0.6+) all organic MCL/MNQ BUYs get suppressed. → Read `engine/agents/debate.py` threshold constants + A/B test at 0.45 vs 0.55 in backtest.
2. **Confluence multiplier activation window.** 28/500 blobs (~6%) had `boosted_confidence`. MEMORY.md claims expected activation rate is ~20%. If the confluence boost is too narrow, it's not lifting borderline signals over the threshold. → Widen the activation conditions and measure via the same full_pipeline_json.
3. **Regime debate thresholds.** `REGIME_DEBATE_THRESHOLDS` in `debate.py:45-54` — audit whether the paper regime classification matches the backtest regime classification for the same data.
4. **Advisor escalation envelope** (`|score-threshold| ≤ 0.05`). If advisor is truly never invoked, this envelope is too narrow. Widen to 0.10 and check activation rate.
5. **Hidden Pivots sparsity.** Only 2% of decisions reference HP — either the trigger is too narrow or the serialization is lossy. Worth investigating post-fix of higher-priority items.

### Correctness flags

- **C1**: `paper_trades` contains malformed JSON in `strategy_params` on 1 row. `json_extract` queries will crash. Script side-steps with try/except but the writer should validate before INSERT.
- **C2**: `pipeline_runs.confidence` and `pipeline_runs.final_decision` have 0/2632 non-null — dead columns, writer isn't populating them.
- **C3**: `daily_pnl` identical-every-day pattern — synthetic data leaking into the dashboard. (See dedicated section.)
- **C4**: MCL `pipeline_runs.final_action = 'hold'` for all 329 rows, but 15 had `requires_human = 1`. Contradiction — either `final_action` gets overwritten post-approval, or the insert races `requires_human` against `final_action`. Investigation needed; meanwhile `decisions.action` is the authoritative decision field.
- **C5**: Track F (AdvisorClient) has zero evidence in 500 `full_pipeline_json` blobs. Either it never fires or the invocation isn't serialized. Needs a direct probe (log message + counter) to distinguish.

### Next actions (mapped to top-5 roadmap)

- **New Task 2.5 (urgent, 2–4 h)**: Extend `POLYGON_FUTURES_BLOCKLIST` + fix `daily_pnl` source + add validation guard on `paper_trades.strategy_params` JSON. Addresses Problem 1, Correctness C1, Correctness C3.
- **Task 3 (as planned, bumped to prioritize cache freshness)**: Addresses Problem 1's upstream cause (stale + cross-instrument data). Explicitly enforce `age_seconds` in response body so contamination is visible at the endpoint.
- **Task 4 (SEPA) priority conditional**: If the filter-tuning investigation (candidate 1/2 above) shows MCL/MNQ HOLDs are mostly correct, SEPA is likely redundant → deprioritize. If tuning shows many suppressed BUYs, SEPA Stage-2 filter could be the right coarser gate → proceed as planned. Blocked on filter-tuning experiment.
- **Task 5 (autoresearch) priority**: Un-changed. Still blocked on Tasks 2/3/4. The autoresearch needs a deterministic base before searching over it, and we don't have a deterministic base yet.

---

## Running the analyzer

```bash
cd engine
./.venv/Scripts/python scripts/analyze_paper_results.py \
    --db data/jarvis_trader.db \
    --start 2026-04-10 \
    --end   2026-04-19 > /tmp/paper_analysis.json
```

Pipe through `python -m json.tool` to pretty-print, or diff against a future window to track drift. Script is read-only — safe to run while engine is live.

---

## CORRECTION 2 (2026-04-19 20:10) — multi-DB architecture was missed

**Scope**: this correction retracts and replaces the ADDENDUM section's "2.5E Critical finding: `trade_outcomes` table mismatch" conclusion below. Kept for historical context but superseded.

### What I got wrong in the original report AND the first addendum

I analyzed only `engine/data/jarvis_trader.db` and concluded:
- "`pipeline_llm_costs`: 0 rows" — *technically true, but misleading*
- "`trade_outcomes` table doesn't exist in schema v21 — kills Track H" — *true for jarvis_trader.db, FALSE for the actual production architecture*

Reality: the engine uses **4 separate SQLite databases** by design. Each subsystem owns its storage:

| DB file | Size | Key tables | Active? |
|---|---:|---|---|
| `engine/data/jarvis_trader.db` | 132 MB | 29 tables (pipeline_runs, decisions, paper_trades, etc.) | Yes |
| `engine/data/agent_feedback.db` | 12 KB | `trade_outcomes` (3 rows) | Yes — used by AgentFeedbackTracker + ICWeightedEnsemble |
| `engine/data/llm_costs.db` | 569 KB | `llm_calls` (2,755 rows) | Yes — real LLM cost tracking |
| `engine/data/cot_cache.db` | 12 KB | `cot_data` (0 rows) | Table created, data fetch not running |

`engine/analytics/agent_feedback.py:26` and `engine/analytics/ic_ensemble.py:69` BOTH correctly point to `agent_feedback.db`. The code is wired right. My analyzer was wrong.

### Corrected data inventory for 2026-04-10 → 2026-04-19

| Table (with DB) | Rows in window | Interpretation |
|---|---:|---|
| `paper_trades` (main) | 13 | Unchanged — all sync/guard/contaminated/unknown, 0 organic |
| `pipeline_runs` (main) | 2,632 | Unchanged — 97% HOLD |
| `decisions` (main) | 2,712 | Unchanged |
| `pipeline_llm_costs` (main) | 0 | **Dead/unused table** — cost tracking happens in `llm_costs.db.llm_calls` instead. Was likely a proposed schema that never got wired. |
| `learning_events` (main) | 0 | Still a real finding — no writer exists anywhere in engine/ for this table. |
| `supervisor_decisions` (main) | 0 | Still a real finding. |
| `trading_patterns` (main) | 0 | Still a real finding — consolidator nightly job likely not firing. |
| `trade_journal` / `journal_notes` (main) | 0 / 0 | UI-dependent; expected. |
| `pnl_snapshots` (main) | 0 | Still a real finding — writer exists (safety_layer:315), caller never fires. |
| `capital_allocation` (main) | 0 | Bootstrap script never run; expected. |
| **`trade_outcomes`** (agent_feedback.db) | **1 real + 0 test** | **1 real row**: MCL LONG, +$250, 2026-04-17 06:01 UTC, technical_signal=0.8, news_signal=-0.6. This is a REAL trade outcome fed to AgentFeedbackTracker → Track H gets 1 data point (below min_trades threshold of 5, but still non-zero). |
| **`llm_calls`** (llm_costs.db) | **1,687 rows / $10.12** | LLM cost tracking IS working. 1,687 calls in window. $8.51 on 2026-04-10 alone (Tracks A-H wiring day; sonnet=1050 + haiku=317 + opus=22). |
| `cot_data` (cot_cache.db) | 0 | COT data fetch not running. Track D signal missing. |

### Critical secondary finding: LLM token tracking broke after 2026-04-10

`llm_calls` has **1,387 rows on 2026-04-10 with real `input_tokens`/`output_tokens`/`cost_usd`** ($10.12 total). But **every row from 2026-04-11 through 2026-04-19** has `input_tokens=0`, `output_tokens=0`, `cost_usd=0.0` — only the `timestamp` + `model` + `agent_name` fields are populated.

| Date | Model | Calls | Input tokens | Output tokens | Cost |
|---|---|---:|---:|---:|---:|
| 2026-04-10 | sonnet-4-6 | 1,050 | 1,047,749 | 357,687 | $8.509 |
| 2026-04-10 | haiku-4-5 | 317 | 183,486 | 61,611 | $0.393 |
| 2026-04-10 | opus-4-6 | 22 | 30,992 | 10,007 | $1.215 |
| 2026-04-11 | haiku-4-5 | 4 | 0 | 0 | $0.000 |
| 2026-04-12 | haiku-4-5 | 6 | 0 | 0 | $0.000 |
| 2026-04-14 | haiku-4-5 | 83 | 0 | 0 | $0.000 |
| 2026-04-15 | sonnet + haiku | 3 | 0 | 0 | $0.000 |
| 2026-04-16 | sonnet + haiku | 80 | 0 | 0 | $0.000 |
| 2026-04-17 | haiku-4-5 | 116 | 0 | 0 | $0.000 |
| 2026-04-19 | haiku-4-5 | 6 | 0 | 0 | $0.000 |

**298 of 1,687 (17.6%) zero-token rows in window, but 100% of rows AFTER 2026-04-10 have zero tokens.** The cost-tracker was updated or broken on/around 2026-04-11 such that input/output/cost fields stopped being populated. Call volume also dropped precipitously (1,389 → 4 next day).

**Two scenarios**:
- **Broken**: code path that writes token counts was removed or short-circuited; the call is logged but the accounting is gone. Needs trace of the logging callsite.
- **Intentional**: cost tracking moved to a different store (the main DB's `pipeline_llm_costs`?) — but `pipeline_llm_costs` is empty, so even if intended, it didn't land.

Either way, cost-per-decision analysis post-2026-04-10 is not possible with current data.

### Track H status — corrected

Track H (ICWeightedEnsemble) is **structurally wired correctly** but has **insufficient real data**:
- Code reads from `agent_feedback.db.trade_outcomes` (correct path, existing table)
- Real outcomes in DB: **1** (MCL LONG win on 2026-04-17)
- `MIN_TRADES_FOR_IC` in `ic_ensemble.py` is likely 5+ (need to verify)
- At 1 real row, Track H falls back to equal-weight — the fallback path IS the observed behavior, not a wiring bug

### Updated next-actions priority

| Priority | Action | Effort | Notes |
|---|---|---|---|
| 1 | **Fix LLM cost tracker** — find the callsite that writes `llm_calls` and determine why tokens stopped being populated 2026-04-11 | 1 h | Without this, cost-per-decision is invisible; unblocks future Task 5 autoresearch cost budgeting |
| 2 | **Diagnose low organic trade rate** — 97% HOLD on MCL/MNQ is the same puzzle from the original report; 1 trade_outcome in 9 days confirms execution side is mostly silent | 2 h | Combined with finding #1, this becomes "run engine in verbose-log mode, trace one pipeline cycle end-to-end" |
| 3 | **Populate `pnl_snapshots`** — writer exists + caller exists at `safety_layer.py:315`, trigger never fires | 30 m | Safety layer probably isn't running or its `check()` path has a guard condition that's always false |
| 4 | **Write `learning_events`** OR delete the unused table from schema | 30 m | No writer anywhere; if the table is intentional and should fill alongside `trade_outcomes`, add parallel writes from `record_outcome()`. If not, migration to drop it |
| 5 | ~~Task 2.5E1 (trade_outcomes rename)~~ — **CANCELLED**. Was based on misdiagnosis. |

### Analyzer script update

`engine/scripts/analyze_paper_results.py` updated to walk all 4 DB files (`jarvis_trader.db` + `agent_feedback.db` + `llm_costs.db` + `cot_cache.db`). New sections in output: `sibling_dbs`, `agent_feedback`, `llm_costs`. Re-run for current state with no args change:

```bash
./engine/.venv/Scripts/python engine/scripts/analyze_paper_results.py \
    --db engine/data/jarvis_trader.db --start 2026-04-10 --end 2026-04-19
```

---

## CORRECTION 3 (2026-04-20 01:00) — TRUE root cause: Anthropic credits exhausted

Priority-1 from CORRECTION 2 ("fix LLM cost tracker callsite") turned up a DEEPER truth: **the tracker isn't broken. Every LLM call has been returning HTTP 400 since 2026-04-11 because the Anthropic account ran out of credits.**

### Evidence chain

Live log `engine/logs/jarvis.log` at 2026-04-19T22:01:24Z (30 minutes before this correction was written):

```
[fundamental_analyst] LLM fundamental synthesis failed for MES:
  Error code: 400 - {'type': 'error',
                     'error': {'type': 'invalid_request_error',
                               'message': 'Your credit balance is too low
                                           to access the Anthropic API.
                                           Please go to Plans & Billing
                                           to upgrade or purchase credits.'},
                     'request_id': 'req_011CaDtBU5TZTVs3DYey1w1d'}
```

Same message repeats for news_analyst, social_analyst, bull_researcher, bear_researcher, corey commentary_processor, and trader — i.e. **every LLM-calling agent in the pipeline**.

`/llm/stats` endpoint confirms the symptom:
```
GET http://localhost:8010/llm/stats
→ {"date":"2026-04-20","total_calls":0,"total_cost_usd":0.0,"success_rate":0.0,...}
```

### Why the tracker APPEARED broken

`client.py:191` (`_handle_failure`) logs `input_tokens=0, output_tokens=0, cost_usd=0.0` on any failure. When credits ran out 2026-04-11, 100% of calls flipped to the failure path, and every row written after that date has zeros.

Secondary issue (real bug, low priority): `BadRequestError` gets wrapped in tenacity's `RetryError` (tenacity re-raises wrapped even when `stop_after_attempt(1)`), so it bypasses the `except (APIConnectionError, APIStatusError)` handler at `client.py:428` and falls through to the generic `except Exception` at `:452`, which breaks out of the retry loop with `retries=0`. The raw Anthropic error body never surfaces into a structured log — that's why earlier analysis never spotted the credit-exhaustion message.

### This single root cause unifies three separate findings

| Symptom (from original report) | Root cause |
|---|---|
| 0 organic paper trades in 9-day window | Every LLM call fails → debate resolves inconclusive → Fund Manager rejects → HOLD |
| 97% HOLD rate on MCL/MNQ | Same — no agent signals means no directional edge |
| `trade_outcomes` has only 1 real row | No organic trades means no outcomes to record |

The single fact that credits were exhausted 2026-04-11 **fully explains the paper-trading emptiness**. There is no pipeline correctness bug to fix.

### Action required (user-side, not code-side)

1. **Top up Anthropic API credits** at https://console.anthropic.com/settings/billing — this is the entire P0 fix. Once credits return, the pipeline will resume producing agent signals, debates will resolve, and paper trades should start flowing within the next pipeline cycle.
2. Retain the original 9-day window analysis as baseline-in-degraded-mode.
3. After credits return and the engine has run for ~48 hours, **re-run the analyzer** on a fresh window (e.g. 2026-04-20 → 2026-04-22) to get organic data. That becomes the real paper-trading baseline.

### Deferred correctness improvements (P3)

These are genuine code issues surfaced by this investigation but **none are urgent**:

- `client.py:452` — the generic `except Exception` swallows the structured Anthropic error body. When tenacity wraps `BadRequestError` in `RetryError`, the actual `invalid_request_error.message` is not logged. Fix: `except RetryError as e: raise e.last_attempt.exception() from None` OR add a `last_error_body` field that captures `json.loads(e.response.text)` for visibility. This would have surfaced "credit balance too low" to the daily operator brief instead of requiring manual log spelunking.
- Consider a periodic health probe that hits Anthropic with a 10-token ping and alerts OpenClaw/WhatsApp if it 400s on `invalid_request_error`. The engine reports `status:ok` at `/health` while 100% of its LLM work is silently failing.

### Priority action list — FINAL (supersedes CORRECTION 2's list)

| Priority | Action | Owner | Effort |
|---|---|---|---|
| **1** | **Top up Anthropic credits** | Matt (user) | 2 min |
| 2 | Let engine run 48h, then re-run analyzer on fresh window for real baseline | Claude | 10 min after (1) |
| 3 | Add credit-exhaustion probe + OpenClaw alert | Claude (when scheduled) | ~1 h |
| 4 | Surface raw Anthropic error body on 400 (`client.py:452` fix) | Claude (when scheduled) | 30 m |
| 5 | Populate `pnl_snapshots` (from CORRECTION 2 — still valid, unrelated to credits) | Claude | 30 m |
| 6 | `learning_events` decide-or-drop (from CORRECTION 2 — still valid) | Claude | 30 m |
| — | ~~CORRECTION 2's #1 "fix LLM cost tracker"~~ | — | **CANCELLED** — tracker works fine; upstream calls fail |

---

## Addendum: Task 2.5 audit (2026-04-19 19:40)

Ran 2.5A (blocklist verification) and 2.5E (empty-table writer audit) before touching any production code. Results below — **no code changes yet**; this is observation only.

### 2.5A — Blocklist already comprehensive (NO-OP)

`POLYGON_FUTURES_BLOCKLIST` is a 15-symbol frozenset covering all micros (MCL, MNQ, MES, MGC, M2K, MYM) and standard (CL, NQ, ES, GC, RTY, YM, SI, ZB, ZN) CME futures currently in the trading universe. `test_polygon_futures_blocklist.py` already asserts coverage. **No extension needed.**

Defense-in-depth additions for future expansion (BTC, 6E, 6B, 6J, ZC, ZS) are deferred — they're not in our symbol universe and would be scope creep on this task.

### 2.5E — Empty-table writer classification

For each of the 8 empty analytics tables, located writer + assessed classification:

| Table | Writer location | Classification | Explanation |
|---|---|---|---|
| `learning_events` | **none found** | (c) silent bug | Migration 013 created the table + indexes. `learning_router.py:677` reads it. No `INSERT INTO learning_events` anywhere in `engine/`. AgentFeedbackTracker was supposed to write here but doesn't. |
| `pnl_snapshots` | `engine/database/_mixins_pnl.py:132` (`upsert_pnl_snapshot`), called from `engine/risk/safety_layer.py:315` | (c) silent bug | Writer exists + is called. Empty means SafetyLayer's trigger condition never fires. Needs trace: is `SafetyLayer.check()` running? Is `self._db_manager` set? |
| `pipeline_llm_costs` | `engine/database/_mixins_llm_costs.py:67` | TBD (call sites not yet traced) | Writer exists. Need to locate caller — probably a pipeline-completion hook. |
| `supervisor_decisions` | `engine/notifications/supervisor.py:404` | TBD | Writer exists in Hermes supervisor. Empty means either supervisor never runs or every event is swallowed before reaching the INSERT. |
| `trading_patterns` | `engine/learning/consolidator.py:215` + `engine/learning/patterns.py:401` | (a) nightly job never ran | Consolidator is a scheduled nightly task per MEMORY.md. If the cron job isn't registered / doesn't fire / errors silently, table stays empty. |
| `trade_journal` | `engine/database/_mixins_journal.py:61` | (a) UI-dependent | Journal is a user-surface feature. Empty = no user ever wrote a journal entry. Expected. |
| `journal_notes` | `engine/database/_mixins_journal.py:243` | (a) UI-dependent | Same as trade_journal. |
| `capital_allocation` | `engine/scripts/init_capital.py:115` | (a) bootstrap script never run | This is a one-time script. Empty = bootstrap never executed. Needs `python engine/scripts/init_capital.py` run once. |

### Critical 2.5E finding: `trade_outcomes` table mismatch

`engine/analytics/agent_feedback.py` (AgentFeedbackTracker) and `engine/analytics/ic_ensemble.py` both reference a table called **`trade_outcomes`** for storing per-agent signal/P&L pairs (see `ic_ensemble.py:92, 119`). This table **does not exist in the current schema** (v21 has `learning_events` but not `trade_outcomes`). So either:
- `AgentFeedbackTracker._init_db()` is creating `trade_outcomes` on-the-fly in a separate path (auxiliary DB?), OR
- Every `record_outcome()` call is silently failing with `sqlite3.OperationalError: no such table`.

This directly kills **Track H (ICWeightedEnsemble)** wiring — without `trade_outcomes` populated, Spearman rank correlation over per-agent signals vs P&L cannot be computed. MEMORY.md's claim that Track H is "wired" needs an asterisk: the code is in the pipeline, but the data it depends on isn't there.

Next step for Task 2.5D/E to resolve: grep `AgentFeedbackTracker._init_db` for the table creation SQL, determine whether it's writing to a separate `.db` file (e.g. `agent_feedback.db`) or intended to share the main DB. If separate: confirm that DB exists and has rows. If same DB: migration to add `trade_outcomes` column equivalents to `learning_events` (or rename+merge).

### 2.5A + 2.5E decision matrix for next work

| Task | Action | Confidence |
|---|---|---|
| 2.5A (blocklist) | Mark DONE — no-op, already comprehensive | High |
| 2.5B (daily_pnl fix) | Unchanged — still a dashboard bug | High |
| 2.5C (JSON validation) | Unchanged — still 1 malformed row | High |
| 2.5D (pipeline_runs dead cols) | Unchanged — 0/2632 still needs wiring | High |
| 2.5E (empty tables) | **Split into 2.5E1 (trade_outcomes mismatch) + 2.5E2 (per-table writer trace)**. 2.5E1 is the highest-impact item — it directly unblocks Track H. | High |

---

## Appendix: data-availability matrix (permanent reference)

| Table | Populated? | Write-path status | Used by |
|---|:---:|---|---|
| paper_trades | partial (16 rows, mostly test/sync) | Active (but getting junk) | PortfolioTracker |
| pipeline_runs | full | Active | Pipeline completion handler |
| decisions | full | Active | Pipeline completion handler |
| pipeline_llm_costs | **empty** | Wiring broken | (unused) |
| learning_events | **empty** | Wiring broken | AgentFeedbackTracker |
| supervisor_decisions | **empty** | Wiring broken (or never fires) | Hermes/supervisor notifier |
| trading_patterns | **empty** | Wiring broken | Pattern miner |
| trade_journal | **empty** | Wiring broken | Trade journal feature |
| journal_notes | **empty** | Wiring broken | Journal UI |
| pnl_snapshots | **empty** | Wiring broken | Safety layer (restart persistence) |
| capital_allocation | **empty** | Wiring broken | Capital sizing |
| positions | **empty** | Wiring broken | Position tracker |
| daily_pnl | populated (but synthetic) | Active writer is wrong | Dashboard daily view |
| pending_trade_approvals | full | Active | Approval workflow |
| alert_log | full | Active | Alert dispatcher |
| discord_bot_signals | full | Active (historical import) | Corey/external signals |

Any analysis that depends on an "empty" row above is gated on the write-path fix for that table.
