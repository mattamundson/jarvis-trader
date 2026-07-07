# US-2001 — Signal Frequency Diagnostic Report

**Date**: 2026-04-04
**Investigator**: JARVIS (Claude Code)
**Status**: FIXED

---

## 1. Diagnostic Query Results

### Query 1 — Pipeline Runs Table
```
pipeline_runs schema: (id, run_id, symbol, webhook_action, source, final_action,
                       final_quantity, requires_human, summary, status,
                       error_message, duration_ms, created_at)
PIPELINE RUNS (last 10): EMPTY
```
**Finding**: Zero rows. Table exists with correct schema but is never written to.

### Query 2 — Pending Approvals
```
PENDING APPROVALS: 1 row — MCL 'buy' 'approved' (from US-1802 E2E test seed, 2026-04-03)
```
**Finding**: Only the synthetic E2E test seed. No real pipeline-generated approvals.

### Query 3 — Scheduler Status
```json
{
  "running": true,
  "total_jobs": 12,
  "total_decisions_logged": 0
}
```
Jobs registered: watchlist_scan, market_open_scan, intraday_scan_15m, mgc_daily_signal, ...

**Critical finding**: `total_decisions_logged: 0` from in-memory ring buffer despite 140 rows
in the `decisions` SQLite table. The in-memory `_decision_log` list resets on every engine
restart — it shows 0 because the engine has been restarted since those decisions were logged.
The 140 SQLite rows confirm the scheduler IS running and calling the pipeline.

### Query 4 — Manual Trigger
```
POST /scanner/trigger → {"action":"trigger","status":"success","message":"Scan started in background"}

Scanner status after trigger:
{"active":true,"symbols":["MCL","MNQ"],"total_scans":2,"approvals_created":0,"errors":0}

pipeline_runs after trigger: STILL EMPTY
```
**Finding**: Scanner ran 2 scans without errors, but pipeline_runs remains empty.

---

## 2. Root Causes Identified

### Bug A (CRITICAL) — MCL Excluded from Watchlist Scheduler

**File**: `engine/config.py`, line 274-277

**Problem**: `FUTURES_WATCHLIST` default was `"MES,MNQ,MCL"`. The scheduler job
`run_watchlist_analysis` uses `settings.FUTURES_WATCHLIST[:2]` to limit the scan to 2
instruments. With MES first, the slice yielded `['MES', 'MNQ']` — completely dropping MCL
(WFE=0.82, the primary approved instrument) from the 30-minute scheduled scan.

MCL only ran via the `SignalScanner` background task (60-min interval), not the watchlist
scheduler. Crucially, the watchlist scheduler writes to the `decisions` table — so the absence
of MCL in `decisions` rows confirmed it was being silently dropped.

**Evidence**: All 140 `decisions` rows are for MES, MNQ, SPY, QQQ, AAPL — zero MCL rows.

### Bug B (CRITICAL) — pipeline_runs Never Written From Any Scan Path

**Files**: `engine/scanner/signal_scanner.py`, `engine/main.py`

**Problem**: `approval/pipeline_history.py` contains a well-formed `pipeline_run_record_from_result()`
helper and `database/_mixins_alerts.py` has `insert_pipeline_run()` — but neither was ever
called from:
- `signal_scanner._scan_symbol()` (60-min MCL/MNQ scanner)
- `market_open_scan_job._scan_one()` (09:31 ET scan)
- `run_watchlist_analysis._analyze_and_alert()` (30-min watchlist scheduler)

The only caller was `strategies/rl_executor.py` — a non-production path. This means the
`pipeline_runs` audit table was structurally correct but dead.

---

## 3. Case Classification

**Case A**: `pipeline_runs` empty — scanner infrastructure not wiring audit log.
**Bonus Bug**: MCL silently excluded from primary scheduler due to watchlist ordering.

---

## 4. Fixes Applied

### Fix 1 — Reorder FUTURES_WATCHLIST (config.py line 274)

```python
# BEFORE
FUTURES_WATCHLIST: Union[str, list[str]] = Field(
    default="MES,MNQ,MCL",
    ...
)

# AFTER
FUTURES_WATCHLIST: Union[str, list[str]] = Field(
    default="MCL,MNQ,MES",
    description="... MCL first (WFE=0.82), MNQ second (WFE=0.57). "
                "MES last (WFE=0.09, data-collection only). "
                "[:2] slice used by watchlist scheduler must yield MCL+MNQ.",
)
```

Effect: `settings.FUTURES_WATCHLIST[:2]` now returns `['MCL', 'MNQ']` — both approved
instruments are scanned every 30 minutes during market hours.

### Fix 2 — Wire pipeline_runs into signal_scanner._scan_symbol (signal_scanner.py)

Added `import time as _time_module` and a timed pipeline call with immediate persistence:

```python
_t0 = _time_module.monotonic()
result = await self.trading_pipeline.analyze_and_decide(...)
_duration_ms = (_time_module.monotonic() - _t0) * 1000.0

# Always persist every pipeline execution to pipeline_runs for audit trail.
try:
    from approval.pipeline_history import pipeline_run_record_from_result
    _run_record = pipeline_run_record_from_result(
        symbol=symbol, result=result, duration_ms=_duration_ms, source="scanner"
    )
    self.db_manager.insert_pipeline_run(_run_record)
except Exception as _db_exc:
    logger.warning("[Scanner] Failed to log pipeline_run for %s: %s", symbol, _db_exc)
```

### Fix 3 — Wire pipeline_runs into market_open_scan_job (main.py)

Same pattern applied to `_scan_one()` inner function, source="market_open".

### Fix 4 — Wire pipeline_runs into run_watchlist_analysis (main.py)

Same pattern applied to `_analyze_and_alert()` inner function, source="watchlist".

---

## 5. Signal Frequency After Fix

### Watchlist Scheduler (30-min, market hours)
- **Before**: MCL=0 scans/day, MNQ=16 scans/day (during 9am-4pm CT window)
- **After**: MCL=16 scans/day, MNQ=16 scans/day

### Signal Scanner (60-min, futures hours)
- MCL and MNQ: unchanged (already scanning both — just not logging to pipeline_runs)
- **Before**: 0 pipeline_runs rows/day
- **After**: All scan results persisted to pipeline_runs with duration_ms and source

### Market Open Scan (09:31 ET)
- MCL, MNQ, MES: unchanged in instruments list
- **Before**: 0 pipeline_runs rows
- **After**: All 3 instruments logged to pipeline_runs at market open

---

## 6. Test Results

```
1208 passed, 6 failed (pre-existing auth=7 category), 95 skipped
```

The 6 failures are pre-existing `TestPortfolioEndpoints` auth failures (live engine at
port 8010 returns 401 when tests call without API key). These are not related to this fix
and were present before this work.

Safety layer tests: all passing. Signal tests: all passing. Pipeline tests: all passing.

---

## 7. Files Changed

| File | Change |
|------|--------|
| `engine/config.py` | Reordered FUTURES_WATCHLIST default to MCL,MNQ,MES |
| `engine/scanner/signal_scanner.py` | Added pipeline_runs write after every _scan_symbol call |
| `engine/main.py` | Added pipeline_runs write in market_open_scan_job and run_watchlist_analysis |
