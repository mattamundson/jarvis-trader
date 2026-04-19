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

1. **MES Polygon contamination is unfixed.** The 2026-04-16 futures blocklist audit fixed MCL but missed MES (and likely MNQ, MGC, ES, NQ, GC). The `FUTURES_EQUITY_CONTAMINATION_RANGES` check in this script catches it at the analysis layer, but the engine itself is still letting Polygon return equity prices for futures symbols. → **Immediate fix**: extend `POLYGON_FUTURES_BLOCKLIST` to all CME futures tickers, not just MCL. (Task 3.B or new T2.5.)
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
