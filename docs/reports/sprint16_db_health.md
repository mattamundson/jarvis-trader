# Sprint 16 — Database Health Report
**Generated**: 2026-04-03
**Investigator**: JARVIS (US-1603)

---

## 1. Database Inventory

The project contains multiple SQLite files across two locations. The engine at startup time points to `engine/data/jarvis_trader.db` — not the root-level `engine/jarvis_trader.db` (which is empty).

| File | Path | Size | Status |
|------|------|------|--------|
| **engine/data/jarvis_trader.db** | `jarvis-trader/engine/data/jarvis_trader.db` | 401 KB | PRIMARY — engine active DB |
| **data/jarvis_trader.db** | `jarvis-trader/data/jarvis_trader.db` | 104.5 MB | Discord data warehouse |
| **engine/data/llm_costs.db** | `jarvis-trader/engine/data/llm_costs.db` | 61 KB | LLM cost tracking |
| **engine/jarvis_trader.db** | `jarvis-trader/engine/jarvis_trader.db` | 0 bytes | GHOST FILE — empty, unused |
| **engine/data/backups/paper_trades_20260402_233000.db** | backup | 385 KB | Backup snapshot 2026-04-02 23:30 |

**Key finding**: `engine/jarvis_trader.db` (root of engine directory) is a 0-byte ghost file created on 2026-04-02. It is likely created whenever the engine initializes without the correct working directory. This is a PATH BUG — see Section 7.

---

## 2. Integrity Check Results

All non-empty databases pass SQLite's integrity check.

| Database | `PRAGMA integrity_check` | Result |
|----------|--------------------------|--------|
| engine/data/jarvis_trader.db | ok | PASS |
| data/jarvis_trader.db | ok | PASS |
| engine/data/llm_costs.db | ok | PASS |
| engine/data/backups/paper_trades_20260402_233000.db | ok | PASS |
| engine/jarvis_trader.db | N/A (0 bytes) | GHOST |

No corruption detected in any populated database.

---

## 3. Primary Engine DB — Table Inventory

**Database**: `engine/data/jarvis_trader.db`
**Schema version**: 11 migrations applied (all on 2026-04-03 17:34:53–54)

| Table | Row Count | Notes |
|-------|-----------|-------|
| paper_trades | **6** | Core trading data — see Section 4 |
| decisions | **100** | Pipeline LLM decisions — all "hold" |
| schema_version | 11 | Full migration history present |
| sqlite_sequence | 2 | Auto-increment counters |
| alert_log | 0 | WhatsApp notification history (unused) |
| capital_allocation | 0 | Cross-market allocations (not populated here) |
| daily_pnl | 0 | Daily PnL aggregates (not populated) |
| discord_bot_signals | 0 | Replicated from data/ warehouse |
| discord_corey_alerts | 0 | Replicated from data/ warehouse |
| discord_corey_commentary | 0 | Replicated from data/ warehouse |
| discord_ib_reports | 0 | Replicated from data/ warehouse |
| journal_notes | 0 | Trade journal notes (unused) |
| pending_trade_approvals | 0 | Human approval queue (unused) |
| pipeline_llm_costs | 0 | Per-pipeline cost tracking (unused) |
| pipeline_runs | 0 | Webhook/manual run history (unused) |
| positions | 0 | Open positions (unused) |
| settings | 0 | System settings key-value store (unused) |
| trade_journal | 0 | Extended trade journal (unused) |

---

## 4. Paper Trades Analysis

### 4a. Full Trade List

| ID | trade_id | Symbol | Side | Qty | Entry | Exit | PnL | Status | Entry Time |
|----|----------|--------|------|-----|-------|------|-----|--------|------------|
| 3 | MES_2026-04-01_long_5800.0 | MES | long | 1 | 5800.00 | NULL | NULL | **closed** | 2026-04-01 |
| 1 | MES_2026-04-02_long_5800.0 | MES | long | 1 | 5800.00 | NULL | NULL | **closed** | 2026-04-02 |
| 4 | MES_2026-04-02_long_5810.0 | MES | long | 1 | 5810.00 | NULL | NULL | **closed** | 2026-04-02 |
| 2 | MES_2026-04-03_short_5800.0 | MES | short | 1 | 5800.00 | NULL | NULL | **closed** | 2026-04-03 |
| 5 | d85d810b-... | MCL | buy | 1 | 72.50 | NULL | NULL | **open** | 2026-04-03T14:38 |
| 6 | b6f20a35-... | MCL | buy | 1 | 72.50 | NULL | NULL | **open** | 2026-04-03T16:13 |

**Total trades**: 6
**Closed**: 4 (MES — IDs 1, 2, 3, 4)
**Open**: 2 (MCL — IDs 5, 6)

### 4b. PnL Reconciliation vs. $10,000 Starting Capital

| Metric | Value |
|--------|-------|
| Starting Capital | $10,000.00 |
| Total Realized PnL (sum of `pnl` column) | **$0.00** |
| NULL pnl count | **6 of 6** — ALL trades have NULL pnl |
| Expected Balance (trades DB) | $10,000.00 |

**CRITICAL**: The `pnl` column is NULL for every single trade in the current engine database. This means the engine DB cannot be used to calculate a meaningful balance. The 4 "closed" MES trades carry `pnl_pct` values inside their `strategy_params` JSON (+4.85%, +4.85%, -5.15%, +4.85%) but the canonical `pnl` field was never populated.

The `strategy_params` JSON for closed MES trades contains `pnl_pct` but not absolute PnL in dollars. These are synthetic seed records — not real executed trades.

### 4c. Cross-Reference: Backup DB (2026-04-02 23:30 snapshot)

The backup DB contains the last known good state with actual PnL populated:

| trade_id | Symbol | Side | Entry | Exit | PnL | Status |
|----------|--------|------|-------|------|-----|--------|
| test-import-single-fixture-001 | TEST | LONG | 5000.00 | 5010.00 | **+$50.00** | CLOSED |
| f62dc466-... | MES | buy | 5800.00 | NULL | NULL | open |
| 594fda13-... | MCL | buy | 65.50 | 72.50 | **+$7.00** | closed |
| 0ac38aff-... | MCL | buy | 72.50 | 72.50 | **$0.00** | closed |
| 92fefd04-... | MCL | buy | 72.50 | 72.50 | **$0.00** | closed |

**Backup daily_pnl (2026-04-02)**: Starting $10,000 → Ending $10,007 | Realized PnL: +$7.00 | 3 total trades | 1 win / 2 flat

The backup represents the only historical state where real PnL was tracked.

### 4d. paper_trades.json (data/paper_trades.json)

A separate JSON-based paper trading log exists at `data/paper_trades.json`:
- **416 trade records** (dict format with `trades` key)
- `summary.total_trades: 0` — the summary counter was not updated
- `summary.total_pnl: 0.0` — computed PnL not persisted
- `summary.avg_trade_value: $7,495.36` — average notional per trade

The 416 JSON trades are NOT mirrored in the engine SQLite DB (which only has 6 records). These appear to be a parallel paper trading log from a different code path (likely `paper/` module vs. `database/` module).

---

## 5. Decisions Table Analysis

**100 decisions** recorded in current engine DB (all from 2026-04-03 scheduler runs):

| Symbol | Decision Count | Action Distribution |
|--------|---------------|---------------------|
| AAPL | 20 | 20x hold |
| MES | 20 | 20x hold |
| MNQ | 20 | 20x hold |
| QQQ | 20 | 20x hold |
| SPY | 20 | 20x hold |

- **Time range**: 2026-04-03 14:00 – 18:31
- **All actions are HOLD** (100/100) — no BUY or SELL decisions reached execution
- Confidence levels consistently at 0.25 (low conviction)
- Most decisions cite elevated VIX (24.5) and ranging/mean-reverting regimes as reasons to hold

**Anomaly**: AAPL, QQQ, and SPY are equity symbols — these should not be in the decisions table if the system is futures-only. SPY appears because it has walkforward data but WFE=0.00 (rejected). This is a scheduler misconfiguration routing non-approved symbols through the pipeline.

---

## 6. LLM Cost Tracking (engine/data/llm_costs.db)

**180 LLM calls** recorded over ~25 hours (2026-04-02 17:18 → 2026-04-03 18:31):

| Model | Calls | Tokens | Cost (USD) |
|-------|-------|--------|-----------|
| claude-opus-4-6 | 55 | 74,110 | $2.3668 |
| claude-sonnet-4-6 | 112 | 114,150 | $0.7326 |
| claude-haiku-4-5-20251001 | 13 | 7,222 | $0.0132 |
| **TOTAL** | **180** | **195,482** | **$3.1126** |

At the current run rate of ~7.6 calls/hour, projected daily LLM spend is approximately **$3.00/day**.

---

## 7. Kill Switch State

The `system_state` table does not exist in any current database. Kill switch state is managed in-memory by `engine/risk/safety_layer.py` and not persisted to SQLite.

**Implication**: On engine restart, the daily loss counter resets. If the engine crashes mid-day after taking losses, the daily loss gate will not carry over. This is a known gap — the safety layer does not have persistence.

---

## 8. Discord Data Warehouse (data/jarvis_trader.db — 104.5 MB)

This separate database contains scraped Discord signal data and is NOT the trading engine DB:

| Table | Row Count |
|-------|-----------|
| discord_bot_signals | 215,887 |
| discord_corey_commentary | 64,943 |
| discord_ib_reports | 940 |
| discord_corey_alerts | 68 |
| capital_allocation | 4 |
| sqlite_sequence | 5 |

The `capital_allocation` table here has the correct $10K allocation config (MES 40%, MNQ 30%, MGC 20%, MCL 10%) but is in the wrong database — the engine DB's `capital_allocation` table is empty.

---

## 9. Anomalies Found

### CRITICAL

| # | Anomaly | Impact | Recommendation |
|---|---------|--------|----------------|
| C1 | **ALL 6 paper_trades have NULL pnl and NULL exit_price** even for "closed" status trades | Cannot compute balance or performance metrics from engine DB | Fix trade close flow to write `exit_price`, `exit_time`, and `pnl` on close |
| C2 | **Ghost DB at engine/jarvis_trader.db (0 bytes)** | Engine may be initializing DB at wrong path in some code paths | Add `DATABASE_PATH` env var validation on startup; delete ghost file |
| C3 | **416 JSON trades vs 6 SQLite trades** — two divergent paper trading storage systems | Dashboard shows inconsistent data depending on which source the endpoint queries | Consolidate to single source of truth (engine/data/jarvis_trader.db) |

### HIGH

| # | Anomaly | Impact | Recommendation |
|---|---------|--------|----------------|
| H1 | **4 MES "closed" trades have no exit_price** — status says "closed" but exit fields are all NULL | These are synthetic seed records masquerading as real closed trades | Mark with `notes='synthetic_seed'` or delete; do not count in performance stats |
| H2 | **2 MCL "open" trades from smoke test** (IDs 5, 6) with `strategy_params: {notes: "smoke_working_today"}` remain open in current DB | Smoke test trades polluting live paper trading state | Add cleanup step to smoke tests; tag test trades and exclude from stats |
| H3 | **AAPL, QQQ, SPY in decisions table** — non-approved equity symbols running through the pipeline | Wasted LLM cost ($0.60+/day); decisions for non-tradeable symbols | Remove AAPL/QQQ/SPY from scheduler symbol list; restrict to MCL and MNQ |
| H4 | **daily_pnl table is empty** in current engine DB despite 6 trades and 1 day of activity | EOD summaries, drawdown tracking, and kill switch persistence all fail silently | Implement daily_pnl write on trade close and on EOD scheduler run |
| H5 | **Kill switch state not persisted** — safety layer is memory-only | Daily loss limit resets on engine crash/restart | Add `system_state` table writes for daily_loss_pct on every trade |

### MEDIUM

| # | Anomaly | Impact | Recommendation |
|---|---------|--------|----------------|
| M1 | **capital_allocation in wrong DB** — populated in data/jarvis_trader.db but empty in engine/data/jarvis_trader.db | Engine queries empty table for allocation data | Run migration to copy allocation records to engine DB |
| M2 | **paper_trades.json summary counters stuck at 0** despite 416 trade records | Dashboard summary widgets show 0 trades if reading JSON summary block | Fix JSON writer to recompute summary on every write |
| M3 | **Backup DB contains `discord_daily_sentiment` table** (997 rows) not present in current engine DB | Schema divergence between backup and current schema | Confirm v11 schema is authoritative; remove stale tables from backup |
| M4 | **100% hold rate** in decisions (100/100) over 4.5 hours | Either system is correctly conservative, or filter is too tight to ever trade | Review signal thresholds against current market conditions |

---

## 10. Summary Scorecard

| Metric | Value |
|--------|-------|
| DB Integrity | PASS (all 4 populated DBs) |
| Total Paper Trades (engine DB) | 6 |
| Closed Trades | 4 (all MES — synthetic seed data) |
| Open Trades | 2 (MCL — smoke test artifacts) |
| Realized PnL (engine DB) | **$0.00** (NULL pnl across all trades) |
| Balance (engine DB) | **$10,000.00** (starting, no updates) |
| Backup Balance (2026-04-02) | **$10,007.00** (+$7 MCL connectivity test) |
| LLM Calls (last 25h) | 180 calls / $3.11 |
| Decisions Logged | 100 (100% hold, 5 symbols) |
| Schema Migrations Applied | 11 |
| Critical Anomalies | 3 |
| High Anomalies | 5 |
| Medium Anomalies | 4 |

---

## 11. Immediate Action Items

1. **[P0]** Fix trade close path to write `exit_price`, `exit_time`, and `pnl` when a trade closes — currently these fields are never populated in the current engine DB.

2. **[P0]** Delete ghost file `engine/jarvis_trader.db` (0 bytes) and add startup assertion that the DB path resolves to `engine/data/jarvis_trader.db`.

3. **[P1]** Remove AAPL, QQQ, SPY from the scheduler's symbol list — only MCL and MNQ should be running through the pipeline per approved instrument list.

4. **[P1]** Implement daily_pnl table writes — on every trade close, upsert the daily aggregate. On EOD, finalize the record. Wire to kill switch persistence.

5. **[P1]** Consolidate paper trading storage — either commit to JSON or SQLite, not both. Recommend SQLite (engine/data/jarvis_trader.db) as the single source of truth and deprecate `data/paper_trades.json`.

6. **[P2]** Copy capital_allocation records from data/jarvis_trader.db into engine/data/jarvis_trader.db, or add a migration step on engine startup.

7. **[P2]** Tag or delete synthetic seed trades (IDs 1–4) and smoke test open trades (IDs 5–6) so they do not pollute live performance reporting.
